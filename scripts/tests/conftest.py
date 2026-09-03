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

from shared.constants import SourceId
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
        source_id=SourceId.GOOGLE,
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
    scraper.SOURCE_ID = SourceId.GOOGLE
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
            source_id=SourceId.GOOGLE,
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


# ============================================================================
# Amazon Scraper Fixtures
# ============================================================================

@pytest.fixture
def amazon_scraper():
    """AmazonJobsScraper instance for transformation tests"""
    from scripts.amazon_jobs_scraper.scraper import AmazonJobsScraper
    return AmazonJobsScraper(headless=True, detail_scrape=False)


@pytest.fixture
def amazon_raw_job() -> Dict[str, Any]:
    """One raw search.json row, shaped from a live 2026-08-09 response."""
    return {
        "id": "8f0d1e2a-0000-4a1b-9c3d-000000000000",  # GUID — NOT the id we key on
        "id_icims": "10496449",
        "title": "Software Development Engineer, Conversational Ads Experience",
        "job_path": "/en/jobs/10496449/software-development-engineer-conversational-ads-experience",
        "description": "Amazon is building a world class advertising business.<br/>Join us.",
        "basic_qualifications": "- 3+ years of experience<br/>- BS in CS",
        "preferred_qualifications": "- Experience with AWS",
        "posted_date": "August  8, 2026",  # NOTE: double space, as Amazon sends it
        "normalized_location": "Seattle, Washington, USA",
        "location": "US, WA, Seattle",
        "job_category": "Software Development",
        "team": {"label": "team-aws-sdm"},
        "job_schedule_type": "Full-Time",
        "business_category": "Advertising",
        "job_family": "Software Development",
        "city": "Seattle",
        "state": "Washington",
        "country_code": "USA",
        "url_next_step": "https://account.amazon.jobs/jobs/10496449/apply",
        "is_intern": None,
        "university_job": None,
        "is_manager": None,
    }


@pytest.fixture
def amazon_search_response(amazon_raw_job) -> Dict[str, Any]:
    """A realistic search.json payload envelope."""
    second = dict(amazon_raw_job)
    second["id_icims"] = "10496467"
    second["title"] = "Sr. Software Development Engineer, EC2"
    second["job_path"] = "/en/jobs/10496467/sr-software-development-engineer-ec2"
    return {"error": None, "hits": 1303, "jobs": [amazon_raw_job, second]}


@pytest.fixture
def amazon_page_factory(amazon_raw_job):
    """Build a search.json payload with `count` synthetic rows."""
    def _make(count: int, offset: int = 0, hits: Any = None) -> Dict[str, Any]:
        jobs = []
        for i in range(count):
            row = dict(amazon_raw_job)
            row["id_icims"] = str(10_000_000 + offset + i)
            row["title"] = f"Software Development Engineer {offset + i}"
            row["job_path"] = f"/en/jobs/{row['id_icims']}/software-development-engineer"
            jobs.append(row)
        return {"error": None, "hits": hits, "jobs": jobs}
    return _make


@pytest.fixture
def sample_amazon_job_data() -> Dict[str, Any]:
    """A standardised Amazon job *card* (post-_parse_job_from_search)."""
    return {
        "id": "10496449",
        "title": "Software Development Engineer II",
        "job_url": "https://www.amazon.jobs/en/jobs/10496449/software-development-engineer",
        "location": "Seattle, Washington, USA",
        "posted_date": "2026-08-08",
        "description": "Build things.\n\n- 3+ years of experience",
        "team": "team-aws-sdm",
        "job_schedule_type": "Full-Time",
        "business_category": "Advertising",
        "job_family": "Software Development",
        "city": "Seattle",
        "state": "Washington",
        "country_code": "USA",
        "apply_url": "https://account.amazon.jobs/jobs/10496449/apply",
        "is_intern": None,
        "university_job": None,
        "is_manager": None,
        "company": "amazon",
    }


@pytest.fixture
def amazon_dirty_json_text() -> str:
    """A JSON document carrying a raw \\x01 control byte inside a string.

    Mirrors the Amazon payloads that break strict JSON parsers (Python's
    json.loads and V8's JSON.parse alike).
    """
    return '{"jobs": [{"id_icims": "1", "title": "SDE", "description": "a\x01b"}], "hits": 1}'


# ============================================================================
# TikTok Scraper Fixtures
# ============================================================================

