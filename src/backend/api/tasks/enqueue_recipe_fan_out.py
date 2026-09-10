"""Procrastinate periodic task: fan out per-company harvests for PUBLISHED recipe boards.

A "recipe board" is a curated, ``visibility='public'`` company whose jobs are
harvested by the deterministic recipe engine (``services/recipe_runner``, replayed
agent-free over the SSRF-guarded client) rather than by a vendor ATS client. It is
marked by ``companies.ats = 'recipe'`` and carries its script in ``company_scripts``
exactly as a private custom board does.

WHY THIS IS A SEVENTH FAN-OUT AND NOT A WIDER CUSTOM CLAIM
----------------------------------------------------------
``claim_custom_companies`` (the ``*/15`` tick) is the PRIVATE lane. Widening its
``WHERE visibility = 'user'`` to include public rows would have been one word, and
it would have been wrong twice over:

* **Budget.** That tick spends a ``_QUEUE_BACKPRESSURE_CEILING`` of 3 queued
  fetches per pass, shared across every user-added board in the fleet. Four
  curated boards landing in it would consume an entire tick's budget and push
  every user's board back by 15 minutes — silently, and worse the more curated
  boards we publish.
* **Scheduling model.** A private board is claimed off ``next_run_at``
  (per-row cadence, jitter, ``FOR UPDATE SKIP LOCKED``) because users add them at
  arbitrary times and the fleet must be spread out. A published board is exactly
  like the six vendor boards: a fixed ``*/30`` cron over an ``enabled`` set. It
  needs no ``next_run_at`` bookkeeping at all, and giving it one would mean a
  curated board could silently stop being harvested because a column drifted.

So this is a straight sibling of ``enqueue_ashby_fan_out`` — same ``*/30`` cron,
same "one defer per enabled company, per-company queueing lock, per-company error
isolation" shape, reading the SAME ``db.list_enabled_companies`` helper the other
six use (which already filters ``enabled = true AND visibility = 'public'``, so a
private row can never be selected here).

WHAT IS SHARED, AND IT IS NEARLY EVERYTHING
-------------------------------------------
The unit of work is the SAME task the private lane defers —
``tasks.fetch_custom_company`` — so the structural gate, ``harvest_verification``'s
verdict, and the whole close-eligibility ladder are one implementation with one set
of guards. The two lanes differ in exactly three places, and all three are here:

1. the queue (``RECIPE_FETCH_QUEUE``, so the two lanes' backpressure is separate);
2. ``visibility="public"``, which selects the ``recipe:<id>`` ``source_id``
   namespace instead of ``custom:<id>`` (see ``scripts.shared.constants.recipe``);
3. no ``next_run_at`` push — this cron is the schedule.

The periodic deferrer passes a ``timestamp: int`` (Unix epoch seconds of the
scheduled tick); we accept and log it for traceability.
"""

from __future__ import annotations

import asyncio
import logging

import psycopg2
from procrastinate import RetryStrategy
from procrastinate import exceptions as procrastinate_exceptions

from scripts.shared import database as db
from scripts.shared.constants import PUBLIC_VISIBILITY, RECIPE_ATS

from ..config import settings
from ..services import custom_companies_service as ccs
from .fetch_custom_company import fetch_custom_company
from .procrastinate_app import RECIPE_FETCH_QUEUE, procrastinate_app

logger = logging.getLogger(__name__)


@procrastinate_app.periodic(
    cron="*/30 * * * *",
    periodic_id="recipe_fan_out",
)
@procrastinate_app.task(
    queue=RECIPE_FETCH_QUEUE,
    name="enqueue_recipe_fan_out",
    # Same rationale as the six vendor fan-outs: a transient DB blip must not
    # cost the whole 30-minute tick. Three exponential-wait attempts (2s, 4s, 8s).
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def enqueue_recipe_fan_out(timestamp: int) -> int:
    """Defer one ``fetch_custom_company`` per enabled, published recipe company.

    Returns the count of successful deferrals. A company whose prior tick's job is
    still queued is skipped via ``AlreadyEnqueued`` — the intended dedupe path, not
    an error.
    """
    # to_thread: psycopg2 has no async API and this periodic task shares the
    # FastAPI event loop with the worker. Mirrors every other fan-out.
    conn = await asyncio.to_thread(db.get_connection, settings.database_url)
    try:
        companies = await asyncio.to_thread(
            db.list_enabled_companies, conn, RECIPE_ATS
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
            "enqueue_recipe_fan_out tick %d: no enabled recipe companies", timestamp
        )
        return 0

    deferred = 0
    failed = 0
    for c in companies:
        company_id = c["id"]
        try:
            await fetch_custom_company.configure(
                # THE SAME per-company lock string the private lane uses, on
                # purpose. ``companies.id`` is a primary key, so ONE namespace
                # across both lanes means "never two concurrent harvests of one
                # board" holds even for a row that changes visibility while a job
                # of its own is still queued. Two lane-specific lock namespaces
                # would each be individually correct and jointly useless in exactly
                # that case. Owned by ``custom_companies_service`` so the removal
                # path (which cancels a queued harvest by name) cannot drift from
                # the deferrers.
                queueing_lock=ccs.harvest_queueing_lock(company_id),
                queue=RECIPE_FETCH_QUEUE,
            ).defer_async(
                company_id=company_id,
                # Selects the ``recipe:<id>`` source_id namespace. The leaf task
                # re-reads ``companies.visibility`` and REFUSES the run if the row
                # disagrees, so this argument cannot mis-namespace anything — it
                # only tells the task which answer to expect.
                visibility=PUBLIC_VISIBILITY,
            )
            deferred += 1
        except procrastinate_exceptions.AlreadyEnqueued:
            logger.info(
                "fetch_custom_company already enqueued for %s; skipping this tick",
                company_id,
            )
        except (procrastinate_exceptions.ConnectorException, psycopg2.Error):
            # Per-company isolation, same as the vendor fan-outs: a transient
            # connector blip on company N must not abort the loop and leave
            # alphabetically-later companies unprocessed for the whole window.
            #
            # Narrow on purpose — programmer errors (AttributeError, TypeError,
            # NameError) propagate so Procrastinate marks the task failed rather
            # than letting a deterministic bug masquerade as a transient blip.
            failed += 1
            logger.exception(
                "Failed to defer fetch_custom_company for recipe board %s; "
                "continuing with remaining companies",
                company_id,
            )

    logger.info(
        "enqueue_recipe_fan_out tick %d: deferred %d / %d companies (failed=%d)",
        timestamp, deferred, len(companies), failed,
    )
    return deferred
