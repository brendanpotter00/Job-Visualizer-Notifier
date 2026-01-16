"""
Unit tests for BatchWriter (shared/batch_writer.py)
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.batch_writer import BatchWriter, BatchWriterStats
from shared.models import JobListing


class TestBatchWriterStats:
    """Tests for BatchWriterStats dataclass"""

    def test_default_values(self):
        """Stats initialize with zero values"""
        stats = BatchWriterStats()
        assert stats.total_processed == 0
        assert stats.total_written == 0
        assert stats.batches_written == 0
        assert stats.errors == 0


class TestBatchWriterInit:
    """Tests for BatchWriter initialization"""

    def test_init_with_defaults(self):
        """Initializes with default batch_size and flags"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()

        writer = BatchWriter(mock_conn, "test", mock_scraper)

        assert writer.db_conn == mock_conn
        assert writer.env == "test"
        assert writer.scraper == mock_scraper
        assert writer.batch_size == 50
        assert writer.detail_scrape is True
        assert writer.use_upsert is True
        assert writer.get_buffer_size() == 0

    def test_init_with_custom_params(self):
        """Accepts custom batch_size and flags"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()

        writer = BatchWriter(
            mock_conn, "prod", mock_scraper,
            batch_size=100,
            detail_scrape=False,
            use_upsert=False
        )

        assert writer.batch_size == 100
        assert writer.detail_scrape is False
        assert writer.use_upsert is False

    def test_init_rejects_zero_batch_size(self):
        """Raises ValueError for batch_size=0"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            BatchWriter(mock_conn, "test", mock_scraper, batch_size=0)

        assert "batch_size must be positive" in str(exc_info.value)

    def test_init_rejects_negative_batch_size(self):
        """Raises ValueError for negative batch_size"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()

        with pytest.raises(ValueError) as exc_info:
            BatchWriter(mock_conn, "test", mock_scraper, batch_size=-5)

        assert "batch_size must be positive" in str(exc_info.value)


class TestBatchWriterAdd:
    """Tests for BatchWriter.add_job method"""

    def test_add_job_increments_buffer(self):
        """Adding a job increases buffer size"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()
        mock_scraper.transform_to_job_model.return_value = JobListing(
            id="job-001",
            title="Test Job",
            company="test",
            location="Test Location",
            url="https://test.com/job",
            source_id="test_scraper",
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

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=10)
        writer.add_job({"id": "job-001", "title": "Test Job"}, "2024-01-15T10:30:00Z")

        assert writer.get_buffer_size() == 1
        assert writer.stats.total_processed == 1

    def test_add_job_sets_timestamps(self):
        """add_job sets first_seen_at and last_seen_at from timestamp"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()
        job = JobListing(
            id="job-001",
            title="Test Job",
            company="test",
            location="Test Location",
            url="https://test.com/job",
            source_id="test_scraper",
            details={},
            created_at="2024-01-15T10:30:00Z",
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            first_seen_at="",  # Will be overwritten
            last_seen_at="",   # Will be overwritten
            consecutive_misses=0,
            details_scraped=False
        )
        mock_scraper.transform_to_job_model.return_value = job

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=10)
        writer.add_job({"id": "job-001"}, "2024-01-20T12:00:00Z")

        # Check that timestamps were set
        assert writer._buffer[0].first_seen_at == "2024-01-20T12:00:00Z"
        assert writer._buffer[0].last_seen_at == "2024-01-20T12:00:00Z"

    def test_add_job_sets_details_scraped_flag(self):
        """add_job sets details_scraped based on constructor flag"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()
        job = JobListing(
            id="job-001",
            title="Test Job",
            company="test",
            location="Test Location",
            url="https://test.com/job",
            source_id="test_scraper",
            details={},
            created_at="2024-01-15T10:30:00Z",
            status="OPEN",
            has_matched=False,
            ai_metadata={},
            first_seen_at="",
            last_seen_at="",
            consecutive_misses=0,
            details_scraped=False
        )
        mock_scraper.transform_to_job_model.return_value = job

        # With detail_scrape=True (default)
        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=10, detail_scrape=True)
        writer.add_job({"id": "job-001"}, "2024-01-20T12:00:00Z")
        assert writer._buffer[0].details_scraped is True

    def test_add_job_handles_transform_error(self):
        """Errors in transform_to_job_model are caught and counted"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()
        mock_scraper.transform_to_job_model.side_effect = ValueError("Transform failed")

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=10)
        writer.add_job({"id": "job-001"}, "2024-01-20T12:00:00Z")

        assert writer.get_buffer_size() == 0
        assert writer.stats.errors == 1
        assert writer.stats.total_processed == 0


class TestBatchWriterFlush:
    """Tests for BatchWriter.flush method"""

    def test_flush_empty_buffer_returns_zero(self):
        """Flushing empty buffer returns 0 and doesn't call db"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()

        writer = BatchWriter(mock_conn, "test", mock_scraper)
        result = writer.flush()

        assert result == 0
        assert writer.stats.batches_written == 0

    @patch('shared.batch_writer.db')
    def test_flush_calls_upsert_when_use_upsert_true(self, mock_db):
        """Uses upsert_jobs_batch when use_upsert=True"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()
        job = JobListing(
            id="job-001",
            title="Test Job",
            company="test",
            location="Test",
            url="https://test.com",
            source_id="test",
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
        mock_scraper.transform_to_job_model.return_value = job
        mock_db.upsert_jobs_batch.return_value = 1

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=10, use_upsert=True)
        writer.add_job({"id": "job-001"}, "2024-01-15T10:30:00Z")
        result = writer.flush()

        mock_db.upsert_jobs_batch.assert_called_once()
        assert result == 1
        assert writer.stats.total_written == 1
        assert writer.stats.batches_written == 1

    @patch('shared.batch_writer.db')
    def test_flush_calls_insert_when_use_upsert_false(self, mock_db):
        """Uses insert_jobs_batch when use_upsert=False"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()
        job = JobListing(
            id="job-001",
            title="Test Job",
            company="test",
            location="Test",
            url="https://test.com",
            source_id="test",
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
        mock_scraper.transform_to_job_model.return_value = job
        mock_db.insert_jobs_batch.return_value = 1

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=10, use_upsert=False)
        writer.add_job({"id": "job-001"}, "2024-01-15T10:30:00Z")
        result = writer.flush()

        mock_db.insert_jobs_batch.assert_called_once()
        assert result == 1

    @patch('shared.batch_writer.db')
    def test_flush_clears_buffer(self, mock_db):
        """Flush empties the buffer after writing"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()
        job = JobListing(
            id="job-001",
            title="Test Job",
            company="test",
            location="Test",
            url="https://test.com",
            source_id="test",
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
        mock_scraper.transform_to_job_model.return_value = job
        mock_db.upsert_jobs_batch.return_value = 1

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=10)
        writer.add_job({"id": "job-001"}, "2024-01-15T10:30:00Z")
        assert writer.get_buffer_size() == 1

        writer.flush()
        assert writer.get_buffer_size() == 0


class TestBatchWriterAutoFlush:
    """Tests for automatic flush when batch_size is reached"""

    @patch('shared.batch_writer.db')
    def test_auto_flush_at_batch_size(self, mock_db):
        """Buffer automatically flushes when batch_size is reached"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()

        def create_job(job_data):
            return JobListing(
                id=job_data.get("id", "unknown"),
                title="Test Job",
                company="test",
                location="Test",
                url="https://test.com",
                source_id="test",
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

        mock_scraper.transform_to_job_model.side_effect = create_job
        mock_db.upsert_jobs_batch.return_value = 3

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=3)

        # Add 3 jobs - should trigger auto-flush
        writer.add_job({"id": "job-001"}, "2024-01-15T10:30:00Z")
        writer.add_job({"id": "job-002"}, "2024-01-15T10:30:00Z")
        writer.add_job({"id": "job-003"}, "2024-01-15T10:30:00Z")

        # Buffer should be empty after auto-flush
        assert writer.get_buffer_size() == 0
        assert writer.stats.batches_written == 1
        assert writer.stats.total_written == 3
        mock_db.upsert_jobs_batch.assert_called_once()


