"""Integration test: the companies schema + seed migrations upgrade cleanly
from 2da4b99b39ea (admins), then reverse cleanly via downgrade -2, then re-upgrade.

The existing `conftest.py::db_conn` fixture bootstraps tables via
``Base.metadata.create_all`` + ``stamp_alembic_head``, which deliberately
short-circuits every ``op.create_*`` body in every revision. That means no
existing test ever exercises the migration files' own SQL — a typo in
``upgrade()`` or a missing DROP in ``downgrade()`` would slip through.

This test runs the real ``alembic upgrade`` and ``alembic downgrade``
commands against a freshly-created database. Mirrors test_migration_features.py.
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

SCHEMA_REV = "438ad0658e53"
SEED_REV = "939331c99a23"
PREV_HEAD = "2da4b99b39ea"
ASHBY_SEED_REV = "a17b7c0ffee500"
ASHBY_PREV_HEAD = "ebb479b7eed5"
LEVER_SEED_REV = "b29cd1eef0aab1"
LEVER_PREV_HEAD = ASHBY_SEED_REV
GEM_SEED_REV = "b29c1ef8800600"
# GEM_PREV_HEAD is the Lever seed — Gem chains directly off Lever
# (Lever landed on main first, so the chain is Ashby → Lever → Gem).
GEM_PREV_HEAD = LEVER_SEED_REV
EIGHTFOLD_SEED_REV = "08e719b2aa03"
# Eightfold's down_revision was rebased from ASHBY_SEED_REV to GEM_SEED_REV
# during the PR #124 → main merge so Alembic has a single head.
EIGHTFOLD_PREV_HEAD = GEM_SEED_REV
WORKDAY_SEED_REV = "b9714f608e21"
# Workday's down_revision was rebased from GEM_SEED_REV to EIGHTFOLD_SEED_REV
# during the PR #123 → main merge so Alembic has a single head. Eightfold's
# migration owns the `provider_config` column add; Workday's migration reuses
# it (no op.add_column / op.drop_column on the Workday side).
WORKDAY_PREV_HEAD = EIGHTFOLD_SEED_REV
EXPECTED_WORKDAY_ROW_COUNT = 11
WORKDAY_PROVIDER_CONFIG_REQUIRED_KEYS = (
    "base_url", "tenant_slug", "career_site_slug",
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


def _greenhouse_row_count(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT count(*) AS c FROM companies WHERE ats = 'greenhouse'")
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"]) if isinstance(row, dict) else int(row[0])


def _ashby_row_count(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT count(*) AS c FROM companies WHERE ats = 'ashby'")
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"]) if isinstance(row, dict) else int(row[0])


def _lever_row_count(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT count(*) AS c FROM companies WHERE ats = 'lever'")
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"]) if isinstance(row, dict) else int(row[0])


def _gem_row_count(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT count(*) AS c FROM companies WHERE ats = 'gem'")
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"]) if isinstance(row, dict) else int(row[0])


def _eightfold_row_count(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT count(*) AS c FROM companies WHERE ats = 'eightfold'")
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"]) if isinstance(row, dict) else int(row[0])


def _workday_row_count(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT count(*) AS c FROM companies WHERE ats = 'workday'")
    row = cur.fetchone()
    if row is None:
        return 0
    return int(row["c"]) if isinstance(row, dict) else int(row[0])


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
def test_companies_migration_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full upgrade head → downgrade -2 → upgrade head on a clean DB."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_companies_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        # Stamp PREV_HEAD so the companies migrations have a prior revision to
        # upgrade from. We skip the upstream rename-style migrations because
        # they try to rename `*_prod`/`*_local` variants that don't exist in
        # this fresh roundtrip DB.
        command.stamp(cfg, PREV_HEAD)

        command.upgrade(cfg, SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "companies"), (
                f"companies missing after upgrade to {SEED_REV}"
            )
            assert _index_exists(verify, "ix_companies_ats_enabled"), (
                "ix_companies_ats_enabled index missing after upgrade"
            )
            assert _greenhouse_row_count(verify) == 45, (
                f"expected 45 greenhouse rows after seed, got "
                f"{_greenhouse_row_count(verify)}"
            )
        finally:
            verify.close()

        command.downgrade(cfg, PREV_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert not _table_exists(verify, "companies"), (
                "companies still present after downgrade -2"
            )
            assert not _index_exists(verify, "ix_companies_ats_enabled"), (
                "ix_companies_ats_enabled still present after downgrade -2"
            )
        finally:
            verify.close()

        command.upgrade(cfg, SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "companies"), (
                "companies missing after re-upgrade"
            )
            assert _greenhouse_row_count(verify) == 45, (
                f"expected 45 greenhouse rows after re-upgrade, got "
                f"{_greenhouse_row_count(verify)}"
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_companies_seed_migration_preserves_pre_existing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I2: a non-greenhouse `companies` row written out-of-band (e.g.
    operator hotfix) must survive both the upgrade-to-seed AND the
    -1 downgrade. If the downgrade ever regresses to `TRUNCATE
    companies` it would silently wipe unrelated rows; this test
    catches that. Uses ats='workday' as the alien value because
    'lever' and 'ashby' are now real seed ats values."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_companies_pre_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        # Upgrade only as far as the schema migration (companies table
        # exists, no greenhouse seed yet) so we can inject a pre-existing
        # row that pre-dates the seed migration.
        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SCHEMA_REV)

        seed_conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed_conn.autocommit = True
        try:
            seed_cur = seed_conn.cursor()
            seed_cur.execute(
                "INSERT INTO companies (id, display_name, ats, board_token) "
                "VALUES (%s, %s, %s, %s)",
                ("preexisting_workday_co", "Pre-Existing", "workday", "preexisting"),
            )
        finally:
            seed_conn.close()

        # Now run the seed migration on top.
        command.upgrade(cfg, SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, "pre-existing workday row was wiped by seed upgrade"
            assert _greenhouse_row_count(verify) == 45
        finally:
            verify.close()

        # Downgrade -1 (just the seed). The pre-existing workday row must
        # still be there; the 45 greenhouse rows must be gone.
        command.downgrade(cfg, SCHEMA_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, (
                "pre-existing workday row was wiped by seed downgrade — "
                "downgrade must scope DELETE to ats='greenhouse', not TRUNCATE"
            )
            assert _greenhouse_row_count(verify) == 0
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_ashby_seed_migration_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full upgrade PREV_HEAD -> ASHBY_SEED_REV -> downgrade -1 -> upgrade
    on a clean DB. Asserts the Ashby seed adds 46 rows on top of the
    existing 45 Greenhouse rows, and that the downgrade is scoped to
    ats='ashby' (Greenhouse rows untouched)."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_ashby_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        # Two-step bootstrap:
        # 1. Stamp PREV_HEAD then upgrade to SEED_REV so the companies
        #    table is materialized and the 45 Greenhouse rows exist.
        # 2. Stamp ASHBY_PREV_HEAD to skip the intermediate
        #    job_listings-touching migrations (which would require a
        #    job_listings table this fresh DB doesn't have), then
        #    upgrade to ASHBY_SEED_REV.
        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, ASHBY_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "companies"), (
                f"companies missing after upgrade to {ASHBY_SEED_REV}"
            )
            assert _ashby_row_count(verify) == 46, (
                f"expected 46 ashby rows after seed, got "
                f"{_ashby_row_count(verify)}"
            )
            assert _greenhouse_row_count(verify) == 45, (
                f"expected 45 greenhouse rows alongside ashby seed, got "
                f"{_greenhouse_row_count(verify)}"
            )
        finally:
            verify.close()

        # Downgrade -1 (just the Ashby seed). Stop at ASHBY_PREV_HEAD so
        # we don't walk through the job_listings-touching downgrades that
        # would fail in this fresh DB. Greenhouse rows must survive.
        command.downgrade(cfg, ASHBY_PREV_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _ashby_row_count(verify) == 0, (
                f"expected 0 ashby rows after ashby seed downgrade, got "
                f"{_ashby_row_count(verify)}"
            )
            assert _greenhouse_row_count(verify) == 45, (
                "Greenhouse rows were wiped by ashby seed downgrade — "
                "downgrade must scope DELETE to ats='ashby'"
            )
        finally:
            verify.close()

        # Re-upgrade. Ashby seed must be idempotent.
        command.upgrade(cfg, ASHBY_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _ashby_row_count(verify) == 46, (
                f"expected 46 ashby rows after re-upgrade, got "
                f"{_ashby_row_count(verify)}"
            )
            assert _greenhouse_row_count(verify) == 45
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_ashby_seed_migration_preserves_pre_existing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-ashby `companies` row written out-of-band (e.g. operator
    hotfix inserting a workday entry) must survive both the upgrade-to-
    ashby-seed AND the -1 downgrade. Same shape as
    test_companies_seed_migration_preserves_pre_existing_rows but for
    the Ashby seed; guarantees the downgrade's WHERE-clause stays scoped
    to ats='ashby'."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_ashby_pre_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        # Upgrade to the Greenhouse seed first (companies table exists,
        # 45 greenhouse rows present, no ashby rows yet). Inject a
        # pre-existing workday row to verify the ashby seed leaves it alone.
        # ('workday' chosen because it is NOT a real seed ats value — using
        # 'lever' here would conflict with the Lever seed test below.)
        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)

        seed_conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed_conn.autocommit = True
        try:
            seed_cur = seed_conn.cursor()
            seed_cur.execute(
                "INSERT INTO companies (id, display_name, ats, board_token) "
                "VALUES (%s, %s, %s, %s)",
                ("preexisting_workday_co", "Pre-Existing", "workday", "preexisting"),
            )
        finally:
            seed_conn.close()

        # Stamp ASHBY_PREV_HEAD to skip the intermediate
        # job_listings-touching migrations (which would require a
        # job_listings table this fresh DB doesn't have), then run the
        # Ashby seed on top.
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, ASHBY_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, "pre-existing workday row was wiped by ashby seed upgrade"
            assert _greenhouse_row_count(verify) == 45
            assert _ashby_row_count(verify) == 46
        finally:
            verify.close()

        # Downgrade -1 (just the ashby seed). Stop at ASHBY_PREV_HEAD so
        # we don't walk through the job_listings-touching downgrades that
        # would fail in this fresh DB. The pre-existing workday row and
        # the 45 greenhouse rows must still be there; the 46 ashby rows
        # must be gone.
        command.downgrade(cfg, ASHBY_PREV_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, (
                "pre-existing workday row was wiped by ashby seed downgrade — "
                "downgrade must scope DELETE to ats='ashby', not TRUNCATE"
            )
            assert _greenhouse_row_count(verify) == 45, (
                "Greenhouse rows were wiped by ashby seed downgrade — "
                "downgrade must scope DELETE to ats='ashby'"
            )
            assert _ashby_row_count(verify) == 0
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_lever_seed_migration_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full upgrade PREV_HEAD -> LEVER_SEED_REV -> downgrade -1 -> upgrade
    on a clean DB. Asserts the Lever seed adds 3 rows on top of the
    existing 45 Greenhouse + 46 Ashby rows, and that the downgrade is
    scoped to ats='lever' (Greenhouse + Ashby rows untouched)."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_lever_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        # Three-step bootstrap (mirrors test_ashby_seed_migration_roundtrip):
        # 1. Stamp PREV_HEAD + upgrade to SEED_REV (Greenhouse rows seeded).
        # 2. Stamp ASHBY_PREV_HEAD + upgrade to ASHBY_SEED_REV (Ashby rows seeded).
        # 3. Upgrade to LEVER_SEED_REV (LEVER_PREV_HEAD == ASHBY_SEED_REV, so no extra stamp needed).
        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, ASHBY_SEED_REV)
        command.upgrade(cfg, LEVER_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "companies"), (
                f"companies missing after upgrade to {LEVER_SEED_REV}"
            )
            assert _lever_row_count(verify) == 3, (
                f"expected 3 lever rows after seed, got "
                f"{_lever_row_count(verify)}"
            )
            assert _ashby_row_count(verify) == 46, (
                f"expected 46 ashby rows alongside lever seed, got "
                f"{_ashby_row_count(verify)}"
            )
            assert _greenhouse_row_count(verify) == 45, (
                f"expected 45 greenhouse rows alongside lever seed, got "
                f"{_greenhouse_row_count(verify)}"
            )
        finally:
            verify.close()

        # Downgrade -1 (just the Lever seed). Ashby + Greenhouse rows
        # must survive.
        command.downgrade(cfg, LEVER_PREV_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _lever_row_count(verify) == 0, (
                f"expected 0 lever rows after lever seed downgrade, got "
                f"{_lever_row_count(verify)}"
            )
            assert _ashby_row_count(verify) == 46, (
                "Ashby rows were wiped by lever seed downgrade — "
                "downgrade must scope DELETE to ats='lever'"
            )
            assert _greenhouse_row_count(verify) == 45, (
                "Greenhouse rows were wiped by lever seed downgrade — "
                "downgrade must scope DELETE to ats='lever'"
            )
        finally:
            verify.close()

        # Re-upgrade. Lever seed must be idempotent.
        command.upgrade(cfg, LEVER_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _lever_row_count(verify) == 3, (
                f"expected 3 lever rows after re-upgrade, got "
                f"{_lever_row_count(verify)}"
            )
            assert _ashby_row_count(verify) == 46
            assert _greenhouse_row_count(verify) == 45
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_lever_seed_migration_preserves_pre_existing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-lever `companies` row written out-of-band must survive both
    the upgrade-to-lever-seed AND the -1 downgrade. Guarantees the Lever
    seed's downgrade WHERE-clause stays scoped to ats='lever'."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_lever_pre_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, ASHBY_SEED_REV)

        # Inject a pre-existing workday row before the Lever seed runs.
        seed_conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed_conn.autocommit = True
        try:
            seed_cur = seed_conn.cursor()
            seed_cur.execute(
                "INSERT INTO companies (id, display_name, ats, board_token) "
                "VALUES (%s, %s, %s, %s)",
                ("preexisting_workday_co2", "Pre-Existing", "workday", "preexisting"),
            )
        finally:
            seed_conn.close()

        command.upgrade(cfg, LEVER_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co2",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, "pre-existing workday row was wiped by lever seed upgrade"
            assert _lever_row_count(verify) == 3
            assert _ashby_row_count(verify) == 46
            assert _greenhouse_row_count(verify) == 45
        finally:
            verify.close()

        command.downgrade(cfg, LEVER_PREV_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co2",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, (
                "pre-existing workday row was wiped by lever seed downgrade — "
                "downgrade must scope DELETE to ats='lever', not TRUNCATE"
            )
            assert _lever_row_count(verify) == 0
            assert _ashby_row_count(verify) == 46, (
                "Ashby rows were wiped by lever seed downgrade — "
                "downgrade must scope DELETE to ats='lever'"
            )
            assert _greenhouse_row_count(verify) == 45, (
                "Greenhouse rows were wiped by lever seed downgrade — "
                "downgrade must scope DELETE to ats='lever'"
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_gem_seed_migration_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full upgrade PREV_HEAD -> LEVER_SEED_REV -> GEM_SEED_REV ->
    downgrade -1 -> re-upgrade on a clean DB. Asserts the Gem seed
    adds 3 rows on top of the existing Greenhouse + Ashby + Lever
    rows, and that the downgrade is scoped to ats='gem' (other rows
    untouched)."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_gem_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        # Four-step bootstrap:
        # 1. Stamp PREV_HEAD + upgrade to SEED_REV (Greenhouse rows seeded).
        # 2. Stamp ASHBY_PREV_HEAD + upgrade to ASHBY_SEED_REV (Ashby rows seeded).
        # 3. Upgrade to LEVER_SEED_REV (LEVER_PREV_HEAD == ASHBY_SEED_REV).
        # 4. Upgrade to GEM_SEED_REV (GEM_PREV_HEAD == LEVER_SEED_REV).
        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, ASHBY_SEED_REV)
        command.upgrade(cfg, LEVER_SEED_REV)
        command.upgrade(cfg, GEM_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "companies"), (
                f"companies missing after upgrade to {GEM_SEED_REV}"
            )
            assert _gem_row_count(verify) == 3, (
                f"expected 3 gem rows after seed, got "
                f"{_gem_row_count(verify)}"
            )
            assert _lever_row_count(verify) == 3, (
                f"expected 3 lever rows alongside gem seed, got "
                f"{_lever_row_count(verify)}"
            )
            assert _ashby_row_count(verify) == 46, (
                f"expected 46 ashby rows alongside gem seed, got "
                f"{_ashby_row_count(verify)}"
            )
            assert _greenhouse_row_count(verify) == 45, (
                f"expected 45 greenhouse rows alongside gem seed, got "
                f"{_greenhouse_row_count(verify)}"
            )
        finally:
            verify.close()

        # Downgrade -1 (just the Gem seed). Lever, Ashby, and Greenhouse
        # rows must survive.
        command.downgrade(cfg, GEM_PREV_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _gem_row_count(verify) == 0, (
                f"expected 0 gem rows after gem seed downgrade, got "
                f"{_gem_row_count(verify)}"
            )
            assert _lever_row_count(verify) == 3, (
                "Lever rows were wiped by gem seed downgrade — "
                "downgrade must scope DELETE to ats='gem'"
            )
            assert _ashby_row_count(verify) == 46, (
                "Ashby rows were wiped by gem seed downgrade — "
                "downgrade must scope DELETE to ats='gem'"
            )
            assert _greenhouse_row_count(verify) == 45, (
                "Greenhouse rows were wiped by gem seed downgrade — "
                "downgrade must scope DELETE to ats='gem'"
            )
        finally:
            verify.close()

        # Re-upgrade. Gem seed must be idempotent.
        command.upgrade(cfg, GEM_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _gem_row_count(verify) == 3, (
                f"expected 3 gem rows after re-upgrade, got "
                f"{_gem_row_count(verify)}"
            )
            assert _lever_row_count(verify) == 3
            assert _ashby_row_count(verify) == 46
            assert _greenhouse_row_count(verify) == 45
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_gem_seed_migration_preserves_pre_existing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-gem `companies` row written out-of-band must survive both
    the upgrade-to-gem-seed AND the -1 downgrade. Guarantees the Gem
    seed's downgrade WHERE-clause stays scoped to ats='gem'."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_gem_pre_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, ASHBY_SEED_REV)
        command.upgrade(cfg, LEVER_SEED_REV)

        # Inject a pre-existing workday row before the Gem seed runs.
        seed_conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed_conn.autocommit = True
        try:
            seed_cur = seed_conn.cursor()
            seed_cur.execute(
                "INSERT INTO companies (id, display_name, ats, board_token) "
                "VALUES (%s, %s, %s, %s)",
                ("preexisting_workday_co3", "Pre-Existing", "workday", "preexisting"),
            )
        finally:
            seed_conn.close()

        command.upgrade(cfg, GEM_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co3",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, "pre-existing workday row was wiped by gem seed upgrade"
            assert _gem_row_count(verify) == 3
            assert _lever_row_count(verify) == 3
            assert _ashby_row_count(verify) == 46
            assert _greenhouse_row_count(verify) == 45
        finally:
            verify.close()

        command.downgrade(cfg, GEM_PREV_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co3",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, (
                "pre-existing workday row was wiped by gem seed downgrade — "
                "downgrade must scope DELETE to ats='gem', not TRUNCATE"
            )
            assert _gem_row_count(verify) == 0
            assert _lever_row_count(verify) == 3, (
                "Lever rows were wiped by gem seed downgrade — "
                "downgrade must scope DELETE to ats='gem'"
            )
            assert _ashby_row_count(verify) == 46, (
                "Ashby rows were wiped by gem seed downgrade — "
                "downgrade must scope DELETE to ats='gem'"
            )
            assert _greenhouse_row_count(verify) == 45, (
                "Greenhouse rows were wiped by gem seed downgrade — "
                "downgrade must scope DELETE to ats='gem'"
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_eightfold_seed_migration_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full upgrade PREV_HEAD -> SEED_REV -> ASHBY_SEED_REV -> LEVER_SEED_REV
    -> GEM_SEED_REV -> EIGHTFOLD_SEED_REV -> downgrade -1 -> re-upgrade on a
    clean DB.

    Eightfold's ``down_revision`` was rebased to ``b29c1ef8800600`` (Gem)
    during the merge of PR #124, so the bootstrap walks the full chain
    through Lever and Gem before applying the Eightfold migration.

    Asserts:
      - The Eightfold seed adds 1 Netflix row alongside the other seeded ATSes
      - The ``provider_config`` column is added by the Eightfold migration
      - Netflix's ``provider_config`` carries both ``tenant_host`` and ``domain``
      - The downgrade is scoped to ats='eightfold' (Lever, Gem, Ashby, Greenhouse untouched)
      - The downgrade drops the ``provider_config`` column cleanly
      - Re-upgrade is idempotent
    """
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_eightfold_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, ASHBY_SEED_REV)
        command.upgrade(cfg, LEVER_SEED_REV)
        command.upgrade(cfg, GEM_SEED_REV)
        command.upgrade(cfg, EIGHTFOLD_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _table_exists(verify, "companies")
            assert _column_exists(verify, "companies", "provider_config"), (
                "provider_config column missing after Eightfold migration"
            )
            assert _eightfold_row_count(verify) == 1
            assert _gem_row_count(verify) == 3
            assert _lever_row_count(verify) == 3
            assert _ashby_row_count(verify) == 46
            assert _greenhouse_row_count(verify) == 45

            cur = verify.cursor()
            cur.execute(
                "SELECT id, provider_config FROM companies "
                "WHERE ats = 'eightfold'"
            )
            rows = cur.fetchall()
            assert len(rows) == 1
            row = rows[0]
            assert row["id"] == "netflix"
            cfg_blob = row["provider_config"]
            assert cfg_blob.get("tenant_host") == "explore.jobs.netflix.net", (
                "Netflix tenant_host must match the SSRF-allowlisted vanity host"
            )
            assert cfg_blob.get("domain") == "netflix.com"

            cur.execute(
                "SELECT count(*) AS c FROM companies "
                "WHERE ats IN ('greenhouse', 'ashby', 'lever', 'gem') "
                "AND provider_config = '{}'::jsonb"
            )
            default_count = cur.fetchone()
            assert int(default_count["c"]) == 45 + 46 + 3 + 3, (
                "Pre-Eightfold rows must get the empty {} provider_config default"
            )
        finally:
            verify.close()

        # Downgrade -1 (just the Eightfold migration). Pre-Eightfold rows
        # must survive; the provider_config column must be dropped cleanly.
        command.downgrade(cfg, GEM_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _eightfold_row_count(verify) == 0
            assert _gem_row_count(verify) == 3, (
                "Gem rows were wiped by Eightfold downgrade — "
                "downgrade must scope DELETE to ats='eightfold'"
            )
            assert _lever_row_count(verify) == 3, (
                "Lever rows were wiped by Eightfold downgrade — "
                "downgrade must scope DELETE to ats='eightfold'"
            )
            assert _ashby_row_count(verify) == 46
            assert _greenhouse_row_count(verify) == 45
            assert not _column_exists(verify, "companies", "provider_config")
        finally:
            verify.close()

        # Re-upgrade. Eightfold seed must be idempotent (ON CONFLICT DO NOTHING).
        command.upgrade(cfg, EIGHTFOLD_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _eightfold_row_count(verify) == 1
            assert _column_exists(verify, "companies", "provider_config")
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_eightfold_seed_migration_preserves_pre_existing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An out-of-band non-eightfold row (operator hotfix, prior partial
    backfill) must survive both the Eightfold seed upgrade AND its -1
    downgrade. Catches regressions in the WHERE-clause scope of the
    downgrade — ats='eightfold', NOT TRUNCATE.

    Uses ats='workday' as the alien value because every other migrated
    ats ('lever', 'gem', 'ashby', 'greenhouse', 'eightfold') is now a real
    seed value."""
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_eightfold_pre_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, ASHBY_SEED_REV)
        command.upgrade(cfg, LEVER_SEED_REV)
        command.upgrade(cfg, GEM_SEED_REV)

        # Inject a pre-existing workday row before the Eightfold seed runs.
        seed_conn = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        seed_conn.autocommit = True
        try:
            seed_cur = seed_conn.cursor()
            seed_cur.execute(
                "INSERT INTO companies (id, display_name, ats, board_token) "
                "VALUES (%s, %s, %s, %s)",
                ("preexisting_workday_co_eightfold", "Pre-Existing", "workday", "preexisting"),
            )
        finally:
            seed_conn.close()

        command.upgrade(cfg, EIGHTFOLD_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co_eightfold",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, (
                "pre-existing workday row was wiped by eightfold seed upgrade"
            )
            assert _eightfold_row_count(verify) == 1
            assert _gem_row_count(verify) == 3
            assert _lever_row_count(verify) == 3
            assert _ashby_row_count(verify) == 46
            assert _greenhouse_row_count(verify) == 45
        finally:
            verify.close()

        command.downgrade(cfg, GEM_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            cur = verify.cursor()
            cur.execute(
                "SELECT count(*) AS c FROM companies WHERE id = %s",
                ("preexisting_workday_co_eightfold",),
            )
            row = cur.fetchone()
            assert row["c"] == 1, (
                "pre-existing workday row was wiped by eightfold seed downgrade — "
                "downgrade must scope DELETE to ats='eightfold', not TRUNCATE"
            )
            assert _eightfold_row_count(verify) == 0
            assert _gem_row_count(verify) == 3
            assert _lever_row_count(verify) == 3
            assert _ashby_row_count(verify) == 46
            assert _greenhouse_row_count(verify) == 45
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_workday_seed_migration_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workday migration: seed 11 Workday rows on top of the existing
    `provider_config` column (added by the Eightfold migration upstream).

    After the PR #123 → main merge Workday's ``down_revision`` chains off
    Eightfold's ``08e719b2aa03``; the Workday migration body no longer
    adds or drops ``provider_config`` (Eightfold owns it). The roundtrip
    therefore asserts:

      - The Workday seed adds 11 rows alongside the already-seeded ATSes.
      - Every Workday row has the three required keys (`base_url`,
        `tenant_slug`, `career_site_slug`) in `provider_config`.
      - The downgrade is scoped to ``ats='workday'`` — Eightfold, Gem,
        Lever, Ashby, Greenhouse counts all survive.
      - The downgrade leaves the ``provider_config`` column in place
        (Eightfold's migration owns the column).
      - Re-upgrade is idempotent.
    """
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_workday_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        # Bootstrap the full chain through Eightfold so the
        # `provider_config` column already exists when the Workday seed
        # runs.
        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, WORKDAY_PREV_HEAD)

        # Apply the Workday seed migration.
        command.upgrade(cfg, WORKDAY_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _column_exists(verify, "companies", "provider_config"), (
                "provider_config column missing after upgrade to "
                f"{WORKDAY_SEED_REV}"
            )
            assert _workday_row_count(verify) == EXPECTED_WORKDAY_ROW_COUNT, (
                f"expected {EXPECTED_WORKDAY_ROW_COUNT} workday rows after "
                f"seed, got {_workday_row_count(verify)}"
            )
            # All 11 Workday rows MUST have the three required keys in
            # provider_config — the per-company task reads these and
            # raises ValueError if any are missing.
            cur = verify.cursor()
            cur.execute(
                "SELECT id, provider_config FROM companies "
                "WHERE ats = 'workday' ORDER BY id"
            )
            for row in cur.fetchall():
                cfg_dict = row["provider_config"]
                assert isinstance(cfg_dict, dict), (
                    f"provider_config for {row['id']!r} is not a dict: "
                    f"{type(cfg_dict).__name__}"
                )
                for k in WORKDAY_PROVIDER_CONFIG_REQUIRED_KEYS:
                    assert k in cfg_dict and cfg_dict[k], (
                        f"workday row {row['id']!r} missing required "
                        f"provider_config key {k!r} (or value is falsy): "
                        f"{cfg_dict!r}"
                    )
            assert _greenhouse_row_count(verify) == 45, (
                f"Greenhouse row count drifted during workday upgrade: "
                f"{_greenhouse_row_count(verify)}"
            )
            assert _ashby_row_count(verify) == 46, (
                f"Ashby row count drifted during workday upgrade: "
                f"{_ashby_row_count(verify)}"
            )
            assert _eightfold_row_count(verify) == 1, (
                f"Eightfold row count drifted during workday upgrade: "
                f"{_eightfold_row_count(verify)}"
            )
        finally:
            verify.close()

        # Downgrade -1: workday rows gone, column remains (Eightfold owns it),
        # other ATSes untouched.
        command.downgrade(cfg, WORKDAY_PREV_HEAD)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _column_exists(verify, "companies", "provider_config"), (
                "provider_config column should still exist after workday "
                "downgrade — Eightfold's migration owns the column"
            )
            assert _workday_row_count(verify) == 0, (
                f"expected 0 workday rows after downgrade, got "
                f"{_workday_row_count(verify)}"
            )
            assert _eightfold_row_count(verify) == 1, (
                "Eightfold rows were wiped by workday seed downgrade — "
                "downgrade must scope DELETE to ats='workday'"
            )
            assert _greenhouse_row_count(verify) == 45, (
                "Greenhouse rows were wiped by workday seed downgrade — "
                "downgrade must scope DELETE to ats='workday'"
            )
            assert _ashby_row_count(verify) == 46, (
                "Ashby rows were wiped by workday seed downgrade — "
                "downgrade must scope DELETE to ats='workday'"
            )
        finally:
            verify.close()

        # Re-upgrade — must be idempotent.
        command.upgrade(cfg, WORKDAY_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _workday_row_count(verify) == EXPECTED_WORKDAY_ROW_COUNT, (
                f"expected {EXPECTED_WORKDAY_ROW_COUNT} workday rows after "
                f"re-upgrade, got {_workday_row_count(verify)}"
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


@pytest.mark.skipif(
    _is_prod_like(TEST_DB_URL),
    reason="refusing to run migration roundtrip against a prod-like TEST_DATABASE_URL",
)
def test_workday_seed_migration_preserves_pre_existing_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workday upgrade must not disturb rows seeded by earlier migrations
    (Greenhouse, Ashby, Lever, Gem, Eightfold).
    """
    monkeypatch.delenv("PYTEST_SCHEMA", raising=False)

    suffix = uuid.uuid4().hex[:8]
    roundtrip_db = f"migrate_workday_preexisting_{suffix}"

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

    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", roundtrip_url)
        cfg.set_main_option("script_location", str(_SCRIPT_LOCATION))
        cfg.config_file_name = None

        command.stamp(cfg, PREV_HEAD)
        command.upgrade(cfg, SEED_REV)
        command.stamp(cfg, ASHBY_PREV_HEAD)
        command.upgrade(cfg, WORKDAY_PREV_HEAD)

        gh_before = ash_before = lev_before = gem_before = ef_before = 0
        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            gh_before = _greenhouse_row_count(verify)
            ash_before = _ashby_row_count(verify)
            lev_before = _lever_row_count(verify)
            gem_before = _gem_row_count(verify)
            ef_before = _eightfold_row_count(verify)
        finally:
            verify.close()

        command.upgrade(cfg, WORKDAY_SEED_REV)

        verify = psycopg2.connect(roundtrip_url, cursor_factory=RealDictCursor)
        try:
            assert _greenhouse_row_count(verify) == gh_before, (
                "Greenhouse row count changed during workday upgrade"
            )
            assert _ashby_row_count(verify) == ash_before, (
                "Ashby row count changed during workday upgrade"
            )
            assert _lever_row_count(verify) == lev_before, (
                "Lever row count changed during workday upgrade"
            )
            assert _gem_row_count(verify) == gem_before, (
                "Gem row count changed during workday upgrade"
            )
            assert _eightfold_row_count(verify) == ef_before, (
                "Eightfold row count changed during workday upgrade"
            )
            assert _workday_row_count(verify) == EXPECTED_WORKDAY_ROW_COUNT
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
