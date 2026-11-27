"""Integration test: the company-categories migration round-trips.

Modelled on test_migration_user_saved_filters_subcategory.py. Build the
pre-migration shape, stamp the parent revision, upgrade through THIS revision
only, assert, downgrade, assert it is all gone, then upgrade again.

The load-bearing assertions:

- a ``user_saved_filters`` row written BEFORE the migration reads ``[]``;
- the two tables, their primary keys and the cascading FK exist;
- downgrade removes all three objects, and a second upgrade still works.
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

_PRIOR_HEAD = "ef0f7d8c8e11"
_CATEGORIES_REV = "c05510cf06fe"


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


def _table_exists(conn, table: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s) AS oid", (f"public.{table}",))
    return cur.fetchone()["oid"] is not None


def _primary_key_columns(conn, table: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        "SELECT a.attname FROM pg_index i "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = %s::regclass AND i.indisprimary "
        "ORDER BY array_position(i.indkey, a.attnum)",
        (f"public.{table}",),
    )
    return [row["attname"] for row in cur.fetchall()]


def _foreign_keys(conn, table: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT confrelid::regclass::text AS target, confdeltype "
        "FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'",
        (f"public.{table}",),
    )
    return [dict(row) for row in cur.fetchall()]


def _upgraded_shape_holds(conn) -> None:
    col = _column(conn, "user_saved_filters", "company_category")
    assert col is not None, "company_category column missing after upgrade"
    assert col["data_type"] == "jsonb"
    assert col["is_nullable"] == "NO"
    assert "'[]'::jsonb" in (col["column_default"] or "")

    assert _table_exists(conn, "company_categories")
    assert _table_exists(conn, "company_category_members")
    assert _primary_key_columns(conn, "company_categories") == ["slug"]
    assert _primary_key_columns(conn, "company_category_members") == [
        "category_slug",
        "company_id",
    ]
    # One FK, onto the categories table, ON DELETE CASCADE ('c'). company_id
    # is a soft link: no FK onto companies.
    assert _foreign_keys(conn, "company_category_members") == [
        {"target": "company_categories", "confdeltype": "c"}
    ]

    # No seed rows: the lifespan seeds them, not the migration.
    cur = conn.cursor()
    cur.execute("SELECT count(*) AS n FROM company_categories")
    assert cur.fetchone()["n"] == 0


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_company_categories_upgrade_downgrade_and_reupgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"company_cats_{suffix}"

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
        # `finally` — Base.metadata is shared process-wide. The two new tables
        # are simply not created.
        cc_col = saved.c["company_category"]
        try:
            saved._columns.remove(cc_col)
            Base.metadata.create_all(engine, tables=[users, saved])
        finally:
            if cc_col.name not in saved.c:
                saved.append_column(cc_col)
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
                "trend_time_window, locations, category, level, subcategory) "
                "VALUES ('u1', '3h', '7d', '[]'::jsonb, '[\"growth\"]'::jsonb, "
                "'[]'::jsonb, '[]'::jsonb)"
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
        command.upgrade(cfg, _CATEGORIES_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            _upgraded_shape_holds(verify)
            cur = verify.cursor()
            cur.execute(
                "SELECT company_category, category FROM user_saved_filters "
                "WHERE user_id = 'u1'"
            )
            row = cur.fetchone()
            # The pre-existing row backfilled to [] and kept its other values.
            assert row["company_category"] == []
            assert row["category"] == ["growth"]

            # The FK cascades: deleting a category drops its members.
            verify.commit()
            verify.autocommit = True
            cur.execute(
                "INSERT INTO company_categories (slug, label, definition, sort_order) "
                "VALUES ('big_tech', 'Big Tech', 'Giants.', 0)"
            )
            cur.execute(
                "INSERT INTO company_category_members (category_slug, company_id, position) "
                "VALUES ('big_tech', 'google', 0)"
            )
            cur.execute("DELETE FROM company_categories WHERE slug = 'big_tech'")
            cur.execute("SELECT count(*) AS n FROM company_category_members")
            assert cur.fetchone()["n"] == 0
        finally:
            verify.close()

        command.downgrade(cfg, _PRIOR_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _column(verify, "user_saved_filters", "company_category") is None
            assert not _table_exists(verify, "company_category_members")
            assert not _table_exists(verify, "company_categories")
            # The siblings this migration did not touch survive.
            assert _column(verify, "user_saved_filters", "category") is not None
            assert _column(verify, "user_saved_filters", "subcategory") is not None
        finally:
            verify.close()

        # A second upgrade after the downgrade works (no leftover objects).
        command.upgrade(cfg, _CATEGORIES_REV)
        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            _upgraded_shape_holds(verify)
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
