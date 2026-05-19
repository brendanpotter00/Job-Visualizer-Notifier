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
LEVER_PREV_HEAD = "a17b7c0ffee500"


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
