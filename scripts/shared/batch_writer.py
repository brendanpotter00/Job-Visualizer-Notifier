"""
Batch writer utility for efficient database writes during scraping.

Provides a buffering approach for writing jobs to the database in batches
during detail scraping, reducing memory usage and ensuring partial progress
is saved if scraping is interrupted.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Protocol

from .models import JobListing
from .database import Connection
from . import database as db


class ScraperProtocol(Protocol):
    """Protocol for scraper objects compatible with BatchWriter"""

    def transform_to_job_model(self, job_data: Dict[str, Any]) -> JobListing:
        ...

logger = logging.getLogger(__name__)


@dataclass
class BatchWriterStats:
    """Statistics from batch writing operations"""
    total_processed: int = 0
    total_written: int = 0
    batches_written: int = 0
    errors: int = 0


class BatchWriter:
    """
    Buffered batch writer for job listings.

    Accumulates jobs in a buffer and writes to database when
    batch_size is reached or flush() is called.

    Usage:
        writer = BatchWriter(conn, env, scraper, batch_size=50)
        async for job in scraper.scrape_job_details_streaming(job_cards):
            writer.add_job(job, timestamp)
        writer.flush()  # Write remaining jobs
    """

    def __init__(
        self,
        db_conn: Connection,
        env: str,
        scraper: ScraperProtocol,
        batch_size: int = 50,
        detail_scrape: bool = True,
        use_upsert: bool = True
    ):
        """
        Initialize batch writer.

        Args:
            db_conn: Database connection
            env: Environment name (local/qa/prod)
            scraper: Scraper instance with transform_to_job_model method
            batch_size: Number of jobs per batch write (default 50, must be > 0)
            detail_scrape: Whether details were scraped (sets details_scraped flag)
            use_upsert: Use upsert (True) or insert (False) for batch writes

        Raises:
            ValueError: If batch_size is not a positive integer
        """
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")

        self.db_conn = db_conn
        self.env = env
        self.scraper = scraper
        self.batch_size = batch_size
        self.detail_scrape = detail_scrape
        self.use_upsert = use_upsert

        self._buffer: List[JobListing] = []
        self.stats = BatchWriterStats()

    def add_job(self, job_data: Dict[str, Any], timestamp: str) -> None:
        """
        Add a job to the buffer, flushing if batch size reached.

        Args:
            job_data: Raw job dictionary from scraper
            timestamp: ISO timestamp for first_seen_at/last_seen_at
        """
        try:
            job = self.scraper.transform_to_job_model(job_data)
            job.first_seen_at = timestamp
            job.last_seen_at = timestamp
            job.details_scraped = self.detail_scrape

            self._buffer.append(job)
            self.stats.total_processed += 1

            if len(self._buffer) >= self.batch_size:
                self.flush()

        except Exception as e:
            logger.error(f"Error transforming job {job_data.get('id', 'unknown')}: {e}")
            self.stats.errors += 1

    def flush(self) -> int:
        """
        Write buffered jobs to database.

        Returns:
            Number of jobs written in this flush
        """
        if not self._buffer:
            return 0

        batch_fn = db.upsert_jobs_batch if self.use_upsert else db.insert_jobs_batch
        count = 0

        try:
            count = batch_fn(self.db_conn, self._buffer, self.env)
            self.stats.batches_written += 1
        except Exception as e:
            logger.error(f"Error writing batch: {e}")
            self.stats.errors += 1
            logger.info("Falling back to individual inserts...")
            count = self._fallback_individual_writes()
        finally:
            # Centralize stats update - only update total_written here
            self.stats.total_written += count
            logger.info(
                f"Flushed batch {self.stats.batches_written}: "
                f"{count} jobs written (total: {self.stats.total_written})"
            )
            self._buffer = []

        return count

    def _fallback_individual_writes(self) -> int:
        """Write jobs individually when batch write fails. Returns count only."""
        write_fn = db.upsert_job if self.use_upsert else db.insert_job
        count = 0
        for job in self._buffer:
            try:
                write_fn(self.db_conn, job, self.env)
                count += 1
            except Exception as e:
                logger.error(f"Fallback insert failed for {job.id}: {e}")
                self.stats.errors += 1
        return count

    def get_buffer_size(self) -> int:
        """Return current buffer size"""
        return len(self._buffer)
