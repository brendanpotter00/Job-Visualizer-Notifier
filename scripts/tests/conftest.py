"""
Shared pytest fixtures for the scraper test suite
"""

import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent.parent
sys.path.insert(0, str(scripts_dir))

# Also add src/backend so we can import api.db_models.Base and api.migrations.
# Used only by the postgres_db fixture for schema bootstrap (mirrors the
# Unit 4 backend conftest pattern).
_repo_root = Path(__file__).parent.parent.parent
src_backend = _repo_root / "src" / "backend"
sys.path.insert(0, str(src_backend))

from shared.models import JobListing, ScrapeRun
from shared import database as db


# Default test database URL (local Docker postgres)
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper"
)


@pytest.fixture
def sample_job_data_dict() -> Dict[str, Any]:
    """Raw scraped job data dictionary (as returned by parser)"""
    return {
        "title": "Software Engineer III, Cloud",
        "location": "Mountain View, CA, USA",
        "job_url": "https://www.google.com/about/careers/applications/jobs/results/114423471240291014-software-engineer-iii-cloud",
        "minimum_qualifications": [
            "Bachelor's degree in Computer Science or equivalent",
            "5 years of software development experience"
        ],
        "preferred_qualifications": [
            "Experience with distributed systems",
            "Experience with Kubernetes"
        ],
        "about_the_job": "Join our Cloud team. Salary: $185,000-$283,000 + bonus + equity",
        "responsibilities": [
            "Design and implement cloud services",
            "Collaborate with cross-functional teams"
        ],
        "experience_level": "Mid-level",
        "salary_range": "$185,000-$283,000",
        "is_remote_eligible": False,
        "apply_url": "https://www.google.com/about/careers/applications/apply?jobId=114423471240291014",
        "company": "google"
    }


@pytest.fixture
def sample_job_listing() -> JobListing:
    """Valid JobListing model instance"""
    return JobListing(
        id="114423471240291014",
        title="Software Engineer III, Cloud",
        company="google",
        location="Mountain View, CA, USA",
        url="https://www.google.com/about/careers/applications/jobs/results/114423471240291014-software-engineer-iii-cloud",
        source_id="google_scraper",
        details={
            "minimum_qualifications": ["Bachelor's degree", "5 years experience"],
            "preferred_qualifications": ["Distributed systems"],
            "about_the_job": "Join our Cloud team",
            "responsibilities": ["Design cloud services"],
            "experience_level": "Mid-level",
            "salary_range": "$185,000-$283,000",
            "is_remote_eligible": False,
            "apply_url": "https://apply.google.com/114423471240291014"
        },
        posted_on=None,
        created_at="2024-01-15T10:30:00Z",
        closed_on=None,
        status="OPEN",
        has_matched=False,
        ai_metadata={},
        first_seen_at="2024-01-15T10:30:00Z",
        last_seen_at="2024-01-15T10:30:00Z",
        consecutive_misses=0,
        details_scraped=True
    )


@pytest.fixture
def sample_scrape_run() -> ScrapeRun:
    """Valid ScrapeRun model instance"""
    return ScrapeRun(
        run_id="test-run-001",
        company="google",
        started_at="2024-01-15T10:30:00Z",
        completed_at="2024-01-15T11:00:00Z",
        mode="incremental",
        jobs_seen=100,
        new_jobs=10,
        closed_jobs=5,
        details_fetched=10,
        error_count=0
    )


@pytest.fixture
def postgres_db():
    """PostgreSQL database connection with per-test schema isolation.

    Creates `test_<hex>` schema, points `search_path` via `PYTEST_SCHEMA`,
    runs Alembic (populates bare-named tables + alembic_version inside the
    schema). Yields the psycopg2 connection tests use. Teardown DROP SCHEMA
    CASCADE — no per-table loop.
    """
    import secrets

    schema = "test_" + secrets.token_hex(4)

    prev_database_url = os.environ.get("DATABASE_URL")
    prev_pytest_schema = os.environ.get("PYTEST_SCHEMA")

    os.environ["DATABASE_URL"] = TEST_DB_URL
    os.environ["PYTEST_SCHEMA"] = schema

    # Create the schema on a one-off connection before Alembic runs.
    bootstrap_conn = psycopg2.connect(TEST_DB_URL)
    try:
        bootstrap_conn.autocommit = True
        with bootstrap_conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    finally:
        bootstrap_conn.close()

    # The Alembic baseline revision is empty; the user tables must be
    # materialized via Base.metadata.create_all. Pin search_path on each
    # engine connection so the DDL lands inside the test schema, not public.
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
    # the probe query looks across all schemas.
    _db_models.Base.metadata.create_all(engine, checkfirst=False)
    engine.dispose()

    # create_all already materialized every ORM table; stamp (not upgrade)
    # avoids re-running each migration body against tables that already exist.
    from api.migrations import stamp_alembic_head
    stamp_alembic_head(TEST_DB_URL)

    conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
    with conn.cursor() as cur:
        cur.execute(f'SET search_path TO "{schema}", public')
    conn.commit()

    try:
        yield conn
    finally:
        # Close the test connection BEFORE DROP SCHEMA — otherwise the DROP
        # blocks on this session's reference to the schema (search_path +
        # any open transactions). A leaked open conn → teardown deadlock.
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
                if prev_pytest_schema is None:
                    os.environ.pop("PYTEST_SCHEMA", None)
                else:
                    os.environ["PYTEST_SCHEMA"] = prev_pytest_schema
                if prev_database_url is None:
                    os.environ.pop("DATABASE_URL", None)
                else:
                    os.environ["DATABASE_URL"] = prev_database_url


