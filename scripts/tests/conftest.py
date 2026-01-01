"""
Shared pytest fixtures for the scraper test suite
"""

import os
import sys
import uuid
from pathlib import Path
from typing import Dict, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import psycopg2
from psycopg2.extras import RealDictCursor

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent.parent
sys.path.insert(0, str(scripts_dir))

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
    PostgreSQL database connection with schema initialized
    Uses unique table names per test to allow parallel execution
    Yields the connection and cleans up tables after test
    """
    conn = psycopg2.connect(TEST_DB_URL, cursor_factory=RealDictCursor)
    db.init_schema(conn, env=test_env)
    yield conn

    # Cleanup: drop test tables
    cursor = conn.cursor()
    try:
        cursor.execute(f"DROP TABLE IF EXISTS job_listings_{test_env} CASCADE")
        cursor.execute(f"DROP TABLE IF EXISTS scrape_runs_{test_env} CASCADE")
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


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
