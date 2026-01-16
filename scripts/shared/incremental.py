"""
5-phase incremental scraping algorithm

This module implements the incremental scraping logic that minimizes scraping time
by only fetching details for NEW jobs, while tracking job lifecycle (open/closed).

Algorithm phases:
1. Quick list scrape (IDs + basic info only)
2. Compare current_ids vs database active_ids
3. Fetch details ONLY for new job IDs (variable time, depends on new jobs)
4. Update last_seen for existing, increment misses for missing
5. Mark as closed if consecutive_misses >= 2
"""

import logging
import uuid
from typing import Set, List, Dict, Any, Tuple

from .models import JobListing, ScrapeRun
from . import database as db
from .batch_writer import BatchWriter
from .utils import get_iso_timestamp

logger = logging.getLogger(__name__)

# Threshold for marking jobs as closed (number of consecutive misses)
MISSED_RUN_THRESHOLD = 2


class ScrapeResult:
    """Result object returned by incremental scrape"""

    def __init__(
        self,
        jobs_seen: int = 0,
        new_jobs: int = 0,
        closed_jobs: int = 0,
        details_fetched: int = 0,
        error_count: int = 0,
        run_id: str = None,
    ):
        self.jobs_seen = jobs_seen
        self.new_jobs = new_jobs
        self.closed_jobs = closed_jobs
        self.details_fetched = details_fetched
        self.error_count = error_count
        self.run_id = run_id or str(uuid.uuid4())


