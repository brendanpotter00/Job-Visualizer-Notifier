"""Integration test: the companies schema + seed migrations upgrade cleanly
from f4008c4fb790, then reverse cleanly via downgrade -2, then re-upgrade.

The existing `conftest.py::db_conn` fixture bootstraps tables via
``Base.metadata.create_all`` + ``stamp_alembic_head``, which deliberately
short-circuits every ``op.create_*`` body in every revision. That means no
existing test ever exercises the migration files' own SQL — a typo in
``upgrade()`` or a missing DROP in ``downgrade()`` would slip through.

This test runs the real ``alembic upgrade`` and ``alembic downgrade``
commands against a freshly-created database. Mirrors test_migration_features.py.
"""

from __future__ import annotations

import logging
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

SCHEMA_REV = "438ad0658e53"
SEED_REV = "939331c99a23"
PREV_HEAD = "f4008c4fb790"


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


def _index_exists(conn, name: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM pg_indexes "
        "WHERE schemaname = 'public' AND indexname = %s",
        (name,),
    )
    return cur.fetchone() is not None


def _greenhouse_row_count(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT count(*) AS c FROM companies WHERE ats = 'greenhouse'")
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"]) if isinstance(row, dict) else int(row[0])


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_companies_migration_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full upgrade head → downgrade -2 → upgrade head on a clean DB."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_companies_{suffix}"

    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint_cur = maint.cursor()
    maint_cur.execute(
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (roundtrip_db,),
    )
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

        # Stamp PREV_HEAD so the companies migrations have a prior revision to
        # upgrade from. We skip the upstream rename-style migrations because
        # they try to rename `*_prod`/`*_local` variants that don't exist in
        # this fresh roundtrip DB.
        command.stamp(cfg, PREV_HEAD)

        command.upgrade(cfg, SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "companies"), (
                f"companies missing after upgrade to {SEED_REV}"
            )
            assert _index_exists(verify, "ix_companies_ats_enabled"), (
                "ix_companies_ats_enabled index missing after upgrade"
            )
            assert _greenhouse_row_count(verify) == 45, (
                f"expected 45 greenhouse rows after seed, got "
                f"{_greenhouse_row_count(verify)}"
            )
        finally:
            verify.close()

        command.downgrade(cfg, PREV_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert not _table_exists(verify, "companies"), (
                "companies still present after downgrade -2"
            )
            assert not _index_exists(verify, "ix_companies_ats_enabled"), (
                "ix_companies_ats_enabled still present after downgrade -2"
            )
        finally:
            verify.close()

        command.upgrade(cfg, SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "companies"), (
                "companies missing after re-upgrade"
            )
            assert _greenhouse_row_count(verify) == 45, (
                f"expected 45 greenhouse rows after re-upgrade, got "
                f"{_greenhouse_row_count(verify)}"
            )
        finally:
            verify.close()

    finally:
        try:
            maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
            maint.autocommit = True
            maint_cur = maint.cursor()
            maint_cur.execute(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (roundtrip_db,),
            )
            maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
            maint.close()
        except Exception as drop_exc:
            logging.getLogger(__name__).error(
                "Failed to drop roundtrip test database %s during teardown: %s",
                roundtrip_db,
                drop_exc,
            )
