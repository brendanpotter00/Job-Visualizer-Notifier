"""
Integration tests for database operations (shared/database.py)

Tests run against SQLite in-memory database.
"""

import pytest
import sqlite3
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.models import JobListing, ScrapeRun
from shared import database as db


class TestInitSchema:
    """Tests for init_schema function"""

    def test_init_schema_creates_tables(self, in_memory_db):
        """Tables exist after init_schema"""
        cursor = in_memory_db.cursor()

        # Check job_listings table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='job_listings_test'
        """)
        assert cursor.fetchone() is not None

        # Check scrape_runs table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='scrape_runs_test'
        """)
        assert cursor.fetchone() is not None

    def test_init_schema_creates_indexes(self, in_memory_db):
        """Indexes created for performance"""
        cursor = in_memory_db.cursor()

        # Get all indexes
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND tbl_name='job_listings_test'
        """)
        indexes = {row[0] for row in cursor.fetchall()}

        # Should have indexes for status, company, and last_seen_at
        assert "idx_job_listings_test_status" in indexes
        assert "idx_job_listings_test_company" in indexes
        assert "idx_job_listings_test_last_seen" in indexes

    def test_env_table_naming(self):
        """Different env creates different tables"""
        conn1 = sqlite3.connect(":memory:")
        conn1.row_factory = sqlite3.Row
        db.init_schema(conn1, env="prod")

        conn2 = sqlite3.connect(":memory:")
        conn2.row_factory = sqlite3.Row
        db.init_schema(conn2, env="local")

        # Check prod tables
        cursor1 = conn1.cursor()
        cursor1.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='job_listings_prod'
        """)
        assert cursor1.fetchone() is not None

        # Check local tables
        cursor2 = conn2.cursor()
        cursor2.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='job_listings_local'
        """)
        assert cursor2.fetchone() is not None

        conn1.close()
        conn2.close()


class TestInsertAndRetrieve:
    """Tests for insert_job and get_job_by_id functions"""

    def test_insert_job_and_retrieve(self, in_memory_db, sample_job_listing):
        """Insert JobListing, verify with get_job_by_id"""
        db.insert_job(in_memory_db, sample_job_listing, env="test")

        retrieved = db.get_job_by_id(in_memory_db, sample_job_listing.id, env="test")

        assert retrieved is not None
        assert retrieved["id"] == sample_job_listing.id
        assert retrieved["title"] == sample_job_listing.title
        assert retrieved["company"] == sample_job_listing.company
        assert retrieved["status"] == "OPEN"

    def test_insert_job_json_serialization(self, in_memory_db, sample_job_listing):
        """Details dict serialized to JSON correctly"""
        db.insert_job(in_memory_db, sample_job_listing, env="test")

        retrieved = db.get_job_by_id(in_memory_db, sample_job_listing.id, env="test")

        # Details should be stored as JSON string
        details = json.loads(retrieved["details"]) if isinstance(retrieved["details"], str) else retrieved["details"]
        assert "minimum_qualifications" in details
        assert details["minimum_qualifications"] == sample_job_listing.details["minimum_qualifications"]

    def test_get_job_by_id_not_found(self, in_memory_db):
        """Returns None for non-existent job"""
        result = db.get_job_by_id(in_memory_db, "nonexistent-id", env="test")
        assert result is None


class TestActiveJobIds:
    """Tests for get_active_job_ids function"""

    def test_get_active_job_ids_returns_open_only(self, in_memory_db, multiple_job_listings):
        """Only returns OPEN status jobs"""
        # Insert jobs
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job, env="test")

        # Mark one as closed
        db.mark_jobs_closed(in_memory_db, ["job-001"], "2024-01-16T10:00:00Z", env="test")

        # Get active job IDs
        active_ids = db.get_active_job_ids(in_memory_db, "google", env="test")

        # Should only have 2 jobs (job-000 and job-002)
        assert len(active_ids) == 2
        assert "job-001" not in active_ids
        assert "job-000" in active_ids
        assert "job-002" in active_ids

    def test_get_active_job_ids_empty(self, in_memory_db):
        """Returns empty set when no jobs exist"""
        active_ids = db.get_active_job_ids(in_memory_db, "google", env="test")
        assert active_ids == set()


class TestUpdateLastSeen:
    """Tests for update_last_seen function"""

    def test_update_last_seen_resets_misses(self, in_memory_db, sample_job_listing):
        """Updates timestamp and resets consecutive_misses"""
        # Insert job with some misses
        sample_job_listing.consecutive_misses = 1
        db.insert_job(in_memory_db, sample_job_listing, env="test")

        # Increment misses to simulate missed runs
        db.increment_consecutive_misses(in_memory_db, [sample_job_listing.id], env="test")

        # Verify misses incremented
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env="test")
        assert job["consecutive_misses"] == 2

        # Update last seen
        new_timestamp = "2024-01-20T10:00:00Z"
        db.update_last_seen(in_memory_db, [sample_job_listing.id], new_timestamp, env="test")

        # Verify misses reset and timestamp updated
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env="test")
        assert job["consecutive_misses"] == 0
        assert job["last_seen_at"] == new_timestamp

    def test_update_last_seen_empty_list(self, in_memory_db):
        """Handles empty job list gracefully"""
        # Should not raise
        db.update_last_seen(in_memory_db, [], "2024-01-20T10:00:00Z", env="test")


class TestIncrementMisses:
    """Tests for increment_consecutive_misses function"""

    def test_increment_consecutive_misses(self, in_memory_db, sample_job_listing):
        """Increments counter correctly"""
        db.insert_job(in_memory_db, sample_job_listing, env="test")

        # Increment misses
        db.increment_consecutive_misses(in_memory_db, [sample_job_listing.id], env="test")

        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env="test")
        assert job["consecutive_misses"] == 1

        # Increment again
        db.increment_consecutive_misses(in_memory_db, [sample_job_listing.id], env="test")

        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env="test")
        assert job["consecutive_misses"] == 2


class TestMarkJobsClosed:
    """Tests for mark_jobs_closed function"""

    def test_mark_jobs_closed(self, in_memory_db, sample_job_listing):
        """Sets status=CLOSED and closed_on timestamp"""
        db.insert_job(in_memory_db, sample_job_listing, env="test")

        close_timestamp = "2024-01-20T15:00:00Z"
        db.mark_jobs_closed(in_memory_db, [sample_job_listing.id], close_timestamp, env="test")

        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env="test")
        assert job["status"] == "CLOSED"
        assert job["closed_on"] == close_timestamp

    def test_mark_jobs_closed_multiple(self, in_memory_db, multiple_job_listings):
        """Can close multiple jobs at once"""
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job, env="test")

        ids_to_close = ["job-000", "job-001"]
        db.mark_jobs_closed(in_memory_db, ids_to_close, "2024-01-20T15:00:00Z", env="test")

        for job_id in ids_to_close:
            job = db.get_job_by_id(in_memory_db, job_id, env="test")
            assert job["status"] == "CLOSED"

        # job-002 should still be open
        job = db.get_job_by_id(in_memory_db, "job-002", env="test")
        assert job["status"] == "OPEN"


class TestReactivateJob:
    """Tests for reactivate_job function"""

    def test_reactivate_job(self, in_memory_db, sample_job_listing):
        """Sets status=OPEN, clears closed_on, resets misses"""
        db.insert_job(in_memory_db, sample_job_listing, env="test")

        # Close the job
        db.mark_jobs_closed(in_memory_db, [sample_job_listing.id], "2024-01-20T15:00:00Z", env="test")

        # Verify closed
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env="test")
        assert job["status"] == "CLOSED"

        # Reactivate
        reactivate_timestamp = "2024-01-21T10:00:00Z"
        db.reactivate_job(in_memory_db, sample_job_listing.id, reactivate_timestamp, env="test")

        # Verify reactivated
        job = db.get_job_by_id(in_memory_db, sample_job_listing.id, env="test")
        assert job["status"] == "OPEN"
        assert job["closed_on"] is None
        assert job["consecutive_misses"] == 0
        assert job["last_seen_at"] == reactivate_timestamp


class TestScrapeRun:
    """Tests for record_scrape_run function"""

    def test_record_scrape_run(self, in_memory_db, sample_scrape_run):
        """Inserts ScrapeRun metadata"""
        db.record_scrape_run(in_memory_db, sample_scrape_run, env="test")

        # Verify by direct query
        cursor = in_memory_db.cursor()
        cursor.execute(
            "SELECT * FROM scrape_runs_test WHERE run_id = ?",
            (sample_scrape_run.run_id,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert dict(row)["company"] == "google"
        assert dict(row)["mode"] == "incremental"
        assert dict(row)["jobs_seen"] == 100
        assert dict(row)["new_jobs"] == 10


class TestGetAllActiveJobs:
    """Tests for get_all_active_jobs function"""

    def test_get_all_active_jobs(self, in_memory_db, multiple_job_listings):
        """Returns list of JobListing objects"""
        for job in multiple_job_listings:
            db.insert_job(in_memory_db, job, env="test")

        # Mark one as closed
        db.mark_jobs_closed(in_memory_db, ["job-001"], "2024-01-16T10:00:00Z", env="test")

        # Get all active jobs
        active_jobs = db.get_all_active_jobs(in_memory_db, "google", env="test")

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
        active_jobs = db.get_all_active_jobs(in_memory_db, "google", env="test")
        assert active_jobs == []

    def test_get_all_active_jobs_filters_by_company(self, in_memory_db, sample_job_listing):
        """Only returns jobs for specified company"""
        # Insert Google job
        db.insert_job(in_memory_db, sample_job_listing, env="test")

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
        db.insert_job(in_memory_db, apple_job, env="test")

        # Get Google jobs only
        google_jobs = db.get_all_active_jobs(in_memory_db, "google", env="test")
        assert len(google_jobs) == 1
        assert google_jobs[0].company == "google"

        # Get Apple jobs only
        apple_jobs = db.get_all_active_jobs(in_memory_db, "apple", env="test")
        assert len(apple_jobs) == 1
        assert apple_jobs[0].company == "apple"