# Alias for backwards compatibility
@pytest.fixture
def in_memory_db(postgres_db):
    """
    Alias for postgres_db fixture (backwards compatibility)
    """
    return postgres_db


@pytest.fixture
def mock_scraper():
    """
    Mocked GoogleJobsScraper for testing without browser
    """
    scraper = MagicMock()
    scraper.get_company_name.return_value = "google"
    scraper.SOURCE_ID = "google_scraper"
    scraper.scrape_all_queries = AsyncMock(return_value=[])
    scraper.scrape_job_details_batch = AsyncMock(return_value=[])
    scraper.transform_to_job_model = MagicMock()
    return scraper


@pytest.fixture
def html_fixture():
    """
    Factory fixture for loading HTML fixture files
    """
    def _load_fixture(name: str) -> str:
        fixture_path = Path(__file__).parent / "fixtures" / name
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture not found: {fixture_path}")
        return fixture_path.read_text()

    return _load_fixture


@pytest.fixture
def multiple_job_listings(sample_job_listing) -> list:
    """
    Multiple JobListing instances for batch testing
    """
    jobs = []
    for i in range(3):
        job = JobListing(
            id=f"job-{i:03d}",
            title=f"Software Engineer {i}",
            company="google",
            location="Mountain View, CA, USA",
            url=f"https://www.google.com/about/careers/applications/jobs/results/job-{i:03d}-software-engineer",
            source_id="google_scraper",
            details={},
            created_at="2024-01-15T10:30:00Z",
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z",
            consecutive_misses=0,
            details_scraped=False
        )
        jobs.append(job)
    return jobs


# ============================================================================
# Microsoft Scraper Fixtures
# ============================================================================

@pytest.fixture
def mock_playwright_page():
    """Mock Playwright page object for API tests"""
    return MagicMock()


@pytest.fixture
def microsoft_scraper():
    """MicrosoftJobsScraper instance for transformation tests"""
    from scripts.microsoft_jobs_scraper.scraper import MicrosoftJobsScraper
    return MicrosoftJobsScraper(headless=True, detail_scrape=False)


@pytest.fixture
def sample_microsoft_job_data() -> Dict[str, Any]:
    """Sample job data from Microsoft scraper"""
    return {
        "id": "1970393556642428",
        "job_number": "200016306",
        "title": "Software Engineer II",
        "job_url": "https://apply.careers.microsoft.com/careers?position_id=1970393556642428&domain=microsoft.com",
        "location": "Redmond, WA, USA",
        "posted_date": "2024-12-15",
        "company": "microsoft",
        "description": "Work on Azure cloud services",
        "responsibilities": "Design and implement cloud solutions",
        "minimum_qualifications": ["BS in Computer Science", "3+ years experience"],
        "preferred_qualifications": ["MS in Computer Science", "Experience with distributed systems"],
        "salary_range": "$130,000 - $190,000",
        "work_site": "Hybrid",
        "travel": "10%",
        "profession": "Engineering",
        "discipline": "Software Development",
        "role_type": "Individual Contributor",
        "employment_type": "Full-time",
    }


@pytest.fixture
def microsoft_search_response() -> Dict[str, Any]:
    """Sample Microsoft search API response"""
    return {
        "positions": [
            {
                "id": "1234567890",
                "title": "Software Engineer",
                "location": "Seattle, WA",
                "postedDate": "2024-12-15",
            },
            {
                "id": "0987654321",
                "title": "Data Scientist",
                "location": "Redmond, WA",
                "postedDate": "2024-12-14",
            },
        ],
        "totalCount": 100,
    }


@pytest.fixture
def microsoft_details_response() -> Dict[str, Any]:
    """Sample Microsoft job details API response"""
    return {
        "position": {
            "title": "Software Engineer II",
            "jobNumber": "200016306",
            "description": "Work on Azure cloud services",
            "responsibilities": "Design and implement cloud solutions",
            "minimumQualifications": "BS in CS\n3+ years experience",
            "preferredQualifications": "MS in CS",
            "location": "Redmond, WA, USA",
            "salaryRange": "$130,000 - $190,000",
            "postedDate": "2024-12-15",
        }
    }
