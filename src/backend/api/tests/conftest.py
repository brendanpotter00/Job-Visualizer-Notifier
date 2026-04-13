"""Test fixtures for FastAPI backend tests.

Uses a real PostgreSQL database with fixed table names (job_listings, scrape_runs).
Tables are created once per module and truncated between tests for isolation.
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

from scripts.shared.database import init_schema, JOBS_TABLE, RUNS_TABLE

# Default test database URL (same as docker-compose)
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper",
)


@pytest.fixture(scope="module")
def db_conn():
    """PostgreSQL connection with test tables created and cleaned up after."""
    conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
    init_schema(conn)
    yield conn
    # Cleanup: truncate tables
    cursor = conn.cursor()
    cursor.execute(sql.SQL("TRUNCATE {}, {}").format(
        sql.Identifier(JOBS_TABLE), sql.Identifier(RUNS_TABLE)
    ))
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


def _insert_job(conn, job: dict) -> None:
    """Insert a job row into the test table."""
    cursor = conn.cursor()
    table = sql.Identifier(JOBS_TABLE)
    cols = sql.SQL(", ").join(sql.Identifier(k) for k in job.keys())
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in job)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(table, cols, placeholders)
    cursor.execute(query, list(job.values()))
    conn.commit()


def _insert_scrape_run(conn, run: dict) -> None:
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
    table = sql.Identifier(RUNS_TABLE)
    cols = sql.SQL(", ").join(sql.Identifier(k) for k in defaults.keys())
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in defaults)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(table, cols, placeholders)
    cursor.execute(query, list(defaults.values()))
    conn.commit()


def _clear_tables(conn) -> None:
    """Truncate test tables between tests."""
    cursor = conn.cursor()
    cursor.execute(sql.SQL("TRUNCATE {}, {}").format(
        sql.Identifier(JOBS_TABLE), sql.Identifier(RUNS_TABLE)
    ))
    conn.commit()


@pytest.fixture(autouse=True)
def clean_tables(db_conn):
    """Truncate tables before each test for isolation."""
    _clear_tables(db_conn)


@pytest.fixture(scope="module")
def test_app(db_conn):
    """FastAPI test app with database connection wired up (no auto-scraper)."""
    from api.routers import jobs, jobs_qa
    from api.dependencies import get_db

    app = FastAPI()
    app.include_router(jobs.router, prefix="/api/jobs")
    app.include_router(jobs_qa.router, prefix="/api/jobs-qa")

    @app.get("/health")
    def health():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("OK")

    # Override the get_db dependency to use the test connection
    def override_get_db():
        yield db_conn

    app.dependency_overrides[get_db] = override_get_db

    # Provide a minimal config for trigger-scrape
    from api.config import Settings
    app.state.config = Settings(
        database_url=TEST_DB_URL,
        scraper_scripts_path="/nonexistent/scripts",
    )

    return app


@pytest.fixture(scope="module")
def client(test_app):
    """FastAPI TestClient."""
    return TestClient(test_app)