def calculate_job_diff(
    current_ids: Set[str],
    active_known_ids: Set[str]
) -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Calculate difference between current scrape and database state

    Args:
        current_ids: Job IDs found in current scrape
        active_known_ids: Job IDs currently marked as OPEN in database

    Returns:
        Tuple of (new_jobs, still_active, missing_jobs)
        - new_jobs: Jobs in current scrape but not in DB
        - still_active: Jobs in both current scrape and DB
        - missing_jobs: Jobs in DB but not in current scrape
    """
    new_jobs = current_ids - active_known_ids
    still_active = current_ids & active_known_ids
    missing_jobs = active_known_ids - current_ids

    logger.info(f"Job diff - New: {len(new_jobs)}, Active: {len(still_active)}, Missing: {len(missing_jobs)}")

    return new_jobs, still_active, missing_jobs


async def process_new_jobs(
    scraper,
    db_conn,
    new_job_cards: List[Dict[str, Any]],
    env: str,
    detail_scrape: bool = True,
    batch_size: int = 50
) -> int:
    """
    Process new jobs: fetch details and insert into database IN BATCHES.

    Jobs are written to the database as they're scraped, not all at the end.
    This provides fault tolerance and reduces memory usage.

    Args:
        scraper: Scraper instance with scrape_job_details_streaming method
        db_conn: Database connection
        new_job_cards: List of job card dicts (basic info from list page)
        env: Environment name
        detail_scrape: Whether to fetch detail pages
        batch_size: Number of jobs per database batch

    Returns:
        Number of details fetched
    """
    if not new_job_cards:
        return 0

    logger.info(f"Processing {len(new_job_cards)} new jobs (batch_size={batch_size})...")

    timestamp = get_iso_timestamp()
    writer = BatchWriter(
        db_conn=db_conn,
        env=env,
        scraper=scraper,
        batch_size=batch_size,
        detail_scrape=detail_scrape,
        use_upsert=True  # Incremental mode uses upsert
    )

    details_fetched = 0

    if detail_scrape:
        # Use streaming approach - jobs are saved as they're scraped
        async for enriched_job in scraper.scrape_job_details_streaming(new_job_cards):
            writer.add_job(enriched_job, timestamp)
            details_fetched += 1
    else:
        # No detail scrape - just batch insert the cards
        for job_data in new_job_cards:
            writer.add_job(job_data, timestamp)

    # Flush any remaining jobs in buffer
    writer.flush()

    logger.info(
        f"Processed {writer.stats.total_processed} jobs: "
        f"{writer.stats.total_written} written, "
        f"{writer.stats.batches_written} batches, "
        f"{writer.stats.errors} errors"
    )

    return details_fetched


def update_existing_jobs(
    db_conn,
    still_active_ids: Set[str],
    missing_ids: Set[str],
    env: str,
    threshold: int = MISSED_RUN_THRESHOLD
) -> int:
    """
    Update existing jobs: reset misses for active, increment for missing, mark closed if threshold reached

    Args:
        db_conn: Database connection
        still_active_ids: Job IDs that are still in search results
        missing_ids: Job IDs that are missing from search results
        env: Environment name
        threshold: Number of consecutive misses before marking as closed

    Returns:
        Number of jobs marked as closed
    """
    timestamp = get_iso_timestamp()

    # Update last_seen for still active jobs
    if still_active_ids:
        db.update_last_seen(db_conn, list(still_active_ids), timestamp, env)

    if not missing_ids:
        return 0

    # Increment consecutive_misses for missing jobs
    db.increment_consecutive_misses(db_conn, list(missing_ids), env)

    # Check which jobs have exceeded threshold and mark as closed (single query)
    # Note: consecutive_misses was already incremented above, so we check >= threshold
    jobs_to_close = db.get_jobs_exceeding_miss_threshold(
        db_conn, list(missing_ids), threshold, env
    )

    if jobs_to_close:
        db.mark_jobs_closed(db_conn, list(jobs_to_close), timestamp, env)
        return len(jobs_to_close)

    return 0


async def run_incremental_scrape(
    scraper,
    db_conn,
    env: str,
    company: str,
    detail_scrape: bool = True
) -> ScrapeResult:
    """
    Run the 5-phase incremental scraping algorithm

    Args:
        scraper: Scraper instance (must have scrape_all_queries and scrape_job_details_streaming methods)
        db_conn: Database connection
        env: Environment name
        company: Company name (e.g., "google", "apple")
        detail_scrape: Whether to fetch detail pages for new jobs

    Returns:
        ScrapeResult with statistics
    """
    logger.info(f"Starting incremental scrape for {company} (env: {env})")

    result = ScrapeResult()
    timestamp = get_iso_timestamp()
    scrape_error = None

    try:
        # Phase 1: Quick list scrape (no details)
        logger.info("Phase 1: Quick list scrape...")
        job_cards = await scraper.scrape_all_queries()
        result.jobs_seen = len(job_cards)
        logger.info(f"Found {result.jobs_seen} jobs in search results")

        # Extract current job IDs
        current_ids = {job['id'] for job in job_cards}

        # Phase 2: Compare against database
        logger.info("Phase 2: Comparing against database...")
        active_known_ids = db.get_active_job_ids(db_conn, company, env)
        new_ids, still_active_ids, missing_ids = calculate_job_diff(current_ids, active_known_ids)

        # Phase 3: Fetch details ONLY for new jobs
        logger.info("Phase 3: Fetching details for new jobs...")
        new_job_cards = [job for job in job_cards if job['id'] in new_ids]
        result.details_fetched = await process_new_jobs(
            scraper, db_conn, new_job_cards, env, detail_scrape
        )
        result.new_jobs = len(new_ids)

        # Phase 4 & 5: Update existing jobs and mark closed
        logger.info("Phase 4 & 5: Updating job status...")
        result.closed_jobs = update_existing_jobs(
            db_conn, still_active_ids, missing_ids, env
        )

    except Exception as e:
        logger.error(f"Incremental scrape failed for {company}: {e}")
        result.error_count += 1
        scrape_error = e

    # Always record scrape run (even on failure for audit trail)
    run_record = ScrapeRun(
        run_id=result.run_id,
        company=company,
        started_at=timestamp,
        completed_at=get_iso_timestamp(),
        mode="incremental",
        jobs_seen=result.jobs_seen,
        new_jobs=result.new_jobs,
        closed_jobs=result.closed_jobs,
        details_fetched=result.details_fetched,
        error_count=result.error_count,
    )
    db.record_scrape_run(db_conn, run_record, env)

    if scrape_error:
        logger.info(
            f"Incremental scrape failed - "
            f"Seen: {result.jobs_seen}, New: {result.new_jobs}, "
            f"Errors: {result.error_count}"
        )
        raise scrape_error

    logger.info(
        f"Incremental scrape complete - "
        f"Seen: {result.jobs_seen}, New: {result.new_jobs}, "
        f"Closed: {result.closed_jobs}, Details: {result.details_fetched}"
    )

    return result
