"""Periodic sweep: nothing may sit at ``health_state='discovering'`` forever — E7.

THE BUG. The provisional row the 202 add creates says "Setting up… / Opening the page"
until :mod:`api.tasks.discover_custom_company` flips it to tracked or refused. That task
is ``retry=1`` on purpose (it spends money), so there is no attempt after the first, and
three ordinary things leave the row with nothing left to move it:

* the worker was **SIGKILLed / OOM-killed** between its first progress write and the
  persist — a hard kill, not an exception, so no handler ever runs;
* the ``custom_company_discovery_enabled`` flag was flipped **off** after the job was
  queued, and the task's defence-in-depth gate returns before touching the row;
* the queue was **never drained** — a dead interactive worker, which is exactly what
  happened on 2026-08-26 and left two of the owner's rows spinning indefinitely.

The row is not merely cosmetic: the My-Companies list polls FASTER while any row is
``discovering`` and keeps doing so for as long as the tab is open, so a wedged row is a
permanent spinner plus a permanent poll.

HOW A WEDGED ROW IS RECOGNISED — two conditions, both required, both chosen so that
"slow" can never be mistaken for "dead":

1. **No progress for :data:`_STALL_GRACE_SECONDS`.** ``provider_config -> 'discovery' ->
   'updated_at'`` is stamped by the RUNNING task on every step it publishes, so its age
   is the run's own liveness signal. The grace is 30 minutes against a task whose entire
   wall-clock budget is 240 seconds (``discover_custom_company._TASK_TIMEOUT_S``) — 7.5×
   the longest a single attempt can legally live, and there is no second attempt. A row
   whose blob has no usable timestamp falls back to ``companies.created_at``, which is
   older still, never newer.
2. **No Procrastinate job for this board that has been touched inside that same
   window.** ``updated_at`` alone is not enough, because the progress writer swallows
   its own connection failures by design — a live run whose progress writes are all
   failing is silent but genuinely working. So we ask the broker: is there an unfinished
   (``todo``/``doing``) job under this board's queueing lock with an event newer than
   the grace? A job in flight has a ``started`` event minutes old; a SIGKILLed one has
   the same event from hours ago. **An unfinished job whose age we cannot read at all
   (no event rows) counts as ALIVE** — a wedge that survives another half hour is the
   status quo, and reaping a running discovery is the one outcome that is not.

WHAT IT LANDS ON — the ORDINARY refusal, byte-identical to the discovery timeout path:
``record_discovery_refusal`` with ``progress=None``. No new health state, no new step
status, no frontend change. The row flips to ``health_state='refused'``, which the list
renders as "We couldn't read {board}'s board", and because no progress blob is written
the LAST LIVE SNAPSHOT survives — the checklist keeps showing how far the run got, the
leftover ``active`` rung draws as a plain ○ under a terminal outcome, and the panel says
"This setup stopped before it could finish." above the one action that changes the
answer. That sentence already exists and already means exactly this; inventing a
``stalled`` state would have been a second word for it. What distinguishes a sweep from
a genuine refusal is the ``company_add_attempts`` audit row, whose ``error_detail`` says
so in full — the operator-facing half, on the path that already carries operator-facing
detail.

WHERE IT RUNS — the **bulk** lane (queue ``custom_ats_fetch``, beside the ``*/15`` claim
tick), and that is the whole point rather than an accident. A dead interactive worker is
one of the three causes above; a reconciler riding the interactive lane would be queued
behind the very wedge it exists to clear, and would only ever run when it was not
needed. It shares the claim tick's queue rather than opening a new one because it is the
same family of work (custom-company scheduling), needs no reservation of its own, and a
new queue is a new thing to keep in sync with ``api.main``'s lane lists.

NEVER-WRONG-CLOSE: this task does not touch ``job_listings``, ``job_freshness`` or
``consecutive_misses``, and it cannot. A ``discovering`` row has never had a script row,
so nothing has ever harvested it and its ``custom:<id>`` namespace is empty; the only
writes here are one ``companies`` UPDATE, one append-only audit row, and the cancel of a
queued job.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import psycopg2
from procrastinate import RetryStrategy
from psycopg2.extensions import connection as Connection

from scripts.shared import database as db

from ..config import settings
from ..services import custom_companies_service as ccs
from ..services.pending_jobs import cancel_queued_jobs
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# How long a 'discovering' row may go without a progress write before it is treated as
# abandoned. 30 minutes against a 240-second task budget: deliberately, absurdly
# generous, because the cost of waiting is a spinner and the cost of being wrong is
# refusing a board we were in the middle of successfully reading.
_STALL_GRACE_SECONDS = 30 * 60

# One sweep never handles more than this many rows. 'discovering' is a transient state
# and a healthy database holds ~zero of them; a bounded read is the house rule anyway,
# and the next tick picks up any remainder ten minutes later.
_SWEEP_LIMIT = 50

_STALL_REASON = (
    "setup stopped before it could finish — no progress for {minutes} minutes and no "
    "discovery run was still working on it"
)

# Every 10 minutes. With the 30-minute grace above, a wedged row is user-visibly stuck
# for at most ~40 minutes; ticking faster would only shorten the last ten of those.
_SWEEP_CRON = "*/10 * * * *"


def _parse_updated_at(provider_config: Any) -> Optional[datetime]:
    """The discovery blob's ``updated_at`` as an aware datetime, or None.

    TOTAL, like :func:`api.services.discovery.progress.read_progress` next door: the
    input is a JSONB column that may hold an ATS provider config, a blob from an older
    deployment, or something an operator typed. Anything unreadable returns ``None`` and
    the caller falls back to ``created_at`` — which is always OLDER, so a malformed blob
    makes the row MORE eligible for reaping, never less. That direction is safe because
    condition 2 (a live job) is what actually protects a running run.

    A naive timestamp is rejected rather than assumed UTC: comparing it to an aware
    ``now`` would raise, and guessing its zone could invent up to a day of fake age.
    """
    if not isinstance(provider_config, dict):
        return None
    discovery = provider_config.get("discovery")
    if not isinstance(discovery, dict):
        return None
    raw = discovery.get("updated_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _find_discovering_rows(conn: Connection, limit: int) -> list[dict[str, Any]]:
    """Every ``discovering`` private company with its owner, oldest first.

    ``now()`` rides along so every age in this sweep is measured against the DATABASE's
    clock — the same clock that stamped ``created_at`` — rather than against the
    worker process's. The two are usually the same machine and never far apart, but a
    reaper is the wrong place to find out.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT c.id, c.display_name, c.board_token, c.created_at, c.provider_config,
               uc.user_id, now() AS db_now
        FROM companies c
        JOIN user_companies uc ON uc.company_id = c.id
        WHERE c.visibility = 'user'
          AND c.health_state = 'discovering'
        ORDER BY c.created_at
        LIMIT %s
        """,
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _has_live_discovery_job(
    conn: Connection, *, queueing_lock: str, db_now: datetime, grace: timedelta
) -> bool:
    """Whether the broker still holds a discovery job for this board that is ALIVE.

    "Alive" is deliberately generous. An unfinished (``todo``/``doing``) job counts as
    alive when its most recent Procrastinate event is inside ``grace`` — a run that
    started four minutes ago, a job queued four minutes ago behind a busy lane — AND
    ALSO when the job exists but has no event rows to date it. Only an unfinished job
    whose newest event is older than the grace is treated as dead, which is the
    SIGKILL/undrained-queue case and the one we came for.

    No Procrastinate schema at all means no jobs, which means no live job — that is a
    ``False``, not an error, so this works in a database a worker has never booted
    against.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT to_regclass('procrastinate_jobs') AS jobs, "
        "to_regclass('procrastinate_events') AS events"
    )
    tables = cursor.fetchone()
    if not tables or tables["jobs"] is None or tables["events"] is None:
        return False

    cursor.execute(
        """
        SELECT count(*) AS n, max(e.at) AS last_event
        FROM procrastinate_jobs j
        LEFT JOIN procrastinate_events e ON e.job_id = j.id
        WHERE j.task_name = 'discover_custom_company'
          AND j.queueing_lock = %s
          AND j.status IN ('todo', 'doing', 'aborting')
        """,
        (queueing_lock,),
    )
    row = cursor.fetchone()
    if not row or int(row["n"] or 0) == 0:
        return False
    last_event = row["last_event"]
    if last_event is None:
        logger.warning(
            "reconcile_discovering: an unfinished discovery job under %s has no events "
            "to date it; treating it as running and leaving the row alone",
            queueing_lock,
        )
        return True
    return bool(db_now - last_event < grace)


