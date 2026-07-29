"""
Integration tests for incremental scraping algorithm (shared/incremental.py)

Tests the 5-phase algorithm with mocked scraper and real database.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.constants import SourceId
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
            source_id=SourceId.GOOGLE,
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z"
        )

        result = await process_new_jobs(
            mock_scraper, in_memory_db, new_job_cards, detail_scrape=False
        )

        # Verify job was inserted
        job = db.get_job_by_id(in_memory_db, SourceId.GOOGLE, "new-job-001")
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
            source_id=SourceId.GOOGLE,
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
            source_id=SourceId.GOOGLE,
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
            in_memory_db, SourceId.GOOGLE, still_active_ids, missing_ids
        )

        # Verify last_seen updated and misses reset
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["consecutive_misses"] == 0
        assert closed_count == 0

    def test_update_existing_jobs_missing_increment(self, in_memory_db, sample_job_listing):
        """Missing jobs get misses incremented but not closed until threshold"""
        db.insert_job(in_memory_db, sample_job_listing)

        still_active_ids = set()
        missing_ids = {sample_job_listing.id}

        closed_count = update_existing_jobs(
            in_memory_db, SourceId.GOOGLE, still_active_ids, missing_ids
        )

        # After first miss: consecutive_misses becomes 1, threshold is 2, so not closed yet
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["consecutive_misses"] == 1
        assert job["status"] == "OPEN"
        assert closed_count == 0

    def test_update_existing_jobs_closes_at_threshold(self, in_memory_db, sample_job_listing):
        """Jobs closed when misses >= threshold (2)"""
        db.insert_job(in_memory_db, sample_job_listing)
        # Start with 1 miss — accrued via the real increment path, since the
        # job_freshness sidecar is trigger-seeded at 0 (not from the model).
        db.increment_consecutive_misses(
            in_memory_db, sample_job_listing.source_id, [sample_job_listing.id]
        )

        still_active_ids = set()
        missing_ids = {sample_job_listing.id}

        closed_count = update_existing_jobs(
            in_memory_db,
            SourceId.GOOGLE,
            still_active_ids,
            missing_ids,
            threshold=MISSED_RUN_THRESHOLD,
        )

        # After second miss (total 2), should be closed
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["status"] == "CLOSED"
        assert closed_count == 1

    def test_update_existing_jobs_mixed(self, in_memory_db, multiple_job_listings):
        """Handles mix of active and missing jobs"""
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job)

        still_active_ids = {"job-000"}  # One still active
        missing_ids = {"job-001", "job-002"}  # Two missing

        closed_count = update_existing_jobs(
            in_memory_db, SourceId.GOOGLE, still_active_ids, missing_ids
        )

        # Active job should have misses reset
        job = db.get_job_by_id(in_memory_db, SourceId.GOOGLE, "job-000")
        assert job["consecutive_misses"] == 0

        # Missing jobs should have misses incremented
        for job_id in missing_ids:
            job = db.get_job_by_id(in_memory_db, SourceId.GOOGLE, job_id)
            assert job["consecutive_misses"] == 1

    def test_update_existing_jobs_rejects_empty_source_id(self, in_memory_db):
        """Highest-level fail-fast guard: empty source_id raises before any
        DB call. Locks the contract added in pass 2 — a future caller
        passing source_id='' (misconfigured env var, dropped class attr)
        MUST fail at this boundary, not silently no-op every UPDATE."""
        with pytest.raises(ValueError, match="source_id"):
            update_existing_jobs(in_memory_db, "", {"job-001"}, set())


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
            source_id=SourceId.GOOGLE,
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
            source_id=SourceId.GOOGLE,
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
        cursor.execute("SELECT * FROM scrape_runs WHERE run_id = %s", (result.run_id,))
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
            source_id=SourceId.GOOGLE,
            created_at="2024-01-10T10:00:00Z",
            first_seen_at="2024-01-10T10:00:00Z",
            last_seen_at="2024-01-10T10:00:00Z",
        )
        db.insert_job(in_memory_db, existing_job)
        # Already missed once — established via the real increment path, since
        # the job_freshness sidecar is trigger-seeded at 0 (model field ignored).
        db.increment_consecutive_misses(in_memory_db, SourceId.GOOGLE, ["will-be-closed"])

        # Mock scraper returns empty (simulates scraper failure)
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        # Safety guard should prevent closure
        job = db.get_job_by_id(in_memory_db, SourceId.GOOGLE, "will-be-closed")
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
            source_id=SourceId.GOOGLE,
            created_at="2024-01-10T10:00:00Z",
            first_seen_at="2024-01-10T10:00:00Z",
            last_seen_at="2024-01-10T10:00:00Z",
        )
        missing_job = JobListing(
            id="will-be-closed",
            title="Closing Job",
            company="google",
            url="https://example.com/closing",
            source_id=SourceId.GOOGLE,
            created_at="2024-01-10T10:00:00Z",
            first_seen_at="2024-01-10T10:00:00Z",
            last_seen_at="2024-01-10T10:00:00Z",
        )
        db.insert_job(in_memory_db, seen_job)
        db.insert_job(in_memory_db, missing_job)
        # Already missed once — via the real increment path (sidecar seeded at 0).
        db.increment_consecutive_misses(in_memory_db, SourceId.GOOGLE, ["will-be-closed"])

        # Scraper returns only the active job (missing_job is absent)
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": "still-active", "title": "Active Job", "job_url": "https://example.com/active"},
        ])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        # Missing job should be closed (non-empty scrape, normal behavior)
        job = db.get_job_by_id(in_memory_db, SourceId.GOOGLE, "will-be-closed")
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
                source_id=SourceId.GOOGLE,
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
    async def test_scrape_at_threshold_now_trips_the_partial_guard(self, in_memory_db, mock_scraper):
        """SEMANTIC CHANGE (was ``test_scrape_at_threshold_does_not_trigger_guard``).

        10-of-100 sits exactly ON the legacy ``SAFETY_GUARD_RATIO`` (0.1)
        boundary, so rule (a) — which is a strict ``<`` — still does not
        fire. It used to be the whole guard, and this test asserted the
        run proceeded into the destructive close phase.

        That expectation was wrong for the real world: losing 90% of a
        100-job board is a catastrophic truncation, not "normal operation."
        Rule (b) now catches it (10 < 0.85*100 = 85, and the 90-job drop
        clears the 15-job floor), so the correct expectation flips to
        ``skipped_update is True``.

        The test is KEPT (not deleted) precisely because it pins that
        boundary: rule (a) must remain a strict ``<`` at 0.1, and the run
        must still be blocked — just under the ``partial_scrape`` reason
        rather than ``empty_scrape``.
        """
        # Insert 100 jobs in DB
        for i in range(100):
            job = JobListing(
                id=f"job-{i}",
                title=f"Job {i}",
                company="google",
                url=f"https://example.com/job-{i}",
                source_id=SourceId.GOOGLE,
                created_at="2024-01-10T10:00:00Z",
                first_seen_at="2024-01-10T10:00:00Z",
                last_seen_at="2024-01-10T10:00:00Z",
                consecutive_misses=1,
            )
            db.insert_job(in_memory_db, job)

        # Return 10 jobs (exactly 10% — rule (a) is `<` so it does NOT fire,
        # but rule (b) does).
        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": f"job-{i}", "title": f"Job {i}", "job_url": f"https://example.com/job-{i}"}
            for i in range(10)
        ])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="google", detail_scrape=False
        )

        assert result.skipped_update is True
        assert result.closed_jobs == 0
        assert result.error_count == 1

    @pytest.mark.asyncio
    async def test_apple_style_partial_scrape_does_not_increment_misses(
        self, in_memory_db, mock_scraper
    ):
        """THE regression test for this whole change.

        Replays the real Apple truncation profile: 3,550 OPEN rows in the
        DB, the scrape returns 2,585 (72.8% of the board). Under the old
        0.1-only guard this ran the full update/close phase — every one of
        the 965 unseen jobs got ``consecutive_misses`` incremented, one
        miss away from mass closure. Six of Apple's seven truncations in
        21 days did exactly this in production.

        The assertions cover BOTH halves of the fix:
          * the guard trips and the run is recorded as an error, and
          * critically, the DB is untouched — nothing may drift toward
            CLOSED. Asserting only ``skipped_update`` would still pass if
            the guard flag were set but the phases ran anyway.
        """
        active_total = 3550
        returned = 2585

        jobs = [
            JobListing(
                id=f"apple-{i}",
                title=f"Job {i}",
                company="apple",
                url=f"https://example.com/apple-{i}",
                source_id=SourceId.GOOGLE,
                created_at="2024-01-10T10:00:00Z",
                first_seen_at="2024-01-10T10:00:00Z",
                last_seen_at="2024-01-10T10:00:00Z",
                consecutive_misses=0,
            )
            for i in range(active_total)
        ]
        # NOTE: don't assert on insert_jobs_batch's return value — it reports
        # psycopg2's rowcount for the LAST execute_values page only (page_size
        # =100), so it under-counts any batch over 100. Verify with a COUNT.
        db.insert_jobs_batch(in_memory_db, jobs)
        seed_cursor = in_memory_db.cursor()
        seed_cursor.execute(
            "SELECT count(*) AS n FROM job_listings WHERE company = 'apple'"
        )
        assert seed_cursor.fetchone()['n'] == active_total

        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": f"apple-{i}", "title": f"Job {i}", "job_url": f"https://example.com/apple-{i}"}
            for i in range(returned)
        ])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="apple", detail_scrape=False
        )

        assert result.skipped_update is True
        assert result.error_count == 1
        assert result.closed_jobs == 0

        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT count(*) AS n FROM job_listings "
            "WHERE company = 'apple' AND (consecutive_misses <> 0 OR status <> 'OPEN')"
        )
        drifted = cursor.fetchone()["n"]
        assert drifted == 0, (
            f"{drifted} rows drifted toward closure on a truncated scrape — "
            "the destructive phases ran despite the safety guard"
        )

        cursor.execute(
            "SELECT count(*) AS n FROM job_listings "
            "WHERE company = 'apple' AND status = 'OPEN'"
        )
        assert cursor.fetchone()["n"] == active_total

    @pytest.mark.asyncio
    async def test_two_consecutive_partials_close_nothing(
        self, in_memory_db, mock_scraper
    ):
        """The literal mass-closure scenario, end to end.

        Closure requires MISSED_RUN_THRESHOLD (2) *consecutive* misses. In
        production, two back-to-back Apple truncations would have closed
        ~2,800 live jobs; prod escaped only because a clean run happened to
        land between two of the seven truncations. That is luck, not a
        control — so run the truncation TWICE and assert zero closures.

        Deliberately smaller than the 3,550-row test above (300/200 keeps
        this fast) while staying well past both guard conditions:
        200 < 0.85*300 = 255, and the 100-job drop clears the 15 floor.
        """
        active_total = 300
        returned = 200

        jobs = [
            JobListing(
                id=f"job-{i}",
                title=f"Job {i}",
                company="apple",
                url=f"https://example.com/job-{i}",
                source_id=SourceId.GOOGLE,
                created_at="2024-01-10T10:00:00Z",
                first_seen_at="2024-01-10T10:00:00Z",
                last_seen_at="2024-01-10T10:00:00Z",
                consecutive_misses=0,
            )
            for i in range(active_total)
        ]
        # NOTE: don't assert on insert_jobs_batch's return value — it reports
        # psycopg2's rowcount for the LAST execute_values page only (page_size
        # =100), so it under-counts any batch over 100. Verify with a COUNT.
        db.insert_jobs_batch(in_memory_db, jobs)
        seed_cursor = in_memory_db.cursor()
        seed_cursor.execute(
            "SELECT count(*) AS n FROM job_listings WHERE company = 'apple'"
        )
        assert seed_cursor.fetchone()['n'] == active_total

        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": f"job-{i}", "title": f"Job {i}", "job_url": f"https://example.com/job-{i}"}
            for i in range(returned)
        ])

        for run_number in (1, 2):
            result = await run_incremental_scrape(
                mock_scraper, in_memory_db, company="apple", detail_scrape=False
            )
            assert result.skipped_update is True, f"run {run_number}"
            assert result.closed_jobs == 0, f"run {run_number}"

        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT count(*) AS n FROM job_listings "
            "WHERE company = 'apple' AND status = 'CLOSED'"
        )
        closed = cursor.fetchone()["n"]
        assert closed == 0, (
            f"{closed} jobs mass-closed by two consecutive truncated scrapes"
        )

    @pytest.mark.asyncio
    async def test_guard_trip_is_persisted_on_the_scrape_run_row(
        self, in_memory_db, mock_scraper
    ):
        """A tripped guard must be legible in ``scrape_runs`` afterwards.

        Before this change ``skipped_update`` was computed and thrown away,
        so a truncated run was persisted with ``error_count=0`` — byte for
        byte identical to a perfect run. That is why seven real Apple
        truncations sat unnoticed in the table for three weeks.
        """
        jobs = [
            JobListing(
                id=f"job-{i}",
                title=f"Job {i}",
                company="apple",
                url=f"https://example.com/job-{i}",
                source_id=SourceId.GOOGLE,
                created_at="2024-01-10T10:00:00Z",
                first_seen_at="2024-01-10T10:00:00Z",
                last_seen_at="2024-01-10T10:00:00Z",
            )
            for i in range(200)
        ]
        db.insert_jobs_batch(in_memory_db, jobs)

        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": f"job-{i}", "title": f"Job {i}", "job_url": f"https://example.com/job-{i}"}
            for i in range(100)
        ])

        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="apple", detail_scrape=False
        )

        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT skipped_update, error_count FROM scrape_runs WHERE run_id = %s",
            (result.run_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["skipped_update"] is True
        assert row["error_count"] == 1


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
