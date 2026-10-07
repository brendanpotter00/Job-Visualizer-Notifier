"""Integration test: revision ``33ff7e590a46`` creates the four launch_radar_* tables
and its downgrade drops them.

Modelled on test_migration_feedback.py: the shared ``db_conn`` fixture builds the
schema with ``create_all`` and stamps head, so no normal test runs this
revision's own DDL. This runs it against a throwaway database of its own. The
revision depends on no table outside its own four (``tracked_company_id`` is a
soft link to ``companies``, not a foreign key), so an empty database stamped at
the parent is a faithful starting point.

Autogenerate never compares CHECK constraints, so the round trip asserts the
card status CHECK directly (and test_db_models.py pins the model text against
this revision's file).
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

_PARENT_REVISION = "904d5bc44e4b"
_LAUNCH_RADAR_REVISION = "33ff7e590a46"

_TABLES = ("launch_radar_cards", "launch_radar_monitors", "launch_radar_runs", "launch_radar_spend")
_INDEXES = (
    "idx_launch_radar_cards_status_posted",
    "idx_launch_radar_runs_started_at",
    "idx_launch_radar_spend_run_id",
)


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _tables(conn) -> set[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename LIKE 'launch\\_radar\\_%'"
    )
    return {r["tablename"] for r in cur.fetchall()}


def _indexes(conn) -> set[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname = 'public' AND indexname LIKE 'idx\\_launch\\_radar\\_%'"
    )
    return {r["indexname"] for r in cur.fetchall()}


def _foreign_keys(conn) -> set[tuple[str, str]]:
    """(table, referenced table) for every FK on a launch_radar_* table."""
    cur = conn.cursor()
    cur.execute(
        "SELECT c.conrelid::regclass::text AS tbl, c.confrelid::regclass::text AS ref "
        "FROM pg_constraint c "
        "WHERE c.contype = 'f' AND c.conrelid::regclass::text LIKE 'launch\\_radar\\_%'"
    )
    return {(r["tbl"], r["ref"]) for r in cur.fetchall()}


def _insert_card(conn, domain: str, status: str, tracked: str | None = None) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO launch_radar_cards (domain, company_name, status, tracked_company_id, payload) "
        "VALUES (%s, %s, %s, %s, %s)",
        (domain, domain, status, tracked, Json({"domain": domain})),
    )


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_launch_radar_tables_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    roundtrip_db = f"lr_tables_{uuid.uuid4().hex[:8]}"
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint.cursor().execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
    maint.cursor().execute(f'CREATE DATABASE "{roundtrip_db}"')
    maint.close()

    roundtrip_url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{roundtrip_db}"

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _PARENT_REVISION)
        command.upgrade(cfg, _LAUNCH_RADAR_REVISION)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        try:
            assert _tables(conn) == set(_TABLES)
            assert _indexes(conn) == set(_INDEXES)
            # Only the run links are real FKs; tracked_company_id is a soft link.
            assert _foreign_keys(conn) == {
                ("launch_radar_cards", "launch_radar_runs"),
                ("launch_radar_spend", "launch_radar_runs"),
            }
            # Every live status plus the tombstone is accepted ...
            _insert_card(conn, "new.ai", "new")
            _insert_card(conn, "kept.ai", "saved")
            _insert_card(conn, "old.ai", "archived")
            # ... a tracked_company_id needs no companies row (there is no
            # companies table here at all) ...
            _insert_card(conn, "tracked.ai", "new", tracked="gone-company")
            # ... and anything else is refused.
            with pytest.raises(psycopg2.errors.CheckViolation):
                _insert_card(conn, "bogus.ai", "starred")
            with pytest.raises(psycopg2.errors.UniqueViolation):
                _insert_card(conn, "new.ai", "new")
        finally:
            conn.close()

        command.downgrade(cfg, _PARENT_REVISION)

        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _tables(conn) == set()
            assert _indexes(conn) == set()
            cur = conn.cursor()
            cur.execute("SELECT version_num FROM alembic_version")
            assert cur.fetchone()["version_num"] == _PARENT_REVISION
        finally:
            conn.close()

        # And back up again, so the revision is re-runnable after a downgrade.
        command.upgrade(cfg, _LAUNCH_RADAR_REVISION)
        conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _tables(conn) == set(_TABLES)
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
