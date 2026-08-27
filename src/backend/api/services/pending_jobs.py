"""Cancel Procrastinate jobs that are queued for work we have decided not to do.

WHY THIS EXISTS. ``remove_owned_company`` used to delete a company and leave its
already-queued ``discover_custom_company`` job on the broker. That job carries the
user id and the URL, not the company id, so when it finally ran it looked up "does
this user own a company for this URL?", found nothing, and **INSERTed a fresh one** —
a board the user had deleted came back, tracked, with jobs. Deleting the work is the
half of the fix that costs nothing: a browser session and a Claude call are not spent,
and the reserved interactive slot is not held, for a board that no longer exists.

It is only HALF the fix, deliberately. A job that has already been picked up
(``status='doing'``) cannot be un-run, so ``add_discovered_company`` /
``record_discovery_refusal`` refuse to create a row whose placeholder is gone. This
module removes the cause; that refusal is the guarantee.

WHY A PLAIN UPDATE and not ``procrastinate_cancel_job(id, false, false)``: that
function's whole body, for these arguments, is this one statement, and calling it
would make every caller depend on a schema FUNCTION resolving on the search_path in
addition to the table. The ``AFTER UPDATE OF status`` trigger Procrastinate installs
fires either way, so the ``cancelled`` event is recorded exactly as the function's
callers would record it.

WHY ``status = 'todo'`` IS THE WHOLE PREDICATE. It is also the concurrency interlock:
``procrastinate_fetch_job`` flips ``todo -> doing`` under a row lock with the same
predicate, so either we cancel first (and the fetch, which selects on ``todo``, skips
the row) or the fetch wins (and our UPDATE matches nothing). There is no ordering in
which a running job is cancelled out from under its worker.

CONNECTION CONTRACT: takes a CURSOR, never a connection, and never commits. The
caller that matters — ``remove_owned_company`` — does the delete and this cancel in
ONE transaction, and a cancel that survived a rolled-back removal would delete work
for a company that still exists.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

logger = logging.getLogger(__name__)


def _table_exists(cursor: Any, name: str) -> bool:
    """True when ``to_regclass(name)`` resolves on the current search_path.

    Not hardcoded to ``public``: tests run inside a per-worker schema, and
    ``procrastinate_jobs`` is absent entirely until a worker has booted against the
    database at least once. An absent table means there are no queued jobs to cancel,
    which is a no-op — never an error that fails the removal it is part of.
    """
    cursor.execute("SELECT to_regclass(%s) AS oid", (name,))
    row = cursor.fetchone()
    if row is None:
        return False
    return (row["oid"] if isinstance(row, dict) else row[0]) is not None


def cancel_queued_jobs(cursor: Any, locks: Sequence[str]) -> int:
    """Cancel every still-``todo`` job whose ``queueing_lock`` is one of ``locks``.

    Returns how many jobs were cancelled. ``locks`` are Procrastinate queueing locks —
    ``discover:{user_id}:{normalized_url}`` for a discovery run and
    ``custom:{company_id}`` for a harvest — because that is the only key on
    ``procrastinate_jobs`` that names the company's work without parsing task args.
    """
    if not locks:
        return 0
    if not _table_exists(cursor, "procrastinate_jobs"):
        return 0
    cursor.execute(
        """
        UPDATE procrastinate_jobs
        SET status = 'cancelled'
        WHERE queueing_lock = ANY(%s)
          AND status = 'todo'
        """,
        (list(locks),),
    )
    cancelled = int(cursor.rowcount or 0)
    if cancelled:
        logger.info(
            "cancelled %d queued Procrastinate job(s) for locks %s",
            cancelled, list(locks),
        )
    return cancelled