@pytest.fixture
def tiktok_scraper():
    """TikTokJobsScraper instance for transformation tests"""
    from scripts.tiktok_jobs_scraper.scraper import TikTokJobsScraper
    return TikTokJobsScraper(headless=True, detail_scrape=False)


@pytest.fixture
def tiktok_raw_job() -> Dict[str, Any]:
    """One raw job_post_list row, shaped from a live 2026-08-09 response."""
    return {
        "id": "7613184212766607621",
        "code": "A07200",
        "title": "Software Engineer, TikTok AIGC Agentic Workflow",
        "description": "About the team\nOur team supports the platform behind AIGC.",
        "requirement": "Minimum Qualifications:\n- BS in Computer Science",
        "city_info": {
            "code": "CT_94",
            "location_type": 3,
            "name": None,
            "en_name": "San Jose",
            "parent": {
                "code": "ST_100",
                "location_type": 2,
                "name": None,
                "en_name": "California",
                "parent": {
                    "code": "CN_6",
                    "location_type": 1,
                    "name": None,
                    "en_name": "United States of America",
                    "parent": None,
                },
            },
        },
        "job_category": {
            "id": "6704215897130666254",
            "name": None,
            "en_name": "Backend",
            "parent": {"id": "6704215862603155720", "name": None, "en_name": "R&D", "parent": None},
        },
        "recruit_type": {"id": "101", "name": None, "en_name": "Regular"},
        "job_subject": None,
        "vacancies": 1,
    }


@pytest.fixture
def tiktok_search_response(tiktok_raw_job) -> Dict[str, Any]:
    """A realistic search envelope (code 0 = success)."""
    second = dict(tiktok_raw_job)
    second["id"] = "7613184219506985269"
    second["title"] = "Senior Software Engineer, TikTok AIGC"
    return {
        "code": 0,
        "message": "ok",
        "error": None,
        "data": {
            "job_post_list": [tiktok_raw_job, second],
            "count": 716,
            "BaseResp": {"StatusCode": 0, "StatusMessage": "Success"},
        },
    }


@pytest.fixture
def tiktok_page_factory(tiktok_raw_job):
    """Build a TikTok envelope with `count` synthetic rows."""
    def _make(count: int, offset: int = 0, total: Any = None) -> Dict[str, Any]:
        jobs = []
        for i in range(count):
            row = dict(tiktok_raw_job)
            row["id"] = str(7_600_000_000_000_000_000 + offset + i)
            row["title"] = f"Software Engineer {offset + i}"
            jobs.append(row)
        return {
            "code": 0,
            "message": "ok",
            "data": {"job_post_list": jobs, "count": total},
        }
    return _make


@pytest.fixture
def sample_tiktok_job_data() -> Dict[str, Any]:
    """A standardised TikTok job *card* (post-_parse_job_from_search)."""
    return {
        "id": "7613184212766607621",
        "title": "Software Engineer, TikTok AIGC Agentic Workflow",
        "job_url": "https://lifeattiktok.com/search/7613184212766607621",
        "location": "San Jose, California, United States of America",
        "posted_date": None,
        "description": "About the team\n\nMinimum Qualifications:",
        "job_code": "A07200",
        "recruit_type": "Regular",
        "job_subject": None,
        "vacancies": 1,
        "company": "tiktok",
    }


# ============================================================================
# Meta Scraper Fixtures
# ============================================================================

@pytest.fixture
def meta_scraper():
    """MetaJobsScraper instance for transformation tests."""
    from scripts.meta_jobs_scraper.scraper import MetaJobsScraper
    return MetaJobsScraper(headless=True, detail_scrape=False)


@pytest.fixture
def meta_graphql_capture() -> list:
    """The decoded ``captured`` list from a realistic metacareers GraphQL run.

    Loaded from ``fixtures/meta_graphql_capture.json``. Shaped like the live
    response: a versioned wrapper key holding ``all_jobs`` + ``featured_jobs``
    (one featured job duplicates an all_jobs id), one job missing ``title`` and
    one missing ``id`` (both dropped), a non-US and a US location, teams +
    sub_teams on one job, and a sibling ``job_count`` scalar equal to the count
    of distinct valid jobs.
    """
    import json
    fixture_path = Path(__file__).parent / "fixtures" / "meta_graphql_capture.json"
    return json.loads(fixture_path.read_text())
