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

# Safety guard: if scraped jobs fall below this ratio of active DB jobs,
# skip update/close phases. Catches full failures (0 jobs) and partial
# failures (e.g., scraper crashed after first page). With 0.1, a company
# with 5000 active jobs must return at least 500 to proceed.
SAFETY_GUARD_RATIO = 0.1


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
        skipped_update: bool = False,
    ):
        self.jobs_seen = jobs_seen
        self.new_jobs = new_jobs
        self.closed_jobs = closed_jobs
        self.details_fetched = details_fetched
        self.error_count = error_count
        self.run_id = run_id or str(uuid.uuid4())
        self.skipped_update = skipped_update


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


async def update_existing_jobs(
    db_conn,
    source_id: str,
    still_active_ids: Set[str],
    missing_ids: Set[str],
    threshold: int = MISSED_RUN_THRESHOLD,
) -> int:
    """
    Update existing jobs: reset misses for active, increment for missing, mark closed if threshold reached.

    Threshold-exceeding rows are gated on a per-source URL verifier before
    being closed — see ``scripts/shared/close_verifier.py``. Sources without
    a registered verifier (Microsoft, plus Greenhouse / Ashby / Lever / Gem /
    Workday until their verifiers ship) fall through to legacy behavior via
    ``unknown_policy="close"``; sources with one (Apple + Eightfold today)
    fail-safe to ``unknown_policy="skip"`` on ambiguity.

    Args:
        db_conn: Database connection
        source_id: Source namespace shared by ``still_active_ids`` and
            ``missing_ids`` (e.g., ``"google_scraper"``). Must be non-empty —
            an empty value would silently no-op every UPDATE in this
            function, mirroring the guard in ``run_incremental_scrape``.
        still_active_ids: Job IDs that are still in search results
        missing_ids: Job IDs that are missing from search results
        threshold: Number of consecutive misses before marking as closed

    Returns:
        Number of jobs marked as closed (after URL re-verification).
    """
    if not source_id:
        raise ValueError(
            "update_existing_jobs requires a non-empty source_id"
        )
    timestamp = get_iso_timestamp()

    # Update last_seen for still active jobs
    if still_active_ids:
        db.update_last_seen(db_conn, source_id, list(still_active_ids), timestamp)

    if not missing_ids:
        return 0

    # Increment consecutive_misses for missing jobs
    db.increment_consecutive_misses(db_conn, source_id, list(missing_ids))

    # Check which jobs have exceeded threshold (single query).
    # consecutive_misses was already incremented above, so we check >= threshold.
    jobs_to_close = db.get_jobs_exceeding_miss_threshold(
        db_conn, source_id, list(missing_ids), threshold
    )

    if not jobs_to_close:
        return 0

    # URL-verification gate: probe each candidate's public URL before
    # closing. See module docstring of ``close_verifier`` for the policy.
    # Sources without a registered verifier (Microsoft) → unknown maps to
    # "close" so legacy behavior is preserved. Sources with one → unknown
    # maps to "skip" (fail-safe — re-evaluate next tick).
    from .close_verifier import verify_close_candidates
    from .source_registry import get_verifier, _unknown_verifier

    has_verifier = get_verifier(source_id) is not _unknown_verifier
    unknown_policy = "skip" if has_verifier else "close"

    closed_ids, _kept_alive_ids, _skipped_ids = await verify_close_candidates(
        db_conn,
        source_id,
        list(jobs_to_close),
        timestamp,
        unknown_policy=unknown_policy,
    )
    return len(closed_ids)


async def run_incremental_scrape(
    scraper,
    db_conn,
    company: str,
    detail_scrape: bool = True,
    source_id: str | None = None,
) -> ScrapeResult:
    """
    Run the 5-phase incremental scraping algorithm

    Args:
        scraper: Scraper instance (must have scrape_all_queries and scrape_job_details_streaming methods)
        db_conn: Database connection
        company: Company name (e.g., "google", "apple")
        detail_scrape: Whether to fetch detail pages for new jobs
        source_id: Source namespace for composite-PK lookups. If None,
            derived from ``scraper.SOURCE_ID``. Required either way;
            raises if neither path resolves.

    Returns:
        ScrapeResult with statistics
    """
    if source_id is None:
        source_id = getattr(scraper, "SOURCE_ID", None)
    if not isinstance(source_id, str) or not source_id:
        raise ValueError(
            "run_incremental_scrape requires source_id, either as an explicit "
            "arg or via scraper.SOURCE_ID class attribute"
        )

    logger.info(f"Starting incremental scrape for {company} (source_id={source_id})")

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
        active_known_ids = db.get_active_job_ids(db_conn, source_id, company)
        new_ids, still_active_ids, missing_ids = calculate_job_diff(current_ids, active_known_ids)

        # Safety guard: skip update/close phases if scraper returned
        # suspiciously few jobs relative to active DB count. Catches full
        # failures (0 jobs) and partial failures (e.g., crash after page 1).
        min_expected = len(active_known_ids) * SAFETY_GUARD_RATIO
        if active_known_ids and result.jobs_seen < min_expected:
            logger.warning(
                "SAFETY GUARD for %s: scraper returned %d jobs but %d active "
                "jobs in database (threshold %.0f%% = %d). Skipping update/close "
                "phases to prevent mass closure. Investigate scraper health.",
                company, result.jobs_seen, len(active_known_ids),
                SAFETY_GUARD_RATIO * 100, int(min_expected),
            )
            result.skipped_update = True
        else:
            # Phase 3: Fetch details ONLY for new jobs
            logger.info("Phase 3: Fetching details for new jobs...")
            new_job_cards = [job for job in job_cards if job['id'] in new_ids]
            result.details_fetched = await process_new_jobs(
                scraper, db_conn, new_job_cards, detail_scrape
            )
            result.new_jobs = len(new_ids)

            # Phase 4 & 5: Update existing jobs and mark closed (URL-verify-gated)
            logger.info("Phase 4 & 5: Updating job status...")
            # Give the scraper a chance to install its source-specific URL
            # verifier before the close path runs. Default is a no-op; the
            # Apple scraper overrides this to open a dedicated Playwright
            # page used by ``apple_jobs_scraper.api_client.verify_url_alive``.
            setup_fn = getattr(scraper, "setup_close_verifier", None)
            if callable(setup_fn):
                try:
                    await setup_fn()
                except Exception:
                    logger.warning(
                        "Close verifier setup raised — proceeding with "
                        "legacy threshold-only close behavior",
                        exc_info=True,
                    )
            result.closed_jobs = await update_existing_jobs(
                db_conn, source_id, still_active_ids, missing_ids
            )

    except Exception as e:
        logger.error(f"Incremental scrape failed for {company}: {e}")
        result.error_count += 1
        scrape_error = e
    finally:
        # ALWAYS record scrape run - even on timeout/kill (defense in depth)
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
        try:
            db.record_scrape_run(db_conn, run_record)
        except Exception as db_err:
            logger.error(f"Failed to record scrape run: {db_err}")

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
        f"{', SKIPPED UPDATE (empty scrape guard)' if result.skipped_update else ''}"
    )

    return result
