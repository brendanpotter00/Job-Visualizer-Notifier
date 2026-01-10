"""
Unit tests for Pydantic models (shared/models.py)
"""

import pytest
from pydantic import ValidationError

from shared.models import JobListing, ScrapeRun


class TestJobListing:
    """Tests for JobListing Pydantic model"""

    def test_job_listing_valid(self, sample_job_listing):
        """Create JobListing with all required fields"""
        assert sample_job_listing.id == "114423471240291014"
        assert sample_job_listing.title == "Software Engineer III, Cloud"
        assert sample_job_listing.company == "google"
        assert sample_job_listing.status == "OPEN"

    def test_job_listing_defaults(self):
        """Verify default values (status='OPEN', consecutive_misses=0)"""
        job = JobListing(
            id="test-001",
            title="Test Job",
            company="google",
            url="https://example.com/job",
            source_id="test_scraper",
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z"
        )

        # Verify defaults
        assert job.status == "OPEN"
        assert job.consecutive_misses == 0
        assert job.has_matched is False
        assert job.details_scraped is False
        assert job.details == {}
        assert job.ai_metadata == {}

    def test_job_listing_optional_fields(self):
        """Verify optional fields can be None"""
        job = JobListing(
            id="test-002",
            title="Test Job",
            company="google",
            url="https://example.com/job",
            source_id="test_scraper",
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z",
            location=None,
            posted_on=None,
            closed_on=None
        )

        assert job.location is None
        assert job.posted_on is None
        assert job.closed_on is None

    def test_job_listing_invalid_missing_required(self):
        """Missing required field raises ValidationError"""
        with pytest.raises(ValidationError) as exc_info:
            JobListing(
                id="test-003",
                # Missing: title, company, url, source_id, created_at, first_seen_at, last_seen_at
            )

        # Should have multiple validation errors for missing fields
        errors = exc_info.value.errors()
        assert len(errors) > 0

        # Check that required fields are mentioned in errors
        error_fields = {e["loc"][0] for e in errors}
        assert "title" in error_fields
        assert "company" in error_fields
        assert "url" in error_fields

    def test_job_listing_with_details(self):
        """JobListing with complex details dict"""
        details = {
            "minimum_qualifications": ["Python", "SQL"],
            "preferred_qualifications": ["Machine Learning"],
            "about_the_job": "Great opportunity",
            "responsibilities": ["Write code", "Review PRs"],
            "nested": {"key": "value", "list": [1, 2, 3]}
        }

        job = JobListing(
            id="test-004",
            title="ML Engineer",
            company="google",
            url="https://example.com/job",
            source_id="test_scraper",
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z",
            details=details
        )

        assert job.details["minimum_qualifications"] == ["Python", "SQL"]
        assert job.details["nested"]["key"] == "value"


class TestScrapeRun:
    """Tests for ScrapeRun Pydantic model"""

    def test_scrape_run_valid(self, sample_scrape_run):
        """Create valid ScrapeRun"""
        assert sample_scrape_run.run_id == "test-run-001"
        assert sample_scrape_run.company == "google"
        assert sample_scrape_run.mode == "incremental"
        assert sample_scrape_run.jobs_seen == 100
        assert sample_scrape_run.new_jobs == 10

    def test_scrape_run_defaults(self):
        """Verify default counters are 0"""
        run = ScrapeRun(
            run_id="test-run-002",
            company="google",
            started_at="2024-01-15T10:30:00Z",
            mode="full"
        )

        assert run.jobs_seen == 0
        assert run.new_jobs == 0
        assert run.closed_jobs == 0
        assert run.details_fetched == 0
        assert run.error_count == 0
        assert run.completed_at is None

    def test_scrape_run_invalid_missing_required(self):
        """Missing required field raises ValidationError"""
        with pytest.raises(ValidationError) as exc_info:
            ScrapeRun(
                run_id="test-run-003"
                # Missing: company, started_at, mode
            )

        errors = exc_info.value.errors()
        error_fields = {e["loc"][0] for e in errors}
        assert "company" in error_fields
        assert "started_at" in error_fields
        assert "mode" in error_fields

    def test_scrape_run_with_all_fields(self):
        """ScrapeRun with all fields populated"""
        run = ScrapeRun(
            run_id="test-run-004",
            company="apple",
            started_at="2024-01-15T10:00:00Z",
            completed_at="2024-01-15T11:30:00Z",
            mode="incremental",
            jobs_seen=500,
            new_jobs=50,
            closed_jobs=20,
            details_fetched=50,
            error_count=3
        )

        assert run.company == "apple"
        assert run.completed_at == "2024-01-15T11:30:00Z"
        assert run.jobs_seen == 500
        assert run.error_count == 3
