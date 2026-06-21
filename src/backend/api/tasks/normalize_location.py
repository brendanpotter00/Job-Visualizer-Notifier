"""Procrastinate task: normalize one job's free-text location (the glue).

LOAD-BEARING connection discipline (Decision #3 — do NOT collapse into one
transaction): the DB connection is NEVER held across the Haiku ``await``.
tx1 (read + Tier-1) -> CLOSE conn -> LLM call (no conn) -> tx2 (fresh conn, write).
The 2026-05-17 pool-exhaustion incident was caused by connections held across
slow work; a 10s LLM hold on an open connection is exactly that anti-pattern.

Graceful no-key (Implementation Addendum): a missing ANTHROPIC_API_KEY leaves the
job unnormalized (status stays NULL) and returns normally — no DB write, no raise,
no retry burn, worker stays green. Leaving NULL lets the Unit-7 safety-net
auto-recover the job once ANTHROPIC_API_KEY is configured (the safety-net skips
deferring while the key is unset, so NULL does NOT cause a stuck re-defer window).
No re-normalize-all needed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from procrastinate import JobContext, RetryStrategy
from psycopg2.extensions import connection as Connection

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
# Shared by the RetryStrategy and the final-attempt check below. Procrastinate's
# job.attempts counts PRIOR runs (0 on the first run), and RetryStrategy stops
# retrying once attempts >= max_attempts — so the run where
# attempts == _RETRY_MAX_ATTEMPTS is the last one (no retry will follow).
_RETRY_MAX_ATTEMPTS = 5

# Sentinel distinguishing "tx1 reached a terminal state" from "proceed to Tier-2".
_DONE_SENTINEL = object()


async def _open_conn(application_name: str) -> Connection:
    return await asyncio.to_thread(
        db.get_connection, settings.database_url,
        application_name=application_name, statement_timeout_ms=_STATEMENT_TIMEOUT_MS,
    )


async def _close_conn(conn: Connection) -> None:
    try:
        await asyncio.to_thread(conn.close)
    except Exception:
        logger.error("Error closing normalize_location task connection (potential leak)", exc_info=True)


@procrastinate_app.task(
    queue="normalize", name="normalize_location",
    retry=RetryStrategy(max_attempts=_RETRY_MAX_ATTEMPTS, exponential_wait=2),
    pass_context=True,
)
async def normalize_location(context: JobContext | None = None, *, job_id: str) -> None:
    """Normalize one job's location via Tier-1 cache then Tier-2 Haiku."""
    # ---- tx1: read + Tier-1. Connection released BEFORE the LLM await. ----
    conn = await _open_conn("task_normalize_location")
    try:
        def _read_and_tier1() -> Any:
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
            if ids is not None and len(ids) == 0:
                # A location_aliases row with zero alias_locations children
                # violates the writer invariant (every alias is written with
                # >=1 child). Falling through to Tier-2 self-heals, but at LLM
                # cost on a string that "should" be a cache hit — make the
                # violation loud so it's debuggable, not silent spend.
                logger.warning(
                    "normalize_location: alias cache invariant violated — alias row for "
                    "key %r has zero alias_locations children; falling back to Tier-2 for job %r",
                    normalize_string(loc), job_id,
                )
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
        # No key: leave the job unnormalized (status stays NULL) so the Unit-7
        # safety-net auto-recovers it once ANTHROPIC_API_KEY is configured. The
        # safety-net skips deferring while the key is unset, so leaving NULL does
        # NOT cause a stuck re-defer window. NO DB write, NO raise (no retry burn,
        # worker stays green).
        logger.warning(
            "normalize_location: ANTHROPIC_API_KEY unset; job %r left unnormalized "
            "(status stays NULL; safety-net will normalize it once the key is set).",
            job_id,
        )
        return
    except LocationLLMError as exc:
        # Parse/schema failures can recur deterministically for a pathological
        # location string. Retries still help (LLM output is nondeterministic),
        # but the FINAL attempt must mark the row 'failed' (terminal, like the
        # no-location and low-confidence paths) instead of leaving NULL —
        # otherwise the scan_unnormalized safety-net re-defers the job every
        # tick forever (the queueing_lock frees on terminal queue failure),
        # burning ~5 Haiku calls per tick per stuck job indefinitely.
        attempts = context.job.attempts if context is not None and context.job is not None else 0
        if attempts < _RETRY_MAX_ATTEMPTS:
            raise  # not the last run: propagate so Procrastinate retries.
        conn2 = await _open_conn("task_normalize_location_llmfail")
        try:
            await asyncio.to_thread(set_normalization_status, conn2, job_id, "failed")
            await asyncio.to_thread(conn2.commit)
        finally:
            await _close_conn(conn2)
        logger.error(
            "normalize_location: job %r permanently unparseable after %d attempts "
            "(location=%r); marked failed (terminal): %s",
            job_id, attempts + 1, location, exc,
        )
        raise  # keep the Procrastinate job record honest (it did fail).
    # anthropic.APIError / APITimeoutError (transient) -> propagate (Procrastinate
    # retries; the row stays NULL so the safety-net recovers it later).

    # ---- Confidence floor (Decision #9): still no conn. ----
    max_conf = max(loc.confidence for loc in locations)
    if max_conf < CONFIDENCE_FLOOR:
        conn3 = await _open_conn("task_normalize_location_lowconf")
        try:
            await asyncio.to_thread(set_normalization_status, conn3, job_id, "failed")
            await asyncio.to_thread(conn3.commit)
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
