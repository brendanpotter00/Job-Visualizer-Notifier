"""Test fixtures for FastAPI backend tests.

Uses a real PostgreSQL database with test-isolated schemas (test_<hex>)
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

from api.migrations import stamp_alembic_head

logger = logging.getLogger(__name__)

# Default test database URL (same as docker-compose)
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper",
)


@pytest.fixture(scope="module")
def db_conn():
    """PostgreSQL connection with per-module schema isolation.

    Creates `test_<hex>` schema, points `search_path` at it via
    `PYTEST_SCHEMA`, materializes the ORM schema with
    `Base.metadata.create_all`, stamps Alembic at head, and yields a psycopg2
    connection already pinned to the schema. Teardown drops the whole schema
    CASCADE — no per-table loop.
    """
    import secrets

    schema = "test_" + secrets.token_hex(4)

    prev_database_url = os.environ.get("DATABASE_URL")
    prev_pytest_schema = os.environ.get("PYTEST_SCHEMA")

    os.environ["DATABASE_URL"] = TEST_DB_URL
    os.environ["PYTEST_SCHEMA"] = schema

    # Create the schema on a one-off connection BEFORE Alembic runs.
    # Alembic's env.py also issues CREATE SCHEMA IF NOT EXISTS defensively,
    # but doing it here first makes the fixture self-contained and keeps
    # the Alembic hook idempotent.
    bootstrap_conn = psycopg2.connect(TEST_DB_URL)
    try:
        bootstrap_conn.autocommit = True
        with bootstrap_conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    finally:
        bootstrap_conn.close()

    # create_all materializes every ORM table inside the per-worker schema;
    # search_path is pinned on each engine connection so DDL lands there, not
    # in public. Then stamp (not upgrade) — running upgrade on top of
    # create_all would re-execute each migration's create_table body and hit
    # DuplicateTable. Migrations are exercised end-to-end by
    # scripts/tests/integration/test_alembic_parity.py.
    from sqlalchemy import create_engine, event
    import api.db_models as _db_models

    engine = create_engine(TEST_DB_URL)

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_conn, _conn_record):
        cur = dbapi_conn.cursor()
        try:
            cur.execute(f'SET search_path TO "{schema}", public')
        finally:
            cur.close()

    # checkfirst=False is critical: SQLAlchemy's default existence probe
    # sees `public.job_listings` in shared dev DBs and skips creation,
    # leaving the test schema empty. search_path pins where DDL LANDS, but
    # the probe query looks across all schemas. Skipping the probe forces
    # CREATE TABLE into the first schema in search_path — our test schema.
    _db_models.Base.metadata.create_all(engine, checkfirst=False)
    engine.dispose()

    stamp_alembic_head(TEST_DB_URL)

    # The connection returned here is what tests use. PYTEST_SCHEMA is
    # set, so our connection helpers pin search_path on open.
    conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{schema}", public')
    conn.commit()

    try:
        yield conn
    finally:
        # Teardown: close the test connection BEFORE DROP SCHEMA — otherwise
        # the DROP blocks on the session's still-open reference to the schema.
        # Then DROP SCHEMA CASCADE takes every table, index, sequence in one
        # statement — no per-table loop, no partial-failure leaks.
        try:
            if not conn.closed:
                try:
                    conn.rollback()
                except Exception:
                    pass
                conn.close()
        finally:
            try:
                drop_conn = psycopg2.connect(TEST_DB_URL)
                drop_conn.autocommit = True
                try:
                    with drop_conn.cursor() as cur:
                        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                finally:
                    drop_conn.close()
            finally:
                # Restore env vars to pre-fixture state.
                if prev_pytest_schema is None:
                    os.environ.pop("PYTEST_SCHEMA", None)
                else:
                    os.environ["PYTEST_SCHEMA"] = prev_pytest_schema
                if prev_database_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = prev_database_url


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
    """Insert a job row into the test table.

    Freshness (``last_seen_at`` / ``consecutive_misses``) now lives in the
    ``job_freshness`` sidecar. The ``AFTER INSERT`` trigger on ``job_listings``
    materializes the sidecar row seeded from ``first_seen_at`` with 0 misses, so
    after the insert we mirror this job dict's requested ``last_seen_at`` /
    ``consecutive_misses`` into the sidecar — the read paths (``get_jobs``,
    problem-jobs, etc.) join it, so it must hold the values the test asked for.
    """
    cursor = conn.cursor()
    table = sql.Identifier("job_listings")
    cols = sql.SQL(", ").join(sql.Identifier(k) for k in job.keys())
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in job)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(table, cols, placeholders)
    cursor.execute(query, list(job.values()))
    if {"id", "source_id", "last_seen_at"} <= set(job.keys()):
        cursor.execute(
            "UPDATE job_freshness SET last_seen_at = %s, consecutive_misses = %s "
            "WHERE source_id = %s AND id = %s",
            (job["last_seen_at"], job.get("consecutive_misses", 0),
             job["source_id"], job["id"]),
        )
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
    table = sql.Identifier("scrape_runs")
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


def _insert_user(conn, user: dict) -> None:
    """Insert a user row into the test table."""
    cursor = conn.cursor()
    table = sql.Identifier("users")
    cols = sql.SQL(", ").join(sql.Identifier(k) for k in user.keys())
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in user)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(table, cols, placeholders)
    cursor.execute(query, list(user.values()))
    conn.commit()


def _clear_tables(conn) -> None:
    """Truncate test tables between tests."""
    cursor = conn.cursor()
    cursor.execute(sql.SQL("TRUNCATE {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {} CASCADE").format(
        sql.Identifier("feature_upvotes"),
        sql.Identifier("features"),
        # feedback FKs users with ON DELETE SET NULL, so a users CASCADE would
        # only null user_id rather than remove the row — truncate it explicitly.
        sql.Identifier("feedback"),
        sql.Identifier("user_enabled_companies"),
        # user_visits FKs users with ON DELETE CASCADE, so a users CASCADE would
        # already clear it; list it explicitly for clarity / future-proofing.
        sql.Identifier("user_visits"),
        sql.Identifier("job_listings"),
        sql.Identifier("scrape_runs"),
        sql.Identifier("admins"),
        sql.Identifier("users"),
        sql.Identifier("companies"),
        sql.Identifier("worker_heartbeats"),
    ))
    conn.commit()


def _insert_admin(conn, user_id: str) -> None:
    """Grant admin status to an existing user row."""
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL("INSERT INTO {} (user_id) VALUES (%s)").format(sql.Identifier("admins")),
        (user_id,),
    )
    conn.commit()


def _insert_user_visit(conn, user_id: str, visited_at: str) -> None:
    """Insert one user_visits row at a specific timestamp (test seeding)."""
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL("INSERT INTO {} (user_id, visited_at) VALUES (%s, %s)").format(
            sql.Identifier("user_visits")
        ),
        (user_id, visited_at),
    )
    conn.commit()


@pytest.fixture(autouse=True)
def clean_tables(db_conn):
    """Truncate tables before each test for isolation."""
    _clear_tables(db_conn)


@pytest.fixture(scope="module")
def test_app(db_conn):
    """FastAPI test app with database connection wired up (no auto-scraper)."""
    from api.routers import admin, companies, feedback, features, jobs, jobs_qa, users
    from api.dependencies import get_db
    from api.auth.dependencies import (
        get_current_user,
        get_optional_user,
        require_admin,
    )

    app = FastAPI()
    app.include_router(jobs.router, prefix="/api/jobs")
    app.include_router(jobs_qa.router, prefix="/api/jobs-qa")
    app.include_router(users.router, prefix="/api/users")
    app.include_router(features.router, prefix="/api/features")
    app.include_router(companies.router, prefix="/api/companies")
    app.include_router(feedback.router, prefix="/api/feedback")
    app.include_router(admin.router, prefix="/api/admin")

    @app.get("/health")
    def health():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("OK")

    # Register the worker-freshness endpoint by reusing the real one so the
    # production logic is what tests exercise. response_model=None mirrors the
    # production decorator: health_worker returns dict | JSONResponse, a union
    # FastAPI can't build a response model from.
    from api.main import health_worker as _health_worker
    app.add_api_route(
        "/health/worker", _health_worker, methods=["GET"], response_model=None
    )

    # Override the get_db dependency to use the test connection
    def override_get_db():
        yield db_conn

    app.dependency_overrides[get_db] = override_get_db
    _test_claims = {
        "sub": "auth0|test_user_123",
        "email": "test@example.com",
        "given_name": "Test",
        "family_name": "User",
        "picture": "https://example.com/photo.jpg",
    }
    app.dependency_overrides[get_current_user] = lambda: _test_claims
    # Default test user is admin so existing jobs_qa/router tests don't need
    # to set up an admin grant per test. Tests that exercise the admin gate
    # (test_admin_router) pop this override and verify 403 / 401 paths.
    app.dependency_overrides[require_admin] = lambda: _test_claims

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
