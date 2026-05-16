"""Procrastinate task: fetch a single Greenhouse company's job board.

Per-company unit of work for the greenhouse fan-out cron (see Unit 5).
Fetches the live Greenhouse Job Board API for one company, upserts rows
into ``job_listings``, advances the consecutive-misses lifecycle, marks
jobs CLOSED once misses exceed ``MISSED_RUN_THRESHOLD``, and records a
single ``scrape_runs`` row.

Concurrency model
-----------------
The task is async; helpers in :mod:`scripts.shared.database` are sync
psycopg2. We acquire a fresh sync connection per task (separate from the
FastAPI request pool) and call helpers directly. Worker concurrency=5
means at most 5 brief blocked event-loop slices, acceptable for a backend
cron worker. Do NOT copy this pattern to request handlers.

Safety guard
------------
If the API returns suspiciously few jobs (< SAFETY_GUARD_RATIO * active
count), record the run with error_count=1 and exit without destructive
writes. Mirrors ``scripts/shared/incremental.py``.

Bookkeeping
-----------
``record_scrape_run`` writes one row with start + complete already
populated. Wrapped in a `finally` try/except that never masks the original
exception (Procrastinate needs the original exception to retry).
"""

from __future__ import annotations

import logging
import uuid
from typing import Set

import httpx
from procrastinate import RetryStrategy

from scripts.shared import database as db
from scripts.shared.incremental import (
    MISSED_RUN_THRESHOLD,
    SAFETY_GUARD_RATIO,
)
from scripts.shared.models import ScrapeRun
from scripts.shared.utils import get_iso_timestamp

from ..config import settings
from ..services.greenhouse_client import fetch_jobs, transform_to_job_listings
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)


@procrastinate_app.task(
    queue="greenhouse_fetch",
    name="fetch_greenhouse_company",
    retry=RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def fetch_greenhouse_company(
    company_id: str,
    board_token: str,
) -> None:
    """Fetch one Greenhouse company, upsert jobs, advance lifecycle.

    Procrastinate retries on any unhandled exception per RetryStrategy;
    the safety guard path returns normally so it doesn't consume retries.
    """
    run_id = str(uuid.uuid4())
    started_at = get_iso_timestamp()
    jobs_seen = 0
    new_jobs_count = 0
    closed_jobs_count = 0
    error_count = 0
    scrape_error: BaseException | None = None

    conn = db.get_connection(settings.database_url)
    try:
        try:
            async with httpx.AsyncClient() as http:
                raw_jobs = await fetch_jobs(board_token, http)
            jobs = transform_to_job_listings(company_id, board_token, raw_jobs)
            jobs_seen = len(jobs)

            active_count = db.count_active_jobs(conn, company_id)

            if active_count > 0 and jobs_seen < SAFETY_GUARD_RATIO * active_count:
                logger.warning(
                    "SAFETY GUARD for %s: returned %d jobs but %d active in DB "
                    "(threshold %.0f%% = %.0f). Skipping update/close phases.",
                    company_id, jobs_seen, active_count,
                    SAFETY_GUARD_RATIO * 100, SAFETY_GUARD_RATIO * active_count,
                )
                error_count = 1
                return

            timestamp = get_iso_timestamp()
            seen_ids: Set[str] = {j.id for j in jobs}

            pre_upsert_active = db.get_active_job_ids(conn, company_id)

            if jobs:
                db.upsert_jobs_batch(conn, jobs)

            if seen_ids:
                db.update_last_seen(conn, list(seen_ids), timestamp)

            new_jobs_count = len(seen_ids - pre_upsert_active)

            post_upsert_active = db.get_active_job_ids(conn, company_id)
            missing_ids = post_upsert_active - seen_ids

            if missing_ids:
                db.increment_consecutive_misses(conn, list(missing_ids))
                to_close = db.get_jobs_exceeding_miss_threshold(
                    conn, list(missing_ids), threshold=MISSED_RUN_THRESHOLD,
                )
                if to_close:
                    db.mark_jobs_closed(conn, list(to_close), timestamp)
                    closed_jobs_count = len(to_close)

            logger.info(
                "fetch_greenhouse_company %s: seen=%d new=%d closed=%d",
                company_id, jobs_seen, new_jobs_count, closed_jobs_count,
            )
        except Exception as e:
            logger.error(
                "fetch_greenhouse_company failed for %s: %s",
                company_id, e, exc_info=True,
            )
            error_count = 1
            scrape_error = e
    finally:
        run_record = ScrapeRun(
            run_id=run_id,
            company=company_id,
            started_at=started_at,
            completed_at=get_iso_timestamp(),
            mode="full",
            jobs_seen=jobs_seen,
            new_jobs=new_jobs_count,
            closed_jobs=closed_jobs_count,
            details_fetched=0,
            error_count=error_count,
        )
        try:
            db.record_scrape_run(conn, run_record)
        except Exception:
            logger.exception(
                "Failed to record scrape run %s on primary connection; "
                "retrying on fresh connection",
                run_id,
            )
            try:
                fallback_conn = db.get_connection(settings.database_url)
                try:
                    db.record_scrape_run(fallback_conn, run_record)
                finally:
                    fallback_conn.close()
            except Exception:
                logger.exception(
                    "Fallback record_scrape_run also failed for %s",
                    run_id,
                )

        try:
            conn.close()
        except Exception:
            logger.warning("Error closing task connection", exc_info=True)

    if scrape_error is not None:
        raise scrape_error
