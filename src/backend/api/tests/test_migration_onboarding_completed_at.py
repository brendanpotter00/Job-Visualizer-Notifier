"""Integration test: `users.onboarding_completed_at` (`ef0f7d8c8e11`) round-trips.

Modelled on test_migration_north_star.py: build the pre-migration shape of
`users` in a fresh database, seed rows that exist "today", stamp the parent
revision, upgrade through THIS revision, assert, downgrade, assert it is gone.

The load-bearing assertions:

* every row that existed before the migration is BACKFILLED with a stamp —
  without it every existing account would see the first-sign-in questions;
* the column is nullable with NO default, so a row inserted AFTER the
  migration starts NULL (a `now()` default would stamp every new account and
  the questions would never show).
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

_PRIOR_HEAD = "bcbc67dbd87e"
_ONBOARDING_REV = "ef0f7d8c8e11"


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


def _insert_user(conn, uid: str) -> None:
    conn.cursor().execute(
        "INSERT INTO users (id, auth0_id, email, created_at, updated_at) "
        "VALUES (%s, %s, %s, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
        (uid, f"auth0|{uid}", f"{uid}@x.io"),
    )


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_onboarding_completed_at_backfills_existing_rows_and_leaves_new_ones_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    roundtrip_db = f"onboarding_{uuid.uuid4().hex[:8]}"
    maintenance_url = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    maint = psycopg2.connect(maintenance_url, cursor_factory=RealDictCursor)
    maint.autocommit = True
    maint.cursor().execute(f'CREATE DATABASE "{roundtrip_db}"')
    maint.close()
    roundtrip_url = TEST_DB_URL.rsplit("/", 1)[0] + f"/{roundtrip_db}"

    from api.db_models import Base

    try:
        from sqlalchemy import create_engine

        engine = create_engine(roundtrip_url)
        users = Base.metadata.tables["users"]
        # The ORM already declares the column this migration adds; strip it for
        # the pre-migration shape and restore it in `finally` (the metadata is
        # shared process-wide).
        stamp_col = users.c["onboarding_completed_at"]
        try:
            users._columns.remove(stamp_col)
            Base.metadata.create_all(engine, tables=[users])
        finally:
            if "onboarding_completed_at" not in users.c:
                users.append_column(stamp_col)
        engine.dispose()

        seed = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed.autocommit = True
        try:
            # Accounts that exist "today", before the migration.
            _insert_user(seed, "old1")
            _insert_user(seed, "old2")
        finally:
            seed.close()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _PRIOR_HEAD)
        command.upgrade(cfg, _ONBOARDING_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        verify.autocommit = True
        try:
            col = _column(verify, "users", "onboarding_completed_at")
            assert col is not None, "onboarding_completed_at missing after upgrade"
            assert col["data_type"] == "timestamp with time zone"
            assert col["is_nullable"] == "YES"
            # No default: a new account must start NULL.
            assert col["column_default"] is None

            cur = verify.cursor()
            cur.execute(
                "SELECT id, onboarding_completed_at FROM users ORDER BY id"
            )
            rows = cur.fetchall()
            assert [r["id"] for r in rows] == ["old1", "old2"]
            # Every pre-existing account was backfilled: none sees the questions.
            assert all(r["onboarding_completed_at"] is not None for r in rows)

            # An account created after the migration starts NULL.
            _insert_user(verify, "new1")
            cur.execute("SELECT onboarding_completed_at FROM users WHERE id = 'new1'")
            assert cur.fetchone()["onboarding_completed_at"] is None
        finally:
            verify.close()

        command.downgrade(cfg, _PRIOR_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _column(verify, "users", "onboarding_completed_at") is None
            cur = verify.cursor()
            cur.execute("SELECT count(*) AS n FROM users")
            assert cur.fetchone()["n"] == 3
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
