"""Integration test: retiring the orphan ``project_manager`` category.

Four things have to happen together, and three of them fail SILENTLY if skipped:

* a live ``job_listings.enrichment_category`` reference must be NULLed first —
  it is a real FK, so a DELETE would otherwise fail (loud, at least);
* a ``user_saved_filters.category`` entry must be scrubbed — that column is
  JSONB with NO FK, so nothing errors and the filter just matches nothing
  forever;
* the dimension row goes;
* downgrade puts the dimension row back.
"""

from __future__ import annotations

import json
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

_PARENT_REVISION = "b93d5c17a842"
_RETIRE_REVISION = "2e6f81ad4b57"


def _is_prod_like(url: str) -> bool:
    lowered = url.lower()
    return ".railway." in lowered or "prod" in lowered


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_retire_project_manager_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_retirepm_{suffix}"

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
        Base.metadata.create_all(
            engine,
            tables=[
                Base.metadata.tables["job_categories"],
                Base.metadata.tables["job_levels"],
                Base.metadata.tables["job_listings"],
                Base.metadata.tables["users"],
                Base.metadata.tables["user_saved_filters"],
            ],
        )
        engine.dispose()

        seed = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed.autocommit = True
        cur = seed.cursor()
        cur.execute(
            "INSERT INTO job_categories (slug, label, sort_order) VALUES "
            "('software_engineering','Software Engineering',0),"
            "('project_manager','Project Manager',3)"
        )
        # A listing PINNED to the doomed slug — this is the FK reference that
        # would block or orphan the DELETE.
        cur.execute(
            "INSERT INTO job_listings (id, source_id, title, company, url, details,"
            " ai_metadata, created_at, status, has_matched, first_seen_at,"
            " details_scraped, enrichment_category) VALUES "
            "('pm-1','src','PM','acme','http://x','{}'::jsonb,'{}'::jsonb,now(),"
            "'OPEN',false,now(),true,'project_manager')"
        )
        cur.execute(
            "INSERT INTO users (id, auth0_id, email, created_at, updated_at) "
            "VALUES ('u1','auth0|1','a@b.c',now(),now())"
        )
        # A saved filter carrying the doomed slug. JSONB, NO FK — nothing would
        # error if the scrub were skipped.
        cur.execute(
            "INSERT INTO user_saved_filters (user_id, category) VALUES (%s, %s)",
            ("u1", json.dumps(["project_manager", "software_engineering"])),
        )
        seed.close()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _PARENT_REVISION)
        command.upgrade(cfg, _RETIRE_REVISION)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS n FROM job_categories WHERE slug='project_manager'"
            )
            assert cur.fetchone()["n"] == 0, "dimension row survived the upgrade"

            cur.execute(
                "SELECT enrichment_category AS c FROM job_listings WHERE id='pm-1'"
            )
            assert cur.fetchone()["c"] is None, (
                "the pinned listing was neither NULLed nor blocked — it is an FK, "
                "so this had to be handled before the DELETE"
            )

            cur.execute("SELECT category FROM user_saved_filters WHERE user_id='u1'")
            assert cur.fetchone()["category"] == ["software_engineering"], (
                "the saved filter still carries a slug facets no longer returns — "
                "no FK protects that column, so nothing would have errored"
            )
        finally:
            verify.close()

        command.downgrade(cfg, _PARENT_REVISION)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT label, sort_order FROM job_categories "
                "WHERE slug='project_manager'"
            )
            row = cur.fetchone()
            assert row is not None, "downgrade did not restore the dimension row"
            assert row["label"] == "Project Manager"
            assert row["sort_order"] == 3
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
