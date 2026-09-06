#!/usr/bin/env python3
"""Terminate ``fetch_custom_company`` jobs wedged in ``doing`` for a deleted company.

WHY THIS EXISTS
---------------
On 2026-09-05 ``scripts/one_off/purge_custom_companies.py`` deleted a custom
company while that company's ``fetch_custom_company`` job was already ``doing``.
``pending_jobs.cancel_queued_jobs`` cancels only ``todo`` jobs -- deliberately,
because a job already picked up cannot be un-run -- so the in-flight harvest was
never stopped. It kept writing against the deleted company and re-inserted 2,057
job rows, which then had no ``companies`` row to make them private and were
served to anonymous callers.

Two code changes on this branch stop that from recurring:

* ``tasks/fetch_custom_company`` now re-checks the ``companies`` row immediately
  before its upsert and exits cleanly if it is gone, so a future post-purge
  harvest terminates itself and releases its slot and its queueing lock.
* ``services/database._ORPHANED_CUSTOM_PREDICATE`` hides any ``custom:`` row
  whose company row is absent, so an orphan is never publicly visible no matter
  what created it.

NEITHER OF THOSE HELPS A JOB THAT IS ALREADY WEDGED. The re-check runs inside
the task, and a task stuck in ``doing`` since before the deploy will never reach
it. That is what this script is for, and it is the only reason it exists.

THE ROW THIS WAS WRITTEN FOR
----------------------------
Production ``procrastinate_jobs`` id 880727: ``fetch_custom_company``,
``status='doing'``, ``queueing_lock='custom:u-okarwa3huc'``, started
2026-09-05 00:05:53 and still ``doing``. Its company row, its job rows
and its ``user_companies`` row are all gone.

FIRST, WHAT IT DOES **NOT** COST -- both claims were in an earlier draft of this
docstring and both are false, verified against production:

* **It does not hold a worker slot.** The row has exactly two events,
  ``deferred`` and ``started``, 0.3s apart, and nothing since -- across a
  container restart. Procrastinate's worker slots are IN-PROCESS; a ``doing`` row
  left behind by a restart is a stale marker, not a held slot. Nothing is running.
* **It does not block re-adding the company.** The index is
  ``CREATE UNIQUE INDEX procrastinate_jobs_queueing_lock_idx ON
  procrastinate_jobs USING btree (queueing_lock) WHERE (status = 'todo')`` --
  ``todo`` ONLY. A ``doing`` row does not stop a new ``todo`` job taking the same
  ``custom:u-okarwa3huc`` lock.

WHAT IT ACTUALLY COSTS, which is still worth cleaning up:

1. It makes ``doing`` counts lie. Any liveness or health view that reads
   non-terminal job status -- including a human reading the table during an
   incident -- sees a harvest that is not happening.
2. It can make ``tasks/reap_ownerless_companies._has_live_job()`` defer, because
   that helper deliberately counts ``doing`` as live so the sweep never purges a
   board with real work in flight. **Bounded, not forever:** the same helper also
   dates the job by ``max(procrastinate_events.at)`` and returns live only while
   that is inside ``_ORPHAN_GRACE_SECONDS`` (30 minutes). Row 880727's newest
   event is many hours old, far outside that grace, so the reaper is NOT
   currently blocked by it. The real window is the first 30 minutes after a
   wedge -- small, but it is the window in which the sweep would have acted.

WHAT IT DOES
------------
Moves matching rows from ``doing`` to the terminal ``failed`` status. ``failed``
rather than ``succeeded`` because the run genuinely did not complete, and
``failed`` is what the health tooling already understands; either way the row
leaves the non-terminal set, which is what stops it reading as live work.

It does NOT touch ``job_listings``, ``companies`` or anything else. It is not a
purge. If you want the data gone, that is ``purge_custom_companies.py``.

THE SAFETY MODEL
----------------
1. **Dry run by default.** Without ``--commit`` the real UPDATE runs, the real
   numbers are reported, and the transaction is rolled back.
2. **A scope flag is required.** ``--orphaned`` (every wedged job whose company
   row is gone) or ``--job-id`` (repeatable, exact ids). No bare invocation means
   anything.
3. **It refuses to touch a job whose company still exists.** That is the whole
   safety property: a ``doing`` row for a LIVE company is a harvest that is
   probably still running, and failing it would abandon real work. Under
   ``--job-id`` a live company is an ABORT, not a silent skip.
4. **It refuses to touch a job that is not ``fetch_custom_company``.** The
   ancient ``fetch_ashby_company`` / ``fetch_workday_company`` rows wedged since
   the 2026-08-29 worker wedge are a different problem with a different cause and
   are deliberately out of scope here.
5. **Local-only unless you say otherwise, out loud.** Without
   ``--yes-this-is-production`` this refuses any database
   ``dev_reset.assert_local_database`` / ``assert_local_connection`` cannot prove
   is loopback. Production additionally makes you restate the host and the job
   count, interactively or via ``--confirm-host`` / ``--confirm-jobs``.
6. **One transaction, REPEATABLE READ,** with before/after invariant snapshots.
   Same reasoning as the purge script: production runs a live worker, and under
   READ COMMITTED a job another process legitimately transitioned between the two
   snapshots would look exactly like this script having damaged something.

INVARIANTS CHECKED (any violation rolls back and exits 3)
---------------------------------------------------------
* No ``job_listings`` row is created, deleted or modified.
* No ``companies`` row is created or deleted.
* The number of ``procrastinate_jobs`` rows is unchanged -- this only ever
  UPDATEs a status, never inserts or deletes.
* Every row that changed status was one of the resolved targets, and each moved
  from ``doing`` to ``failed`` and nowhere else.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

import psycopg2
from psycopg2.extras import RealDictCursor

# Make ``src.backend.api...`` / ``scripts...`` importable when run from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.shared.constants import CUSTOM_SOURCE_PREFIX  # noqa: E402
from src.backend.api.services.dev_reset import (  # noqa: E402
    NonLocalDatabaseError,
    assert_local_connection,
    assert_local_database,
)

# The task this script is scoped to. Nothing else is ever touched.
_TASK_NAME = "fetch_custom_company"

# ``fetch_custom_company``'s queueing lock is ``custom:<company_id>`` -- see
# ``custom_companies_service.harvest_queueing_lock``. The company id is therefore
# the lock with the prefix stripped, which is how a wedged row is mapped back to
# the company whose existence decides whether it is safe to touch.
_LOCK_PREFIX = CUSTOM_SOURCE_PREFIX

EXIT_OK = 0
EXIT_ABORTED = 1
EXIT_REFUSED = 2
EXIT_INVARIANT = 3


class Refusal(RuntimeError):
    """A precondition failed. Nothing was changed."""


class InvariantViolation(RuntimeError):
    """The after-snapshot disagreed with the before-snapshot. Rolled back."""


@dataclass(frozen=True)
class Target:
    job_id: int
    queueing_lock: Optional[str]
    company_id: Optional[str]
    company_exists: bool
    started_at: Optional[str]


def _company_id_from_lock(lock: Optional[str]) -> Optional[str]:
    """``custom:u-abc`` -> ``u-abc``; anything else -> None."""
    if not lock or not lock.startswith(_LOCK_PREFIX):
        return None
    return lock[len(_LOCK_PREFIX):] or None


def _read_invariants(cursor: Any) -> dict[str, int]:
    """The counts that this script must not move."""
    cursor.execute(
        """
        SELECT
          (SELECT count(*) FROM job_listings)          AS job_listings,
          (SELECT count(*) FROM companies)             AS companies,
          (SELECT count(*) FROM procrastinate_jobs)    AS procrastinate_jobs,
          (SELECT count(*) FROM procrastinate_jobs
             WHERE status = 'doing')                   AS doing,
          (SELECT count(*) FROM procrastinate_jobs
             WHERE status = 'failed')                  AS failed
        """
    )
    return {k: int(v) for k, v in dict(cursor.fetchone()).items()}


def _resolve_targets(
    cursor: Any, explicit_job_ids: Optional[Sequence[int]]
) -> list[Target]:
    """Every candidate row, annotated with whether its company still exists.

    Under ``--orphaned`` the missing-company rows ARE the scope. Under
    ``--job-id`` the ids are the scope and a live company is a refusal, so both
    modes need the same annotation and it is computed once, here.
    """
    if explicit_job_ids is not None:
        cursor.execute(
            """
            SELECT j.id, j.task_name, j.status, j.queueing_lock,
                   (SELECT min(e.at) FROM procrastinate_events e
                     WHERE e.job_id = j.id AND e.type = 'started') AS started_at
            FROM procrastinate_jobs j
            WHERE j.id = ANY(%s)
            """,
            (list(explicit_job_ids),),
        )
        rows = [dict(r) for r in cursor.fetchall()]

        found = {int(r["id"]) for r in rows}
        missing = [i for i in explicit_job_ids if i not in found]
        if missing:
            raise Refusal(
                f"no procrastinate_jobs row for {missing}. Nothing was changed."
            )
        wrong_task = [
            f"{r['id']} (task_name={r['task_name']!r})"
            for r in rows
            if r["task_name"] != _TASK_NAME
        ]
        if wrong_task:
            raise Refusal(
                f"this script only ever touches {_TASK_NAME} jobs, and these are "
                "not: " + ", ".join(wrong_task) + ". Nothing was changed."
            )
        wrong_status = [
            f"{r['id']} (status={r['status']!r})"
            for r in rows
            if r["status"] != "doing"
        ]
        if wrong_status:
            raise Refusal(
                "only jobs wedged in 'doing' can be unwedged, and these are not: "
                + ", ".join(wrong_status)
                + ". Nothing was changed."
            )
    else:
        cursor.execute(
            """
            SELECT j.id, j.task_name, j.status, j.queueing_lock,
                   (SELECT min(e.at) FROM procrastinate_events e
                     WHERE e.job_id = j.id AND e.type = 'started') AS started_at
            FROM procrastinate_jobs j
            WHERE j.task_name = %s AND j.status = 'doing'
            ORDER BY j.id
            """,
            (_TASK_NAME,),
        )
        rows = [dict(r) for r in cursor.fetchall()]

    targets: list[Target] = []
    for row in rows:
        company_id = _company_id_from_lock(row["queueing_lock"])
        exists = False
        if company_id is not None:
            cursor.execute(
                "SELECT 1 FROM companies WHERE id = %s", (company_id,)
            )
            exists = cursor.fetchone() is not None
        targets.append(
            Target(
                job_id=int(row["id"]),
                queueing_lock=row["queueing_lock"],
                company_id=company_id,
                company_exists=exists,
                started_at=(
                    str(row["started_at"]) if row["started_at"] is not None else None
                ),
            )
        )

    if explicit_job_ids is not None:
        # A live company under --job-id ABORTS. It is not skipped: being asked to
        # fail a harvest that is probably still running is a sign the operator has
        # the wrong id, and guessing which they meant is not this script's job.
        alive = [
            f"{t.job_id} (company {t.company_id!r} still exists)"
            for t in targets
            if t.company_exists
        ]
        if alive:
            raise Refusal(
                "these jobs belong to companies that still exist, so they may be "
                "live harvests: " + ", ".join(alive) + ". Nothing was changed."
            )
        unparseable = [
            f"{t.job_id} (queueing_lock={t.queueing_lock!r})"
            for t in targets
            if t.company_id is None
        ]
        if unparseable:
            raise Refusal(
                "these jobs have no parseable custom: queueing lock, so this "
                "script cannot prove their company is gone: "
                + ", ".join(unparseable)
                + ". Nothing was changed."
            )
        return targets

    # --orphaned: keep only the provably-orphaned rows.
    return [t for t in targets if t.company_id is not None and not t.company_exists]


def _confirm_production(host: str, targets: list[Target], args) -> bool:
    """Make the operator restate the host and the job count before committing."""
    print()
    print("=" * 74)
    print("  THIS IS NOT A LOCAL DATABASE.")
    print(f"  host                 : {host}")
    print(f"  jobs to mark failed  : {len(targets)}")
    for target in targets:
        print(
            f"      {target.job_id}  lock={target.queueing_lock!r}  "
            f"company={target.company_id!r} (gone)  started={target.started_at}"
        )
    print("=" * 74)

    if args.confirm_host is not None or args.confirm_jobs is not None:
        if args.confirm_host is None or args.confirm_jobs is None:
            print(
                "REFUSED: --confirm-host and --confirm-jobs must be given together.",
                file=sys.stderr,
            )
            return False
        if args.confirm_host != host:
            print(
                f"REFUSED: --confirm-host {args.confirm_host!r} does not match the "
                f"host actually dialed ({host!r}).",
                file=sys.stderr,
            )
            return False
        if args.confirm_jobs != len(targets):
            print(
                f"REFUSED: --confirm-jobs {args.confirm_jobs} does not match the "
                f"{len(targets)} jobs this would mark failed.",
                file=sys.stderr,
            )
            return False
        print("non-interactive confirmation matched the measured host and counts.")
        return True

    if input(f"Type the host exactly ({host}): ").strip() != host:
        print("aborted: host did not match.")
        return False
    if input("Type the number of jobs to mark failed: ").strip() != str(len(targets)):
        print("aborted: job count did not match.")
        return False
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="unwedge_custom_fetch_jobs.py",
        description=(
            "Move fetch_custom_company jobs wedged in 'doing' for a deleted "
            "company to a terminal 'failed' status, releasing their worker slot "
            "and their queueing lock."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples
--------
  # See what is wedged locally. Writes nothing.
  python scripts/one_off/unwedge_custom_fetch_jobs.py --orphaned

  # The production row this was written for, dry run first (ALWAYS do this):
  python scripts/one_off/unwedge_custom_fetch_jobs.py \\
      --job-id 880727 --yes-this-is-production --dsn "$PROD_DATABASE_URL"

  # ...then the same command with --commit, plus the two confirmations it
  # measured in the dry run:
  python scripts/one_off/unwedge_custom_fetch_jobs.py \\
      --job-id 880727 --yes-this-is-production --dsn "$PROD_DATABASE_URL" \\
      --commit --confirm-host <host:port> --confirm-jobs 1

  # Every orphaned wedged harvest, not just one:
  python scripts/one_off/unwedge_custom_fetch_jobs.py --orphaned --commit
""",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--orphaned",
        action="store_true",
        help=(
            "Every fetch_custom_company job in 'doing' whose company row is gone."
        ),
    )
    scope.add_argument(
        "--job-id",
        dest="job_ids",
        type=int,
        action="append",
        metavar="ID",
        help="An exact procrastinate_jobs id. Repeatable.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write. Without it this is a dry run that rolls back.",
    )
    parser.add_argument(
        "--yes-this-is-production",
        dest="production",
        action="store_true",
        help=(
            "Allow a non-loopback database. You will still have to restate the "
            "host and the job count."
        ),
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Database DSN. Defaults to the backend's settings.database_url.",
    )
    parser.add_argument(
        "--confirm-host",
        default=None,
        help="Non-interactive production confirmation: the host:port, restated.",
    )
    parser.add_argument(
        "--confirm-jobs",
        type=int,
        default=None,
        help="Non-interactive production confirmation: the job count, restated.",
    )
    return parser


