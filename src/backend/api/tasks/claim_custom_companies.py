"""Procrastinate periodic task: claim due custom companies and fan out (E7).

Fires every 15 minutes. Selects ``visibility='user'`` companies whose
``next_run_at`` has passed, claims them with ``FOR UPDATE SKIP LOCKED`` (so two
overlapping ticks — or a future multi-replica worker — never double-claim a
row), immediately bumps ``next_run_at`` to ``now() + cadence_hours ± jitter``
(so the row won't be re-selected next tick), and defers one
``fetch_custom_company`` per claimed company with a per-company queueing lock.

Two bounds keep this gentle:

* a **global concurrency ceiling of 3** in-flight custom fetches (counted off
  ``procrastinate_jobs``), so a burst of newly-added companies drains a few at a
  time rather than all at once, and
* **±90 min jitter** on the next run, so companies added together don't
  synchronize into a nightly thundering herd.

The claim task carries no queueing lock of its own — if two ticks race, the
``FOR UPDATE SKIP LOCKED`` claim + the per-company defer lock make the second a
cheap no-op.
"""

from __future__ import annotations

import asyncio
import logging
import random

import psycopg2
from procrastinate import RetryStrategy
from procrastinate import exceptions as procrastinate_exceptions

from scripts.shared import database as db

from ..config import settings
from .fetch_custom_company import fetch_custom_company
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# Backpressure ceiling: never queue more than this many not-yet-started custom
# fetches per tick. This throttles a burst of newly-added companies; the hard cap
# on CONCURRENTLY RUNNING fetches is the worker's own concurrency (5), and the
# per-company queueing lock prevents duplicates for any single company.
_QUEUE_BACKPRESSURE_CEILING = 3
# ±90 minutes of jitter on the next scheduled run, in seconds.
_JITTER_SECONDS = 90 * 60


def _count_queued_fetches(conn: psycopg2.extensions.connection) -> int:
    """Count only QUEUED-but-not-started (``'todo'``) fetch jobs, best-effort.

    Deliberately counts ``'todo'`` ONLY, not ``'doing'``. Counting ``'doing'``
    would starve the whole feature: if a worker is killed mid-task, Procrastinate
    leaves that job stuck in ``'doing'`` (it does not auto-requeue stalled jobs),
    so three wedged ``'doing'`` rows would hold the budget at <= 0 forever and no
    custom company would ever be claimed again. Counting only ``'todo'`` means a
    wedged job blocks ONLY its own company (via the per-company queueing lock),
    never the rest of the fleet — the correct failure isolation. A dedicated
    stalled-job reaper is Phase 2 (see BUILD-PLAN §4.4).

    Reads Procrastinate's own ``procrastinate_jobs`` table. If it is absent
    (e.g. a schema where the Procrastinate bootstrap has not run), treat it as
    zero queued rather than failing the tick.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT to_regclass('procrastinate_jobs') AS t")
    row = cursor.fetchone()
    if not row or row["t"] is None:
        return 0
    cursor.execute(
        "SELECT count(*) AS n FROM procrastinate_jobs "
        "WHERE task_name = 'fetch_custom_company' "
        "AND status = 'todo'"
    )
    row = cursor.fetchone()
    return int(row["n"]) if row else 0


def _claim_due_companies(conn: psycopg2.extensions.connection, limit: int) -> list[str]:
    """Atomically claim up to ``limit`` due custom companies; return their ids.

    Claiming = select the due rows FOR UPDATE SKIP LOCKED and, in the same
    transaction, push their ``next_run_at`` forward by one cadence ± jitter. The
    push is what prevents the next tick from re-selecting the same rows before
    their deferred fetch has run.
    """
    if limit <= 0:
        return []
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id
            FROM companies
            WHERE visibility = 'user'
              AND enabled = TRUE
              AND next_run_at IS NOT NULL
              AND next_run_at <= now()
            ORDER BY next_run_at
            FOR UPDATE SKIP LOCKED
            LIMIT %s
            """,
            (limit,),
        )
        ids = [row["id"] for row in cursor.fetchall()]
        for company_id in ids:
            jitter = random.uniform(-_JITTER_SECONDS, _JITTER_SECONDS)
            cursor.execute(
                """
                UPDATE companies
                SET next_run_at = now()
                    + (COALESCE(cadence_hours, 24) || ' hours')::interval
                    + (%s || ' seconds')::interval
                WHERE id = %s
                """,
                (jitter, company_id),
            )
        conn.commit()
        return ids
    except psycopg2.Error:
        conn.rollback()
        raise


@procrastinate_app.periodic(cron="*/15 * * * *", periodic_id="custom_companies_claim")
@procrastinate_app.task(
    queue="custom_ats_fetch",
    name="claim_custom_companies",
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def claim_custom_companies(timestamp: int) -> int:
    """Claim due custom companies (bounded by the concurrency ceiling) and defer.

    Returns the number of ``fetch_custom_company`` jobs deferred this tick.
    """
    conn = await asyncio.to_thread(db.get_connection, settings.database_url)
    try:
        queued = await asyncio.to_thread(_count_queued_fetches, conn)
        budget = _QUEUE_BACKPRESSURE_CEILING - queued
        if budget <= 0:
            logger.info(
                "claim_custom_companies tick %d: %d queued >= ceiling %d; skipping",
                timestamp, queued, _QUEUE_BACKPRESSURE_CEILING,
            )
            return 0
        claimed = await asyncio.to_thread(_claim_due_companies, conn, budget)
    finally:
        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error(
                "Error closing claim connection (potential connection leak)",
                exc_info=True,
            )

    if not claimed:
        logger.info("claim_custom_companies tick %d: no due companies", timestamp)
        return 0

    deferred = 0
    for company_id in claimed:
        try:
            await fetch_custom_company.configure(
                queueing_lock=f"custom:{company_id}",
            ).defer_async(company_id=company_id)
            deferred += 1
        except procrastinate_exceptions.AlreadyEnqueued:
            logger.info(
                "fetch_custom_company already enqueued for %s; skipping this tick",
                company_id,
            )
        except (procrastinate_exceptions.ConnectorException, psycopg2.Error):
            logger.exception(
                "Failed to defer fetch_custom_company for %s; continuing", company_id,
            )

    logger.info(
        "claim_custom_companies tick %d: deferred %d / %d claimed (queued=%d)",
        timestamp, deferred, len(claimed), queued,
    )
    return deferred
