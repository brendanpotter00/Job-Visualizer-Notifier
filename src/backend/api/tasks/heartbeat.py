"""Worker heartbeat: a no-op periodic task that proves the Procrastinate
scheduler + worker pair is still alive.

Why a heartbeat at all when /health/worker already reads
``procrastinate_events``? Two reasons:

1. ``_insert_heartbeat_sync`` opens a **fresh** psycopg2 connection
   (independent of Procrastinate's connector pool) before writing. So
   the heartbeat row hits Postgres via a different code path than the
   Procrastinate event-stream — a Procrastinate connector that's
   serving stale/broken connections to its own event writes can still
   produce healthy heartbeat rows iff the worker can dequeue, and a
   sick application/IO path that breaks fresh connections too will
   show up here even when Procrastinate's events table is also stale.
   Two signals, two write paths.
2. Independent table = independent of Procrastinate's schema. A future
   Procrastinate upgrade that renames or reshapes ``procrastinate_events``
   won't break the freshness probe.

Fires every 5 minutes. The companion cleanup task (``cleanup_heartbeats``)
prunes rows older than 24 hours so the table stays tiny.
"""

from __future__ import annotations

import asyncio
import logging

import psycopg2

from scripts.shared import database as db

from ..config import settings
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)


def _insert_heartbeat_sync(database_url: str) -> None:
    """Open a fresh sync psycopg2 conn, INSERT one heartbeat row, close.

    Uses path-specific application_name so connection leaks here can be
    attributed in pg_stat_activity. statement_timeout=10s — heartbeat
    write should be instant; a hang here is itself a hang signal.
    """
    conn = db.get_connection(
        database_url,
        application_name="task_heartbeat",
        statement_timeout_ms=10_000,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO worker_heartbeats (at) VALUES (now())")
        conn.commit()
    except Exception:
        # End the aborted transaction explicitly so close() doesn't have
        # to handle TRANSACTION_STATUS_INERROR cleanup, and so the
        # original exception isn't masked by a close-time error.
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            logger.error(
                "task_heartbeat connection close failed", exc_info=True
            )


def _cleanup_heartbeats_sync(database_url: str) -> int:
    """DELETE worker_heartbeats rows older than 24 hours. Returns row count."""
    conn = db.get_connection(
        database_url,
        application_name="task_heartbeat_cleanup",
        statement_timeout_ms=30_000,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM worker_heartbeats WHERE at < now() - interval '24 hours'"
            )
            deleted = cur.rowcount
        conn.commit()
        return int(deleted)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            logger.error(
                "task_heartbeat_cleanup connection close failed", exc_info=True
            )


@procrastinate_app.periodic(cron="*/5 * * * *", periodic_id="heartbeat")
@procrastinate_app.task(queue="heartbeat", name="worker_heartbeat")
async def worker_heartbeat(timestamp: int) -> None:
    """Insert one row into ``worker_heartbeats``. No retries — if a tick
    misses (connector blip, etc.) the next */5 tick will catch up; a
    persistent freshness gap is what /health/worker is supposed to detect.
    """
    try:
        await asyncio.to_thread(_insert_heartbeat_sync, settings.database_url)
    except (psycopg2.Error, OSError) as e:
        # Narrow: programmer errors must propagate so Procrastinate marks
        # the task failed. We log instead of re-raise on DB/network errors
        # because the heartbeat is the canary — a noisy stack trace every
        # 5 minutes would drown out real worker errors.
        logger.error("worker_heartbeat insert failed: %s", e, exc_info=True)


@procrastinate_app.periodic(cron="17 */6 * * *", periodic_id="heartbeat_cleanup")
@procrastinate_app.task(queue="heartbeat", name="cleanup_heartbeats")
async def cleanup_heartbeats(timestamp: int) -> int:
    """Prune worker_heartbeats rows older than 24h. Returns count deleted.

    Fires every 6 hours at :17 past to avoid colliding with the */5 ticks
    or the */30 fan-outs. With heartbeats inserted every 5 minutes (288/day),
    each cleanup removes at most ~288 rows — cheap.
    """
    deleted = await asyncio.to_thread(_cleanup_heartbeats_sync, settings.database_url)
    logger.info("cleanup_heartbeats: pruned %d rows older than 24h", deleted)
    return deleted
