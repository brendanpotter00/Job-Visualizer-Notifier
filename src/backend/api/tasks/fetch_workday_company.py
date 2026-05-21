"""Procrastinate task: fetch a single Workday company's postings.

Per-company unit of work for the Workday fan-out cron (see Unit 5).
Fetches the live Workday CXS endpoint for one company, upserts rows into
``job_listings``, advances the consecutive-misses lifecycle, marks jobs
CLOSED once misses exceed ``MISSED_RUN_THRESHOLD``, and records a single
``scrape_runs`` row.

Workday differs from Greenhouse/Ashby/Gem/Lever in that it requires a
per-company JSONB blob (``provider_config``) to construct the URL +
request body. That blob arrives as a third task argument; Procrastinate
serializes it as JSON over the wire and we re-validate the required keys
at the task boundary so a malformed row produces a clean recorded error
rather than a stack trace.

Concurrency model
-----------------
Identical to ``fetch_lever_company``: the task is async; helpers in
:mod:`scripts.shared.database` are sync psycopg2. We acquire a fresh
sync connection per task (separate from the FastAPI request pool) and
wrap calls in ``asyncio.to_thread``. Worker concurrency=5 means at most
5 brief blocked event-loop slices.

Safety guard
------------
If the API returns suspiciously few jobs (< SAFETY_GUARD_RATIO * active
count), record the run with error_count=1 and exit without destructive
writes. Same pattern as ``scripts/shared/incremental.py``.

Bookkeeping
-----------
``record_scrape_run`` writes one row with start + complete already
populated. Wrapped in ``finally`` so a fetch failure still produces a
row. The nested-try shape mirrors fetch_lever_company verbatim — the
fallback connection acquire on bookkeeping failure was added in the
Greenhouse PR Pass 2 review and reproduces here.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Set

import httpx
import psycopg2
from procrastinate import RetryStrategy

from scripts.shared import database as db
from scripts.shared.incremental import (
    MISSED_RUN_THRESHOLD,
    SAFETY_GUARD_RATIO,
)
from scripts.shared.models import ScrapeRun
from scripts.shared.utils import get_iso_timestamp

from ..config import settings
from ..services.workday_client import (
    SOURCE_ID,
    _validate_provider_config,
    fetch_jobs,
    transform_to_job_listings,
)
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)


# Per-task wall-clock cap. Slowest observed prod task is Workday ~43s; 120s
# leaves ~3x headroom. Hitting this raises asyncio.TimeoutError → Procrastinate
# retries via RetryStrategy. Tests monkeypatch this to a low value to
# exercise the timeout path without sleeping for two minutes.
_TASK_TIMEOUT_S: float = 120.0


@procrastinate_app.task(
    queue="workday_fetch",
    name="fetch_workday_company",
    retry=RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def fetch_workday_company(
    company_id: str,
    board_token: str,
    provider_config: dict,
) -> None:
    """Fetch one Workday company, upsert jobs, advance lifecycle.

    ``provider_config`` is the JSONB blob from ``companies.provider_config``.
    Procrastinate serializes the dict to JSON over the wire; we re-validate
    required keys here so a malformed row records a clean error instead
    of producing a half-baked POST URL.

    Procrastinate retries on any unhandled exception per RetryStrategy;
    the safety-guard and missing-provider-keys paths return normally so
    they don't consume retries on what is fundamentally data-driven
    (not transient).

    ``board_token`` is accepted for API symmetry with the other
    per-company fetch tasks (greenhouse/ashby/gem/lever) — it's a no-op
    for Workday because the per-row identifier lives in `provider_config`,
    but the fan-out passes all three so the trigger-endpoint code can
    share the lookup shape across providers.
    """
    run_id = str(uuid.uuid4())
    started_at = get_iso_timestamp()
    jobs_seen = 0
    new_jobs_count = 0
    closed_jobs_count = 0
    error_count = 0
    scrape_error: BaseException | None = None

    # Acquire a sync psycopg2 connection in a thread. libpq connect_timeout=10
    # (set by augment_db_url in scripts/shared/database.py) bounds the
    # handshake; no shield needed — the wait_for below depends on this await
    # being cancellable so the worker slot can be freed on timeout.
    conn = await asyncio.to_thread(
        db.get_connection,
        settings.database_url,
        application_name="task_fetch_workday",
        statement_timeout_ms=60_000,
    )
    try:
        try:
            async def _work() -> None:
                nonlocal jobs_seen, new_jobs_count, closed_jobs_count, error_count

                # Validate provider_config BEFORE doing any IO so a bad row
                # doesn't waste an HTTP round-trip. ValueError lands in the
                # narrow except below and is recorded as a failed run.
                _validate_provider_config(provider_config)

                async with httpx.AsyncClient() as http:
                    raw_jobs = await fetch_jobs(provider_config, http)
                jobs = transform_to_job_listings(
                    company_id, raw_jobs, provider_config,
                )
                jobs_seen = len(jobs)

                active_count = await asyncio.to_thread(
                    db.count_active_jobs, conn, SOURCE_ID, company_id
                )

                if active_count > 0 and jobs_seen < SAFETY_GUARD_RATIO * active_count:
                    # ERROR (not WARNING): Railway routes by Python level —
                    # see _configure_logging in main.py. A persistently-
                    # tripping safety guard would otherwise be invisible in
                    # @level:error filters.
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
                # A mid-task failure (worker crash, Procrastinate kill, etc.) can
                # leave the DB partially-applied, and the RetryStrategy re-runs
                # the whole handler. The order below makes that safe:
                #
                #   1. upsert_jobs_batch       -- INSERT ... ON CONFLICT DO UPDATE.
                #                                 Idempotent: same input → same row state.
                #   2. update_last_seen        -- Sets last_seen_at AND resets
                #                                 consecutive_misses=0 for any id we
                #                                 saw in *this* run. Wipes any spurious
                #                                 increments from a prior partial run
                #                                 for any job still on the board.
                #   3. increment_consecutive_misses -- Only for ids active before
                #                                 this fetch and NOT in seen_ids. If
                #                                 a previous retry already incremented
                #                                 them and the job is still missing,
                #                                 the increment is correct (missed both
                #                                 runs). If the job came back, step 2
                #                                 reset the counter.
                #   4. mark_jobs_closed        -- Idempotent (status='CLOSED' terminal).
                #
                # Do NOT reorder these without re-doing the analysis. Mirrors
                # fetch_ashby_company / fetch_lever_company verbatim.
                # =================================================================

                if jobs:
                    await asyncio.to_thread(db.upsert_jobs_batch, conn, jobs)

                if seen_ids:
                    await asyncio.to_thread(
                        db.update_last_seen, conn, SOURCE_ID, list(seen_ids), timestamp,
                    )

                new_jobs_count = len(seen_ids - pre_upsert_active)

                post_upsert_active = await asyncio.to_thread(
                    db.get_active_job_ids, conn, SOURCE_ID, company_id
                )
                missing_ids = post_upsert_active - seen_ids

                if missing_ids:
                    await asyncio.to_thread(
                        db.increment_consecutive_misses,
                        conn, SOURCE_ID, list(missing_ids),
                    )
                    to_close = await asyncio.to_thread(
                        db.get_jobs_exceeding_miss_threshold,
                        conn,
                        SOURCE_ID,
                        list(missing_ids),
                        MISSED_RUN_THRESHOLD,
                    )
                    if to_close:
                        await asyncio.to_thread(
                            db.mark_jobs_closed,
                            conn, SOURCE_ID, list(to_close), timestamp,
                        )
                        closed_jobs_count = len(to_close)

                logger.info(
                    "fetch_workday_company %s: seen=%d new=%d closed=%d",
                    company_id, jobs_seen, new_jobs_count, closed_jobs_count,
                )

            await asyncio.wait_for(_work(), timeout=_TASK_TIMEOUT_S)
        except asyncio.TimeoutError as e:
            logger.error(
                "fetch_workday_company exceeded 120s for %s — Procrastinate will retry",
                company_id,
            )
            error_count = 1
            scrape_error = e
        except (httpx.HTTPError, ValueError, psycopg2.Error) as e:
            # Narrow on purpose: programmer errors (AttributeError, TypeError,
            # NameError, etc.) should propagate so Procrastinate marks the
            # task failed immediately rather than burning all 5 retries on a
            # deterministic bug. ValueError covers both `_validate_provider_config`
            # rejecting a bad row AND the client's response-shape guards.
            logger.error(
                "fetch_workday_company failed for %s: %s",
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
                    application_name="task_fetch_workday_fallback",
                    statement_timeout_ms=60_000,
                )
                try:
                    await asyncio.to_thread(
                        db.record_scrape_run, fallback_conn, run_record,
                    )
                finally:
                    try:
                        await asyncio.to_thread(fallback_conn.close)
                    except Exception:
                        # ERROR: a leaked fallback connection won't show
                        # in pool metrics. @level:error so it's visible.
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
            # ERROR (not WARNING): leaked task connections are direct
            # (not pooled) and need @level:error visibility.
            logger.error(
                "Error closing task connection (potential connection leak)",
                exc_info=True,
            )

    if scrape_error is not None:
        raise scrape_error
