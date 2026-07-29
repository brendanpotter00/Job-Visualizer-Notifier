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

Safety guard
------------
Phases 4-5 are destructive (they can mark thousands of jobs CLOSED), so
they run only when the scrape result passes ``evaluate_safety_guard`` —
the one shared, pure helper every caller uses (this module AND the six
``src/backend/api/tasks/fetch_*_company.py`` leaf tasks).

Two rules, both keyed off the count of currently-OPEN rows:

  (a) ``jobs_seen < 0.10 * active``                     -> "empty_scrape"
  (b) ``jobs_seen < 0.85 * active`` AND
      ``(active - jobs_seen) >= 15``                    -> "partial_scrape"

Rule (b) was added after a prod audit of 134,777 successful runs over 129
companies (2026-07-07 -> 2026-07-28) found Apple truncating **7 times in
21 days** — returning 5%, 21%, 22%, 29%, 31%, 73% and 80% of its normal
board — while the 0.1-only guard caught only the 5% run. The other six
executed the close phase against partial data; only a lucky clean run
landing between two truncations kept ~2,800 Apple jobs from being
mass-closed. On that same dataset rule (b) fires exactly 7 times, all of
them those Apple truncations, with zero false positives.

See the constant block below for the full calibration notes and the
accepted "no auto-release" trade-off.
"""

import logging
import os
import uuid
from typing import Set, List, Dict, Any, Tuple

from .models import JobListing, ScrapeRun
from . import database as db
from .batch_writer import BatchWriter
from .utils import get_iso_timestamp

logger = logging.getLogger(__name__)

# Threshold for marking jobs as closed (number of consecutive misses)
MISSED_RUN_THRESHOLD = 2

# Safety guard rule (a) — "empty scrape". If scraped jobs fall below this
# ratio of active DB jobs, skip update/close phases. Catches full failures
# (0 jobs) and catastrophic partial failures. With 0.1, a company with 5000
# active jobs must return at least 500 to proceed.
#
# Kept at 0.1 deliberately. It is NOT the primary guard any more (rule (b)
# below subsumes it numerically), but it survives as the distinct
# "empty_scrape" reason code so operators can tell a total scraper outage
# apart from a partial truncation in logs and in scrape_runs.
SAFETY_GUARD_RATIO = 0.1

# Safety guard rule (b) — "partial scrape". Env-overridable so an operator
# can widen the gate without a redeploy (see the no-auto-release trade-off
# below). Read HERE, in this module, so the scraper subprocess
# (scripts/run_scraper.py) and the backend Procrastinate worker
# (src/backend/api/tasks/fetch_*_company.py) share ONE source of truth.
#
# Calibration (empirical, do NOT retune without re-running the numbers):
# derived from 134,777 successful prod scrape runs across 129 companies
# between 2026-07-07 and 2026-07-28. The pair
# `jobs_seen < 0.85 * active AND (active - jobs_seen) >= 15` trips exactly
# 7 times over that window — and all 7 are the real Apple truncations
# (runs returning 5%, 21%, 22%, 29%, 31%, 73% and 80% of the normal board
# size). Zero false positives. Notably it does NOT trip on Google's
# 769-of-798 run (96%) nor on genuine day-to-day hiring drift.
#
# The two conditions are ANDed on purpose:
#   * the ratio alone would fire constantly on small boards (a 30-job board
#     dropping to 22 is 73% — noise, not a truncation);
#   * the absolute drop alone would fire on large healthy boards.
#
# Why this matters: the OLD 0.1-only guard let SIX of those seven Apple
# truncations run the destructive close phase against partial data. Closure
# needs MISSED_RUN_THRESHOLD (2) *consecutive* misses, and prod was saved
# only because a clean run happened to land between two truncations. Two
# back-to-back truncations would have mass-closed ~2,800 Apple jobs.
#
# ACCEPTED TRADE-OFF — the guard has NO auto-release. A company that
# genuinely shrinks by more than 15% in one shot (on a board of >= ~100
# jobs) trips rule (b) on every subsequent run too, because the stale DB
# rows keep `active_count` high. That company stays locked out of the
# update/close phases until a human widens SCRAPER_GUARD_MIN_RATIO (or
# clears the stale rows). This is deliberate: silently mass-closing
# thousands of live jobs is far worse than freezing one company's
# lifecycle. The daily scraper-health check
# (src/backend/api/services/scraper_health.py, surfaced by
# .github/workflows/scraper-health.yml) makes such a lockout visible
# within 24h.
SCRAPER_GUARD_MIN_RATIO = float(os.environ.get("SCRAPER_GUARD_MIN_RATIO", "0.85"))
SCRAPER_GUARD_MIN_ABS_DROP = int(os.environ.get("SCRAPER_GUARD_MIN_ABS_DROP", "15"))


def evaluate_safety_guard(jobs_seen: int, active_count: int) -> str | None:
    """Decide whether a scrape result is too small to trust.

    THE single source of truth for the scraper safety guard. Pure and sync
    so both the scraper subprocess (``run_incremental_scrape`` below) and
    the six backend ATS leaf tasks call the exact same logic — the guard
    used to be copy-pasted inline in seven places and drifted.

    Args:
        jobs_seen: Number of jobs the scrape actually returned.
        active_count: Number of rows currently OPEN in the DB for this
            company/source.

    Returns:
        ``None`` when the run looks healthy and the caller should proceed
        with the update/close phases; otherwise a short machine-readable
        reason string:

        * ``"empty_scrape"``  — rule (a): jobs_seen < SAFETY_GUARD_RATIO
          (10%) of active. A total or near-total scraper failure.
        * ``"partial_scrape"`` — rule (b): jobs_seen < 85% of active AND
          the absolute drop is at least 15 jobs. An Apple-style truncation.

        A cold start (``active_count == 0``) always returns ``None`` — with
        nothing in the DB there is nothing to protect and nothing to close.
    """
    if active_count <= 0:
        return None

    if jobs_seen < SAFETY_GUARD_RATIO * active_count:
        return "empty_scrape"

    if (
        jobs_seen < SCRAPER_GUARD_MIN_RATIO * active_count
        and (active_count - jobs_seen) >= SCRAPER_GUARD_MIN_ABS_DROP
    ):
        return "partial_scrape"

    return None


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


def update_existing_jobs(
    db_conn,
    source_id: str,
    still_active_ids: Set[str],
    missing_ids: Set[str],
    threshold: int = MISSED_RUN_THRESHOLD
) -> int:
    """
    Update existing jobs: reset misses for active, increment for missing, mark closed if threshold reached

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
        Number of jobs marked as closed
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

    # Check which jobs have exceeded threshold and mark as closed (single query)
    # Note: consecutive_misses was already incremented above, so we check >= threshold
    jobs_to_close = db.get_jobs_exceeding_miss_threshold(
        db_conn, source_id, list(missing_ids), threshold
    )

    if jobs_to_close:
        db.mark_jobs_closed(db_conn, source_id, list(jobs_to_close), timestamp)
        return len(jobs_to_close)

    return 0


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

        # Safety guard: skip update/close phases if the scraper returned
        # suspiciously few jobs relative to the active DB count. Catches full
        # failures (0 jobs) and Apple-style truncations (crash after page N).
        # Logic lives in evaluate_safety_guard so this module and the six
        # backend ATS leaf tasks can never drift apart.
        guard_reason = evaluate_safety_guard(result.jobs_seen, len(active_known_ids))
        if guard_reason is not None:
            logger.warning(
                "SAFETY GUARD (%s) for %s: scraper returned %d jobs but %d active "
                "jobs in database (empty<%.0f%%, partial<%.0f%% with drop>=%d). "
                "Skipping update/close phases to prevent mass closure. "
                "Investigate scraper health.",
                guard_reason, company, result.jobs_seen, len(active_known_ids),
                SAFETY_GUARD_RATIO * 100, SCRAPER_GUARD_MIN_RATIO * 100,
                SCRAPER_GUARD_MIN_ABS_DROP,
            )
            result.skipped_update = True
            # error_count=1 harmonizes with the six ATS leaf tasks, which
            # have always recorded a tripped guard as an error. Without it a
            # truncated run is written to scrape_runs as error_count=0 —
            # literally indistinguishable from a perfect run.
            result.error_count = 1
        else:
            # Phase 3: Fetch details ONLY for new jobs
            logger.info("Phase 3: Fetching details for new jobs...")
            new_job_cards = [job for job in job_cards if job['id'] in new_ids]
            result.details_fetched = await process_new_jobs(
                scraper, db_conn, new_job_cards, detail_scrape
            )
            result.new_jobs = len(new_ids)

            # Phase 4 & 5: Update existing jobs and mark closed
            logger.info("Phase 4 & 5: Updating job status...")
            result.closed_jobs = update_existing_jobs(
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
            skipped_update=result.skipped_update,
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
        f"{', SKIPPED UPDATE (safety guard)' if result.skipped_update else ''}"
    )

    return result
