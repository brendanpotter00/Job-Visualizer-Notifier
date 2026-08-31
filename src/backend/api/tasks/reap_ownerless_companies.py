"""Periodic sweep: a private company with NO OWNER cannot survive — E7.

THE STATE. Every path that creates a ``visibility='user'`` company writes its
``user_companies`` row in the SAME transaction (``add_custom_company``,
``add_discovering_placeholder``), and ``remove_owned_company`` purges the company
outright once the last owner goes. So "private company, zero owners" is unreachable
by design — and the dev database held one anyway: ``u-6hkpc6fh0z`` ("Amazon (live
check)"), a ``companies`` row with a recipe, six harvests and 12,437 job rows, and
zero owners. It leaked from a test path that deleted the ownership row without the
purge that is supposed to follow it.

WHY THAT IS NOT COSMETIC. The claim tick selects on
``visibility='user' AND enabled AND next_run_at <= now()`` and does NOT join
``user_companies`` (``claim_custom_companies._CLAIM_SQL``), so an ownerless row keeps
harvesting a stranger's board on its 24-hour cadence forever, keeps feeding rows into
the enrichment queue, and is counted by every naive ``visibility='user'`` query —
while being invisible in every UI (the list JOINs ``user_companies``) and undeletable
through the API (``DELETE /api/users/companies/{id}`` proves ownership first, so it
404s). Nothing but this sweep can end it.

WHY NOT A DATABASE CONSTRAINT — the honest answer, because "at least one owner" IS
expressible in Postgres and the reason to reject it is not that it cannot be written:

* A ``CHECK`` cannot subquery and a foreign key cannot express "at least one" in the
  one-to-many direction, so the only shape that works is a ``CREATE CONSTRAINT
  TRIGGER … DEFERRABLE INITIALLY DEFERRED`` firing at COMMIT — late enough to see
  both inserts of the one transaction the add paths use. That much is real.
* It would have to guard BOTH SIDES to be worth anything. The row we actually have
  was produced by a bare ``DELETE FROM user_companies``, not by an insert, so an
  insert-side trigger alone would not have caught it.
* And the delete-side guard is where it breaks: ``user_companies.user_id`` is
  ``ON DELETE CASCADE`` to ``users``, so deleting an account would start raising
  whenever that account still owned a private board — turning account deletion into
  an error instead of a cleanup.
* ``user_companies.company_id`` is deliberately FK-free (house style; see
  :class:`api.db_models.UserCompany`) because ``companies`` is truncated freely in
  tests. A constraint trigger reintroduces exactly that coupling at a level tests
  cannot opt out of — and the tests that would break first are the ones that seed an
  ownerless row ON PURPOSE to prove the detector notices it
  (``test_custom_company_integrity.py``, ``test_admin_custom_companies.py``). Making
  the state unrepresentable makes its detector untestable.
* A trigger is also invisible: nothing in the Python source would say the invariant
  exists, and a violation surfaces as a raw ``psycopg2`` error at COMMIT on an API
  path that has no idea what it means.

So the guarantee is not "the state cannot be written" but "the state cannot PERSIST":
it is corrected within one tick, by a delete path that already exists, and the
``ownerless`` detector stays as the tripwire that says the correction stopped working.

⚠️ WHAT MAKES THIS SAFE — three conditions, ALL required, because getting it wrong
deletes a board somebody is in the middle of adding, along with its jobs:

1. **No owner**, by the same ``NOT EXISTS`` the integrity report uses, so the sweep
   and the report can never disagree about what an orphan is.
2. **Older than :data:`_ORPHAN_GRACE_SECONDS`** measured on the DATABASE's clock
   against ``companies.created_at``. The two inserts of every add path are ONE
   transaction, so no reader ever observes a committed company without its owner —
   the mid-add window this is protecting against does not exist today. The floor is
   there so it stays safe if a future path ever splits that transaction, and 30
   minutes is the same number ``reconcile_discovering`` chose for the same reason:
   7.5× the entire 240-second discovery budget, against a cost of being wrong that is
   somebody's board.
3. **No live Procrastinate job for this board.** Same reasoning as
   ``reconcile_discovering._has_live_discovery_job``, and the same generosity: an
   unfinished (``todo``/``doing``/``aborting``) job counts as ALIVE when its newest
   event is inside the grace, AND ALSO when it has no event rows to date it at all.
   Only a job whose newest event is older than the grace is treated as dead.

A ``discovering`` row is NOT exempt, and that is deliberate. ``reconcile_discovering``
JOINs ``user_companies``, so an ownerless row wedged at ``discovering`` is invisible to
it and would spin forever with nobody able to see it, retry it or delete it. Conditions
2 and 3 are what make purging it safe: the 30-minute floor is 7.5x the entire discovery
budget, and a run genuinely in flight still holds a live job.

NEVER-WRONG-CLOSE. This task closes nothing. :func:`ccs.purge_custom_company` is
DELETEs end to end — no ``status='CLOSED'``, no ``closed_on``, no
``consecutive_misses``, no ``job_freshness`` write of any kind (it cascades). A purge
removes a board's history; a close decides a job went away, and those must never be
the same operation.

WHERE IT RUNS — the BULK lane (queue ``custom_ats_fetch``), beside the claim tick and
``reconcile_discovering``, for the same reasons: it is custom-company scheduling work,
it needs no reservation, and it must not sit behind the interactive lane it may have
to clean up after.

HOW OFTEN — hourly, deliberately slower than ``reconcile_discovering``'s ``*/10``.
Nobody is staring at an orphan (it is invisible by construction), the cost of another
hour is at most one skipped harvest cycle, and this is the most destructive periodic
in the codebase: it should tick as rarely as it can while still bounding the damage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import psycopg2
from procrastinate import RetryStrategy
from psycopg2.extensions import connection as Connection

from scripts.shared import database as db

from ..config import settings
from ..services import custom_companies_service as ccs
from .procrastinate_app import procrastinate_app

logger = logging.getLogger(__name__)

# How old a private company must be before an ownerless one may be purged. See
# condition 2 in the module docstring: the mid-add window it guards is not
# observable today, and this floor is what keeps that true if it ever becomes so.
_ORPHAN_GRACE_SECONDS = 30 * 60

# One sweep never purges more than this many boards. 'ownerless' is supposed to be
# an empty set; a bounded read is the house rule anyway, and a bounded DELETE means
# a bug in the recognition rule cannot take the whole custom fleet in one tick.
_SWEEP_LIMIT = 20

# Hourly. See the module docstring.
_SWEEP_CRON = "17 * * * *"

# The recognition rule, condition 1 + condition 2. ``NOT EXISTS`` rather than a LEFT
# JOIN so it stops at the first ownership row, and it is the SAME predicate
# ``custom_company_integrity._ORPHAN_WHERE`` reports on — the sweep must never be able
# to purge something the report would not have named.
#
# ``now()`` rides along so the age is measured against the clock that stamped
# ``created_at``, never against the worker process's.
_FIND_ORPHANS_SQL = """
    SELECT c.id, c.display_name, c.board_token, c.created_at, c.enabled,
           now() AS db_now
    FROM companies c
    WHERE c.visibility = 'user'
      AND c.created_at < now() - make_interval(secs => %s)
      AND NOT EXISTS (
            SELECT 1 FROM user_companies uc WHERE uc.company_id = c.id
          )
    ORDER BY c.created_at
    LIMIT %s
