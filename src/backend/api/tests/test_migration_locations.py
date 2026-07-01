"""Integration test: the location-normalization migration upgrades cleanly on
top of its parent head d5e1a9c30f72 and reverses cleanly via downgrade.

Mirrors test_migration_features.py: create only the FK-dependency table this
migration touches (job_listings — it ADD COLUMNs it), stamp this migration's
parent head d5e1a9c30f72 (so Alembic treats everything up to there as applied
without running the ~20 seed migrations — several of which INSERT INTO companies,
a table this test never creates), upgrade through THIS migration only, assert
the 4 tables + unique constraint + new column exist, downgrade back and assert
they're gone while job_listings survives.
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

_PRIOR_HEAD = "d5e1a9c30f72"
_LOCATIONS_REV = "c876c313e55c"


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
        "SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = %s",
        (name,),
    )
    return cur.fetchone() is not None


def _constraint_exists(conn, name: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,))
    return cur.fetchone() is not None


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
def test_locations_migration_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_loc_{suffix}"

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

    from api.db_models import Base

    try:
        from sqlalchemy import create_engine
        engine = create_engine(roundtrip_url)
        job_listings = Base.metadata.tables.get("job_listings")
        assert job_listings is not None, (
            "expected 'job_listings' in Base.metadata; got "
            f"{list(Base.metadata.tables.keys())}"
        )
        # The ORM's job_listings has since grown enrichment_category /
        # enrichment_level FK columns pointing at the job_categories / job_levels
        # dimension tables (added by a LATER migration than the one under test).
        # create_all-ing job_listings alone would emit those FKs against tables
        # that don't exist yet and fail with UndefinedTable, so materialize the
        # two FK-target dimensions first. They're harmless to this roundtrip —
        # the locations migration never touches them.
        job_categories = Base.metadata.tables["job_categories"]
        job_levels = Base.metadata.tables["job_levels"]
        # The migration ADD COLUMNs job_listings.normalization_status. The ORM
        # model already declares that column, so creating job_listings from the
        # full model would collide with the migration's add_column. Build the
        # pre-migration job_listings (without normalization_status), then put
        # the column back on the in-memory model so nothing else is affected.
        normalization_col = job_listings.c["normalization_status"]
        job_listings._columns.remove(normalization_col)
        try:
            Base.metadata.create_all(
                engine, tables=[job_categories, job_levels, job_listings]
            )
        finally:
            job_listings.append_column(normalization_col)
        engine.dispose()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _PRIOR_HEAD)
        command.upgrade(cfg, _LOCATIONS_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            for tbl in ("locations", "location_aliases", "alias_locations", "job_locations"):
                assert _table_exists(verify, tbl), f"{tbl} missing after upgrade"
            assert _constraint_exists(verify, "uq_locations_canonical"), "uq missing after upgrade"
            assert _index_exists(verify, "idx_job_locations_job_listing_id"), "index missing after upgrade"
            assert _column_exists(verify, "job_listings", "normalization_status"), "column missing after upgrade"
        finally:
            verify.close()

        command.downgrade(cfg, _PRIOR_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            for tbl in ("locations", "location_aliases", "alias_locations", "job_locations"):
                assert not _table_exists(verify, tbl), f"{tbl} still present after downgrade"
            assert not _constraint_exists(verify, "uq_locations_canonical"), "uq still present after downgrade"
            assert not _column_exists(verify, "job_listings", "normalization_status"), "column still present after downgrade"
            assert _table_exists(verify, "job_listings"), "job_listings unexpectedly dropped"
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
                "Failed to drop roundtrip test database %s during teardown: %s",
                roundtrip_db, drop_exc,
            )
