"""Integration test: the phase-1 subcategory STRUCTURE migration round-trips.

Modelled on test_migration_locations.py — create only the FK-dependency tables
this migration touches, stamp its parent head so Alembic treats everything up to
there as applied (without running the ~30 seed migrations, several of which
INSERT INTO companies), upgrade through THIS revision only, assert, downgrade,
assert everything is gone and the pre-existing tables survive.

The load-bearing assertion is `job_subcategories` having EXACTLY ZERO rows.
Phase 1 ships the dimension empty on purpose: seeding it is what makes the public
dropdown appear, so a seed here would publish fifteen checkboxes that all return
"No jobs found".
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

# main's head — see api/tests/test_alembic_single_head.py for the chain.
# Was `536c1cddcd28` (PR #252's last revision) while #252 was open; after #252
# squash-merged, its chain was joined to main's by `776b9dbc68cc`.
_PRIOR_HEAD = "776b9dbc68cc"
_SUBCATEGORIES_REV = "7c1a4f2b9e30"


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


def _column(conn, table: str, column: str):
    cur = conn.cursor()
    cur.execute(
        "SELECT data_type, is_nullable, udt_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    return cur.fetchone()


def _indexdef(conn, name: str) -> str | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = %s",
        (name,),
    )
    row = cur.fetchone()
    return row["indexdef"] if row else None


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_job_subcategories_structure_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_subcat_{suffix}"

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
        job_listings = Base.metadata.tables["job_listings"]
        job_enrichment = Base.metadata.tables["job_enrichment"]
        job_categories = Base.metadata.tables["job_categories"]
        job_levels = Base.metadata.tables["job_levels"]

        # The ORM already declares everything THIS migration adds, so build the
        # pre-migration shape: strip the two job_listings columns (and the GIN
        # index keyed on one of them) and job_enrichment.subcategory_confidence,
        # create_all, then put them straight back. Base.metadata is shared
        # process-wide — the restore happens in a `finally` so a failure here
        # cannot corrupt every later test in the session.
        subcat_col = job_listings.c["enrichment_subcategories"]
        source_col = job_listings.c["enrichment_subcategory_source"]
        conf_col = job_enrichment.c["subcategory_confidence"]
        gin_indexes: set = set()
        try:
            gin_indexes = {
                ix for ix in job_listings.indexes if subcat_col.name in ix.columns.keys()
            }
            job_listings.indexes -= gin_indexes
            job_listings._columns.remove(subcat_col)
            job_listings._columns.remove(source_col)
            job_enrichment._columns.remove(conf_col)
            Base.metadata.create_all(
                engine,
                tables=[job_categories, job_levels, job_listings, job_enrichment],
            )
        finally:
            if subcat_col.name not in job_listings.c:
                job_listings.append_column(subcat_col)
            if source_col.name not in job_listings.c:
                job_listings.append_column(source_col)
            if conf_col.name not in job_enrichment.c:
                job_enrichment.append_column(conf_col)
            job_listings.indexes |= gin_indexes
        engine.dispose()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _PRIOR_HEAD)
        command.upgrade(cfg, _SUBCATEGORIES_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "job_subcategories")

            # THE phase-1 assertion: the dimension ships EMPTY.
            cur = verify.cursor()
            cur.execute("SELECT count(*) AS n FROM job_subcategories")
            assert cur.fetchone()["n"] == 0, (
                "job_subcategories must be EMPTY after the phase-1 structure "
                "migration — seeding it publishes the public dropdown, and that "
                "belongs to SCHEMA-7 in phase 2."
            )

            subcats = _column(verify, "job_listings", "enrichment_subcategories")
            assert subcats is not None, "enrichment_subcategories missing"
            assert subcats["data_type"] == "ARRAY"
            assert subcats["udt_name"] == "_text"
            assert subcats["is_nullable"] == "YES"

            source = _column(verify, "job_listings", "enrichment_subcategory_source")
            assert source is not None, "enrichment_subcategory_source missing"
            assert source["is_nullable"] == "YES"

            conf = _column(verify, "job_enrichment", "subcategory_confidence")
            assert conf is not None, "job_enrichment.subcategory_confidence missing"
            assert conf["is_nullable"] == "YES"

            indexdef = _indexdef(verify, "idx_job_listings_open_subcategories_gin")
            assert indexdef is not None, "partial GIN missing after upgrade"
            assert "USING gin" in indexdef, indexdef
            # The PARTIAL predicate is the point — without it the index covers
            # the CLOSED majority of the table for no reader.
            assert "WHERE (status = 'OPEN'::text)" in indexdef, indexdef
        finally:
            verify.close()

        command.downgrade(cfg, _PRIOR_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert not _table_exists(verify, "job_subcategories")
            assert _column(verify, "job_listings", "enrichment_subcategories") is None
            assert _column(verify, "job_listings", "enrichment_subcategory_source") is None
            assert _column(verify, "job_enrichment", "subcategory_confidence") is None
            assert _indexdef(verify, "idx_job_listings_open_subcategories_gin") is None
            # The tables the migration only ADDED to must survive.
            assert _table_exists(verify, "job_listings")
            assert _table_exists(verify, "job_enrichment")
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


# --- SCHEMA-7 (phase 2): the seed -------------------------------------------

# SCHEMA-11 (retire_project_manager_category) is the parent of the seed
# revision — the chain is 7c1a4f2b9e30 -> b93d5c17a842 -> 2e6f81ad4b57 -> here.
_SEED_PARENT = "2e6f81ad4b57"
_SEED_REV = "5a7d3e9c1b46"


def _load_seed_migration():
    """Import the seed revision module by path.

    Alembic revision files are not importable as a package, so read the module
    off disk the way `test_internal_enrichment.py` does. Importing rather than
    re-typing the fifteen rows is the whole point: a copy in this file would be
    a seventh place the taxonomy can drift.
    """
    import importlib.util

    matches = sorted(_SCRIPT_LOCATION.glob("versions/*seed_job_subcategories*.py"))
    assert len(matches) == 1, f"expected exactly one seed revision file, got {matches}"
    spec = importlib.util.spec_from_file_location("_seed_job_subcategories", matches[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_job_subcategories_seed_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The phase-2 seed publishes exactly the fifteen canonical rows.

    Stamps SCHEMA-11 (so Alembic treats the structure migration as applied
    without re-running the ~30 seed migrations before it), upgrades through THIS
    revision only, asserts the dimension, then downgrades and asserts the table
    is empty again but still present.
    """
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    seed_mig = _load_seed_migration()

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"seed_subcat_{suffix}"

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
        job_categories = Base.metadata.tables["job_categories"]
        job_subcategories = Base.metadata.tables["job_subcategories"]
        # The ORM already declares the post-SCHEMA-1 shape, which is exactly the
        # state this revision expects to find.
        Base.metadata.create_all(engine, tables=[job_categories, job_subcategories])
        engine.dispose()

        seed_conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed_conn.autocommit = True
        try:
            cur = seed_conn.cursor()
            # job_subcategories.parent_slug is a real FK, so the parent category
            # row has to exist before the seed runs.
            cur.execute(
                "INSERT INTO job_categories (slug, label, sort_order) "
                "VALUES ('software_engineering', 'Software Engineering', 0) "
                "ON CONFLICT (slug) DO NOTHING"
            )
        finally:
            seed_conn.close()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, _SEED_PARENT)
        command.upgrade(cfg, _SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT slug, label, parent_slug, sort_order "
                "FROM job_subcategories ORDER BY sort_order"
            )
            rows = cur.fetchall()

            assert len(rows) == 15, f"expected exactly 15 seeded rows, got {len(rows)}"

            # Byte-for-byte against the migration's own export — never re-typed.
            expected = [
                (slug, label, sort_order, parent)
                for slug, label, sort_order, parent in seed_mig.ADDED_SUBCATEGORIES
            ]
            actual = [
                (r["slug"], r["label"], r["sort_order"], r["parent_slug"]) for r in rows
            ]
            assert actual == expected

            assert all(r["parent_slug"] == "software_engineering" for r in rows)
            # Contiguous 0..14, no gaps and no duplicates.
            assert sorted(r["sort_order"] for r in rows) == list(range(15))
        finally:
            verify.close()

        command.downgrade(cfg, _SEED_PARENT)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            # Downgrade removes exactly those 15 rows and leaves the table.
            assert _table_exists(verify, "job_subcategories")
            cur = verify.cursor()
            cur.execute("SELECT count(*) AS n FROM job_subcategories")
            assert cur.fetchone()["n"] == 0
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
