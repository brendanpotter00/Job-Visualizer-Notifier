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
    # Mirror the write path (scripts.shared.database._build_job_values): the list
    # endpoint reads these two denormalized columns, NOT details->..., to avoid
    # detoasting the wide `details` JSONB (2026-07-13 /api/jobs outage). Derive
    # them from `details` unless a test set them explicitly, so any job seeded
    # with details.experience_level/is_remote_eligible behaves like a real
    # upsert. Deriving matters more than it looks: a fixture that hand-set
    # `details` only is how a missing denormalized column can stay invisible to
    # the whole test suite while production serves nothing.
    _details = base["details"]
    if isinstance(_details, str):
        _details = json.loads(_details)
    base.setdefault("experience_level", _details.get("experience_level"))
    base.setdefault("is_remote_eligible", _details.get("is_remote_eligible", False))
    return base


def _insert_job(conn, job: dict) -> None:
    """Insert a job row into the test table.

    Freshness (``last_seen_at`` / ``consecutive_misses``) lives in the
    ``job_freshness`` sidecar — the Unit-4 contract migration (18fe9c20a8fd)
    dropped both columns from ``job_listings``, so they are stripped out of the
    parent INSERT here. The ``AFTER INSERT`` trigger on ``job_listings``
    materializes the sidecar row seeded from ``first_seen_at`` with 0 misses, so
    after the insert we mirror this job dict's requested ``last_seen_at`` /
    ``consecutive_misses`` into the sidecar — the read paths (``get_jobs``,
    problem-jobs, etc.) join it, so it must hold the values the test asked for.
    """
    cursor = conn.cursor()
    listing = {k: v for k, v in job.items()
               if k not in ("last_seen_at", "consecutive_misses")}
    table = sql.Identifier("job_listings")
    cols = sql.SQL(", ").join(sql.Identifier(k) for k in listing.keys())
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in listing)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(table, cols, placeholders)
    cursor.execute(query, list(listing.values()))
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
    # Comma-joined rather than a hand-counted "{}" format string: the
    # placeholder count drifting from the identifier list is a silent footgun
    # (#283 appended two tables and the "{}"s did not follow).
    tables = (
        sql.Identifier("feature_upvotes"),
        sql.Identifier("features"),
        # feedback FKs users with ON DELETE SET NULL, so a users CASCADE would
        # only null user_id rather than remove the row — truncate it explicitly.
        sql.Identifier("feedback"),
        sql.Identifier("user_enabled_companies"),
        # user_visits FKs users with ON DELETE CASCADE, so a users CASCADE would
        # already clear it; list it explicitly for clarity / future-proofing.
        sql.Identifier("user_visits"),
        # E7 custom-company tables. user_companies FKs users (CASCADE), the
        # other three are soft-linked (no FK) so they need explicit truncation.
        sql.Identifier("user_companies"),
        sql.Identifier("company_scripts"),
        sql.Identifier("company_harvests"),
        sql.Identifier("company_add_attempts"),
        sql.Identifier("job_listings"),
        # job_tags and job_locations carry NO foreign key to job_listings — the
        # parent's PK is the composite (source_id, id), which a single-column FK
        # cannot reference (see JobLocation's docstring). So the job_listings
        # CASCADE above does NOT reach them, and without listing them here their
        # rows survive into the next test and silently join onto a later job that
        # happens to reuse an id. locations is truncated for the same reason
        # (job_locations FKs *it*, not the reverse).
        sql.Identifier("job_tags"),
        sql.Identifier("job_locations"),
        sql.Identifier("locations"),
        # The Tier-1 alias cache. Same reasoning as job_locations above: nothing
        # else here reaches them, so without this an alias written by one test
        # stays cached for every later test in the module's schema. That leak is
        # what forced the scan_unnormalized tests to TRUNCATE these tables
        # themselves (#283) — a test asserting "this key is COLD" silently
        # depended on no earlier test having warmed it.
        sql.Identifier("alias_locations"),
        sql.Identifier("location_aliases"),
        sql.Identifier("scrape_runs"),
        sql.Identifier("admins"),
        sql.Identifier("users"),
        sql.Identifier("companies"),
        sql.Identifier("worker_heartbeats"),
        # The facet dimensions. Not truncating them made `seed_taxonomy`
        # ORDER-LEAKY: `_seed_taxonomy` is `ON CONFLICT DO NOTHING`, so once any
        # test in the session had opted into the fixture, its rows survived every
        # later truncation and a test that never asked for them still found
        # `enrichment_category`/`enrichment_level` FKs resolvable. Such a test
        # passes in a full run and fails alone, which is the worst way to learn
        # about a missing fixture. `job_listings` is truncated above and both are
        # in this same statement, so the FK from it is not an ordering problem.
        sql.Identifier("job_categories"),
        sql.Identifier("job_levels"),
    )
    cursor.execute(
        sql.SQL("TRUNCATE {} CASCADE").format(sql.SQL(", ").join(tables))
    )
    conn.commit()


