"""Test fixtures for FastAPI backend tests.

Uses a real PostgreSQL database with test-isolated tables (test_<hex> env pattern)
that are created before each test module and dropped after.
"""

import json
import os
import uuid

import psycopg2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from scripts.shared.database import init_schema, _get_table_name

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
    conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
    init_schema(conn, test_env)
    yield conn
    # Cleanup: drop test tables (children before parents to satisfy FK dependencies)
    cursor = conn.cursor()
    jobs_table = _get_table_name(test_env, "jobs")
    runs_table = _get_table_name(test_env, "runs")
    users_table = _get_table_name(test_env, "users")
    enabled_companies_table = f"user_enabled_companies_{test_env}"
    migrations_table = f"schema_migrations_{test_env}"
    # Drop user_enabled_companies before users to satisfy the FK on user_id.
    cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(enabled_companies_table)))
    cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(jobs_table)))
    cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(runs_table)))
    cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(users_table)))
    cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(migrations_table)))
    conn.commit()
    conn.close()


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
