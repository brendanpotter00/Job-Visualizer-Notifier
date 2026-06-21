"""Procrastinate periodic task: scan for unnormalized jobs (the safety net).

Fires every 5 minutes (Procrastinate periodic deferrer; no external cron). Finds
job_listings with normalization_status IS NULL and defers one normalize_location
per id, throttled to SCAN_LIMIT/tick. Recovery path for: subprocess-scraper jobs
(Google/Apple/Microsoft) not covered by Unit-6 chaining; the initial ~44,666-row
backlog; the LLM-failure tail.

SKIP-WHEN-NO-KEY (load-bearing): if ANTHROPIC_API_KEY is unset, defer NOTHING and
return 0. This makes Unit-5's leave-NULL-on-missing-key safe (no stuck re-defer
churn) and gives auto-recovery: the NULL backlog stays dormant while the key is
absent and drains on the next tick once the key is set — no manual
re-normalize-all. Key read at call time (not cached).

Connection discipline (mirrors enqueue_greenhouse_fan_out): open a standalone
psycopg2 conn for the SELECT only and CLOSE it in finally BEFORE the defer loop
(deferring uses the app connector, not this conn).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import psycopg2
from procrastinate import RetryStrategy
from procrastinate import exceptions as procrastinate_exceptions

from scripts.shared import database as db

from ..config import settings
from .normalize_location import normalize_location
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# SCAN_LIMIT=100 * 12 ticks/hr * 24 = 28,800/day => ~44,666 backlog drains in
# ~1.5 days. Early on <=100 cache-miss ids/tick => ~100 Haiku calls/tick (cents).
# queueing_lock dedups vs Unit-6 chaining + prior ticks (AlreadyEnqueued no-op).
SCAN_LIMIT = 100
SCAN_CRON = "*/5 * * * *"
_STATEMENT_TIMEOUT_MS = 60_000


@procrastinate_app.periodic(cron=SCAN_CRON, periodic_id="scan_unnormalized")
@procrastinate_app.task(
    queue="normalize",
    name="scan_unnormalized",
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def scan_unnormalized(timestamp: int, limit: int = SCAN_LIMIT) -> int:
    """Defer normalize_location for up to ``limit`` unnormalized jobs. Returns count deferred."""
    if not settings.anthropic_api_key:
        logger.info(
            "scan_unnormalized tick %d: ANTHROPIC_API_KEY unset; skipping "
            "(jobs stay NULL for auto-recovery once the key is set)", timestamp,
        )
        return 0

    conn = await asyncio.to_thread(
        db.get_connection, settings.database_url,
        application_name="task_scan_unnormalized", statement_timeout_ms=_STATEMENT_TIMEOUT_MS,
    )
    try:
        def _select_ids() -> list[Any]:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT id FROM job_listings WHERE normalization_status IS NULL LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
            finally:
                cur.close()
            return [r["id"] if isinstance(r, dict) else r[0] for r in rows]
        job_ids = await asyncio.to_thread(_select_ids)
    finally:
        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error("Error closing scan_unnormalized connection (potential leak)", exc_info=True)

    if not job_ids:
        logger.info("scan_unnormalized tick %d: no unnormalized jobs", timestamp)
        return 0

    deferred = 0
    failed = 0
    for job_id in job_ids:
        try:
            await normalize_location.configure(
                queueing_lock=f"normalize:{job_id}",
            ).defer_async(job_id=job_id)
            deferred += 1
        except procrastinate_exceptions.AlreadyEnqueued:
            logger.debug("normalize_location already enqueued for %s; skipping", job_id)
        except (procrastinate_exceptions.ConnectorException, psycopg2.Error):
            failed += 1
            logger.exception(
                "Failed to defer normalize_location for %s; continuing with remaining ids", job_id,
            )

    if failed > 0 and deferred == 0:
        # Every defer failed: the safety-net-of-last-resort made zero progress
        # this tick. Escalate to @level:error so a fully-broken tick is visible
        # in Railway's error stream (not buried in the INFO summary).
        logger.error(
            "scan_unnormalized tick %d: ALL %d defer(s) FAILED (deferred=0, limit=%d); "
            "no progress this tick", timestamp, failed, limit,
        )
    else:
        logger.info(
            "scan_unnormalized tick %d: deferred %d / %d unnormalized (failed=%d, limit=%d)",
            timestamp, deferred, len(job_ids), failed, limit,
        )
    return deferred
