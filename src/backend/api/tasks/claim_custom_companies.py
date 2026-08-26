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

THE THREE PUBLIC HELPERS BELOW (:func:`defer_fetch`, :func:`push_next_run_at` and
:func:`start_first_harvest`, which composes the first two) are this module's scheduling
contract. BOTH add paths call :func:`start_first_harvest` the moment a company becomes
trackable — ``discover_custom_company`` when it accepts a discovered board, and
``routers/user_companies.add_company`` when a pasted URL resolves to a supported ATS —
so the first harvest starts in seconds instead of on the next tick. They live here
rather than being copied precisely so there is ONE way a custom harvest gets enqueued:
same per-company queueing lock, same cadence±jitter push. A second enqueue path with its
own idea of the lock is how the same board ends up harvested twice concurrently — which
is the one thing the lock exists to prevent.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Literal

import psycopg2
from procrastinate import RetryStrategy
from procrastinate import exceptions as procrastinate_exceptions

from scripts.shared import database as db

from ..config import settings
from .fetch_custom_company import fetch_custom_company
from .procrastinate_app import CUSTOM_ATS_FIRST_FETCH_QUEUE, procrastinate_app

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


# The ONE statement that says "this company has been handed to a harvest; do not hand it
# over again until its next cadence". Shared verbatim by the claim tick and by the
# out-of-band first harvest, because the two must agree on what "already scheduled"
# means — a second copy that forgot the jitter would resynchronize the fleet it exists
# to spread out.
_PUSH_NEXT_RUN_SQL = """
    UPDATE companies
    SET next_run_at = now()
        + (COALESCE(cadence_hours, 24) || ' hours')::interval
        + (%s || ' seconds')::interval
    WHERE id = %s
"""


def _jitter() -> float:
    return random.uniform(-_JITTER_SECONDS, _JITTER_SECONDS)


