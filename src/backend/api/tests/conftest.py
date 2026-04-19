"""Test fixtures for FastAPI backend tests.

Uses a real PostgreSQL database with test-isolated tables (test_<hex> env pattern)
that are created before each test module and dropped after.
"""

import json
import logging
import os
import uuid

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from scripts.shared.database import _get_table_name
from api.migrations import apply_alembic_migrations

logger = logging.getLogger(__name__)

# Default test database URL (same as docker-compose)
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper",
)


def _make_test_env() -> str:
    """Generate a unique test environment name matching _TEST_ENV_PATTERN."""
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def test_env():
    """Unique environment name for this test module's tables."""
    return _make_test_env()


@pytest.fixture(scope="module")
def db_conn(test_env):
    """PostgreSQL connection with test tables created and cleaned up after."""
    # Alembic's env.py imports `from api.config import settings` at module load
    # time and reads settings.scraper_environment to compute the
    # alembic_version_<env> table name. api.config.Settings restricts
    # SCRAPER_ENVIRONMENT to {local, qa, prod}, so we (a) set SCRAPER_ENVIRONMENT
    # to a valid value first so the module-level `settings = Settings()` at
    # import time succeeds, (b) widen ALLOWED_ENVIRONMENTS in-process to include
    # this test_<hex> env, and (c) rebuild the module-level settings singleton
    # with the test env so env.py sees it. Mirrors the workaround in
    # scripts/tests/integration/test_alembic_parity.py — entirely in-process,
    # does not modify api/config.py on disk.
    #
    # Capture prev values BEFORE mutating anything so teardown can restore.
    # Otherwise the singleton + env vars leak across test modules.
    prev_database_url = os.environ.get("DATABASE_URL")
    prev_env_var = os.environ.get("SCRAPER_ENVIRONMENT")

    os.environ["DATABASE_URL"] = TEST_DB_URL
    os.environ["SCRAPER_ENVIRONMENT"] = "local"  # valid, temporary

    import api.config as _api_config
    prev_allowed = set(_api_config.ALLOWED_ENVIRONMENTS)
    prev_settings = _api_config.settings
    _api_config.ALLOWED_ENVIRONMENTS = _api_config.ALLOWED_ENVIRONMENTS | {test_env}
    os.environ["SCRAPER_ENVIRONMENT"] = test_env
    _api_config.settings = _api_config.Settings()

    # The Alembic baseline revision is intentionally empty (prod is already
    # stamped at this state — see PLAN.md / DEPLOY.md). Running
    # `alembic upgrade head` against a fresh test DB therefore creates only
    # `alembic_version_<env>`, not the actual job_listings/users/etc tables.
    # Bootstrap the schema from db_models.Base.metadata via SQLAlchemy
    # `create_all` (mirrors the Unit 6 parity test pattern), then call
    # apply_alembic_migrations so `alembic_version_<env>` is populated.
    #
    # _ENV in db_models is captured at import time, so we (1) reload the module
    # under SCRAPER_ENVIRONMENT=test_<hex> so its tables get the right suffix,
    # (2) create_all those tables, then (3) reload AGAIN under the original
    # local env so we don't pollute the global module for sibling fixtures
    # (test_db_models.py has its own `db_models_module` fixture that asserts
    # against `_local` table names; an autouse-triggered db_conn must not
    # leave the global db_models module pointed at a test_<hex> env).
    import importlib
    import sys
    import api.db_models as _db_models
    importlib.reload(_db_models)

    from sqlalchemy import create_engine
    engine = create_engine(TEST_DB_URL)
    _db_models.Base.metadata.create_all(engine)
    engine.dispose()

    # Restore db_models to the local-env baseline so other tests / fixtures
    # in this run see the global module the way it was before db_conn ran.
    os.environ["SCRAPER_ENVIRONMENT"] = "local"
    importlib.reload(_db_models)
    # Restore SCRAPER_ENVIRONMENT to the test env for the remainder of the
    # test module so api.config.settings + Alembic env.py keep targeting it.
    os.environ["SCRAPER_ENVIRONMENT"] = test_env

    conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
    apply_alembic_migrations(TEST_DB_URL, test_env)
    yield conn

    # Cleanup: drop test tables (children before parents to satisfy FK dependencies).
    # Each DROP is wrapped individually so a single failure doesn't cascade and
    # leak the rest, and env-var/settings restore is in a `finally` so it runs
    # even if every drop fails. Mirrors the pattern in scripts/tests/conftest.py
    # — the asymmetric version of this file was flagged in Pass 3 review as the
    # same silent-leak class the 2026-04-19 volume incident taught us to avoid.
    jobs_table = _get_table_name(test_env, "jobs")
    runs_table = _get_table_name(test_env, "runs")
    users_table = _get_table_name(test_env, "users")
    enabled_companies_table = f"user_enabled_companies_{test_env}"
    alembic_version_table = f"alembic_version_{test_env}"
    drop_errors: list[tuple[str, Exception]] = []
    try:
        cursor = conn.cursor()
        for tbl in (
            enabled_companies_table,
            jobs_table,
            runs_table,
            users_table,
            alembic_version_table,
        ):
            try:
                cursor.execute(
                    sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(tbl))
                )
                conn.commit()
            except Exception as drop_exc:
                conn.rollback()
                drop_errors.append((tbl, drop_exc))
    finally:
        conn.close()

        # Restore env vars and api.config singleton so sibling test modules don't
        # inherit our test_<hex> env. _api_config is the same module the rest of
        # the process imports — leaking ALLOWED_ENVIRONMENTS or `settings` from
        # one test module into another is exactly the cross-module contamination
        # pr-test-analyzer flagged. Must run even if every drop above failed,
        # else a DROP exception would also leak env state to sibling modules.
        if prev_env_var is None:
            os.environ.pop("SCRAPER_ENVIRONMENT", None)
        else:
            os.environ["SCRAPER_ENVIRONMENT"] = prev_env_var
        if prev_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_database_url
        _api_config.ALLOWED_ENVIRONMENTS = prev_allowed
        # Rebuild the singleton from the restored env so it reflects pre-fixture
        # state (rather than the test_<hex> Settings we constructed above).
        try:
            _api_config.settings = _api_config.Settings()
        except Exception:
            # If the restored env can't construct a Settings (e.g. SCRAPER_ENVIRONMENT
            # was unset and the default 'local' is no longer in ALLOWED_ENVIRONMENTS,
            # which shouldn't happen but guard anyway), log and fall back to the
            # captured singleton so we don't leave _api_config.settings broken.
            logger.exception(
                "Failed to rebuild api.config.settings after db_conn teardown; "
                "falling back to captured singleton"
            )
            _api_config.settings = prev_settings

    if drop_errors:
        for tbl, exc in drop_errors:
            logger.error("Failed to drop test table %s during teardown: %s", tbl, exc)
        raise RuntimeError(
            "db_conn teardown leaked tables: "
            + ", ".join(tbl for tbl, _ in drop_errors)
        )