"""


def _has_live_job(
    conn: Connection, *, company_id: str, board_token: Any, db_now: datetime,
    grace: timedelta,
) -> bool:
    """Whether the broker still holds work for this board that is ALIVE.

    Matches two lock shapes, because a board's work is queued under two:
    ``custom:{company_id}`` for a harvest (exact), and ``discover:{user}:{url}`` for
    a discovery — whose user half is unknowable for a row with no owner, so it is
    matched on the URL suffix instead. ``right()``, not ``LIKE``, on purpose: a board
    token is a URL and may legitimately contain ``%`` (percent-encoding) or ``_``,
    which ``LIKE`` would read as wildcards.

    No Procrastinate schema at all means no jobs, which means no live job — a
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

    token = str(board_token) if board_token else None
    cursor.execute(
        """
        SELECT count(*) AS n, max(e.at) AS last_event
        FROM procrastinate_jobs j
        LEFT JOIN procrastinate_events e ON e.job_id = j.id
        WHERE j.status IN ('todo', 'doing', 'aborting')
          AND (
                j.queueing_lock = %(harvest_lock)s
                OR (
                    %(token)s IS NOT NULL
                    AND j.queueing_lock LIKE 'discover:%%'
                    AND right(j.queueing_lock, length(%(token)s) + 1)
                        = ':' || %(token)s
                )
              )
        """,
        {
            "harvest_lock": ccs.harvest_queueing_lock(company_id),
            "token": token,
        },
    )
    row = cursor.fetchone()
    if not row or int(row["n"] or 0) == 0:
        return False
    last_event = row["last_event"]
    if last_event is None:
        logger.warning(
            "reap_ownerless: an unfinished job for %s has no events to date it; "
            "treating it as running and leaving the board alone", company_id,
        )
        return True
    return bool(db_now - last_event < grace)