class TestBatchWriterFallback:
    """Tests for fallback to individual inserts on batch failure"""

    @patch('shared.batch_writer.db')
    def test_fallback_to_individual_inserts_on_batch_error(self, mock_db):
        """Falls back to individual inserts when batch fails"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()
        job = JobListing(
            id="job-001",
            title="Test Job",
            company="test",
            location="Test",
            url="https://test.com",
            source_id="test",
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
        mock_scraper.transform_to_job_model.return_value = job

        # Batch insert fails
        mock_db.upsert_jobs_batch.side_effect = Exception("Batch insert failed")
        # Individual upsert succeeds
        mock_db.upsert_job.return_value = True

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=10, use_upsert=True)
        writer.add_job({"id": "job-001"}, "2024-01-15T10:30:00Z")
        result = writer.flush()

        # Should have attempted batch, then fallback to individual
        mock_db.upsert_jobs_batch.assert_called_once()
        mock_db.upsert_job.assert_called_once()
        assert result == 1
        assert writer.stats.errors == 1  # Batch error counted
        assert writer.stats.total_written == 1

    @patch('shared.batch_writer.db')
    def test_fallback_counts_individual_errors(self, mock_db):
        """Errors in individual fallback inserts are counted"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()

        def create_job(job_data):
            return JobListing(
                id=job_data.get("id", "unknown"),
                title="Test Job",
                company="test",
                location="Test",
                url="https://test.com",
                source_id="test",
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

        mock_scraper.transform_to_job_model.side_effect = create_job

        # Batch fails
        mock_db.upsert_jobs_batch.side_effect = Exception("Batch failed")
        # First individual succeeds, second fails
        mock_db.upsert_job.side_effect = [True, Exception("Individual failed")]

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=10)
        writer.add_job({"id": "job-001"}, "2024-01-15T10:30:00Z")
        writer.add_job({"id": "job-002"}, "2024-01-15T10:30:00Z")
        result = writer.flush()

        # 1 batch error + 1 individual error = 2 errors
        assert writer.stats.errors == 2
        assert writer.stats.total_written == 1
        assert result == 1


class TestBatchWriterBufferSize:
    """Tests for get_buffer_size method"""

    def test_get_buffer_size_empty(self):
        """Returns 0 for empty buffer"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()
        writer = BatchWriter(mock_conn, "test", mock_scraper)
        assert writer.get_buffer_size() == 0

    def test_get_buffer_size_after_adds(self):
        """Returns correct count after adding jobs"""
        mock_conn = MagicMock()
        mock_scraper = MagicMock()

        def create_job(job_data):
            return JobListing(
                id=job_data.get("id", "unknown"),
                title="Test Job",
                company="test",
                location="Test",
                url="https://test.com",
                source_id="test",
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

        mock_scraper.transform_to_job_model.side_effect = create_job

        writer = BatchWriter(mock_conn, "test", mock_scraper, batch_size=100)
        writer.add_job({"id": "job-001"}, "2024-01-15T10:30:00Z")
        writer.add_job({"id": "job-002"}, "2024-01-15T10:30:00Z")

        assert writer.get_buffer_size() == 2
