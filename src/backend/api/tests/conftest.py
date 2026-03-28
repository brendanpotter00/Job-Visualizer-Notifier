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
    # Cleanup: drop test tables
    cursor = conn.cursor()
    jobs_table = _get_table_name(test_env, "jobs")
    runs_table = _get_table_name(test_env, "runs")
    cursor.execute(f"DROP TABLE IF EXISTS {jobs_table}")
    cursor.execute(f"DROP TABLE IF EXISTS {runs_table}")
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
    table = _get_table_name(env, "jobs")
    cols = ", ".join(job.keys())
    placeholders = ", ".join(["%s"] * len(job))
    cursor.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(job.values()))
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
    table = _get_table_name(env, "runs")
    cols = ", ".join(defaults.keys())
    placeholders = ", ".join(["%s"] * len(defaults))
    cursor.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(defaults.values()))
    conn.commit()


def _clear_tables(conn, env: str) -> None:
    """Truncate test tables between tests."""
    cursor = conn.cursor()
    jobs_table = _get_table_name(env, "jobs")
    runs_table = _get_table_name(env, "runs")
    cursor.execute(f"TRUNCATE {jobs_table}, {runs_table}")
    conn.commit()


@pytest.fixture(autouse=True)
def clean_tables(db_conn, test_env):
    """Truncate tables before each test for isolation."""
    _clear_tables(db_conn, test_env)


@pytest.fixture(scope="module")
def test_app(db_conn, test_env):
    """FastAPI test app with database connection wired up (no auto-scraper)."""
    from api.routers import jobs, jobs_qa

    app = FastAPI()
    app.include_router(jobs.router, prefix="/api/jobs")
    app.include_router(jobs_qa.router, prefix="/api/jobs-qa")

    @app.get("/health")
    def health():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("OK")

    # Wire up app state (same as main.py lifespan, but without auto-scraper)
    app.state.db_conn = db_conn
    app.state.env = test_env
    # Provide a minimal config for trigger-scrape
    from api.config import Settings
    app.state.config = Settings(
        database_url=TEST_DB_URL,
        scraper_environment=test_env,
    )

    return app


@pytest.fixture(scope="module")
def client(test_app):
    """FastAPI TestClient."""
    return TestClient(test_app)