def push_next_run_at(conn: psycopg2.extensions.connection, company_id: str) -> None:
    """Push ONE company's ``next_run_at`` forward by a cadence ± jitter, committed.

    The claim tick does this INSIDE its claim transaction; this is the standalone form
    for a harvest enqueued outside a tick (:func:`start_first_harvest`, on either add
    path). It is the PRIMARY interlock against a double harvest: with ``next_run_at`` a
    cadence away the 15-minute tick simply does not select the row, so it never even
    reaches the defer. The per-company queueing lock is the backstop for the window
    where it does.

    Call it only AFTER the defer has succeeded. Pushing first and failing to enqueue
    would silently cost the board a whole cadence — the caller's fallback is to leave
    the row due so the very next tick picks it up, which is the old behaviour and
    therefore the safe direction.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(_PUSH_NEXT_RUN_SQL, (_jitter(), company_id))
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


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
            cursor.execute(_PUSH_NEXT_RUN_SQL, (_jitter(), company_id))
        conn.commit()
        return ids
    except psycopg2.Error:
        conn.rollback()
        raise


DeferResult = Literal["deferred", "already_queued", "failed"]


async def defer_fetch(company_id: str, *, queue: str | None = None) -> DeferResult:
    """Enqueue ONE ``fetch_custom_company`` under the per-company queueing lock.

    THE single place a custom harvest is enqueued (the claim tick, and both add paths'
    first harvest via :func:`start_first_harvest`). The lock ``custom:{company_id}`` is
    what makes a duplicate enqueue impossible while a job for that company is still
    ``todo``:
    Procrastinate rejects the second defer with ``AlreadyEnqueued``, which is a normal
    outcome here and not an error.

    ``queue`` overrides the task's declared queue for THIS defer only. The claim tick
    passes nothing and lands on ``custom_ats_fetch`` (the bulk lane). The add-time
    first harvest passes ``CUSTOM_ATS_FIRST_FETCH_QUEUE`` so a user watching the
    add checklist is not queued behind the nightly re-harvest of every other tracked
    board. The queueing lock is a UNIQUE index on ``queueing_lock`` across all
    unfinished jobs regardless of queue, so routing the first harvest elsewhere does
    NOT weaken the "never two concurrent harvests of one board" interlock.

    Three outcomes, because the two callers need to distinguish them:

    * ``"deferred"``     — a job was created by this call.
    * ``"already_queued"`` — one was already waiting; the company IS scheduled, so a
      caller deciding whether to push ``next_run_at`` should treat this as success.
    * ``"failed"``       — the defer did not happen (broker or database trouble). The
      caller must leave the row due so the next tick retries; never swallow this into
      a state that says the harvest is scheduled.
    """
    try:
        deferrer = (
            fetch_custom_company.configure(
                queueing_lock=f"custom:{company_id}", queue=queue
            )
            if queue is not None
            else fetch_custom_company.configure(
                queueing_lock=f"custom:{company_id}"
            )
        )
        await deferrer.defer_async(company_id=company_id)
        return "deferred"
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "fetch_custom_company already enqueued for %s; skipping", company_id,
        )
        return "already_queued"
    except (procrastinate_exceptions.ConnectorException, psycopg2.Error):
        logger.exception(
            "Failed to defer fetch_custom_company for %s; continuing", company_id,
        )
        return "failed"


async def start_first_harvest(
    conn: psycopg2.extensions.connection, *, company_id: str, transport: str
) -> None:
    """Enqueue a just-added company's FIRST harvest now, not on the next claim tick.

    BOTH add paths call this: ``discover_custom_company`` when it accepts a discovered
    board, and ``routers/user_companies.add_company`` when a pasted URL resolves
    straight to a supported ATS. They share it because they share the bug — a row that
    says "Successfully tracking" over "0 open jobs · Not yet checked" for up to fifteen
    minutes, which reads as "we looked and your board is empty" rather than "we have not
    read it yet". Enqueuing here collapses that window to the length of one harvest.

    It composes the two primitives above rather than issuing its own defer, so there is
    exactly ONE way a ``fetch_custom_company`` gets queued:

    1. :func:`defer_fetch` — same per-company queueing lock ``custom:{id}``. If the tick
       somehow already queued this company, Procrastinate answers ``already_queued`` and
       we do not add a second job. The ONE thing that differs from the tick's defer is
       the queue: this one goes to ``CUSTOM_ATS_FIRST_FETCH_QUEUE``, drained by the
       reserved interactive worker in ``api.main``'s lifespan, because a user is
       watching the add checklist's fifth step wait on exactly this job. The nightly
       re-harvests stay on ``custom_ats_fetch`` in the bulk lane.
    2. :func:`push_next_run_at` — moves the row's ``next_run_at`` a full cadence ± jitter
       ahead, but ONLY once the defer is on the broker. That is the real interlock: the
       15-minute tick selects on ``next_run_at <= now()``, so a rescheduled row is not
       even a candidate and the two enqueue paths can never produce two concurrent
       harvests of the same board.

    THE ONLY GATE IS THE TRANSPORT, and it is the leaf task's own rule mirrored here, not
    a second policy: ``fetch_custom_company`` skips a ``browser_fetch`` harvest while
    ``custom_company_discovery_enabled`` is off (discovery is the only thing that ever
    creates that tier), so queueing one would be queueing a guaranteed no-op. Every other
    transport — ``ats_client`` from the ATS fast path, ``http_json`` from a discovered
    board — is NOT gated there and MUST NOT be gated here: an ATS board has nothing to do
    with discovery, and reading that flag for it would silently break the immediate
    harvest for every ATS add whenever the flag is off, which is the production default.
    The parent ``custom_company_sources_enabled`` flag is the caller's gate; you cannot
    reach either add path with it off.

    THE FAILURE PATH IS THE OLD BEHAVIOUR, deliberately. If the defer fails, we leave
    ``next_run_at = now()`` (where the add left it) and say so in the log — the next tick
    claims the row within 15 minutes exactly as it did before this existed. Never push
    the schedule forward on a failed defer: that trades a 15-minute wait for a 24-hour
    one, silently.

    NEVER RAISES. The company is already created and committed by the time we get here;
    an enqueue problem must not turn a successful add into a failed one — not a failed
    task on the discovery side, and not a 500 on the synchronous ATS add the user is
    waiting on.
    """
    if transport == "browser_fetch" and not settings.custom_company_discovery_enabled:
        logger.info(
            "start_first_harvest: custom_company_discovery_enabled off; leaving %s "
            "for the claim tick rather than queueing a browser_fetch no-op", company_id,
        )
        return

    try:
        result = await defer_fetch(
            company_id, queue=CUSTOM_ATS_FIRST_FETCH_QUEUE
        )
    except Exception:  # noqa: BLE001
        # ``defer_fetch`` already narrows to broker/database errors; this is the
        # last-resort guard so no enqueue surprise can cost us a company that is
        # otherwise fully added (``AppNotOpen`` is the concrete one — a Procrastinate
        # exception, NOT a ConnectorException, so it escapes the narrow tuple).
        logger.exception(
            "start_first_harvest: unexpected error deferring %s; the claim tick will "
            "pick it up", company_id,
        )
        return

    if result == "failed":
        logger.warning(
            "start_first_harvest: could not queue the first harvest for %s; leaving it "
            "due so the next claim tick runs it", company_id,
        )
        return

    try:
        await asyncio.to_thread(push_next_run_at, conn, company_id)
    except psycopg2.Error:
        # The harvest IS queued; only the reschedule failed. Worst case the next tick
        # sees the row due and calls defer_fetch again, which the queueing lock answers
        # with ``already_queued`` — the backstop doing exactly its job.
        logger.warning(
            "start_first_harvest: queued the first harvest for %s but could not push "
            "next_run_at; the queueing lock will absorb a duplicate claim",
            company_id, exc_info=True,
        )
        return

    logger.info(
        "start_first_harvest: %s first harvest %s (transport=%s); next cadence "
        "scheduled", company_id, result, transport,
    )


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
        # Counts FRESH defers only: an ``already_queued`` company is already being
        # harvested (usually because ``discover_custom_company`` just enqueued its
        # first run), and counting it would make the tick log claim work it did not do.
        if await defer_fetch(company_id) == "deferred":
            deferred += 1

    logger.info(
        "claim_custom_companies tick %d: deferred %d / %d claimed (queued=%d)",
        timestamp, deferred, len(claimed), queued,
    )
    return deferred
