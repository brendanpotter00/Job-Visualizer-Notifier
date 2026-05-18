"""
Integration tests for database operations (shared/database.py)

Tests run against PostgreSQL (requires docker-compose postgres to be running).
"""

import pytest
import json
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.constants import SourceId
from shared.models import JobListing, ScrapeRun
from shared import database as db


def _parse_ts(value):
    """Normalize a timestamptz column value (datetime or ISO str) for comparison."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestInsertAndRetrieve:
    """Tests for insert_job and get_job_by_id functions"""

    def test_insert_job_and_retrieve(self, in_memory_db, sample_job_listing):
        """Insert JobListing, verify with get_job_by_id"""
        db.insert_job(in_memory_db, sample_job_listing)

        retrieved = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)

        assert retrieved is not None
        assert retrieved["id"] == sample_job_listing.id
        assert retrieved["title"] == sample_job_listing.title
        assert retrieved["company"] == sample_job_listing.company
        assert retrieved["status"] == "OPEN"

    def test_insert_job_json_serialization(self, in_memory_db, sample_job_listing):
        """Details dict serialized to JSON correctly"""
        db.insert_job(in_memory_db, sample_job_listing)

        retrieved = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)

        # Details should be JSONB (already parsed by psycopg2)
        details = retrieved["details"]
        if isinstance(details, str):
            details = json.loads(details)
        assert "minimum_qualifications" in details
        assert details["minimum_qualifications"] == sample_job_listing.details["minimum_qualifications"]

    def test_get_job_by_id_not_found(self, in_memory_db):
        """Returns None for non-existent job"""
        result = db.get_job_by_id(in_memory_db, SourceId.GOOGLE, "nonexistent-id")
        assert result is None


class TestActiveJobIds:
    """Tests for get_active_job_ids function"""

    def test_get_active_job_ids_returns_open_only(self, in_memory_db, multiple_job_listings):
        """Only returns OPEN status jobs"""
        # Insert jobs
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job)

        # Mark one as closed
        db.mark_jobs_closed(in_memory_db, SourceId.GOOGLE, ["job-001"], "2024-01-16T10:00:00Z")

        # Get active job IDs
        active_ids = db.get_active_job_ids(in_memory_db, SourceId.GOOGLE, "google")

        # Should only have 2 jobs (job-000 and job-002)
        assert len(active_ids) == 2
        assert "job-001" not in active_ids
        assert "job-000" in active_ids
        assert "job-002" in active_ids

    def test_get_active_job_ids_empty(self, in_memory_db):
        """Returns empty set when no jobs exist"""
        active_ids = db.get_active_job_ids(in_memory_db, SourceId.GOOGLE, "google")
        assert active_ids == set()


class TestUpdateLastSeen:
    """Tests for update_last_seen function"""

    def test_update_last_seen_resets_misses(self, in_memory_db, sample_job_listing):
        """Updates timestamp and resets consecutive_misses"""
        # Insert job with some misses
        sample_job_listing.consecutive_misses = 1
        db.insert_job(in_memory_db, sample_job_listing)

        # Increment misses to simulate missed runs
        db.increment_consecutive_misses(in_memory_db, sample_job_listing.source_id, [sample_job_listing.id])

        # Verify misses incremented
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["consecutive_misses"] == 2

        # Update last seen
        new_timestamp = "2024-01-20T10:00:00Z"
        db.update_last_seen(in_memory_db, sample_job_listing.source_id, [sample_job_listing.id], new_timestamp)

        # Verify misses reset and timestamp updated
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["consecutive_misses"] == 0
        assert _parse_ts(job["last_seen_at"]) == _parse_ts(new_timestamp)

    def test_update_last_seen_empty_list(self, in_memory_db):
        """Handles empty job list gracefully"""
        # Should not raise
        db.update_last_seen(in_memory_db, SourceId.GOOGLE, [], "2024-01-20T10:00:00Z")


class TestIncrementMisses:
    """Tests for increment_consecutive_misses function"""

    def test_increment_consecutive_misses(self, in_memory_db, sample_job_listing):
        """Increments counter correctly"""
        db.insert_job(in_memory_db, sample_job_listing)

        # Increment misses
        db.increment_consecutive_misses(in_memory_db, sample_job_listing.source_id, [sample_job_listing.id])

        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["consecutive_misses"] == 1

        # Increment again
        db.increment_consecutive_misses(in_memory_db, sample_job_listing.source_id, [sample_job_listing.id])

        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["consecutive_misses"] == 2


class TestMarkJobsClosed:
    """Tests for mark_jobs_closed function"""

    def test_mark_jobs_closed(self, in_memory_db, sample_job_listing):
        """Sets status=CLOSED and closed_on timestamp"""
        db.insert_job(in_memory_db, sample_job_listing)

        close_timestamp = "2024-01-20T15:00:00Z"
        db.mark_jobs_closed(in_memory_db, sample_job_listing.source_id, [sample_job_listing.id], close_timestamp)

        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["status"] == "CLOSED"
        assert _parse_ts(job["closed_on"]) == _parse_ts(close_timestamp)

    def test_mark_jobs_closed_multiple(self, in_memory_db, multiple_job_listings):
        """Can close multiple jobs at once"""
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job)

        ids_to_close = ["job-000", "job-001"]
        db.mark_jobs_closed(in_memory_db, SourceId.GOOGLE, ids_to_close, "2024-01-20T15:00:00Z")

        for job_id in ids_to_close:
            job = db.get_job_by_id(in_memory_db, SourceId.GOOGLE, job_id)
            assert job["status"] == "CLOSED"

        # job-002 should still be open
        job = db.get_job_by_id(in_memory_db, SourceId.GOOGLE, "job-002")
        assert job["status"] == "OPEN"


class TestReactivateJob:
    """Tests for reactivate_job function"""

    def test_reactivate_job(self, in_memory_db, sample_job_listing):
        """Sets status=OPEN, clears closed_on, resets misses"""
        db.insert_job(in_memory_db, sample_job_listing)

        # Close the job
        db.mark_jobs_closed(in_memory_db, sample_job_listing.source_id, [sample_job_listing.id], "2024-01-20T15:00:00Z")

        # Verify closed
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["status"] == "CLOSED"

        # Reactivate
        reactivate_timestamp = "2024-01-21T10:00:00Z"
        db.reactivate_job(in_memory_db, sample_job_listing.source_id, sample_job_listing.id, reactivate_timestamp)

        # Verify reactivated
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["status"] == "OPEN"
        assert job["closed_on"] is None
        assert job["consecutive_misses"] == 0
        assert _parse_ts(job["last_seen_at"]) == _parse_ts(reactivate_timestamp)


class TestScrapeRun:
    """Tests for record_scrape_run function"""

    def test_record_scrape_run(self, in_memory_db, sample_scrape_run):
        """Inserts ScrapeRun metadata"""
        db.record_scrape_run(in_memory_db, sample_scrape_run)

        # Verify by direct query
        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT * FROM scrape_runs WHERE run_id = %s",
            (sample_scrape_run.run_id,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert dict(row)["company"] == "google"
        assert dict(row)["mode"] == "incremental"
        assert dict(row)["jobs_seen"] == 100
        assert dict(row)["new_jobs"] == 10


class TestUpsertJob:
    """Tests for upsert_job function (handles reappearing closed jobs)"""

    def test_upsert_job_inserts_new(self, in_memory_db, sample_job_listing):
        """New job gets inserted"""
        result = db.upsert_job(in_memory_db, sample_job_listing)

        assert result is True  # Was inserted (new)

        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job is not None
        assert job["title"] == sample_job_listing.title
        assert job["status"] == "OPEN"

    def test_upsert_job_reactivates_closed(self, in_memory_db, sample_job_listing):
        """Closed job gets reactivated when it reappears"""
        # Insert and close the job
        db.insert_job(in_memory_db, sample_job_listing)
        db.mark_jobs_closed(in_memory_db, sample_job_listing.source_id, [sample_job_listing.id], "2024-01-16T10:00:00Z")

        # Verify it's closed
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["status"] == "CLOSED"
        assert job["closed_on"] is not None

        # Now upsert with updated data (simulating job reappearing in scrape)
        updated_job = JobListing(
            id=sample_job_listing.id,
            title="Updated Title",  # Title might have changed
            company=sample_job_listing.company,
            location="New Location",  # Location might have changed
            url=sample_job_listing.url,
            source_id=sample_job_listing.source_id,
            details={"new": "details"},
            created_at="2024-01-17T10:00:00Z",
            first_seen_at="2024-01-17T10:00:00Z",
            last_seen_at="2024-01-17T10:00:00Z"
        )

        result = db.upsert_job(in_memory_db, updated_job)

        assert result is False  # Was updated (not inserted)

        # Verify it's reactivated with updated fields
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["status"] == "OPEN"
        assert job["closed_on"] is None
        assert job["consecutive_misses"] == 0
        assert job["title"] == "Updated Title"
        assert job["location"] == "New Location"
        # Original timestamps should be preserved
        assert _parse_ts(job["first_seen_at"]) == _parse_ts(sample_job_listing.first_seen_at)
        assert _parse_ts(job["created_at"]) == _parse_ts(sample_job_listing.created_at)

    def test_upsert_job_updates_existing_open(self, in_memory_db, sample_job_listing):
        """Existing open job gets updated (should not happen in practice, but handles edge case)"""
        db.insert_job(in_memory_db, sample_job_listing)

        # Upsert again with same ID
        updated_job = JobListing(
            id=sample_job_listing.id,
            title="Updated Title",
            company=sample_job_listing.company,
            url=sample_job_listing.url,
            source_id=sample_job_listing.source_id,
            created_at="2024-01-17T10:00:00Z",
            first_seen_at="2024-01-17T10:00:00Z",
            last_seen_at="2024-01-17T10:00:00Z"
        )

        result = db.upsert_job(in_memory_db, updated_job)

        assert result is False  # Was updated
        job = db.get_job_by_id(in_memory_db, sample_job_listing.source_id, sample_job_listing.id)
        assert job["title"] == "Updated Title"


class TestGetAllActiveJobs:
    """Tests for get_all_active_jobs function"""

    def test_get_all_active_jobs(self, in_memory_db, multiple_job_listings):
        """Returns list of JobListing objects"""
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job)

        # Mark one as closed
        db.mark_jobs_closed(in_memory_db, SourceId.GOOGLE, ["job-001"], "2024-01-16T10:00:00Z")

        # Get all active jobs
        active_jobs = db.get_all_active_jobs(in_memory_db, "google")

        # Should return JobListing objects
        assert len(active_jobs) == 2
        assert all(isinstance(j, JobListing) for j in active_jobs)

        # Should only have open jobs
        job_ids = {j.id for j in active_jobs}
        assert "job-000" in job_ids
        assert "job-002" in job_ids
        assert "job-001" not in job_ids

    def test_get_all_active_jobs_empty(self, in_memory_db):
        """Returns empty list when no active jobs"""
        active_jobs = db.get_all_active_jobs(in_memory_db, "google")
        assert active_jobs == []

    def test_get_all_active_jobs_filters_by_company(self, in_memory_db, sample_job_listing):
        """Only returns jobs for specified company"""
        # Insert Google job
        db.insert_job(in_memory_db, sample_job_listing)

        # Insert Apple job
        apple_job = JobListing(
            id="apple-001",
            title="iOS Developer",
            company="apple",
            url="https://apple.com/job",
            source_id=SourceId.APPLE,
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z"
        )
        db.insert_job(in_memory_db, apple_job)

        # Get Google jobs only
        google_jobs = db.get_all_active_jobs(in_memory_db, "google")
        assert len(google_jobs) == 1
        assert google_jobs[0].company == "google"

        # Get Apple jobs only
        apple_jobs = db.get_all_active_jobs(in_memory_db, "apple")
        assert len(apple_jobs) == 1
        assert apple_jobs[0].company == "apple"


class TestTimestamptzColumns:
    """End-to-end: scraper-side ISO 8601 strings must round-trip through
    timestamptz columns after migrations 0003 and 0004.

    The existing test_inserting_iso_string_works (test_migrations.py) proves
    psycopg2's implicit cast. This test proves the full upsert_job() path
    (Pydantic JobListing -> shared.database -> timestamptz column) works
    without changing the scraper-side str types.
    """

    def test_upsert_job_writes_iso_strings_to_timestamptz(
        self, in_memory_db, sample_job_listing
    ):
        from datetime import datetime

        db.upsert_job(in_memory_db, sample_job_listing)

        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT created_at, first_seen_at, last_seen_at, "
            "pg_typeof(created_at) AS created_type "
            "FROM job_listings WHERE id = %s",
            (sample_job_listing.id,),
        )
        row = cursor.fetchone()
        assert row is not None

        # psycopg2 returns tz-aware datetimes from timestamptz columns.
        for col in ("created_at", "first_seen_at", "last_seen_at"):
            value = row[col]
            assert isinstance(value, datetime), f"{col} should be datetime, got {type(value)}"
            assert value.tzinfo is not None, f"{col} should be tz-aware"

        assert row["created_type"] == "timestamp with time zone"

    def test_get_all_active_jobs_returns_iso_string_timestamps(
        self, in_memory_db, sample_job_listing
    ):
        """get_all_active_jobs normalizes tz-aware datetimes from psycopg2
        back into ISO 8601 strings so the shared JobListing model (which
        types these fields as str) keeps validating. Without this test a
        refactor could regress the endpoint to emit datetime-repr strings
        that would still type-check as str but fail frontend parsing.
        """
        from datetime import datetime

        db.upsert_job(in_memory_db, sample_job_listing)

        jobs = db.get_all_active_jobs(in_memory_db, sample_job_listing.company)
        assert len(jobs) == 1
        job = jobs[0]

        for field in ("created_at", "first_seen_at", "last_seen_at"):
            value = getattr(job, field)
            assert isinstance(value, str), f"{field} must be str, got {type(value)}"
            parsed = datetime.fromisoformat(value)
            assert parsed.tzinfo is not None, f"{field} should round-trip as tz-aware"


class TestSourceScopedHelpersCrossSource:
    """Cross-source coverage for the source-scoped helpers in database.py.

    Each test seeds two jobs that share an `id` but differ in `source_id`,
    then runs a source-A operation and asserts source-B's row is untouched.
    A regression that drops `source_id = %s` from any of these helpers
    would clobber source B and these tests would fail.
    """

    SHARED_ID = "shared-id-7"

    def _seed_pair(self, conn):
        """Insert two jobs that share `id` but differ in `source_id`."""
        job_a = JobListing(
            id=self.SHARED_ID,
            title="Source A Role",
            company="acme",
            url="https://a.example/job",
            source_id="source_a",
            created_at="2024-01-15T10:00:00Z",
            first_seen_at="2024-01-15T10:00:00Z",
            last_seen_at="2024-01-15T10:00:00Z",
            consecutive_misses=0,
        )
        job_b = JobListing(
            id=self.SHARED_ID,
            title="Source B Role",
            company="acme",
            url="https://b.example/job",
            source_id="source_b",
            created_at="2024-01-15T10:00:00Z",
            first_seen_at="2024-01-15T10:00:00Z",
            last_seen_at="2024-01-15T10:00:00Z",
            consecutive_misses=0,
        )
        db.insert_job(conn, job_a)
        db.insert_job(conn, job_b)

    def test_update_last_seen_does_not_touch_other_source(self, in_memory_db):
        self._seed_pair(in_memory_db)
        new_ts = "2024-02-01T10:00:00Z"
        db.update_last_seen(in_memory_db, "source_a", [self.SHARED_ID], new_ts)

        a = db.get_job_by_id(in_memory_db, "source_a", self.SHARED_ID)
        b = db.get_job_by_id(in_memory_db, "source_b", self.SHARED_ID)
        assert _parse_ts(a["last_seen_at"]) == _parse_ts(new_ts)
        # Source B unchanged.
        assert _parse_ts(b["last_seen_at"]) == _parse_ts("2024-01-15T10:00:00Z")

    def test_increment_consecutive_misses_does_not_touch_other_source(
        self, in_memory_db
    ):
        self._seed_pair(in_memory_db)
        db.increment_consecutive_misses(
            in_memory_db, "source_a", [self.SHARED_ID]
        )
        a = db.get_job_by_id(in_memory_db, "source_a", self.SHARED_ID)
        b = db.get_job_by_id(in_memory_db, "source_b", self.SHARED_ID)
        assert a["consecutive_misses"] == 1
        assert b["consecutive_misses"] == 0

    def test_mark_jobs_closed_does_not_touch_other_source(self, in_memory_db):
        self._seed_pair(in_memory_db)
        db.mark_jobs_closed(
            in_memory_db, "source_a", [self.SHARED_ID],
            "2024-02-01T10:00:00Z",
        )
        a = db.get_job_by_id(in_memory_db, "source_a", self.SHARED_ID)
        b = db.get_job_by_id(in_memory_db, "source_b", self.SHARED_ID)
        assert a["status"] == "CLOSED"
        assert b["status"] == "OPEN"
        assert b["closed_on"] is None

    def test_get_jobs_exceeding_miss_threshold_scopes_to_source(
        self, in_memory_db
    ):
        self._seed_pair(in_memory_db)
        # Push only source_b's misses above the threshold.
        db.increment_consecutive_misses(
            in_memory_db, "source_b", [self.SHARED_ID]
        )
        db.increment_consecutive_misses(
            in_memory_db, "source_b", [self.SHARED_ID]
        )

        # Querying source_a with threshold 1 should NOT see source_b's row.
        exceeded_a = db.get_jobs_exceeding_miss_threshold(
            in_memory_db, "source_a", [self.SHARED_ID], 1
        )
        assert exceeded_a == set()

        # Querying source_b finds it.
        exceeded_b = db.get_jobs_exceeding_miss_threshold(
            in_memory_db, "source_b", [self.SHARED_ID], 1
        )
        assert exceeded_b == {self.SHARED_ID}

    def test_reactivate_job_does_not_touch_other_source(self, in_memory_db):
        self._seed_pair(in_memory_db)
        # Close BOTH rows so we can prove reactivate only reopens source_a.
        db.mark_jobs_closed(
            in_memory_db, "source_a", [self.SHARED_ID],
            "2024-02-01T10:00:00Z",
        )
        db.mark_jobs_closed(
            in_memory_db, "source_b", [self.SHARED_ID],
            "2024-02-01T10:00:00Z",
        )

        db.reactivate_job(
            in_memory_db, "source_a", self.SHARED_ID,
            "2024-02-02T10:00:00Z",
        )

        a = db.get_job_by_id(in_memory_db, "source_a", self.SHARED_ID)
        b = db.get_job_by_id(in_memory_db, "source_b", self.SHARED_ID)
        assert a["status"] == "OPEN"
        assert a["closed_on"] is None
        assert b["status"] == "CLOSED"
        assert b["closed_on"] is not None

    def test_upsert_job_does_not_touch_other_source(self, in_memory_db):
        """ON CONFLICT (source_id, id) — upserting source_a must NOT
        overwrite source_b's row even though they share `id`."""
        self._seed_pair(in_memory_db)
        updated_a = JobListing(
            id=self.SHARED_ID,
            title="Source A Updated Title",
            company="acme",
            url="https://a.example/job",
            source_id="source_a",
            created_at="2024-01-15T10:00:00Z",
            first_seen_at="2024-01-15T10:00:00Z",
            last_seen_at="2024-03-01T10:00:00Z",
        )
        db.upsert_job(in_memory_db, updated_a)

        a = db.get_job_by_id(in_memory_db, "source_a", self.SHARED_ID)
        b = db.get_job_by_id(in_memory_db, "source_b", self.SHARED_ID)
        assert a["title"] == "Source A Updated Title"
        # Source B's title untouched.
        assert b["title"] == "Source B Role"

    def test_insert_jobs_batch_does_not_touch_other_source(self, in_memory_db):
        """ON CONFLICT (source_id, id) DO NOTHING — re-inserting source_a's
        row is a no-op, but inserting source_a with a new `id` succeeds
        independently of source_b's id space."""
        self._seed_pair(in_memory_db)

        # Re-insert source_a with the shared id (should be a no-op skip)
        # and a brand-new source_a id (should land). Source B untouched.
        new_a_id = "new-source-a-only"
        batch = [
            JobListing(
                id=self.SHARED_ID,  # collides with existing (source_a, shared)
                title="Should NOT overwrite source_a's existing row",
                company="acme",
                url="https://a.example/job-collide",
                source_id="source_a",
                created_at="2024-01-15T10:00:00Z",
                first_seen_at="2024-01-15T10:00:00Z",
                last_seen_at="2024-01-15T10:00:00Z",
            ),
            JobListing(
                id=new_a_id,
                title="Brand new source_a row",
                company="acme",
                url="https://a.example/new",
                source_id="source_a",
                created_at="2024-01-15T10:00:00Z",
                first_seen_at="2024-01-15T10:00:00Z",
                last_seen_at="2024-01-15T10:00:00Z",
            ),
        ]
        inserted = db.insert_jobs_batch(in_memory_db, batch)
        assert inserted == 1, (
            f"expected 1 actual insert (1 skip + 1 new), got {inserted}"
        )

        a_shared = db.get_job_by_id(in_memory_db, "source_a", self.SHARED_ID)
        a_new = db.get_job_by_id(in_memory_db, "source_a", new_a_id)
        b_shared = db.get_job_by_id(in_memory_db, "source_b", self.SHARED_ID)
        b_new = db.get_job_by_id(in_memory_db, "source_b", new_a_id)
        assert a_shared["title"] == "Source A Role"  # not clobbered
        assert a_new is not None
        assert b_shared["title"] == "Source B Role"  # untouched
        assert b_new is None  # source_b never had this id