def _reap(conn: Connection, row: dict[str, Any], *, stalled_for: timedelta) -> bool:
    """Refuse ONE wedged row and cancel whatever is still queued for it. Returns done.

    The refusal itself is ``record_discovery_refusal`` with ``progress=None`` — the
    exact call the discovery TIMEOUT path makes, so a swept row and a timed-out row are
    the same user-visible thing (see the module docstring). ``submitted_url`` is the
    normalized board URL because that is what the row still carries; the original
    pasted URL lives in the ``discovery_pending`` attempt this sweep's row will sit
    beside in the same audit.
    """
    minutes = int(stalled_for.total_seconds() // 60)
    company_id = ccs.record_discovery_refusal(
        conn,
        user_id=str(row["user_id"]),
        submitted_url=str(row["board_token"]),
        normalized_url=str(row["board_token"]),
        display_name=str(row["display_name"]),
        reason=_STALL_REASON.format(minutes=minutes),
        progress=None,
    )
    if company_id is None:
        # Removed between this sweep's SELECT and its write. Nothing to do and nothing
        # wrong — the user got there first.
        return False

    # Cancel the corpse. Without this a worker that comes back an hour later would run
    # the job we just declared dead, and ``add_discovered_company`` would promote the
    # refused row straight back to tracked — a board flipping from "we couldn't read
    # it" to "tracking" with no user action in between.
    cursor = conn.cursor()
    try:
        cancel_queued_jobs(
            cursor,
            [ccs.discovery_queueing_lock(str(row["user_id"]), str(row["board_token"]))],
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        # The row IS refused (that committed above) and the user is unstuck, which is
        # the point of the sweep. A surviving queued job is caught by the placeholder
        # refusal in ``add_discovered_company`` if it ever runs.
        logger.warning(
            "reconcile_discovering: refused %s but could not cancel its queued job",
            company_id, exc_info=True,
        )
    logger.warning(
        "reconcile_discovering: %s (%s) sat at 'discovering' for %d minutes with no "
        "live discovery job; refused it so the user can retry",
        company_id, row["board_token"], minutes,
    )
    return True


def sweep_stalled_discoveries(conn: Connection) -> int:
    """Refuse every wedged ``discovering`` row visible on this connection. Returns count.

    Split out of the task body so the recognition rule is testable against a plain
    psycopg2 connection, with no broker and no worker — the same shape as
    ``claim_custom_companies``' helpers.
    """
    grace = timedelta(seconds=_STALL_GRACE_SECONDS)
    rows = _find_discovering_rows(conn, _SWEEP_LIMIT)
    reaped = 0
    for row in rows:
        db_now = row["db_now"]
        stamp = _parse_updated_at(row["provider_config"]) or row["created_at"]
        if stamp is None:
            # ``created_at`` is NOT NULL, so this is unreachable in practice; treating
            # it as "not stale" keeps the unreachable case on the safe side.
            continue
        stalled_for = db_now - stamp
        if stalled_for < grace:
            continue
        lock = ccs.discovery_queueing_lock(str(row["user_id"]), str(row["board_token"]))
        if _has_live_discovery_job(
            conn, queueing_lock=lock, db_now=db_now, grace=grace
        ):
            logger.info(
                "reconcile_discovering: %s has published no progress for %s but its "
                "discovery job is still live; leaving it alone",
                row["id"], stalled_for,
            )
            continue
        if _reap(conn, row, stalled_for=stalled_for):
            reaped += 1
    return reaped


@procrastinate_app.periodic(
    cron=_SWEEP_CRON, periodic_id="reconcile_discovering_companies"
)
@procrastinate_app.task(
    # BULK lane on purpose — see the module docstring. A dead interactive worker is one
    # of the things this sweep exists to recover from, so it must not ride that lane.
    queue="custom_ats_fetch",
    name="reconcile_discovering_companies",
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def reconcile_discovering_companies(timestamp: int) -> int:
    """Sweep abandoned ``discovering`` rows onto ``refused``. Returns how many."""
    conn = await asyncio.to_thread(db.get_connection, settings.database_url)
    try:
        reaped = await asyncio.to_thread(sweep_stalled_discoveries, conn)
    finally:
        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error(
                "Error closing reconcile_discovering connection (potential leak)",
                exc_info=True,
            )
    if reaped:
        logger.warning(
            "reconcile_discovering tick %d: refused %d abandoned 'discovering' row(s)",
            timestamp, reaped,
        )
    return reaped


__all__ = [
    "reconcile_discovering_companies",
    "sweep_stalled_discoveries",
    "_STALL_GRACE_SECONDS",
]