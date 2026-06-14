"""Integration test: the feedback migration upgrades cleanly from its parent
revision and reverses cleanly via ``downgrade``.

Mirrors ``test_migration_features.py``: the shared ``db_conn`` fixture stamps
the alembic head and short-circuits every ``op.create_*`` body, so no normal
test exercises the migration's own SQL. This runs the real migration against a
freshly-created database.

The feedback migration's ``down_revision`` is ``c876c313e55c`` (a long chain
behind it). We avoid replaying that whole chain by ``create_all``-ing only the
FK dependency (``users``), stamping ``c876c313e55c``, then upgrading the single
step to the feedback revision.
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

_PARENT_REVISION = "c876c313e55c"
_FEEDBACK_REVISION = "b38c364cd0c4"


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
def test_feedback_migration_upgrade_and_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade to the feedback revision → downgrade roundtrip on a clean DB."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_fb_{suffix}"

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

    from api.db_models import Base

    try:
        from sqlalchemy import create_engine
        engine = create_engine(roundtrip_url)
        # The feedback migration FKs ``users``; create only that table so it
        # doesn't collide with the migration's own op.create_table('feedback').
        dep_tables = [
            t for name, t in Base.metadata.tables.items() if name == "users"
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

        # Stamp the parent so the feedback migration upgrades one step from it,
        # without replaying the whole chain (which would need companies/etc.).
        command.stamp(cfg, _PARENT_REVISION)

        command.upgrade(cfg, _FEEDBACK_REVISION)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "feedback"), "feedback missing after upgrade"
            assert _index_exists(verify, "idx_feedback_user_id"), (
                "idx_feedback_user_id missing after upgrade"
            )
            assert _index_exists(verify, "idx_feedback_created_at"), (
                "idx_feedback_created_at missing after upgrade"
            )
        finally:
            verify.close()

        command.downgrade(cfg, _PARENT_REVISION)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert not _table_exists(verify, "feedback"), (
                "feedback still present after downgrade"
            )
            assert not _index_exists(verify, "idx_feedback_user_id"), (
                "idx_feedback_user_id still present after downgrade"
            )
            assert not _index_exists(verify, "idx_feedback_created_at"), (
                "idx_feedback_created_at still present after downgrade"
            )
            # Dependency table (``users``) must survive the downgrade.
            assert _table_exists(verify, "users"), (
                "users was unexpectedly dropped by downgrade"
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