def _make_job(overrides: dict | None = None) -> dict:
    """Build a complete job row dict with sensible defaults."""
    base = {
        "id": f"test-{uuid.uuid4().hex[:8]}",
        "title": "Software Engineer",
        "company": "google",
        "location": "Mountain View, CA",
        "url": "https://careers.google.com/jobs/123",
        "source_id": "google_scraper",
        "details": json.dumps({}),
        "created_at": "2025-01-10T10:00:00Z",
        "posted_on": None,
        "closed_on": None,
        "status": "OPEN",
        "has_matched": False,
        "ai_metadata": json.dumps({}),
        "first_seen_at": "2025-01-10T10:00:00Z",
        "last_seen_at": "2025-01-15T10:00:00Z",
        "consecutive_misses": 0,
        "details_scraped": False,
    }
    if overrides:
        base.update(overrides)
    return base


def _insert_job(conn, env: str, job: dict) -> None:
    """Insert a job row into the test table."""
    cursor = conn.cursor()
    table = sql.Identifier(_get_table_name(env, "jobs"))
    cols = sql.SQL(", ").join(sql.Identifier(k) for k in job.keys())
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in job)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(table, cols, placeholders)
    cursor.execute(query, list(job.values()))
    conn.commit()


def _insert_scrape_run(conn, env: str, run: dict) -> None:
    """Insert a scrape run row into the test table."""
    defaults = {
        "run_id": f"run-{uuid.uuid4().hex[:8]}",
        "company": "google",
        "started_at": "2025-01-15T10:00:00Z",
        "completed_at": None,
        "mode": "incremental",
        "jobs_seen": 0,
        "new_jobs": 0,
        "closed_jobs": 0,
        "details_fetched": 0,
        "error_count": 0,
    }
    defaults.update(run)
    cursor = conn.cursor()
    table = sql.Identifier(_get_table_name(env, "runs"))
    cols = sql.SQL(", ").join(sql.Identifier(k) for k in defaults.keys())
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in defaults)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(table, cols, placeholders)
    cursor.execute(query, list(defaults.values()))
    conn.commit()


