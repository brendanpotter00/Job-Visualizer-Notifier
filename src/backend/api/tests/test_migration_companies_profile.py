"""Integration test: the blurb/accomplishment column migration applies and
reverses cleanly on the real `companies` table.

Mirrors test_migration_companies.py: bootstrap a fresh DB up to the
add-companies-table revision (so `companies` exists), then stamp directly to
this migration's down_revision (skipping the job_listings-touching chain that a
fresh DB can't run) and apply just this migration. Asserts the two columns are
added on upgrade, dropped on downgrade, and re-added idempotently.
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

ADMINS_REV = "2da4b99b39ea"        # prior revision before the companies table
COMPANIES_SCHEMA_REV = "438ad0658e53"  # add companies table
PROFILE_PREV_HEAD = "b38c364cd0c4"  # add feedback table (this migration's down_revision)
PROFILE_REV = "e015cd4d01a8"        # add blurb + accomplishment to companies


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _column_exists(conn, table: str, column: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone() is not None


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_blurb_accomplishment_migration_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_company_profile_{suffix}"

    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint_cur = maint.cursor()
    maint_cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
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

        # Materialize the companies table (no blurb/accomplishment yet).
        command.stamp(cfg, ADMINS_REV)
        command.upgrade(cfg, COMPANIES_SCHEMA_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert not _column_exists(verify, "companies", "blurb")
            assert not _column_exists(verify, "companies", "accomplishment")
        finally:
            verify.close()

        # Jump the version pointer to this migration's down_revision (skipping
        # the job_listings-touching chain a fresh DB can't run), then apply it.
        command.stamp(cfg, PROFILE_PREV_HEAD)
        command.upgrade(cfg, PROFILE_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _column_exists(verify, "companies", "blurb"), "blurb missing after upgrade"
            assert _column_exists(verify, "companies", "accomplishment"), (
                "accomplishment missing after upgrade"
            )
        finally:
            verify.close()

        # Downgrade drops both columns.
        command.downgrade(cfg, PROFILE_PREV_HEAD)
        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert not _column_exists(verify, "companies", "blurb")
            assert not _column_exists(verify, "companies", "accomplishment")
        finally:
            verify.close()

        # Re-upgrade is clean.
        command.upgrade(cfg, PROFILE_REV)
        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _column_exists(verify, "companies", "blurb")
            assert _column_exists(verify, "companies", "accomplishment")
        finally:
            verify.close()

    finally:
        try:
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
        except Exception as drop_exc:
            logging.getLogger(__name__).error(
                "Failed to drop roundtrip test database %s: %s", roundtrip_db, drop_exc
            )