class TestActiveJobIdsCrossSource:
    """Cross-source coverage for get_active_job_ids / count_active_jobs.

    Two sources can share a `company` post composite-PK. Without source_id
    scoping, a multi-source-per-company setup would silently miscount and
    miss-route the consecutive-misses lifecycle.
    """

    def test_get_active_job_ids_scopes_to_source(self, in_memory_db):
        # Same `company`, different `source_id`. Each source contributes
        # its own id space to the company.
        for i, sid in enumerate(("source_a", "source_b")):
            job = JobListing(
                id=f"only-in-{sid}",
                title=f"{sid} role",
                company="acme",
                url=f"https://{sid}.example/job",
                source_id=sid,
                created_at="2024-01-15T10:00:00Z",
                first_seen_at="2024-01-15T10:00:00Z",
                last_seen_at="2024-01-15T10:00:00Z",
            )
            db.insert_job(in_memory_db, job)

        a_ids = db.get_active_job_ids(in_memory_db, "source_a", "acme")
        b_ids = db.get_active_job_ids(in_memory_db, "source_b", "acme")
        assert a_ids == {"only-in-source_a"}
        assert b_ids == {"only-in-source_b"}

    def test_count_active_jobs_scopes_to_source(self, in_memory_db):
        for i in range(3):
            db.insert_job(
                in_memory_db,
                JobListing(
                    id=f"a-{i}",
                    title="t",
                    company="acme",
                    url="https://a.example/job",
                    source_id="source_a",
                    created_at="2024-01-15T10:00:00Z",
                    first_seen_at="2024-01-15T10:00:00Z",
                    last_seen_at="2024-01-15T10:00:00Z",
                ),
            )
        db.insert_job(
            in_memory_db,
            JobListing(
                id="b-0",
                title="t",
                company="acme",
                url="https://b.example/job",
                source_id="source_b",
                created_at="2024-01-15T10:00:00Z",
                first_seen_at="2024-01-15T10:00:00Z",
                last_seen_at="2024-01-15T10:00:00Z",
            ),
        )

        assert db.count_active_jobs(in_memory_db, "source_a", "acme") == 3
        assert db.count_active_jobs(in_memory_db, "source_b", "acme") == 1


class TestSourceScopedHelpersRejectEmptySource:
    """Lock the empty-source_id ValueError contract added in pass 2.

    Three representative shapes — SELECT, bulk-UPDATE, single-row. Future
    refactors that catch ValueError upstream or weaken `if not source_id`
    to `is None` would re-open the silent `WHERE source_id = ''` no-op
    surface that pass-1's divergence WARN was only a backstop for.
    """

    def test_get_active_job_ids_rejects_empty_source_id(self, in_memory_db):
        # SELECT-shape guard.
        with pytest.raises(ValueError, match="source_id"):
            db.get_active_job_ids(in_memory_db, "", "google")

    def test_update_last_seen_rejects_empty_source_id(self, in_memory_db):
        # Bulk-UPDATE-shape guard.
        with pytest.raises(ValueError, match="source_id"):
            db.update_last_seen(
                in_memory_db, "", ["job-001"], "2024-01-15T10:00:00Z"
            )

    def test_get_job_by_id_rejects_empty_source_id(self, in_memory_db):
        # Single-row-shape guard.
        with pytest.raises(ValueError, match="source_id"):
            db.get_job_by_id(in_memory_db, "", "job-001")
