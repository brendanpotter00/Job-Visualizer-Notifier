"""Procrastinate periodic task: fan out per-company custom_json fetches.

Mirrors ``enqueue_workday_fan_out`` (custom_json rows carry their scrape recipe
in ``provider_config``, exactly like Workday carries its tenant config). Fires
every 30 minutes; defers one ``fetch_custom_json_company`` per enabled
``custom_json`` company with a per-company queueing lock so a slow run can't pile
up duplicates.

These are the user-added custom sites: the fan-out is queue/table-driven just
like the six ATS fan-outs, so a company added at runtime is picked up on the next
tick with no code change.
"""

from __future__ import annotations

import asyncio
import logging

import psycopg2
from procrastinate import RetryStrategy
from procrastinate import exceptions as procrastinate_exceptions

from scripts.shared import database as db

from ..config import settings
from .fetch_custom_json_company import fetch_custom_json_company
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)


@procrastinate_app.periodic(
    cron="*/30 * * * *",
    periodic_id="custom_json_fan_out",
)
@procrastinate_app.task(
    queue="custom_json_fetch",
    name="enqueue_custom_json_fan_out",
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def enqueue_custom_json_fan_out(timestamp: int) -> int:
    """Defer one ``fetch_custom_json_company`` per enabled custom_json company."""
    conn = await asyncio.to_thread(db.get_connection, settings.database_url)
    try:
        companies = await asyncio.to_thread(
            db.list_enabled_companies, conn, "custom_json"
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
            "enqueue_custom_json_fan_out tick %d: no enabled custom_json companies",
            timestamp,
        )
        return 0

    deferred = 0
    failed = 0
    for c in companies:
        company_id = c["id"]
        provider_config = c.get("provider_config") or {}
        try:
            await fetch_custom_json_company.configure(
                queueing_lock=f"custom_json:{company_id}",
            ).defer_async(
                company_id=company_id,
                provider_config=provider_config,
            )
            deferred += 1
        except procrastinate_exceptions.AlreadyEnqueued:
            logger.info(
                "fetch_custom_json_company already enqueued for %s; skipping tick",
                company_id,
            )
        except (procrastinate_exceptions.ConnectorException, psycopg2.Error):
            failed += 1
            logger.exception(
                "Failed to defer fetch_custom_json_company for %s; continuing",
                company_id,
            )

    logger.info(
        "enqueue_custom_json_fan_out tick %d: deferred %d / %d companies (failed=%d)",
        timestamp, deferred, len(companies), failed,
    )
    return deferred
