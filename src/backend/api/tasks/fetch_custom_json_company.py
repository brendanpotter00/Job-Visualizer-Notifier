"""Procrastinate task: fetch one custom_json company's jobs via its recipe.

Per-company unit of work for the ``custom_json`` fan-out. Structurally identical
to ``fetch_greenhouse_company`` (same upsert → last-seen → miss → close
idempotent order, same safety guard, same ``scrape_runs`` bookkeeping) but the
source is a stored recipe replayed by ``services/custom_json_client`` rather than
an ATS client.

One behavioural difference: when the low-yield safety guard trips (a recipe that
suddenly returns almost nothing — the classic "the site changed its API" failure
for user-added custom sources) we flip ``companies.health_status`` to
``degraded`` so it surfaces for regeneration, in addition to skipping the
destructive update/close phases. We never mass-close the user's jobs on a
suspicious low yield.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Set

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
from ..services.custom_json_client import (
    SOURCE_ID,
    RecipeError,
    fetch_jobs,
    transform_to_job_listings,
)
from ..services.url_guard import BlockedURLError
from .normalize_location import normalize_location
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

_TASK_TIMEOUT_S: float = 120.0


@procrastinate_app.task(
    queue="custom_json_fetch",
    name="fetch_custom_json_company",
    retry=RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def fetch_custom_json_company(
    company_id: str,
    provider_config: dict[str, Any],
) -> None:
    """Fetch one custom_json company, upsert jobs, advance lifecycle."""
    run_id = str(uuid.uuid4())
    started_at = get_iso_timestamp()
    jobs_seen = 0
    new_jobs_count = 0
    closed_jobs_count = 0
    error_count = 0
    new_ids: Set[str] = set()
    scrape_error: BaseException | None = None

    conn = await asyncio.to_thread(
        db.get_connection,
        settings.database_url,
        application_name="task_fetch_custom_json",
        statement_timeout_ms=60_000,
    )
    try:
        try:
            async def _work() -> None:
                nonlocal jobs_seen, new_jobs_count, closed_jobs_count, error_count, new_ids
                async with httpx.AsyncClient() as http:
                    raw = await fetch_jobs(provider_config, http)
                jobs = transform_to_job_listings(company_id, raw, provider_config)
                jobs_seen = len(jobs)

                active_count = await asyncio.to_thread(
                    db.count_active_jobs, conn, SOURCE_ID, company_id
                )

                if active_count > 0 and jobs_seen < SAFETY_GUARD_RATIO * active_count:
                    logger.error(
                        "SAFETY GUARD for custom_json %s: returned %d jobs but %d "
                        "active in DB (threshold %.0f%%). Skipping update/close and "
                        "marking health=degraded (recipe may be stale).",
                        company_id, jobs_seen, active_count, SAFETY_GUARD_RATIO * 100,
                    )
                    error_count = 1
                    # Surface the likely-broken recipe without mass-closing jobs.
                    try:
                        await asyncio.to_thread(
                            db.set_company_health_status, conn, company_id, "degraded"
                        )
                    except psycopg2.Error:
                        logger.exception(
                            "Failed to set health=degraded for %s", company_id
                        )
                    return

                timestamp = get_iso_timestamp()
                seen_ids: Set[str] = {j.id for j in jobs}
                pre_upsert_active = await asyncio.to_thread(
                    db.get_active_job_ids, conn, SOURCE_ID, company_id
                )

                # Same idempotent order as fetch_greenhouse_company — see that
                # file for the retry-safety analysis.
                if jobs:
                    await asyncio.to_thread(db.upsert_jobs_batch, conn, jobs)
                if seen_ids:
                    await asyncio.to_thread(
                        db.update_last_seen, conn, SOURCE_ID, list(seen_ids), timestamp
                    )

                new_ids = seen_ids - pre_upsert_active
                new_jobs_count = len(new_ids)

                post_upsert_active = await asyncio.to_thread(
                    db.get_active_job_ids, conn, SOURCE_ID, company_id
                )
                missing_ids = post_upsert_active - seen_ids
                if missing_ids:
                    await asyncio.to_thread(
                        db.increment_consecutive_misses, conn, SOURCE_ID, list(missing_ids)
                    )
                    to_close = await asyncio.to_thread(
                        db.get_jobs_exceeding_miss_threshold,
                        conn, SOURCE_ID, list(missing_ids), MISSED_RUN_THRESHOLD,
                    )
                    if to_close:
                        await asyncio.to_thread(
                            db.mark_jobs_closed, conn, SOURCE_ID, list(to_close), timestamp
                        )
                        closed_jobs_count = len(to_close)

                # Recipe worked and returned a healthy count — clear any prior
                # degraded flag so a recovered site returns to 'ok'.
                if jobs_seen > 0:
                    try:
                        await asyncio.to_thread(
                            db.set_company_health_status, conn, company_id, "ok"
                        )
                    except psycopg2.Error:
                        logger.exception("Failed to reset health=ok for %s", company_id)

                logger.info(
                    "fetch_custom_json_company %s: seen=%d new=%d closed=%d",
                    company_id, jobs_seen, new_jobs_count, closed_jobs_count,
                )

            await asyncio.wait_for(_work(), timeout=_TASK_TIMEOUT_S)

            # Defer location normalization for new ids (mirrors the ATS tasks).
            for job_id in new_ids:
                try:
                    await normalize_location.configure(
                        queueing_lock=f"normalize:{job_id}",
                    ).defer_async(job_id=job_id)
                except Exception:  # noqa: BLE001 - best-effort; never fail the scrape
                    logger.debug(
                        "normalize_location defer skipped for %s", job_id, exc_info=True
                    )
        except asyncio.TimeoutError as e:
            logger.error(
                "fetch_custom_json_company exceeded %ss for %s — will retry",
                _TASK_TIMEOUT_S, company_id,
            )
            error_count = 1
            scrape_error = e
        except (httpx.HTTPError, BlockedURLError, RecipeError, ValueError, psycopg2.Error) as e:
            logger.error(
                "fetch_custom_json_company failed for %s: %s",
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
            logger.exception("Failed to record scrape run %s for custom_json", run_id)
        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error(
                "Error closing task connection (potential connection leak)",
                exc_info=True,
            )

    # Re-raise the original error AFTER recording the run so Procrastinate retries.
    if scrape_error is not None:
        raise scrape_error