def _make_user(overrides: dict | None = None) -> dict:
    """Build a complete user row dict with sensible defaults."""
    base = {
        "id": uuid.uuid4().hex,
        "auth0_id": f"auth0|{uuid.uuid4().hex[:12]}",
        "email": "test@example.com",
        "display_name": None,
        "given_name": "Test",
        "family_name": "User",
        "picture_url": None,
        "created_at": "2025-01-10T10:00:00Z",
        "updated_at": "2025-01-10T10:00:00Z",
    }
    if overrides:
        base.update(overrides)
    return base


def _insert_user(conn, env: str, user: dict) -> None:
    """Insert a user row into the test table."""
    cursor = conn.cursor()
    table = sql.Identifier(_get_table_name(env, "users"))
    cols = sql.SQL(", ").join(sql.Identifier(k) for k in user.keys())
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in user)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(table, cols, placeholders)
    cursor.execute(query, list(user.values()))
    conn.commit()


def _clear_tables(conn, env: str) -> None:
    """Truncate test tables between tests."""
    cursor = conn.cursor()
    jobs_table = _get_table_name(env, "jobs")
    runs_table = _get_table_name(env, "runs")
    users_table = _get_table_name(env, "users")
    enabled_companies_table = f"user_enabled_companies_{env}"
    cursor.execute(sql.SQL("TRUNCATE {}, {}, {}, {} CASCADE").format(
        sql.Identifier(jobs_table),
        sql.Identifier(runs_table),
        sql.Identifier(users_table),
        sql.Identifier(enabled_companies_table),
    ))
    conn.commit()


@pytest.fixture(autouse=True)
def clean_tables(db_conn, test_env):
    """Truncate tables before each test for isolation."""
    _clear_tables(db_conn, test_env)


@pytest.fixture(scope="module")
def test_app(db_conn, test_env):
    """FastAPI test app with database connection wired up (no auto-scraper)."""
    from api.routers import jobs, jobs_qa, users
    from api.dependencies import get_db
    from api.auth.dependencies import get_current_user

    app = FastAPI()
    app.include_router(jobs.router, prefix="/api/jobs")
    app.include_router(jobs_qa.router, prefix="/api/jobs-qa")
    app.include_router(users.router, prefix="/api/users")

    @app.get("/health")
    def health():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("OK")

    # Override the get_db dependency to use the test connection
    def override_get_db():
        yield db_conn

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "auth0|test_user_123",
        "email": "test@example.com",
        "given_name": "Test",
        "family_name": "User",
        "picture": "https://example.com/photo.jpg",
    }

    app.state.env = test_env
    # Provide a minimal config for trigger-scrape (use "local" for validation;
    # routes use app.state.env for table selection, not config.scraper_environment)
    from api.config import Settings
    app.state.config = Settings(
        database_url=TEST_DB_URL,
        scraper_environment="local",
        scraper_scripts_path="/nonexistent/scripts",
    )

    return app


@pytest.fixture(scope="module")
def client(test_app):
    """FastAPI TestClient."""
    return TestClient(test_app)
