"""
Integration tests for incremental scraping algorithm (shared/incremental.py)

Tests the 5-phase algorithm with mocked scraper and real database.
"""

import logging

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
    SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS,
    RELEASED_RUN_MISS_THRESHOLD,
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
            "SELECT count(*) AS n FROM job_listings j "
            "JOIN job_freshness f ON f.source_id = j.source_id AND f.id = j.id "
            "WHERE j.company = 'apple' "
            "AND (f.consecutive_misses <> 0 OR j.status <> 'OPEN')"
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


class TestGuardLogRouting:
    """The guard trip must reach Railway's ``@level:error`` filter."""

    @pytest.mark.asyncio
    async def test_guard_trip_logs_at_error_level(
        self, in_memory_db, mock_scraper, caplog
    ):
        """Must be ERROR, not WARNING.

        ``_configure_logging`` in ``src/backend/api/main.py`` caps the
        stdout handler below ERROR and sends ERROR+ to stderr, and Railway
        derives its ``@level`` field from the OS stream. A WARNING here
        therefore never appears in the ``@level:error`` query operators
        actually watch.

        This mattered specifically: the six ATS leaf tasks have always
        logged the guard at ERROR (with a load-bearing comment saying why),
        while THIS path — the one used by the script-scraped companies,
        i.e. google/apple/microsoft — logged at WARNING. Apple, the company
        this entire change exists for, was the one silently outside the
        filter.
        """
        for i in range(200):
            db.insert_job(
                in_memory_db,
                JobListing(
                    id=f"job-{i}",
                    title=f"Job {i}",
                    company="apple",
                    url=f"https://example.com/job-{i}",
                    source_id=SourceId.GOOGLE,
                    created_at="2024-01-10T10:00:00Z",
                    first_seen_at="2024-01-10T10:00:00Z",
                    last_seen_at="2024-01-10T10:00:00Z",
                ),
            )

        mock_scraper.scrape_all_queries = AsyncMock(return_value=[
            {"id": f"job-{i}", "title": f"Job {i}", "job_url": f"https://example.com/job-{i}"}
            for i in range(100)
        ])

        with caplog.at_level(logging.WARNING, logger="shared.incremental"):
            await run_incremental_scrape(
                mock_scraper, in_memory_db, company="apple", detail_scrape=False
            )

        guard_records = [
            r for r in caplog.records if "SAFETY GUARD" in r.getMessage()
        ]
        assert guard_records, "no SAFETY GUARD log line was emitted at all"
        assert all(r.levelno == logging.ERROR for r in guard_records), (
            "the safety-guard log must be ERROR so Railway routes it to "
            "stderr and it shows up under @level:error; got "
            f"{[r.levelname for r in guard_records]}"
        )