# Mirrors the post-migration state of the seeded facet dimensions: the
# CATEGORY_SEED / LEVEL_SEED of ``0fa33aca5bda`` plus the ``intern`` level added
# by ``0b61e444ea25`` (rank 0, renumbering the rest +1).
#
# Needed because ``db_conn`` materializes the schema with ``create_all`` and then
# *stamps* Alembic — migration ``upgrade()`` bodies never run, so these rows do
# not exist in tests. ``job_listings.enrichment_category`` / ``enrichment_level``
# are real FKs to them, so any test writing a facet must seed first.
_CATEGORY_SEED = [
    ("software_engineering", "Software Engineering", 0),
    ("hardware_engineer", "Hardware Engineer", 1),
    ("product_manager", "Product Manager", 2),
    ("project_manager", "Project Manager", 3),
    ("data_scientist", "Data Scientist", 4),
    ("growth", "Growth", 5),
    ("business_ops", "Business Ops", 6),
]
# Parents first: ``new_grad`` carries a self-FK to ``entry``.
_LEVEL_SEED = [
    ("intern", "Intern", 0, None),
    ("entry", "Entry", 2, None),
    ("mid", "Mid", 3, None),
    ("senior", "Senior", 4, None),
    ("senior_plus", "Staff / Principal", 5, None),
    ("manager", "Manager", 6, None),
    ("new_grad", "New Grad", 1, "entry"),
]


def _seed_taxonomy(conn) -> None:
    """Seed job_categories / job_levels so enrichment FKs resolve."""
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT INTO job_categories (slug, label, sort_order) VALUES (%s, %s, %s)"
        " ON CONFLICT (slug) DO NOTHING",
        _CATEGORY_SEED,
    )
    cursor.executemany(
        "INSERT INTO job_levels (slug, label, rank, parent_slug) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (slug) DO NOTHING",
        _LEVEL_SEED,
    )
    conn.commit()


@pytest.fixture
def seed_taxonomy(db_conn, clean_tables):
    """Opt-in fixture seeding the facet dimensions.

    Depends on ``clean_tables`` so it runs AFTER job_listings is truncated —
    seeding a FK target before its children are gone is fine, but the ordering
    makes the dependency explicit for any future truncation of the dimensions.
    """
    _seed_taxonomy(db_conn)
    return None


def _insert_location(conn, **cols) -> int:
    """Insert one ``locations`` row from keyword columns; return its id.

    ``kind`` and ``canonical_name`` are required by the schema; ``city`` /
    ``region`` / ``country`` / ``remote_scope`` are optional and default to NULL,
    which is meaningful (a country row has no city, a remote row has no city).
    """
    keys = list(cols)
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
        sql.Identifier("locations"),
        sql.SQL(", ").join(sql.Identifier(k) for k in keys),
        sql.SQL(", ").join(sql.Placeholder() for _ in keys),
    )
    cursor = conn.cursor()
    cursor.execute(stmt, [cols[k] for k in keys])
    location_id = cursor.fetchone()["id"]
    conn.commit()
    return int(location_id)


def _link_job_location(conn, job_id: str, location_id: int, is_primary: bool = True) -> None:
    """Attach a canonical location to a job (``job_locations`` is keyed by job id
    alone — no source_id column, see db_models.JobLocation)."""
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "INSERT INTO {} (job_listing_id, normalized_location_id, is_primary)"
            " VALUES (%s, %s, %s)"
        ).format(sql.Identifier("job_locations")),
        (job_id, location_id, is_primary),
    )
    conn.commit()


