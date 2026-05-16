"""Procrastinate periodic task: fan out per-company Greenhouse fetches.

Fires every 30 minutes via Procrastinate's built-in periodic deferrer
(no external cron needed - the in-process worker started in FastAPI's
lifespan runs the deferrer alongside its task loop).

For each enabled Greenhouse company, defers one ``fetch_greenhouse_company``
job with a per-company queueing lock so:

* a slow / stuck per-company run cannot cause the next tick to pile up
  duplicates;
* a manual trigger (Unit 6's admin endpoint) plus the periodic fire
  collapse to a single in-flight job per company.

Per-company task locks are intentional. The fan-out task itself does
**not** carry a queueing lock - if two ticks race, the second one is a
cheap no-op (each per-company defer is either deduped by lock or by the
periodic-defers unique constraint).

The periodic deferrer passes a ``timestamp: int`` argument (Unix epoch
seconds of the scheduled tick) into the task; we accept and log it for
traceability but don't otherwise use it.
"""

from __future__ import annotations

import asyncio
import logging

from procrastinate import exceptions as procrastinate_exceptions

from scripts.shared import database as db

from ..config import settings
from .fetch_greenhouse_company import fetch_greenhouse_company
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)


@procrastinate_app.periodic(
    cron="*/30 * * * *",
    periodic_id="greenhouse_fan_out",
)
@procrastinate_app.task(
    queue="greenhouse_fetch",
    name="enqueue_greenhouse_fan_out",
)
async def enqueue_greenhouse_fan_out(timestamp: int) -> int:
    """Defer one ``fetch_greenhouse_company`` per enabled Greenhouse company.

    Returns the count of successful deferrals (some may be silently
    skipped because a prior tick's job is still in the queue with the
    same queueing lock - that is the intended dedupe path).
    """
    # to_thread: psycopg2 has no async API, and this periodic task shares the
    # FastAPI event loop with the worker. Blocking here would freeze every
    # in-flight HTTP request for the duration of the connect + query.
    conn = await asyncio.to_thread(db.get_connection, settings.database_url)
    try:
        companies = await asyncio.to_thread(
            db.list_enabled_companies, conn, "greenhouse"
        )
    finally:
        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error(
                "Error closing fan-out connection (potential connection leak)",
                exc_info=True,
            )

    if not companies:
        logger.info(
            "enqueue_greenhouse_fan_out tick %d: no enabled greenhouse companies",
            timestamp,
        )
        return 0

    deferred = 0
    failed = 0
    for c in companies:
        company_id = c["id"]
        board_token = c["board_token"]
        try:
            await fetch_greenhouse_company.configure(
                queueing_lock=f"greenhouse:{company_id}",
            ).defer_async(
                company_id=company_id,
                board_token=board_token,
            )
            deferred += 1
        except procrastinate_exceptions.AlreadyEnqueued:
            logger.info(
                "fetch_greenhouse_company already enqueued for %s; "
                "skipping this tick",
                company_id,
            )
        except Exception:
            # Per-company isolation: a transient connector blip on company N
            # must NOT abort the loop and leave alphabetically-later companies
            # unprocessed for the entire 30-min window. Log and continue.
            failed += 1
            logger.exception(
                "Failed to defer fetch_greenhouse_company for %s; "
                "continuing with remaining companies",
                company_id,
            )

    logger.info(
        "enqueue_greenhouse_fan_out tick %d: deferred %d / %d companies "
        "(failed=%d)",
        timestamp, deferred, len(companies), failed,
    )
    return deferred
