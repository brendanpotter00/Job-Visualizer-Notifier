"""Integration test: the ``app_settings`` migration round-trips.

Stamp-parent-then-upgrade shape, modelled on ``test_migration_feedback.py``.
``app_settings`` has no foreign keys, so nothing needs to be created first — the
migration runs against an empty database.

THE LOAD-BEARING ASSERTION IS ``SELECT count(*) = 0``. The no-seed policy is what
makes a fresh database, a deleted flag and a rolled-back migration behave
identically, and what lets the reader materialize defaults instead of handling a
missing row. A test is the only thing that keeps a well-meaning
``INSERT ... ON CONFLICT DO NOTHING`` from creeping back in.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

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

_PARENT_REVISION = "7c1a4f2b9e30"
_APP_SETTINGS_REVISION = "b93d5c17a842"


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _table_exists(conn, name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = %s",
        (name,),
    )
    return cur.fetchone() is not None


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_app_settings_migration_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_appset_{suffix}"

    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint_cur = maint.cursor()
    maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
    maint_cur.execute(f'CREATE DATABASE "{roundtrip_db}"')
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
        command.upgrade(cfg, _APP_SETTINGS_REVISION)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "app_settings")

            cur = verify.cursor()
            cur.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='app_settings'"
            )
            cols = {r["column_name"]: r for r in cur.fetchall()}
            assert set(cols) == {"key", "value", "updated_at", "updated_by"}
            assert cols["value"]["data_type"] == "jsonb"
            assert cols["value"]["is_nullable"] == "NO"
            assert cols["updated_at"]["is_nullable"] == "NO"
            assert cols["updated_by"]["is_nullable"] == "YES"

            cur.execute(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid "
                "AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = 'app_settings'::regclass AND i.indisprimary"
            )
            assert [r["attname"] for r in cur.fetchall()] == ["key"]

            # THE no-seed assertion. A policy stated only in a comment is a
            # policy someone re-adds a seed against next quarter.
            cur.execute("SELECT count(*) AS n FROM app_settings")
            assert cur.fetchone()["n"] == 0, (
                "app_settings must ship EMPTY — absent means the code default, "
                "which is what makes a fresh DB, a deleted flag and a rolled-back "
                "migration behave identically."
            )
        finally:
            verify.close()

        command.downgrade(cfg, _PARENT_REVISION)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert not _table_exists(verify, "app_settings")
        finally:
            verify.close()

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