def _purge(conn: Connection, row: dict[str, Any]) -> bool:
    """Purge ONE ownerless board. Returns whether the ``companies`` row went.

    ``FOR UPDATE`` re-reads the row inside this transaction and pins it, so a
    concurrent claim tick cannot flip it to running between the sweep's SELECT and
    this DELETE — and the re-read of ``user_companies`` under that lock is what makes
    the whole sweep safe against a second user (or a re-add) claiming the board in the
    window since the scan. A board that gained an owner is left completely alone.
    """
    company_id = str(row["id"])
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT visibility, board_token FROM companies WHERE id = %s FOR UPDATE",
            (company_id,),
        )
        locked = cursor.fetchone()
        if locked is None or locked["visibility"] != "user":
            # Purged, or re-pointed at a public board, since the scan. Neither is
            # ours to act on — a public board's data must never go through here.
            conn.rollback()
            return False
        cursor.execute(
            "SELECT count(*) AS n FROM user_companies WHERE company_id = %s",
            (company_id,),
        )
        owners = cursor.fetchone()
        if owners and int(owners["n"]) > 0:
            logger.info(
                "reap_ownerless: %s gained an owner since the scan; leaving it alone",
                company_id,
            )
            conn.rollback()
            return False

        purged = ccs.purge_custom_company(
            cursor,
            company_id=company_id,
            board_token=(
                str(locked["board_token"]) if locked["board_token"] else None
            ),
            # No owner, so no ``discover:{user}:{url}`` lock can be reconstructed.
            owner_user_id=None,
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise

    if not purged:
        logger.warning(
            "reap_ownerless: %s is ownerless but not an id we could have minted; "
            "left in place", company_id,
        )
        return False
    logger.warning(
        "reap_ownerless: purged ownerless private company %s (%r, board %r) — it had "
        "no user_companies row and was created %s",
        company_id, row["display_name"], row["board_token"], row["created_at"],
    )
    return True


def sweep_ownerless_companies(conn: Connection) -> int:
    """Purge every ownerless private company visible on this connection. Returns count.

    Split out of the task body so the recognition rule is testable against a plain
    psycopg2 connection, with no broker and no worker — the same shape as
    ``reconcile_discovering.sweep_stalled_discoveries``.
    """
    grace = timedelta(seconds=_ORPHAN_GRACE_SECONDS)
    cursor = conn.cursor()
    cursor.execute(_FIND_ORPHANS_SQL, (_ORPHAN_GRACE_SECONDS, _SWEEP_LIMIT))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.rollback()

    purged = 0
    for row in rows:
        if _has_live_job(
            conn,
            company_id=str(row["id"]),
            board_token=row["board_token"],
            db_now=row["db_now"],
            grace=grace,
        ):
            logger.info(
                "reap_ownerless: %s has no owner but still has live queued work; "
                "leaving it alone", row["id"],
            )
            continue
        if _purge(conn, row):
            purged += 1
    return purged


@procrastinate_app.periodic(
    cron=_SWEEP_CRON, periodic_id="reap_ownerless_companies"
)
@procrastinate_app.task(
    # BULK lane on purpose — see the module docstring.
    queue="custom_ats_fetch",
    name="reap_ownerless_companies",
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def reap_ownerless_companies(timestamp: int) -> int:
    """Purge private companies that have lost every owner. Returns how many."""
    conn = await asyncio.to_thread(db.get_connection, settings.database_url)
    try:
        purged = await asyncio.to_thread(sweep_ownerless_companies, conn)
    finally:
        try:
            await asyncio.to_thread(conn.close)
        except Exception:
            logger.error(
                "Error closing reap_ownerless connection (potential leak)",
                exc_info=True,
            )
    if purged:
        logger.warning(
            "reap_ownerless tick %d: purged %d ownerless private company/companies",
            timestamp, purged,
        )
    return purged


__all__ = [
    "reap_ownerless_companies",
    "sweep_ownerless_companies",
    "_ORPHAN_GRACE_SECONDS",
]