def _resolve_dsn(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    from src.backend.api.config import settings

    return str(settings.database_url)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    dsn = _resolve_dsn(args.dsn)

    if not args.production:
        # Deliberately before connecting: a DSN that cannot be proven loopback
        # should not even open a socket.
        try:
            assert_local_database(dsn)
        except NonLocalDatabaseError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            print(
                "\nIf you really do mean to run this against a remote database, "
                "pass --yes-this-is-production. That is a separate path around "
                "this guard, and it will make you retype the host and the count.",
                file=sys.stderr,
            )
            return EXIT_REFUSED

    conn = psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    try:
        # See the module docstring: this is what stops a live worker from making a
        # correct run look like a violated invariant.
        conn.set_session(isolation_level="REPEATABLE READ", readonly=False)
        if not args.production:
            try:
                assert_local_connection(conn)
            except NonLocalDatabaseError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return EXIT_REFUSED

        host = f"{conn.info.host or '?'}:{conn.info.port or '?'}"
        cursor = conn.cursor()

        targets = _resolve_targets(cursor, None if args.orphaned else args.job_ids)

        print(f"database : {host} / {conn.info.dbname}")
        print(f"scope    : {'--orphaned' if args.orphaned else '--job-id'}")
        print(f"mode     : {'COMMIT' if args.commit else 'DRY RUN (rolls back)'}")
        print(
            f"guard    : "
            f"{'PRODUCTION OPT-OUT' if args.production else 'localhost-only'}"
        )

        if not targets:
            print("targets  : none")
            print()
            print(f"no wedged {_TASK_NAME} jobs matched. Nothing to do.")
            return EXIT_OK

        print("targets  :")
        for target in targets:
            print(
                f"    job {target.job_id}  lock={target.queueing_lock!r}  "
                f"company={target.company_id!r} (row gone)  "
                f"started={target.started_at}"
            )
        print()

        if args.production and args.commit:
            if not _confirm_production(host, targets, args):
                return EXIT_ABORTED

        before = _read_invariants(cursor)

        job_ids = [t.job_id for t in targets]
        cursor.execute(
            """
            UPDATE procrastinate_jobs
            SET status = 'failed'
            WHERE id = ANY(%s) AND status = 'doing' AND task_name = %s
            RETURNING id
            """,
            (job_ids, _TASK_NAME),
        )
        updated = [int(r["id"]) for r in cursor.fetchall()]

        after = _read_invariants(cursor)

        # --- invariants ---------------------------------------------------
        for key in ("job_listings", "companies", "procrastinate_jobs"):
            if before[key] != after[key]:
                raise InvariantViolation(
                    f"{key} count moved from {before[key]} to {after[key]}; this "
                    "script must only ever UPDATE a status."
                )
        unexpected = set(updated) - set(job_ids)
        if unexpected:
            raise InvariantViolation(
                f"updated jobs that were not targets: {sorted(unexpected)}"
            )
        if after["doing"] != before["doing"] - len(updated):
            raise InvariantViolation(
                f"'doing' went {before['doing']} -> {after['doing']} while "
                f"{len(updated)} rows were failed; something else moved."
            )
        if after["failed"] != before["failed"] + len(updated):
            raise InvariantViolation(
                f"'failed' went {before['failed']} -> {after['failed']} while "
                f"{len(updated)} rows were failed; something else moved."
            )

        print(f"jobs marked failed : {len(updated)}  {updated}")
        print(
            f"procrastinate_jobs : doing {before['doing']} -> {after['doing']}, "
            f"failed {before['failed']} -> {after['failed']}"
        )
        print(
            f"untouched          : job_listings {after['job_listings']:,}, "
            f"companies {after['companies']}"
        )

        if args.commit:
            conn.commit()
            print()
            print("COMMITTED.")
        else:
            conn.rollback()
            print()
            print("DRY RUN -- rolled back. Re-run with --commit to apply.")
        return EXIT_OK

    except Refusal as exc:
        conn.rollback()
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except InvariantViolation as exc:
        conn.rollback()
        print(f"INVARIANT VIOLATED: {exc}", file=sys.stderr)
        print("Rolled back. Nothing was changed.", file=sys.stderr)
        return EXIT_INVARIANT
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
