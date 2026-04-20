"""Integration test: the features+upvotes migration upgrades cleanly from the
baseline and then reverses cleanly via ``downgrade -1``.

The existing `conftest.py::db_conn` fixture bootstraps tables via
``Base.metadata.create_all`` + ``stamp_alembic_head``, which deliberately
short-circuits every ``op.create_*`` body in every revision. That means no
existing test ever exercises the migration file's own SQL — a typo in
``upgrade()`` or a missing DROP in ``downgrade()`` would slip through.

This test runs the real ``alembic upgrade head`` against a freshly-created
database, asserts the tables + indexes exist with the expected env suffix,
then runs ``alembic downgrade -1`` and asserts they're gone. Mirrors the
isolation pattern of ``scripts/tests/integration/test_alembic_parity.py``
(unique ``test_<hex>`` env, separate DB created from the maintenance
database, aggressive cleanup in ``finally``).
"""

from __future__ import annotations

import importlib
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
    """Full upgrade head → downgrade -1 roundtrip on a clean DB."""
    test_env = f"test_{uuid.uuid4().hex[:8]}"
    roundtrip_db = f"migrate_{test_env}"

    # Prime SCRAPER_ENVIRONMENT to a valid value so api.config's module-level
    # settings construction at import time succeeds; then widen
    # ALLOWED_ENVIRONMENTS and rebuild the singleton so alembic/env.py and
    # the migration module see the test env when they run.
    monkeypatch.setenv("SCRAPER_ENVIRONMENT", "local")
    import api.config as _api_config
    monkeypatch.setattr(
        _api_config,
        "ALLOWED_ENVIRONMENTS",
        _api_config.ALLOWED_ENVIRONMENTS | {test_env},
    )
    monkeypatch.setenv("SCRAPER_ENVIRONMENT", test_env)
    monkeypatch.setattr(_api_config, "settings", _api_config.Settings())

    # Create the roundtrip database from the postgres maintenance DB so the
    # schema starts empty (no leftover *_local tables from the shared DB).
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

    # The feature-voting migration FKs to users_<env>; the baseline migration
    # would create that table but the baseline is intentionally empty. Build
    # the users table via ORM create_all before the features migration runs.
    # Same approach the main fixture uses — reload db_models under the test
    # env so its tables resolve to users_<env>.
    import api.db_models
    importlib.reload(api.db_models)
    from api.db_models import Base

    try:
        from sqlalchemy import create_engine
        engine = create_engine(roundtrip_url)
        # Create only the tables the features migration references. We can't
        # use the full metadata here because features+feature_upvotes are also
        # in Base.metadata — create_all would create them and then alembic
        # upgrade would hit DuplicateTable. Filter to the deps only.
        dep_tables = [
            t for name, t in Base.metadata.tables.items()
            if name == f"users_{test_env}"
        ]
        assert dep_tables, (
            f"expected users_{test_env} in Base.metadata after reload; "
            f"got {list(Base.metadata.tables.keys())}"
        )
        Base.metadata.create_all(engine, tables=dep_tables)
        engine.dispose()

        # Stamp the baseline so the features migration can find a prior
        # revision to upgrade FROM. Then run the real upgrade head to exercise
        # the migration body. Finally run downgrade -1 to exercise the inverse.
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        # Stamp baseline (91337142414f). Can't upgrade from scratch because
        # the baseline is a no-op and the feature tables' FK to users_<env>
        # requires that table to exist first (which we just create_all'd).
        command.stamp(cfg, "91337142414f")

        # 1) UPGRADE: run the actual op.create_table bodies.
        command.upgrade(cfg, "head")

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, f"features_{test_env}"), (
                f"features_{test_env} missing after upgrade head"
            )
            assert _table_exists(verify, f"feature_upvotes_{test_env}"), (
                f"feature_upvotes_{test_env} missing after upgrade head"
            )
            assert _index_exists(
                verify, f"idx_feature_upvotes_{test_env}_feature_id"
            ), "feature_id index missing after upgrade"
            assert _index_exists(
                verify, f"idx_feature_upvotes_{test_env}_user_id"
            ), "user_id index missing after upgrade"
        finally:
            verify.close()

        # 2) DOWNGRADE: reverse the most recent revision.
        command.downgrade(cfg, "-1")

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert not _table_exists(verify, f"features_{test_env}"), (
                f"features_{test_env} still present after downgrade -1"
            )
            assert not _table_exists(verify, f"feature_upvotes_{test_env}"), (
                f"feature_upvotes_{test_env} still present after downgrade -1"
            )
            assert not _index_exists(
                verify, f"idx_feature_upvotes_{test_env}_feature_id"
            ), "feature_id index still present after downgrade"
            assert not _index_exists(
                verify, f"idx_feature_upvotes_{test_env}_user_id"
            ), "user_id index still present after downgrade"
            # Dependency table (users_<env>) must survive downgrade — the
            # revision only touches features/feature_upvotes.
            assert _table_exists(verify, f"users_{test_env}"), (
                f"users_{test_env} was unexpectedly dropped by downgrade"
            )
        finally:
            verify.close()

    finally:
        # Restore db_models so sibling tests see the original env.
        os.environ["SCRAPER_ENVIRONMENT"] = "local"
        try:
            importlib.reload(api.db_models)
        except Exception:
            logging.getLogger(__name__).exception(
                "Failed to restore db_models after migration roundtrip test"
            )

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
