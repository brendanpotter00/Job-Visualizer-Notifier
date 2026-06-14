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

import asyncio
import logging
import uuid
from typing import Set

import httpx
import psycopg2
from procrastinate import RetryStrategy
from procrastinate import exceptions as procrastinate_exceptions

from scripts.shared import database as db
from scripts.shared.incremental import (
    MISSED_RUN_THRESHOLD,
    SAFETY_GUARD_RATIO,
)
from scripts.shared.models import ScrapeRun
from scripts.shared.utils import get_iso_timestamp

from ..config import settings
from ..services.greenhouse_client import SOURCE_ID, fetch_jobs, transform_to_job_listings
from .normalize_location import normalize_location
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)


# Per-task wall-clock cap. Slowest observed prod task is Workday ~43s; 120s
# leaves ~3x headroom. Hitting this raises asyncio.TimeoutError → Procrastinate
# retries via RetryStrategy. Tests monkeypatch this to a low value to
# exercise the timeout path without sleeping for two minutes.
_TASK_TIMEOUT_S: float = 120.0


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
    new_ids: Set[str] = set()
    scrape_error: BaseException | None = None

    # Acquire a sync psycopg2 connection in a thread. libpq connect_timeout=10
    # (set by augment_db_url in scripts/shared/database.py) bounds the
    # handshake; no shield — task-level cancellation (Procrastinate shutdown /
    # SIGTERM) must propagate so the worker slot frees cleanly. The wait_for
    # below wraps `_work()` only; this acquire runs to completion first.
    conn = await asyncio.to_thread(
        db.get_connection,
        settings.database_url,
        application_name="task_fetch_greenhouse",
        statement_timeout_ms=60_000,
    )
    try:
        try:
            async def _work() -> None:
                nonlocal jobs_seen, new_jobs_count, closed_jobs_count, error_count, new_ids
                async with httpx.AsyncClient() as http:
                    raw_jobs = await fetch_jobs(board_token, http)
                jobs = transform_to_job_listings(company_id, raw_jobs)
                jobs_seen = len(jobs)

                active_count = await asyncio.to_thread(
                    db.count_active_jobs, conn, SOURCE_ID, company_id
                )

                if active_count > 0 and jobs_seen < SAFETY_GUARD_RATIO * active_count:
                    # ERROR (not WARNING) so Railway routes this to stderr — the
                    # platform's @level field is derived from the OS stream
                    # (see _configure_logging in main.py). A persistently-tripping
                    # safety guard would otherwise be invisible in Railway's
                    # @level:error filter.
                    logger.error(
                        "SAFETY GUARD for %s: returned %d jobs but %d active in DB "
                        "(threshold %.0f%% = %.0f). Skipping update/close phases.",
                        company_id, jobs_seen, active_count,
                        SAFETY_GUARD_RATIO * 100, SAFETY_GUARD_RATIO * active_count,
                    )
                    error_count = 1
                    return

                timestamp = get_iso_timestamp()
                seen_ids: Set[str] = {j.id for j in jobs}

                pre_upsert_active = await asyncio.to_thread(
                    db.get_active_job_ids, conn, SOURCE_ID, company_id
                )

                # =================================================================
                # Per-step auto-commit + retry idempotency (load-bearing comment).
                #
                # Each helper below opens its own transaction and commits internally.
                # That means a mid-task failure (worker crash, Procrastinate kill, etc.)
                # can leave the DB in a partially-applied state, and the @retry will
                # re-run the WHOLE handler from the top. The order below is what makes
                # that safe:
                #
                #   1. upsert_jobs_batch       -- INSERT ... ON CONFLICT DO UPDATE.
                #                                 Idempotent: re-running with the same
                #                                 input produces the same row state.
                #   2. update_last_seen        -- Sets last_seen_at AND resets
                #                                 consecutive_misses=0 for any id we
                #                                 saw in *this* run. So spurious
                #                                 increments from a prior partial run
                #                                 get wiped clean for any job that's
                #                                 still on the board.
                #   3. increment_consecutive_misses -- Only run for ids that were
                #                                 active before this fetch and NOT in
                #                                 today's seen_ids. If a previous
                #                                 retry already incremented them and
                #                                 the job is *still* missing on this
                #                                 retry, the increment is correct
                #                                 (the job missed both runs). If the
                #                                 job came back, step 2 reset the
                #                                 counter to 0.
                #   4. mark_jobs_closed        -- Idempotent (status='CLOSED' is a
                #                                 terminal write). Closing twice has
                #                                 no extra effect.
                #
                # Net: any partial failure that's later retried converges to the
                # right state. Do NOT reorder these without re-doing the analysis.
                # =================================================================

                if jobs:
                    await asyncio.to_thread(db.upsert_jobs_batch, conn, jobs)

                if seen_ids:
                    await asyncio.to_thread(db.update_last_seen, conn, SOURCE_ID, list(seen_ids), timestamp)

                new_ids = seen_ids - pre_upsert_active
                new_jobs_count = len(new_ids)

                post_upsert_active = await asyncio.to_thread(
                    db.get_active_job_ids, conn, SOURCE_ID, company_id
                )
                missing_ids = post_upsert_active - seen_ids

                if missing_ids:
                    await asyncio.to_thread(db.increment_consecutive_misses, conn, SOURCE_ID, list(missing_ids))
                    to_close = await asyncio.to_thread(
                        db.get_jobs_exceeding_miss_threshold,
                        conn,
                        SOURCE_ID,
                        list(missing_ids),
                        MISSED_RUN_THRESHOLD,
                    )
                    if to_close:
                        await asyncio.to_thread(db.mark_jobs_closed, conn, SOURCE_ID, list(to_close), timestamp)
                        closed_jobs_count = len(to_close)

                logger.info(
                    "fetch_greenhouse_company %s: seen=%d new=%d closed=%d",
                    company_id, jobs_seen, new_jobs_count, closed_jobs_count,
                )
            await asyncio.wait_for(_work(), timeout=_TASK_TIMEOUT_S)

            # ===== Unit 6: defer normalize_location for new ids =====
            # new_ids = seen_ids - pre_upsert_active (same set as new_jobs_count).
            # Run AFTER wait_for so deferring isn't charged against
            # _TASK_TIMEOUT_S and only happens when the scrape succeeded (the
            # upsert committed inside _work, so job_listings rows exist).
            # queueing_lock dedups against a defer for the same job already
            # pending (Unit-6 re-run or the Unit-7 safety-net) — AlreadyEnqueued
            # is the expected, swallowed path. Per-id try/except mirrors
            # enqueue_*_fan_out so one transient blip doesn't strand the rest.
            normalize_deferred = 0
            for job_id in new_ids:
                try:
                    await normalize_location.configure(
                        queueing_lock=f"normalize:{job_id}",
                    ).defer_async(job_id=job_id)
                    normalize_deferred += 1
                except procrastinate_exceptions.AlreadyEnqueued:
                    logger.debug(
                        "normalize_location already enqueued for job %s; skipping",
                        job_id,
                    )
                except (
                    procrastinate_exceptions.ConnectorException,
                    psycopg2.Error,
                ):
                    logger.exception(
                        "Failed to defer normalize_location for job %s; "
                        "continuing with remaining new ids",
                        job_id,
                    )
            if new_ids:
                logger.info(
                    "%s: deferred normalize_location for %d/%d new job(s)",
                    company_id, normalize_deferred, len(new_ids),
                )
            # ===== end Unit 6 =====
        except asyncio.TimeoutError as e:
            logger.error(
                "fetch_greenhouse_company exceeded %ss for %s — Procrastinate will retry",
                _TASK_TIMEOUT_S,
                company_id,
            )
            error_count = 1
            scrape_error = e
        except (httpx.HTTPError, ValueError, psycopg2.Error) as e:
            # Programmer errors (AttributeError, TypeError, NameError, etc.)
            # should propagate so Procrastinate marks the task failed
            # immediately rather than burning all 5 retries on a deterministic
            # bug. Only catch the *expected* failure modes (HTTP transport,
            # malformed payload, DB error) and convert them into a recorded
            # error so we still write a scrape_runs row.
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
            await asyncio.to_thread(db.record_scrape_run, conn, run_record)
        except Exception:
            logger.exception(
                "Failed to record scrape run %s on primary connection; "
                "retrying on fresh connection",
                run_id,
            )
            try:
                fallback_conn = await asyncio.to_thread(
                    db.get_connection,
                    settings.database_url,
                    application_name="task_fetch_greenhouse_fallback",
                    statement_timeout_ms=60_000,
                )
                try:
                    await asyncio.to_thread(db.record_scrape_run, fallback_conn, run_record)
                finally:
                    # Wrap in its own try/except so a close failure does NOT
                    # mask the original write-failure context (the outer
                    # `except` here would otherwise swallow the real cause
                    # and log "close failed" to Sentry, hiding the actual
                    # write error from the operator).
                    try:
                        await asyncio.to_thread(fallback_conn.close)
                    except Exception:
                        logger.error(
                            "Fallback record_scrape_run connection close "
                            "failed for %s (potential connection leak)",
                            run_id,
                            exc_info=True,
                        )
            except Exception:
                logger.exception(
                    "Fallback record_scrape_run also failed for %s",
                    run_id,
                )

        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            # ERROR (not WARNING): a leaked task connection is direct (not
            # pooled), so it won't show up in pool metrics. We need this in
            # Railway's stderr stream so it's visible to @level:error queries.
            logger.error(
                "Error closing task connection (potential connection leak)",
                exc_info=True,
            )

    if scrape_error is not None:
        raise scrape_error
