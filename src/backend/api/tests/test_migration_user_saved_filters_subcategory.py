"""Integration test: `user_saved_filters.subcategory` round-trips.

Modelled on test_migration_job_subcategories.py — build the pre-migration shape,
stamp the parent revision so Alembic treats everything up to there as applied,
upgrade through THIS revision only, assert, downgrade, assert it is gone.

The load-bearing assertions are that the column is NOT NULL with a `'[]'::jsonb`
default and that a row inserted BEFORE the migration comes out carrying `[]`.
The frontend sends the whole saved-filters object on every PUT against an
`extra='forbid'` model, so a nullable column or a missing backfill would surface
as an unrelated section's save wiping a user's stored value.
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

# SCHEMA-7's seed revision is this migration's parent.
_PRIOR_HEAD = "5a7d3e9c1b46"
_SUBCATEGORY_REV = "c48b0f2e7d19"


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


def _column(conn, table: str, column: str):
    cur = conn.cursor()
    cur.execute(
        "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone()


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_user_saved_filters_subcategory_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"usf_subcat_{suffix}"

    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint_cur = maint.cursor()
    maint_cur.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}"')
    maint_cur.execute(f'CREATE DATABASE "{roundtrip_db}"')
    maint.close()

    roundtrip_url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{roundtrip_db}"

    from api.db_models import Base

    try:
        from sqlalchemy import create_engine

        engine = create_engine(roundtrip_url)
        users = Base.metadata.tables["users"]
        saved = Base.metadata.tables["user_saved_filters"]

        # The ORM already declares the column this migration adds, so strip it
        # to build the pre-migration shape and put it straight back in a
        # `finally` — Base.metadata is shared process-wide.
        subcat_col = saved.c["subcategory"]
        try:
            saved._columns.remove(subcat_col)
            Base.metadata.create_all(engine, tables=[users, saved])
        finally:
            if subcat_col.name not in saved.c:
                saved.append_column(subcat_col)
        engine.dispose()

        seed = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed.autocommit = True
        try:
            cur = seed.cursor()
            cur.execute(
                "INSERT INTO users (id, auth0_id, email, created_at, updated_at) "
                "VALUES ('u1', 'auth0|u1', 'a@b.c', '2026-01-01T00:00:00Z', "
                "'2026-01-01T00:00:00Z') ON CONFLICT (id) DO NOTHING"
            )
            # A PRE-EXISTING row, written before this column existed.
            cur.execute(
                "INSERT INTO user_saved_filters (user_id, recent_time_window, "
                "trend_time_window, locations, category, level) "
                "VALUES ('u1', '3h', '7d', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb)"
            )
        finally:
            seed.close()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _PRIOR_HEAD)
        command.upgrade(cfg, _SUBCATEGORY_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            col = _column(verify, "user_saved_filters", "subcategory")
            assert col is not None, "subcategory column missing after upgrade"
            assert col["data_type"] == "jsonb"
            assert col["is_nullable"] == "NO"
            assert "'[]'::jsonb" in (col["column_default"] or "")

            cur = verify.cursor()
            cur.execute("SELECT subcategory FROM user_saved_filters WHERE user_id = 'u1'")
            # The pre-existing row backfilled to [] rather than NULL.
            assert cur.fetchone()["subcategory"] == []
        finally:
            verify.close()

        command.downgrade(cfg, _PRIOR_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _column(verify, "user_saved_filters", "subcategory") is None
            # The siblings this migration did not touch survive.
            assert _column(verify, "user_saved_filters", "category") is not None
            assert _column(verify, "user_saved_filters", "level") is not None
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