class TestBoundedAutoReleaseEndToEnd:
    """The auto-release, exercised through the real DB history read.

    ``TestBoundedAutoRelease`` in ``tests/unit/test_incremental_diff.py``
    pins the pure decision. These tests prove the wiring: that
    ``resolve_safety_guard`` actually reads ``scrape_runs.skipped_update``,
    that the streak is counted correctly, and — the part that matters
    operationally — that a released run still cannot mass-close anything.
    """

    @staticmethod
    def _seed(in_memory_db, total, company="apple"):
        jobs = [
            JobListing(
                id=f"job-{i}",
                title=f"Job {i}",
                company=company,
                url=f"https://example.com/job-{i}",
                source_id=SourceId.GOOGLE,
                created_at="2024-01-10T10:00:00Z",
                first_seen_at="2024-01-10T10:00:00Z",
                last_seen_at="2024-01-10T10:00:00Z",
                consecutive_misses=0,
            )
            for i in range(total)
        ]
        db.insert_jobs_batch(in_memory_db, jobs)

    @staticmethod
    def _cards(returned):
        return [
            {"id": f"job-{i}", "title": f"Job {i}", "job_url": f"https://example.com/job-{i}"}
            for i in range(returned)
        ]

    @pytest.mark.asyncio
    async def test_permanent_shrink_releases_after_n_consecutive_skips(
        self, in_memory_db, mock_scraper
    ):
        """The reviewer's scenario: a company permanently cuts its board
        from 200 to 150 and keeps returning 150 forever.

        Runs 1..N are skipped (the guard cannot yet tell a permanent shrink
        from a transient truncation). Run N+1 is released so the DB can
        reconcile — otherwise the company is frozen out of ingestion and
        lifecycle indefinitely, which is what shipped before this fix.
        """
        self._seed(in_memory_db, 200)
        mock_scraper.scrape_all_queries = AsyncMock(return_value=self._cards(150))

        skipped_flags = []
        for _ in range(SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS + 1):
            result = await run_incremental_scrape(
                mock_scraper, in_memory_db, company="apple", detail_scrape=False
            )
            skipped_flags.append(result.skipped_update)

        assert skipped_flags[:SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS] == [True] * (
            SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS
        ), "the guard must latch first — releasing immediately would defeat it"
        assert skipped_flags[-1] is False, (
            "after N consecutive partial skips the guard must release one run; "
            "without this the company is frozen forever"
        )

    @pytest.mark.asyncio
    async def test_a_single_released_run_closes_nothing_on_a_pristine_board(
        self, in_memory_db, mock_scraper
    ):
        """Baseline (weak) case: no job carries prior miss evidence.

        Kept, but do NOT mistake it for proof — it is a confirming instance.
        The falsifying case is the next test, where jobs enter the freeze
        already at misses=1; that is what exposed the original
        "can never close anything" claim as false.
        """
        self._seed(in_memory_db, 200)
        mock_scraper.scrape_all_queries = AsyncMock(return_value=self._cards(150))

        for _ in range(SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS + 1):
            await run_incremental_scrape(
                mock_scraper, in_memory_db, company="apple", detail_scrape=False
            )

        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT count(*) AS n FROM job_listings "
            "WHERE company = 'apple' AND status = 'CLOSED'"
        )
        assert cursor.fetchone()["n"] == 0

        # Freshness lives in the job_freshness sidecar — job_listings has
        # no consecutive_misses column at all since 18fe9c20a8fd (#239).
        cursor.execute(
            "SELECT max(f.consecutive_misses) AS m FROM job_freshness f "
            "JOIN job_listings j ON j.source_id = f.source_id AND j.id = f.id "
            "WHERE j.company = 'apple'"
        )
        assert cursor.fetchone()["m"] == 1

    @pytest.mark.asyncio
    async def test_released_run_closes_nothing_when_jobs_carry_prior_misses(
        self, in_memory_db, mock_scraper
    ):
        """FALSIFICATION TEST — this is the one that matters.

        ``consecutive_misses`` PERSISTS across guard trips, because a tripped
        run is a total no-op on ``job_listings``. So jobs that already carry
        a miss from an earlier healthy run walk into the freeze one step from
        closure, and the released run finishes them off.

        Replays the reviewer's A/B exactly: a 1000-job board where every job
        stays live throughout. Run 1 is a sub-threshold hiccup returning 870
        (87% — correctly does NOT trip, and correctly records one miss for
        the 130 jobs it did not return). Runs 2..N+1 truncate to 500. With
        the released run using the ordinary MISSED_RUN_THRESHOLD, run N+1
        closed all 130 live jobs. It must close zero.
        """
        total, hiccup, truncated = 1000, 870, 500
        self._seed(in_memory_db, total)

        # Run 1: sub-threshold hiccup. 870/1000 = 87% > 85%, and this is
        # exactly the shape the guard is designed NOT to catch.
        mock_scraper.scrape_all_queries = AsyncMock(return_value=self._cards(hiccup))
        first = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="apple", detail_scrape=False
        )
        assert first.skipped_update is False, "hiccup should not trip the guard"
        assert first.closed_jobs == 0

        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT count(*) AS n FROM job_freshness f "
            "JOIN job_listings j ON j.source_id = f.source_id AND j.id = f.id "
            "WHERE j.company = 'apple' AND f.consecutive_misses = 1"
        )
        primed = cursor.fetchone()["n"]
        assert primed == total - hiccup == 130, (
            "test setup failed to prime any jobs with a prior miss — without "
            "that this degenerates into the weak pristine-board case"
        )

        # Runs 2..N+1: sustained truncation, ending on the released run.
        mock_scraper.scrape_all_queries = AsyncMock(return_value=self._cards(truncated))
        flags = []
        for _ in range(SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS + 1):
            result = await run_incremental_scrape(
                mock_scraper, in_memory_db, company="apple", detail_scrape=False
            )
            flags.append(result.skipped_update)

        assert flags[-1] is False, "the run under test must be the released one"

        cursor.execute(
            "SELECT count(*) AS n FROM job_listings "
            "WHERE company = 'apple' AND status = 'CLOSED'"
        )
        closed = cursor.fetchone()["n"]
        assert closed == 0, (
            f"{closed} live jobs were closed by a single released run. Jobs "
            "entering a freeze can already carry MISSED_RUN_THRESHOLD-1 "
            "misses, so the released run must close at "
            "RELEASED_RUN_MISS_THRESHOLD, not MISSED_RUN_THRESHOLD."
        )

    @pytest.mark.asyncio
    async def test_two_release_cycles_do_reconcile_a_permanent_shrink(
        self, in_memory_db, mock_scraper
    ):
        """The stricter released-run threshold must not break liveness.

        Raising the bar so one release can't close anything is only correct
        if repeated releases still reconcile — otherwise the freeze is
        permanent again, just with extra steps. Drives enough cycles to
        reach RELEASED_RUN_MISS_THRESHOLD and asserts the vanished jobs do
        finally close.
        """
        self._seed(in_memory_db, 200)
        mock_scraper.scrape_all_queries = AsyncMock(return_value=self._cards(150))

        releases = 0
        # Each cycle is N skips + 1 release; RELEASED_RUN_MISS_THRESHOLD
        # releases are needed to accumulate that many misses.
        for _ in range((SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS + 1)
                       * RELEASED_RUN_MISS_THRESHOLD):
            result = await run_incremental_scrape(
                mock_scraper, in_memory_db, company="apple", detail_scrape=False
            )
            if result.skipped_update is False:
                releases += 1

        assert releases >= RELEASED_RUN_MISS_THRESHOLD

        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT count(*) AS n FROM job_listings "
            "WHERE company = 'apple' AND status = 'CLOSED'"
        )
        assert cursor.fetchone()["n"] == 50, (
            "a permanent 200->150 shrink never reconciled — the release is "
            "now so strict it has become the freeze it was meant to fix"
        )

    @pytest.mark.asyncio
    async def test_released_run_can_close_an_anomalous_row(
        self, in_memory_db, mock_scraper
    ):
        """Pins the ONE gap in the safety argument, honestly.

        The proof that a single released run cannot close anything rests on
        "a healthy run closes any job reaching MISSED_RUN_THRESHOLD, so an
        OPEN job entering a freeze carries at most THRESHOLD-1 misses". A row
        that is somehow already at/above the threshold while still OPEN
        (legacy data, or a close interrupted between increment and
        mark_jobs_closed) violates that premise and IS closable by the first
        release.

        Asserted rather than hidden so the bound in the module docstring
        stays honest, and so anyone who later claims blanket immunity has to
        confront this test.
        """
        self._seed(in_memory_db, 200)
        cursor = in_memory_db.cursor()
        # Seed the anomaly in the sidecar — the only store there is: the
        # close path reads it, and job_listings has carried no
        # consecutive_misses column since 18fe9c20a8fd (#239).
        cursor.execute(
            "UPDATE job_freshness SET consecutive_misses = %s "
            "WHERE (source_id, id) IN "
            "(SELECT source_id, id FROM job_listings "
            " WHERE company = 'apple' AND id = 'job-199')",
            (RELEASED_RUN_MISS_THRESHOLD,),
        )
        in_memory_db.commit()

        mock_scraper.scrape_all_queries = AsyncMock(return_value=self._cards(150))
        for _ in range(SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS + 1):
            await run_incremental_scrape(
                mock_scraper, in_memory_db, company="apple", detail_scrape=False
            )

        cursor.execute(
            "SELECT status FROM job_listings "
            "WHERE company = 'apple' AND id = 'job-199'"
        )
        assert cursor.fetchone()["status"] == "CLOSED"

    @pytest.mark.asyncio
    async def test_empty_scrape_skips_do_not_earn_a_release(
        self, in_memory_db, mock_scraper
    ):
        """FALSIFICATION TEST — rule (a) must not feed the rule (b) counter.

        The streak used to be counted on ``skipped_update``, which BOTH rules
        set. So a totally dead scraper returning 0, 0, 0 accumulated three
        "skips" and released the very FIRST truncated run that followed —
        with zero repetition evidence, and in exactly the
        repaired-dead-scraper scenario (appliedintuition, unity3d) the
        release exists to protect.

        Three empty scrapes, then one truncated run: the truncated run must
        still latch.
        """
        self._seed(in_memory_db, 200)

        mock_scraper.scrape_all_queries = AsyncMock(return_value=[])
        for _ in range(SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS):
            result = await run_incremental_scrape(
                mock_scraper, in_memory_db, company="apple", detail_scrape=False
            )
            assert result.guard_reason == "empty_scrape"

        mock_scraper.scrape_all_queries = AsyncMock(return_value=self._cards(150))
        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="apple", detail_scrape=False
        )

        assert result.skipped_update is True, (
            "a dead scraper's empty_scrape skips released the first "
            "partial_scrape run — rule (a) is documented as never "
            "auto-released and must not supply release evidence either"
        )
        assert result.guard_reason == "partial_scrape"

    @pytest.mark.asyncio
    async def test_alternating_outage_and_truncation_never_releases(
        self, in_memory_db, mock_scraper
    ):
        """The reviewer's 'Regime I': 0, 0, 0, 150 repeating, with no real
        shrink anywhere. Counting the boolean, run 8 closed 50 of 200. With
        the streak counted on partial_scrape only, nothing may ever close —
        no two partial runs are ever consecutive."""
        self._seed(in_memory_db, 200)

        empty = AsyncMock(return_value=[])
        truncated = AsyncMock(return_value=self._cards(150))

        for cycle in range(3):
            for scrape in (empty, empty, empty, truncated):
                mock_scraper.scrape_all_queries = scrape
                result = await run_incremental_scrape(
                    mock_scraper, in_memory_db, company="apple", detail_scrape=False
                )
                assert result.skipped_update is True, f"cycle {cycle}"

        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT count(*) AS n FROM job_listings "
            "WHERE company = 'apple' AND status = 'CLOSED'"
        )
        assert cursor.fetchone()["n"] == 0

    @pytest.mark.asyncio
    async def test_a_healthy_run_resets_the_streak(
        self, in_memory_db, mock_scraper
    ):
        """A transient truncation must NOT accumulate toward a release.

        Two skips, then one healthy run, then two more skips = five runs
        but never N in a row, so the guard stays latched. This is the case
        the release must not fire on: an intermittent scraper, not a real
        shrink.
        """
        self._seed(in_memory_db, 200)

        truncated = AsyncMock(return_value=self._cards(150))
        healthy = AsyncMock(return_value=self._cards(200))

        flags = []
        for scrape in (truncated, truncated, healthy, truncated, truncated):
            mock_scraper.scrape_all_queries = scrape
            result = await run_incremental_scrape(
                mock_scraper, in_memory_db, company="apple", detail_scrape=False
            )
            flags.append(result.skipped_update)

        assert flags == [True, True, False, True, True], (
            "an intervening healthy run must reset the consecutive-skip "
            "streak; otherwise a flaky scraper eventually earns a release"
        )

    @pytest.mark.asyncio
    async def test_null_skipped_update_rows_do_not_count_toward_release(
        self, in_memory_db, mock_scraper
    ):
        """Pre-column rows are NULL = "unknown", and an unknown must never
        be counted as evidence for releasing a destructive guard.

        Seeds N historical runs with skipped_update IS NULL (exactly what
        every row written before migration ae99a1939dc1 looks like) and
        asserts the very next truncated run still latches.
        """
        self._seed(in_memory_db, 200)

        cursor = in_memory_db.cursor()
        for i in range(SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS + 2):
            cursor.execute(
                "INSERT INTO scrape_runs (run_id, company, started_at, mode, "
                "jobs_seen, skipped_update) VALUES (%s, 'apple', %s, 'incremental', 150, NULL)",
                (f"legacy-{i}", f"2020-01-0{i + 1}T00:00:00Z"),
            )
        in_memory_db.commit()

        mock_scraper.scrape_all_queries = AsyncMock(return_value=self._cards(150))
        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="apple", detail_scrape=False
        )

        assert result.skipped_update is True

    @pytest.mark.asyncio
    async def test_streak_is_scoped_per_company(self, in_memory_db, mock_scraper):
        """One company's skips must not release another's guard."""
        self._seed(in_memory_db, 200, company="apple")
        self._seed(in_memory_db, 200, company="google")

        cursor = in_memory_db.cursor()
        for i in range(SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS + 2):
            cursor.execute(
                "INSERT INTO scrape_runs (run_id, company, started_at, mode, "
                "jobs_seen, skipped_update) VALUES (%s, 'google', %s, 'incremental', 150, TRUE)",
                (f"g-{i}", f"2020-01-0{i + 1}T00:00:00Z"),
            )
        in_memory_db.commit()

        mock_scraper.scrape_all_queries = AsyncMock(
            return_value=[
                {"id": f"job-{i}", "title": f"Job {i}",
                 "job_url": f"https://example.com/job-{i}"}
                for i in range(150)
            ]
        )
        result = await run_incremental_scrape(
            mock_scraper, in_memory_db, company="apple", detail_scrape=False
        )

        assert result.skipped_update is True, (
            "google's skip streak released apple's guard — the history read "
            "is not filtered by company"
        )


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
