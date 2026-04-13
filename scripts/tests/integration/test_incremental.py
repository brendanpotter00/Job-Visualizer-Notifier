"""
Integration tests for incremental scraping algorithm (shared/incremental.py)

Tests the 5-phase algorithm with mocked scraper and real database.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.models import JobListing
from shared import database as db
from shared.incremental import (
    process_new_jobs,
    update_existing_jobs,
    run_incremental_scrape,
    ScrapeResult,
    MISSED_RUN_THRESHOLD,
    SAFETY_GUARD_RATIO,
)


class TestProcessNewJobs:
    """Tests for process_new_jobs function"""

    @pytest.mark.asyncio
    async def test_process_new_jobs_inserts_to_db(self, in_memory_db, mock_scraper):
        """New jobs inserted into database"""
        new_job_cards = [
            {
                "id": "new-job-001",
                "title": "Software Engineer",
                "job_url": "https://example.com/jobs/results/new-job-001-software-engineer",
                "location": "Mountain View, CA"
            }
        ]

        # Configure mock scraper
        mock_scraper.transform_to_job_model.return_value = JobListing(
            id="new-job-001",
            title="Software Engineer",
            company="google",
            url="https://example.com/jobs/results/new-job-001",
            source_id="google_scraper",
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z"
        )

        result = await process_new_jobs(
            mock_scraper, in_memory_db, new_job_cards, detail_scrape=False
        )

        # Verify job was inserted
        job = db.get_job_by_id(in_memory_db, "new-job-001")
        assert job is not None
        assert job["title"] == "Software Engineer"

    @pytest.mark.asyncio
    async def test_process_new_jobs_with_details(self, in_memory_db, mock_scraper):
        """Details fetched when detail_scrape=True"""
        new_job_cards = [
            {"id": "job-001", "title": "Test Job", "job_url": "https://example.com/job"}
        ]

        # Mock scrape_job_details_streaming as an async generator
        async def mock_streaming(job_cards):
            for job in job_cards:
                yield {"id": "job-001", "title": "Test Job", "job_url": "https://example.com/job", "salary": "$100k"}

        mock_scraper.scrape_job_details_streaming = mock_streaming
        mock_scraper.transform_to_job_model.return_value = JobListing(
            id="job-001",
            title="Test Job",
            company="google",
            url="https://example.com/job",
            source_id="google_scraper",
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z"
        )

        result = await process_new_jobs(
            mock_scraper, in_memory_db, new_job_cards, detail_scrape=True
        )

        # Should have yielded 1 enriched job
        assert result == 1  # 1 detail fetched

    @pytest.mark.asyncio
    async def test_process_new_jobs_without_details(self, in_memory_db, mock_scraper):
        """Details skipped when detail_scrape=False"""
        new_job_cards = [
            {"id": "job-001", "title": "Test Job", "job_url": "https://example.com/job"}
        ]

        # Track whether streaming was called
        streaming_called = False

        async def mock_streaming(job_cards):
            nonlocal streaming_called
            streaming_called = True
            for job in job_cards:
                yield job

        mock_scraper.scrape_job_details_streaming = mock_streaming
        mock_scraper.transform_to_job_model.return_value = JobListing(
            id="job-001",
            title="Test Job",
            company="google",
            url="https://example.com/job",
            source_id="google_scraper",
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z"
        )

        result = await process_new_jobs(
            mock_scraper, in_memory_db, new_job_cards, detail_scrape=False
        )

        # Should NOT have called scrape_job_details_streaming when detail_scrape=False
        assert not streaming_called
        assert result == 0  # 0 details fetched

    @pytest.mark.asyncio
    async def test_process_new_jobs_empty(self, in_memory_db, mock_scraper):
        """Returns 0 for empty job list"""
        result = await process_new_jobs(
            mock_scraper, in_memory_db, [], detail_scrape=True
        )
        assert result == 0


class TestUpdateExistingJobs:
    """Tests for update_existing_jobs function"""

    def test_update_existing_jobs_active(self, in_memory_db, sample_job_listing):
        """Active jobs get last_seen updated"""
        db.insert_job(in_memory_db, sample_job_listing)

        still_active_ids = {sample_job_listing.id}
        missing_ids = set()

        closed_count = update_existing_jobs(
            in_memory_db, still_active_ids, missing_ids
        )

        # Verify last_seen updated and misses reset
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id)
        assert job["consecutive_misses"] == 0
        assert closed_count == 0

    def test_update_existing_jobs_missing_increment(self, in_memory_db, sample_job_listing):
        """Missing jobs get misses incremented but not closed until threshold"""
        db.insert_job(in_memory_db, sample_job_listing)

        still_active_ids = set()
        missing_ids = {sample_job_listing.id}

        closed_count = update_existing_jobs(
            in_memory_db, still_active_ids, missing_ids
        )

        # After first miss: consecutive_misses becomes 1, threshold is 2, so not closed yet
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id)
        assert job["consecutive_misses"] == 1
        assert job["status"] == "OPEN"
        assert closed_count == 0

    def test_update_existing_jobs_closes_at_threshold(self, in_memory_db, sample_job_listing):
        """Jobs closed when misses >= threshold (2)"""
        # Start with 1 miss
        sample_job_listing.consecutive_misses = 1
        db.insert_job(in_memory_db, sample_job_listing)

        still_active_ids = set()
        missing_ids = {sample_job_listing.id}

        closed_count = update_existing_jobs(
            in_memory_db, still_active_ids, missing_ids, threshold=2
        )

        # After second miss (total 2), should be closed
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id)
        assert job["status"] == "CLOSED"
        assert closed_count == 1

    def test_update_existing_jobs_mixed(self, in_memory_db, multiple_job_listings):
        """Handles mix of active and missing jobs"""
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job)

        still_active_ids = {"job-000"}  # One still active
        missing_ids = {"job-001", "job-002"}  # Two missing

        closed_count = update_existing_jobs(
            in_memory_db, still_active_ids, missing_ids
        )

        # Active job should have misses reset
        job = db.get_job_by_id(in_memory_db, "job-000")
        assert job["consecutive_misses"] == 0

        # Missing jobs should have misses incremented
        for job_id in missing_ids:
            job = db.get_job_by_id(in_memory_db, job_id)
            assert job["consecutive_misses"] == 1


class TestRunIncrementalScrape:
    """Tests for run_incremental_scrape function (full 5-phase algorithm)"""

    @pytest.mark.asyncio
    async def test_run_incremental_scrape_full_flow(self, in_memory_db, mock_scraper):
        """Complete 5-phase algorithm"""
        # Setup: Insert existing jobs
        existing_job = JobListing(
            id="existing-001",
            title="Existing Job",
            company="google",
            url="https://example.com/existing",
            source_id="google_scraper",
            created_at="2024-01-10T10:00:00Z",
            first_seen_at="2024-01-10T10:00:00Z",
            last_seen_at="2024-01-10T10:00:00Z"
        )
        db.insert_job(in_memory_db, existing_job)

        # Mock scraper returns one existing and one new job
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": "existing-001", "title": "Existing Job", "job_url": "https://example.com/existing"},
            {"id": "new-001", "title": "New Job", "job_url": "https://example.com/new"}
        ])

        mock_scraper.transform_to_job_model.return_value = JobListing(
            id="new-001",
            title="New Job",
            company="google",
            url="https://example.com/new",
            source_id="google_scraper",
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z"
        )

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        # Verify result
        assert isinstance(result, ScrapeResult)
        assert result.jobs_seen == 2
        assert result.new_jobs == 1

    @pytest.mark.asyncio
    async def test_run_incremental_scrape_records_run(self, in_memory_db, mock_scraper):
        """ScrapeRun recorded in database"""
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        # Verify scrape run recorded
        cursor = in_memory_db.cursor()
        cursor.execute(f"SELECT * FROM {db.RUNS_TABLE} WHERE run_id = %s", (result.run_id,))
        row = cursor.fetchone()

        assert row is not None
        assert dict(row)["company"] == "google"
        assert dict(row)["mode"] == "incremental"

    @pytest.mark.asyncio
    async def test_run_incremental_scrape_empty_scrape_skips_closure(self, in_memory_db, mock_scraper):
        """Empty scrape with active jobs in DB triggers safety guard - jobs NOT closed"""
        # Insert job that would normally be closed on 2nd miss
        existing_job = JobListing(
            id="will-be-closed",
            title="Closing Job",
            company="google",
            url="https://example.com/closing",
            source_id="google_scraper",
            created_at="2024-01-10T10:00:00Z",
            first_seen_at="2024-01-10T10:00:00Z",
            last_seen_at="2024-01-10T10:00:00Z",
            consecutive_misses=1  # Already missed once
        )
        db.insert_job(in_memory_db, existing_job)

        # Mock scraper returns empty (simulates scraper failure)
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        # Safety guard should prevent closure
        job = db.get_job_by_id(in_memory_db, "will-be-closed")
        assert job["status"] == "OPEN"
        assert job["consecutive_misses"] == 1  # Unchanged
        assert result.closed_jobs == 0
        assert result.skipped_update is True

    @pytest.mark.asyncio
    async def test_run_incremental_scrape_nonempty_scrape_closes_missing(self, in_memory_db, mock_scraper):
        """Non-empty scrape with missing jobs still closes them normally"""
        # Insert two jobs: one will be seen, one will be missing
        seen_job = JobListing(
            id="still-active",
            title="Active Job",
            company="google",
            url="https://example.com/active",
            source_id="google_scraper",
            created_at="2024-01-10T10:00:00Z",
            first_seen_at="2024-01-10T10:00:00Z",
            last_seen_at="2024-01-10T10:00:00Z",
        )
        missing_job = JobListing(
            id="will-be-closed",
            title="Closing Job",
            company="google",
            url="https://example.com/closing",
            source_id="google_scraper",
            created_at="2024-01-10T10:00:00Z",
            first_seen_at="2024-01-10T10:00:00Z",
            last_seen_at="2024-01-10T10:00:00Z",
            consecutive_misses=1  # Already missed once
        )
        db.insert_job(in_memory_db, seen_job)
        db.insert_job(in_memory_db, missing_job)

        # Scraper returns only the active job (missing_job is absent)
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": "still-active", "title": "Active Job", "job_url": "https://example.com/active"},
        ])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        # Missing job should be closed (non-empty scrape, normal behavior)
        job = db.get_job_by_id(in_memory_db, "will-be-closed")
        assert job["status"] == "CLOSED"
        assert result.closed_jobs == 1
        assert result.skipped_update is False

    @pytest.mark.asyncio
    async def test_run_incremental_scrape_empty_scrape_empty_db(self, in_memory_db, mock_scraper):
        """Empty scrape with empty DB does not trigger safety guard"""
        # No jobs in database
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        assert result.jobs_seen == 0
        assert result.skipped_update is False
        assert result.closed_jobs == 0

    @pytest.mark.asyncio
    async def test_partial_scrape_triggers_safety_guard(self, in_memory_db, mock_scraper):
        """Scraper returning fewer jobs than SAFETY_GUARD_RATIO triggers guard"""
        # Insert 100 jobs in DB
        for i in range(100):
            job = JobListing(
                id=f"job-{i}",
                title=f"Job {i}",
                company="google",
                url=f"https://example.com/job-{i}",
                source_id="google_scraper",
                created_at="2024-01-10T10:00:00Z",
                first_seen_at="2024-01-10T10:00:00Z",
                last_seen_at="2024-01-10T10:00:00Z",
                consecutive_misses=1,
            )
            db.insert_job(in_memory_db, job)

        # Return 5 jobs (5% < 10% threshold) — simulates crash after first page
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": f"job-{i}", "title": f"Job {i}", "job_url": f"https://example.com/job-{i}"}
            for i in range(5)
        ])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        assert result.skipped_update is True
        assert result.closed_jobs == 0

    @pytest.mark.asyncio
    async def test_scrape_at_threshold_does_not_trigger_guard(self, in_memory_db, mock_scraper):
        """Scraper returning exactly at SAFETY_GUARD_RATIO does NOT trigger guard"""
        # Insert 100 jobs in DB
        for i in range(100):
            job = JobListing(
                id=f"job-{i}",
                title=f"Job {i}",
                company="google",
                url=f"https://example.com/job-{i}",
                source_id="google_scraper",
                created_at="2024-01-10T10:00:00Z",
                first_seen_at="2024-01-10T10:00:00Z",
                last_seen_at="2024-01-10T10:00:00Z",
                consecutive_misses=1,
            )
            db.insert_job(in_memory_db, job)

        # Return 10 jobs (10% = threshold, not below) — normal operation proceeds
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": f"job-{i}", "title": f"Job {i}", "job_url": f"https://example.com/job-{i}"}
            for i in range(10)
        ])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        assert result.skipped_update is False


class TestScrapeResult:
    """Tests for ScrapeResult class"""

    def test_scrape_result_defaults(self):
        """ScrapeResult has correct defaults"""
        result = ScrapeResult()

        assert result.jobs_seen == 0
        assert result.new_jobs == 0
        assert result.closed_jobs == 0
        assert result.details_fetched == 0
        assert result.error_count == 0
        assert result.run_id is not None  # Auto-generated
        assert result.skipped_update is False

    def test_scrape_result_with_values(self):
        """ScrapeResult accepts custom values"""
        result = ScrapeResult(
            jobs_seen=100,
            new_jobs=10,
            closed_jobs=5,
            details_fetched=10,
            error_count=2,
            run_id="custom-run-id"
        )

        assert result.jobs_seen == 100
        assert result.new_jobs == 10
        assert result.closed_jobs == 5
        assert result.details_fetched == 10
        assert result.error_count == 2
        assert result.run_id == "custom-run-id"
        assert result.skipped_update is False

    def test_scrape_result_skipped_update(self):
        """ScrapeResult accepts skipped_update flag"""
        result = ScrapeResult(skipped_update=True)
        assert result.skipped_update is True