def _insert_job_tag(conn, source_id: str, job_id: str, tag: str) -> None:
    """Attach one free-form enrichment tag to a job."""
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "INSERT INTO {} (source_id, job_listing_id, tag) VALUES (%s, %s, %s)"
        ).format(sql.Identifier("job_tags")),
        (source_id, job_id, tag),
    )
    conn.commit()


def _insert_company(conn, company_id: str, *, enabled: bool = True) -> None:
    """Seed a ``companies`` row so the hidden-company anti-join has something to
    find. Absent a row the anti-join is a no-op and the job stays visible."""
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled)"
            " VALUES (%s, %s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), "greenhouse", company_id, enabled),
    )
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


@pytest.fixture(autouse=True)
def disable_db_watchdog():
    """Keep lifespan-driven tests from starting real watchdogs.

    Both default on_fatal hooks call os._exit against settings.database_url
    (db_watchdog: exit 70; worker_watchdog: exit 75) — with aggressive
    .env-supplied intervals either could hard-kill the pytest process.
    """
    from api.config import settings

    prev_db = settings.db_watchdog_enabled
    prev_worker = settings.worker_watchdog_enabled
    settings.db_watchdog_enabled = False
    settings.worker_watchdog_enabled = False
    yield
    settings.db_watchdog_enabled = prev_db
    settings.worker_watchdog_enabled = prev_worker


@pytest.fixture(scope="module")
def test_app(db_conn):
    """FastAPI test app with database connection wired up (no auto-scraper)."""
    from api.routers import (
        admin,
        companies,
        features,
        feedback,
        jobs,
        jobs_qa,
        jobs_search,
        user_companies,
        users,
    )
    from api.dependencies import get_db
    from api.auth.dependencies import (
        get_current_user,
        get_optional_user,
        require_admin,
    )

    app = FastAPI()
    app.include_router(jobs.router, prefix="/api/jobs")
    # Same prefix as production (api/main.py). No conflict with the jobs router's
    # /{source_id}/{job_id}: that route needs two path segments, this one has one.
    app.include_router(jobs_search.router, prefix="/api/jobs/search")
    app.include_router(jobs_qa.router, prefix="/api/jobs-qa")
    app.include_router(users.router, prefix="/api/users")
    app.include_router(user_companies.router, prefix="/api/users/companies")
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


@pytest.fixture
def procrastinate_schema(db_conn):
    """Materialize Procrastinate's own tables inside the per-module test schema.

    Applied from the installed package's ``schema.sql`` with plain psycopg2 rather
    than through ``procrastinate_app`` — DELIBERATELY. That app's connector is built
    at IMPORT time from ``settings.database_url``, so anything that touches it reads
    and writes the developer's REAL local database no matter what ``TEST_DATABASE_URL``
    says (the trap ``test_worker_lanes.py`` documents). Tests that only need the
    ``procrastinate_jobs`` / ``procrastinate_events`` TABLES — the queued-job cancel
    and the wedged-row reconciler — must never open the broker at all, so they get the
    schema this way and stay entirely inside ``db_conn``.

    THE EXISTENCE PROBE IS SCHEMA-QUALIFIED, and that is load-bearing.
    ``to_regclass('procrastinate_jobs')`` resolves through the whole search_path, and
    ``test_procrastinate_bootstrap`` leaves a copy of Procrastinate's schema in
    ``public`` (its ``PGOPTIONS`` search_path pin does not reach the connector's pool).
    An unqualified probe therefore says "already installed" and this fixture creates
    nothing — so the test then reads and WRITES the shared ``public`` tables that other
    modules depend on. Asking about ``"<schema>".procrastinate_jobs`` keeps every job
    row this fixture's tests create inside the schema that gets dropped at teardown.

    ``search_path`` is already pinned with the test schema FIRST, so every CREATE lands
    there and the fixture's teardown is the module fixture's ``DROP SCHEMA … CASCADE``.
    """
    import pathlib

    import procrastinate as _procrastinate

    schema = os.environ["PYTEST_SCHEMA"]
    cur = db_conn.cursor()
    cur.execute("SELECT to_regclass(%s) AS t", (f'"{schema}".procrastinate_jobs',))
    row = cur.fetchone()
    if (row["t"] if row else None) is None:
        sql_path = pathlib.Path(_procrastinate.__file__).parent / "sql" / "schema.sql"
        cur.execute(sql_path.read_text())
    db_conn.commit()
    return db_conn
