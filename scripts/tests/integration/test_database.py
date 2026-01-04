"""
Integration tests for database operations (shared/database.py)

Tests run against PostgreSQL (requires docker-compose postgres to be running).
"""

import pytest
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.models import JobListing, ScrapeRun
from shared import database as db


class TestInitSchema:
    """Tests for init_schema function"""

    def test_init_schema_creates_tables(self, in_memory_db, test_env):
        """Tables exist after init_schema"""
        cursor = in_memory_db.cursor()

        # Check job_listings table exists (PostgreSQL system catalog)
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        """, (f"job_listings_{test_env}",))
        assert cursor.fetchone() is not None

        # Check scrape_runs table exists
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        """, (f"scrape_runs_{test_env}",))
        assert cursor.fetchone() is not None

    def test_init_schema_creates_indexes(self, in_memory_db, test_env):
        """Indexes created for performance"""
        cursor = in_memory_db.cursor()

        # Get all indexes for the job_listings table
        cursor.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = %s
        """, (f"job_listings_{test_env}",))
        indexes = {row['indexname'] for row in cursor.fetchall()}

        # Should have indexes for status, company, and last_seen_at
        assert f"idx_job_listings_{test_env}_status" in indexes
        assert f"idx_job_listings_{test_env}_company" in indexes
        assert f"idx_job_listings_{test_env}_last_seen" in indexes

    def test_env_table_naming(self, postgres_db):
        """Different env creates different tables"""
        # Create tables with prod env
        db.init_schema(postgres_db, env="prod_test")

        # Create tables with local env
        db.init_schema(postgres_db, env="local_test")

        cursor = postgres_db.cursor()

        # Check prod tables
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'job_listings_prod_test'
        """)
        assert cursor.fetchone() is not None

        # Check local tables
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'job_listings_local_test'
        """)
        assert cursor.fetchone() is not None

        # Cleanup
        cursor.execute("DROP TABLE IF EXISTS job_listings_prod_test CASCADE")
        cursor.execute("DROP TABLE IF EXISTS scrape_runs_prod_test CASCADE")
        cursor.execute("DROP TABLE IF EXISTS job_listings_local_test CASCADE")
        cursor.execute("DROP TABLE IF EXISTS scrape_runs_local_test CASCADE")
        postgres_db.commit()


class TestInsertAndRetrieve:
    """Tests for insert_job and get_job_by_id functions"""

    def test_insert_job_and_retrieve(self, in_memory_db, test_env, sample_job_listing):
        """Insert JobListing, verify with get_job_by_id"""
        db.insert_job(in_memory_db, sample_job_listing, env=test_env)

        retrieved = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)

        assert retrieved is not None
        assert retrieved["id"] == sample_job_listing.id
        assert retrieved["title"] == sample_job_listing.title
        assert retrieved["company"] == sample_job_listing.company
        assert retrieved["status"] == "OPEN"

    def test_insert_job_json_serialization(self, in_memory_db, test_env, sample_job_listing):
        """Details dict serialized to JSON correctly"""
        db.insert_job(in_memory_db, sample_job_listing, env=test_env)

        retrieved = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)

        # Details should be JSONB (already parsed by psycopg2)
        details = retrieved["details"]
        if isinstance(details, str):
            details = json.loads(details)
        assert "minimum_qualifications" in details
        assert details["minimum_qualifications"] == sample_job_listing.details["minimum_qualifications"]

    def test_get_job_by_id_not_found(self, in_memory_db, test_env):
        """Returns None for non-existent job"""
        result = db.get_job_by_id(in_memory_db, "nonexistent-id", env=test_env)
        assert result is None


class TestActiveJobIds:
    """Tests for get_active_job_ids function"""

    def test_get_active_job_ids_returns_open_only(self, in_memory_db, test_env, multiple_job_listings):
        """Only returns OPEN status jobs"""
        # Insert jobs
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job, env=test_env)

        # Mark one as closed
        db.mark_jobs_closed(in_memory_db, ["job-001"], "2024-01-16T10:00:00Z", env=test_env)

        # Get active job IDs
        active_ids = db.get_active_job_ids(in_memory_db, "google", env=test_env)

        # Should only have 2 jobs (job-000 and job-002)
        assert len(active_ids) == 2
        assert "job-001" not in active_ids
        assert "job-000" in active_ids
        assert "job-002" in active_ids

    def test_get_active_job_ids_empty(self, in_memory_db, test_env):
        """Returns empty set when no jobs exist"""
        active_ids = db.get_active_job_ids(in_memory_db, "google", env=test_env)
        assert active_ids == set()


class TestUpdateLastSeen:
    """Tests for update_last_seen function"""

    def test_update_last_seen_resets_misses(self, in_memory_db, test_env, sample_job_listing):
        """Updates timestamp and resets consecutive_misses"""
        # Insert job with some misses
        sample_job_listing.consecutive_misses = 1
        db.insert_job(in_memory_db, sample_job_listing, env=test_env)

        # Increment misses to simulate missed runs
        db.increment_consecutive_misses(in_memory_db, [sample_job_listing.id], env=test_env)

        # Verify misses incremented
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job["consecutive_misses"] == 2

        # Update last seen
        new_timestamp = "2024-01-20T10:00:00Z"
        db.update_last_seen(in_memory_db, [sample_job_listing.id], new_timestamp, env=test_env)

        # Verify misses reset and timestamp updated
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job["consecutive_misses"] == 0
        assert job["last_seen_at"] == new_timestamp

    def test_update_last_seen_empty_list(self, in_memory_db, test_env):
        """Handles empty job list gracefully"""
        # Should not raise
        db.update_last_seen(in_memory_db, [], "2024-01-20T10:00:00Z", env=test_env)


class TestIncrementMisses:
    """Tests for increment_consecutive_misses function"""

    def test_increment_consecutive_misses(self, in_memory_db, test_env, sample_job_listing):
        """Increments counter correctly"""
        db.insert_job(in_memory_db, sample_job_listing, env=test_env)

        # Increment misses
        db.increment_consecutive_misses(in_memory_db, [sample_job_listing.id], env=test_env)

        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job["consecutive_misses"] == 1

        # Increment again
        db.increment_consecutive_misses(in_memory_db, [sample_job_listing.id], env=test_env)

        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job["consecutive_misses"] == 2


class TestMarkJobsClosed:
    """Tests for mark_jobs_closed function"""

    def test_mark_jobs_closed(self, in_memory_db, test_env, sample_job_listing):
        """Sets status=CLOSED and closed_on timestamp"""
        db.insert_job(in_memory_db, sample_job_listing, env=test_env)

        close_timestamp = "2024-01-20T15:00:00Z"
        db.mark_jobs_closed(in_memory_db, [sample_job_listing.id], close_timestamp, env=test_env)

        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job["status"] == "CLOSED"
        assert job["closed_on"] == close_timestamp

    def test_mark_jobs_closed_multiple(self, in_memory_db, test_env, multiple_job_listings):
        """Can close multiple jobs at once"""
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job, env=test_env)

        ids_to_close = ["job-000", "job-001"]
        db.mark_jobs_closed(in_memory_db, ids_to_close, "2024-01-20T15:00:00Z", env=test_env)

        for job_id in ids_to_close:
            job = db.get_job_by_id(in_memory_db, job_id, env=test_env)
            assert job["status"] == "CLOSED"

        # job-002 should still be open
        job = db.get_job_by_id(in_memory_db, "job-002", env=test_env)
        assert job["status"] == "OPEN"


class TestReactivateJob:
    """Tests for reactivate_job function"""

    def test_reactivate_job(self, in_memory_db, test_env, sample_job_listing):
        """Sets status=OPEN, clears closed_on, resets misses"""
        db.insert_job(in_memory_db, sample_job_listing, env=test_env)

        # Close the job
        db.mark_jobs_closed(in_memory_db, [sample_job_listing.id], "2024-01-20T15:00:00Z", env=test_env)

        # Verify closed
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job["status"] == "CLOSED"

        # Reactivate
        reactivate_timestamp = "2024-01-21T10:00:00Z"
        db.reactivate_job(in_memory_db, sample_job_listing.id, reactivate_timestamp, env=test_env)

        # Verify reactivated
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job["status"] == "OPEN"
        assert job["closed_on"] is None
        assert job["consecutive_misses"] == 0
        assert job["last_seen_at"] == reactivate_timestamp


class TestScrapeRun:
    """Tests for record_scrape_run function"""

    def test_record_scrape_run(self, in_memory_db, test_env, sample_scrape_run):
        """Inserts ScrapeRun metadata"""
        db.record_scrape_run(in_memory_db, sample_scrape_run, env=test_env)

        # Verify by direct query
        cursor = in_memory_db.cursor()
        cursor.execute(
            f"SELECT * FROM scrape_runs_{test_env} WHERE run_id = %s",
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

    def test_upsert_job_inserts_new(self, in_memory_db, test_env, sample_job_listing):
        """New job gets inserted"""
        result = db.upsert_job(in_memory_db, sample_job_listing, env=test_env)

        assert result is True  # Was inserted (new)

        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job is not None
        assert job["title"] == sample_job_listing.title
        assert job["status"] == "OPEN"

    def test_upsert_job_reactivates_closed(self, in_memory_db, test_env, sample_job_listing):
        """Closed job gets reactivated when it reappears"""
        # Insert and close the job
        db.insert_job(in_memory_db, sample_job_listing, env=test_env)
        db.mark_jobs_closed(in_memory_db, [sample_job_listing.id], "2024-01-16T10:00:00Z", env=test_env)

        # Verify it's closed
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
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

        result = db.upsert_job(in_memory_db, updated_job, env=test_env)

        assert result is False  # Was updated (not inserted)

        # Verify it's reactivated with updated fields
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job["status"] == "OPEN"
        assert job["closed_on"] is None
        assert job["consecutive_misses"] == 0
        assert job["title"] == "Updated Title"
        assert job["location"] == "New Location"
        # Original timestamps should be preserved
        assert job["first_seen_at"] == sample_job_listing.first_seen_at
        assert job["created_at"] == sample_job_listing.created_at

    def test_upsert_job_updates_existing_open(self, in_memory_db, test_env, sample_job_listing):
        """Existing open job gets updated (should not happen in practice, but handles edge case)"""
        db.insert_job(in_memory_db, sample_job_listing, env=test_env)

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

        result = db.upsert_job(in_memory_db, updated_job, env=test_env)

        assert result is False  # Was updated
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job["title"] == "Updated Title"


class TestGetAllActiveJobs:
    """Tests for get_all_active_jobs function"""

    def test_get_all_active_jobs(self, in_memory_db, test_env, multiple_job_listings):
        """Returns list of JobListing objects"""
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job, env=test_env)

        # Mark one as closed
        db.mark_jobs_closed(in_memory_db, ["job-001"], "2024-01-16T10:00:00Z", env=test_env)

        # Get all active jobs
        active_jobs = db.get_all_active_jobs(in_memory_db, "google", env=test_env)

        # Should return JobListing objects
        assert len(active_jobs) == 2
        assert all(isinstance(j, JobListing) for j in active_jobs)

        # Should only have open jobs
        job_ids = {j.id for j in active_jobs}
        assert "job-000" in job_ids
        assert "job-002" in job_ids
        assert "job-001" not in job_ids

    def test_get_all_active_jobs_empty(self, in_memory_db, test_env):
        """Returns empty list when no active jobs"""
        active_jobs = db.get_all_active_jobs(in_memory_db, "google", env=test_env)
        assert active_jobs == []

    def test_get_all_active_jobs_filters_by_company(self, in_memory_db, test_env, sample_job_listing):
        """Only returns jobs for specified company"""
        # Insert Google job
        db.insert_job(in_memory_db, sample_job_listing, env=test_env)

        # Insert Apple job
        apple_job = JobListing(
            id="apple-001",
            title="iOS Developer",
            company="apple",
            url="https://apple.com/job",
            source_id="apple_scraper",
            created_at="2024-01-15T10:30:00Z",
            first_seen_at="2024-01-15T10:30:00Z",
            last_seen_at="2024-01-15T10:30:00Z"
        )
        db.insert_job(in_memory_db, apple_job, env=test_env)

        # Get Google jobs only
        google_jobs = db.get_all_active_jobs(in_memory_db, "google", env=test_env)
        assert len(google_jobs) == 1
        assert google_jobs[0].company == "google"

        # Get Apple jobs only
        apple_jobs = db.get_all_active_jobs(in_memory_db, "apple", env=test_env)
        assert len(apple_jobs) == 1
        assert apple_jobs[0].company == "apple"


class TestUpsertJobNoCommit:
    """Tests for upsert_job_no_commit function (batch support)"""

    def test_upsert_job_no_commit_does_not_commit(self, in_memory_db, test_env, sample_job_listing):
        """Job is visible within transaction but not after rollback"""
        db.upsert_job_no_commit(in_memory_db, sample_job_listing, env=test_env)

        # Job should be visible in same transaction
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job is not None

        # Rollback should remove the job
        in_memory_db.rollback()
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job is None

    def test_upsert_job_no_commit_then_commit(self, in_memory_db, test_env, sample_job_listing):
        """Job persists after explicit commit"""
        db.upsert_job_no_commit(in_memory_db, sample_job_listing, env=test_env)
        in_memory_db.commit()

        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env=test_env)
        assert job is not None
        assert job["id"] == sample_job_listing.id

    def test_upsert_job_no_commit_returns_insert_status(self, in_memory_db, test_env, sample_job_listing):
        """Returns True for insert, False for update"""
        # First call = insert
        result = db.upsert_job_no_commit(in_memory_db, sample_job_listing, env=test_env)
        assert result is True
        in_memory_db.commit()

        # Second call = update
        result = db.upsert_job_no_commit(in_memory_db, sample_job_listing, env=test_env)
        assert result is False
        in_memory_db.commit()

    def test_multiple_jobs_single_commit(self, in_memory_db, test_env, multiple_job_listings):
        """Multiple jobs can be inserted with single commit"""
        for job in multiple_job_listings:
            db.upsert_job_no_commit(in_memory_db, job, env=test_env)

        in_memory_db.commit()

        # All jobs should be in database
        active_ids = db.get_active_job_ids(in_memory_db, "google", env=test_env)
        assert len(active_ids) == 3

    def test_partial_batch_rollback(self, in_memory_db, test_env, multiple_job_listings):
        """Rollback removes all uncommitted jobs"""
        # Insert 2 jobs without commit
        db.upsert_job_no_commit(in_memory_db, multiple_job_listings[0], env=test_env)
        db.upsert_job_no_commit(in_memory_db, multiple_job_listings[1], env=test_env)

        # Rollback
        in_memory_db.rollback()

        # No jobs should exist
        active_ids = db.get_active_job_ids(in_memory_db, "google", env=test_env)
        assert len(active_ids) == 0
