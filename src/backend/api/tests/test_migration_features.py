"""Integration test: the features+upvotes migration upgrades cleanly from the
baseline and then reverses cleanly via ``downgrade``.

The existing `conftest.py::db_conn` fixture bootstraps tables via
``Base.metadata.create_all`` + ``stamp_alembic_head``, which deliberately
short-circuits every ``op.create_*`` body in every revision. That means no
existing test ever exercises the migration file's own SQL — a typo in
``upgrade()`` or a missing DROP in ``downgrade()`` would slip through.

This test runs the real ``alembic upgrade head`` against a freshly-created
database, asserts the tables + indexes exist with their bare names, then
runs ``alembic downgrade`` back to the pre-features revision and asserts
they're gone. Mirrors the isolation pattern of
``scripts/tests/integration/test_alembic_parity.py`` (separate DB created
from the maintenance database, aggressive cleanup in ``finally``).
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_features_migration_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full upgrade head → downgrade 91337142414f roundtrip on a clean DB."""
    # conftest's autouse `clean_tables` invokes `db_conn`, which sets
    # PYTEST_SCHEMA=test_<hex>. env.py honors that and would land this
    # migration's tables inside that schema in our fresh roundtrip DB,
    # while we verify against `public`. We isolate via the per-test DB
    # name, not via PYTEST_SCHEMA — clear it for the duration of this test.
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_{suffix}"

    # Create the roundtrip database from the postgres maintenance DB so the
    # schema starts empty (no leftover tables from the shared DB).
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

    # The features migration FKs to ``users``; the baseline migration is
    # empty, so we build the users table via ORM create_all before the
    # features migration runs.
    from api.db_models import Base

    try:
        from sqlalchemy import create_engine
        engine = create_engine(roundtrip_url)
        # Create only the tables the features migration references. Using the
        # full metadata would also create features + feature_upvotes, which
        # would then collide with the migration's own op.create_table.
        dep_tables = [
            t for name, t in Base.metadata.tables.items()
            if name == "users"
        ]
        assert dep_tables, (
            "expected 'users' in Base.metadata; got "
            f"{list(Base.metadata.tables.keys())}"
        )
        Base.metadata.create_all(engine, tables=dep_tables)
        engine.dispose()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        # Stamp baseline so the features migration has a prior revision to
        # upgrade from. The baseline is empty, and the users table we just
        # create_all'd is the FK dependency the features migration expects.
        command.stamp(cfg, "91337142414f")

        # 1) UPGRADE through the features migration only. We don't want to
        # run the rename-style migrations here — they would try to rename
        # `*_prod`/`*_local` variants that don't exist in this roundtrip DB.
        command.upgrade(cfg, "050b9adc98e1")

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "features"), (
                "features missing after upgrade to 050b9adc98e1"
            )
            assert _table_exists(verify, "feature_upvotes"), (
                "feature_upvotes missing after upgrade to 050b9adc98e1"
            )
            assert _index_exists(verify, "idx_feature_upvotes_feature_id"), (
                "feature_id index missing after upgrade"
            )
            assert _index_exists(verify, "idx_feature_upvotes_user_id"), (
                "user_id index missing after upgrade"
            )
        finally:
            verify.close()

        # 2) DOWNGRADE to the baseline, reversing the features migration.
        command.downgrade(cfg, "91337142414f")

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert not _table_exists(verify, "features"), (
                "features still present after downgrade"
            )
            assert not _table_exists(verify, "feature_upvotes"), (
                "feature_upvotes still present after downgrade"
            )
            assert not _index_exists(verify, "idx_feature_upvotes_feature_id"), (
                "feature_id index still present after downgrade"
            )
            assert not _index_exists(verify, "idx_feature_upvotes_user_id"), (
                "user_id index still present after downgrade"
            )
            # Dependency table (``users``) must survive downgrade — the
            # revision only touches features/feature_upvotes.
            assert _table_exists(verify, "users"), (
                "users was unexpectedly dropped by downgrade"
            )
        finally:
            verify.close()

    finally:
        # Drop the roundtrip DB. Teardown keeps going past failures (so a
        # partial-upgrade-then-abort leaves no leftover DB on disk), but logs
        # rather than silently masking DROP failures — the 2026-04-19 volume
        # incident is the consequence of silent leaked state.
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
