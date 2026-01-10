"""
5-phase incremental scraping algorithm

This module implements the incremental scraping logic that minimizes scraping time
by only fetching details for NEW jobs, while tracking job lifecycle (open/closed).

Algorithm phases:
1. Quick list scrape (IDs + basic info only) → 2-3 min
2. Compare current_ids vs database active_ids → instant
3. Fetch details ONLY for new job IDs → variable (depends on new jobs)
4. Update last_seen for existing, increment misses for missing
5. Mark as closed if consecutive_misses >= 2
"""

import logging
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set, List, Dict, Any, Tuple

# Add parent directory for google_jobs_scraper imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from google_jobs_scraper.utils import get_iso_timestamp
from .models import JobListing, ScrapeRun
from . import database as db

logger = logging.getLogger(__name__)

# Threshold for marking jobs as closed (number of consecutive misses)
MISSED_RUN_THRESHOLD = 2


def _generate_run_id() -> str:
    """Generate a unique run ID."""
    return str(uuid.uuid4())


@dataclass
class ScrapeResult:
    """Result object returned by incremental scrape."""

    jobs_seen: int = 0
    new_jobs: int = 0
    closed_jobs: int = 0
    details_fetched: int = 0
    error_count: int = 0
    run_id: str = field(default_factory=_generate_run_id)


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
    detail_scrape: bool = True
) -> int:
    """
    Process new jobs: fetch details and insert into database

    Args:
        scraper: Scraper instance with extract_job_details method
        db_conn: Database connection
        new_job_cards: List of job card dicts (basic info from list page)
        env: Environment name
        detail_scrape: Whether to fetch detail pages

    Returns:
        Number of details fetched
    """
    if not new_job_cards:
        return 0

    logger.info(f"Processing {len(new_job_cards)} new jobs...")

    # Fetch details if requested
    details_fetched = 0
    if detail_scrape:
        enriched_jobs = await scraper.scrape_job_details_batch(new_job_cards)
        details_fetched = len(enriched_jobs)
    else:
        enriched_jobs = new_job_cards

    # Transform to JobListing models and insert
    timestamp = get_iso_timestamp()
    for job_data in enriched_jobs:
        try:
            job = scraper.transform_to_job_model(job_data)

            # Set incremental tracking fields
            job.first_seen_at = timestamp
            job.last_seen_at = timestamp
            job.consecutive_misses = 0
            job.details_scraped = detail_scrape

            db.upsert_job(db_conn, job, env)
        except Exception as e:
            logger.error(f"Error inserting job {job_data.get('id', 'unknown')}: {e}")

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

    # Increment consecutive_misses for missing jobs
    if missing_ids:
        db.increment_consecutive_misses(db_conn, list(missing_ids), env)

        # Check which jobs have exceeded threshold and mark as closed
        jobs_to_close = []
        for job_id in missing_ids:
            job_data = db.get_job_by_id(db_conn, job_id, env)
            if job_data and job_data['consecutive_misses'] + 1 >= threshold:
                jobs_to_close.append(job_id)

        if jobs_to_close:
            db.mark_jobs_closed(db_conn, jobs_to_close, timestamp, env)
            return len(jobs_to_close)

    return 0


def handle_reappearing_jobs(
    db_conn,
    current_ids: Set[str],
    env: str
) -> int:
    """
    Check if any currently found jobs were previously marked as closed
    and reactivate them

    Args:
        db_conn: Database connection
        current_ids: Job IDs found in current scrape
        env: Environment name

    Returns:
        Number of jobs reactivated
    """
    # This is a simplified version - in production you'd query for closed jobs
    # For now, we'll skip this step as it requires additional DB queries
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
        scraper: Scraper instance (must have scrape_query and scrape_job_details_batch methods)
        db_conn: Database connection
        env: Environment name
        company: Company name (e.g., "google")
        detail_scrape: Whether to fetch detail pages for new jobs

    Returns:
        ScrapeResult with statistics
    """
    logger.info(f"Starting incremental scrape for {company} (env: {env})")

    result = ScrapeResult()
    timestamp = get_iso_timestamp()

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

    # Record scrape run
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

    logger.info(
        f"Incremental scrape complete - "
        f"Seen: {result.jobs_seen}, New: {result.new_jobs}, "
        f"Closed: {result.closed_jobs}, Details: {result.details_fetched}"
    )

    return result
