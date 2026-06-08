"""Procrastinate task: normalize one job's free-text location (the glue).

LOAD-BEARING connection discipline (Decision #3 — do NOT collapse into one
transaction): the DB connection is NEVER held across the Haiku ``await``.
tx1 (read + Tier-1) -> CLOSE conn -> LLM call (no conn) -> tx2 (fresh conn, write).
The 2026-05-17 pool-exhaustion incident was caused by connections held across
slow work; a 10s LLM hold on an open connection is exactly that anti-pattern.

Graceful no-key (Implementation Addendum): a missing ANTHROPIC_API_KEY marks the
job 'failed' (logged no-api-key) and returns normally — no raise, no retry burn,
worker stays green. Marking 'failed' (not NULL) advances the safety-net's
WHERE normalization_status IS NULL window. After the key is set, the operator
runs the Unit-8 re-normalize-all endpoint to reprocess.
"""

from __future__ import annotations

import asyncio
import logging

from procrastinate import RetryStrategy

from scripts.shared import database as db

from ..config import settings
from ..services.llm_client import (
    LocationLLMError,
    MissingAnthropicKeyError,
    normalize_location_via_llm,
)
from ..services.location_normalization import (
    lookup_alias,
    normalize_string,
    persist_llm_result,
    set_normalization_status,
    write_job_locations_from_ids,
)
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

CONFIDENCE_FLOOR: float = 0.5
_STATEMENT_TIMEOUT_MS = 60_000

# Sentinel distinguishing "tx1 reached a terminal state" from "proceed to Tier-2".
_DONE_SENTINEL = object()


async def _open_conn(application_name: str):
    return await asyncio.to_thread(
        db.get_connection, settings.database_url,
        application_name=application_name, statement_timeout_ms=_STATEMENT_TIMEOUT_MS,
    )


async def _close_conn(conn) -> None:
    try:
        await asyncio.to_thread(conn.close)
    except Exception:
        logger.error("Error closing normalize_location task connection (potential leak)", exc_info=True)


@procrastinate_app.task(
    queue="normalize", name="normalize_location",
    retry=RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def normalize_location(job_id: str) -> None:
    """Normalize one job's location via Tier-1 cache then Tier-2 Haiku."""
    # ---- tx1: read + Tier-1. Connection released BEFORE the LLM await. ----
    conn = await _open_conn("task_normalize_location")
    try:
        def _read_and_tier1():
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT location, normalization_status FROM job_listings WHERE id = %s LIMIT 1",
                    (job_id,),
                )
                row = cur.fetchone()
            finally:
                cur.close()
            if row is None:
                logger.info("normalize_location: no job_listings row for id=%r; skipping", job_id)
                return None
            status = row["normalization_status"] if isinstance(row, dict) else row[1]
            loc = row["location"] if isinstance(row, dict) else row[0]
            if status == "done":
                logger.debug("normalize_location: job %r already done; short-circuit", job_id)
                return _DONE_SENTINEL
            if loc is None or not loc.strip():
                set_normalization_status(conn, job_id, "failed")
                conn.commit()
                logger.info("normalize_location: job %r has no location (no-location); marked failed", job_id)
                return _DONE_SENTINEL
            ids = lookup_alias(conn, loc)
            if ids is not None and len(ids) > 0:
                write_job_locations_from_ids(conn, job_id, ids)
                conn.commit()
                logger.info("normalize_location: job %r Tier-1 cache HIT (%d location(s)); done", job_id, len(ids))
                return _DONE_SENTINEL
            return loc
        result = await asyncio.to_thread(_read_and_tier1)
    finally:
        await _close_conn(conn)  # Decision #3: closed BEFORE the LLM await.

    if result is _DONE_SENTINEL or result is None:
        return
    location = result  # non-empty raw location, Tier-1 miss

    # ---- LLM call: NO connection open. ----
    try:
        locations = await normalize_location_via_llm(location)
    except MissingAnthropicKeyError:
        conn2 = await _open_conn("task_normalize_location_nokey")
        try:
            set_normalization_status(conn2, job_id, "failed")
            conn2.commit()
        finally:
            await _close_conn(conn2)
        logger.warning(
            "normalize_location: ANTHROPIC_API_KEY unset; job %r marked failed (no-api-key). "
            "Set the key and run re-normalize-all to reprocess.", job_id,
        )
        return
    # LocationLLMError / anthropic.APIError / APITimeoutError -> propagate (Procrastinate retries).

    # ---- Confidence floor (Decision #9): still no conn. ----
    max_conf = max(loc.confidence for loc in locations)
    if max_conf < CONFIDENCE_FLOOR:
        conn3 = await _open_conn("task_normalize_location_lowconf")
        try:
            set_normalization_status(conn3, job_id, "failed")
            conn3.commit()
        finally:
            await _close_conn(conn3)
        logger.warning("normalize_location: job %r low-confidence (max=%.2f < %.2f); marked failed, not cached.",
                       job_id, max_conf, CONFIDENCE_FLOOR)
        return

    # ---- tx2: fresh connection, persist. ----
    raw_text = normalize_string(location)
    conn4 = await _open_conn("task_normalize_location_write")
    try:
        await asyncio.to_thread(persist_llm_result, conn4, job_id, raw_text, locations)
        await asyncio.to_thread(conn4.commit)
        logger.info("normalize_location: job %r normalized via Tier-2 (%d location(s)); done", job_id, len(locations))
    finally:
        await _close_conn(conn4)
