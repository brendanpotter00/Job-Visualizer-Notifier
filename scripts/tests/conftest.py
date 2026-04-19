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
def test_env():
    """
    Generate unique test environment name to isolate test tables
    """
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def postgres_db(test_env):
    """
    PostgreSQL database connection with schema bootstrapped via Base.metadata.create_all.

    The Alembic baseline revision is empty (prod was stamped, not applied), so
    fresh test databases need create_all to materialize tables. After create_all
    we run apply_alembic_migrations so alembic_version_{env} is populated and
    subsequent upgrade()s are no-ops.

    Mirrors the Unit 4 backend conftest pattern. Yields the psycopg2 connection
    the tests actually use (the engine is bootstrap-only).
    """
    import importlib

    # 1) Set env vars before importing api.config / Alembic. Capture prev
    #    values so teardown can restore them (avoid leaking test state across
    #    modules).
    prev_database_url = os.environ.get("DATABASE_URL")
    prev_env_var = os.environ.get("SCRAPER_ENVIRONMENT")
    os.environ["DATABASE_URL"] = TEST_DB_URL
    os.environ["SCRAPER_ENVIRONMENT"] = "local"  # valid, temporary

    # 2) api.config rejects test_<hex> by default; widen ALLOWED_ENVIRONMENTS
    #    in-process before the singleton is rebuilt. Mirrors src/backend/api/tests/conftest.py.
    import api.config as _api_config
    prev_allowed = set(_api_config.ALLOWED_ENVIRONMENTS)
    prev_settings = _api_config.settings
    _api_config.ALLOWED_ENVIRONMENTS = _api_config.ALLOWED_ENVIRONMENTS | {test_env}
    os.environ["SCRAPER_ENVIRONMENT"] = test_env
    _api_config.settings = _api_config.Settings()

    # 3) Import Base AFTER env vars are set so table names resolve to {tbl}_{test_env}.
    #    db_models captures _ENV at import time; reload to pick up the new env.
    import api.db_models as _db_models
    importlib.reload(_db_models)

    # 4) Bootstrap schema via create_all, then run Alembic so alembic_version is populated.
    from sqlalchemy import create_engine
    engine = create_engine(TEST_DB_URL)
    _db_models.Base.metadata.create_all(engine)
    engine.dispose()

    from api.migrations import apply_alembic_migrations
    apply_alembic_migrations(TEST_DB_URL, test_env)

    # 5) Open the psycopg2 connection the tests actually use.
    conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
    yield conn

    # 6) Teardown: drop env-suffixed tables (children-before-parents for FK).
    #    Each DROP is independent and idempotent; wrap them individually so a
    #    single failure doesn't cascade and leak the rest. Failures are
    #    logged AND raised — silent leaks are exactly the 2026-04-19 volume
    #    incident pattern (see docs/incidents/...). The whole teardown still
    #    runs to completion before raising.
    cursor = conn.cursor()
    drop_errors: list[tuple[str, Exception]] = []
    try:
        for tbl in (
            f"user_enabled_companies_{test_env}",
            f"scrape_runs_{test_env}",
            f"job_listings_{test_env}",
            f"users_{test_env}",
            f"alembic_version_{test_env}",
        ):
            try:
                cursor.execute(f'DROP TABLE IF EXISTS "{tbl}" CASCADE')
                conn.commit()
            except Exception as drop_exc:
                conn.rollback()
                drop_errors.append((tbl, drop_exc))
    finally:
        conn.close()

    # 7) Restore api.db_models, env vars, and api.config singleton to their
    #    pre-fixture state so sibling tests (e.g. test_db_models.py asserting
    #    against `_local` table names) see the global modules untouched.
    if prev_env_var is None:
        os.environ.pop("SCRAPER_ENVIRONMENT", None)
        # importlib.reload reads SCRAPER_ENVIRONMENT; set a valid placeholder
        # so the reload doesn't fail, then pop it again afterwards.
        os.environ["SCRAPER_ENVIRONMENT"] = "local"
        importlib.reload(_db_models)
        os.environ.pop("SCRAPER_ENVIRONMENT", None)
    else:
        os.environ["SCRAPER_ENVIRONMENT"] = prev_env_var
        importlib.reload(_db_models)
    if prev_database_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = prev_database_url
    _api_config.ALLOWED_ENVIRONMENTS = prev_allowed
    _api_config.settings = prev_settings

    if drop_errors:
        for tbl, exc in drop_errors:
            logger.error("Failed to drop test table %s during teardown: %s", tbl, exc)
        raise RuntimeError(
            "postgres_db teardown leaked tables: "
            + ", ".join(tbl for tbl, _ in drop_errors)
        )


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
