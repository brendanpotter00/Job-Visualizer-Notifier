"""Integration test: revision ``f0dc42c3d985`` adds 'saved' to the card status CHECK.

Modelled on test_migration_user_saved_filters_subcategory.py, in a throwaway
database of its own. The pre-migration shape is built by the REAL parent
revision (``a67d3d0286a2`` creates the launch_radar_* tables with the old
CHECK) on top of ``companies``, the one table its FK needs. Then: upgrade
through this revision only, assert 'saved' is accepted, downgrade, assert the
saved row went back to 'new' and 'saved' is refused again.

Autogenerate never compares CHECK constraints, so this round trip (plus the
model/migration text pin in test_db_models.py) is the only thing that proves
the hand-written revision does what the model says.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import Json, RealDictCursor

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
_SCRIPT_LOCATION = _REPO_ROOT / "src" / "backend" / "alembic"
_SRC_BACKEND = _REPO_ROOT / "src" / "backend"

if str(_SRC_BACKEND) not in sys.path:
    sys.path.insert(0, str(_SRC_BACKEND))

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper",
)

_TABLES_PARENT = "904d5bc44e4b"  # main's head before the launch radar tables
_TABLES_REV = "a67d3d0286a2"  # launch_radar_* tables, CHECK without 'saved'
_SAVED_REV = "f0dc42c3d985"  # this revision


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _status_check(conn) -> str:
    cur = conn.cursor()
    cur.execute(
        "SELECT pg_get_constraintdef(c.oid) AS def FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE t.relname = 'launch_radar_cards' AND c.conname = 'ck_launch_radar_cards_status'"
    )
    row = cur.fetchone()
    assert row is not None, "ck_launch_radar_cards_status is missing"
    return str(row["def"])


def _insert_card(conn, domain: str, status: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO launch_radar_cards (domain, company_name, status, payload) "
        "VALUES (%s, %s, %s, %s)",
        (domain, domain, status, Json({"domain": domain})),
    )


def _statuses(conn) -> dict[str, str]:
    cur = conn.cursor()
    cur.execute("SELECT domain, status FROM launch_radar_cards")
    return {r["domain"]: r["status"] for r in cur.fetchall()}


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_launch_radar_saved_status_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    roundtrip_db = f"lr_saved_{uuid.uuid4().hex[:8]}"
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint.cursor().execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
    maint.cursor().execute(f'CREATE DATABASE "{roundtrip_db}"')
    maint.close()

    roundtrip_url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{roundtrip_db}"

    from api.db_models import Base

    try:
        from sqlalchemy import create_engine

        engine = create_engine(roundtrip_url)
        Base.metadata.create_all(engine, tables=[Base.metadata.tables["companies"]])
        engine.dispose()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _TABLES_PARENT)
        command.upgrade(cfg, _TABLES_REV)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        try:
            assert "saved" not in _status_check(conn)
            _insert_card(conn, "new.ai", "new")
            _insert_card(conn, "old.ai", "archived")
            with pytest.raises(psycopg2.errors.CheckViolation):
                _insert_card(conn, "early.ai", "saved")
        finally:
            conn.close()

        command.upgrade(cfg, _SAVED_REV)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        try:
            definition = _status_check(conn)
            for status in ("new", "saved", "archived", "deleted"):
                assert f"'{status}'" in definition, definition
            # Existing rows are untouched, and 'saved' is now a legal status.
            _insert_card(conn, "kept.ai", "saved")
            assert _statuses(conn) == {"new.ai": "new", "old.ai": "archived", "kept.ai": "saved"}
            with pytest.raises(psycopg2.errors.CheckViolation):
                _insert_card(conn, "bogus.ai", "starred")
        finally:
            conn.close()

        command.downgrade(cfg, _TABLES_REV)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        try:
            assert "saved" not in _status_check(conn)
            # The saved card went back to New rather than failing the downgrade.
            assert _statuses(conn) == {"new.ai": "new", "old.ai": "archived", "kept.ai": "new"}
            with pytest.raises(psycopg2.errors.CheckViolation):
                _insert_card(conn, "again.ai", "saved")
            cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version")
            assert cur.fetchone()["version_num"] == _TABLES_REV
        finally:
            conn.close()

        # And back up again, so the revision is re-runnable after a downgrade.
        command.upgrade(cfg, _SAVED_REV)
        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert "'saved'" in _status_check(conn)
        finally:
            conn.close()
    finally:
        maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
        maint.autocommit = True
        maint_cur = maint.cursor()
        maint_cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (roundtrip_db,),
        )
        maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
        maint.close()
