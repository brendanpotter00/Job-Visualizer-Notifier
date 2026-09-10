#!/usr/bin/env python3
"""Purge user-added (``visibility='user'``) companies and everything they own.

WHY THIS EXISTS, AND WHY IT IS NOT ``dev_reset_custom_companies.py``
-------------------------------------------------------------------
``scripts/one_off/dev_reset_custom_companies.py`` is the developer's reset. It
refuses anything that is not a loopback database, and it scopes by USER: its
narrowest setting deletes *every* custom company one user owns. Both of those are
correct for the thing it is for.

Neither is what a demo reset needs. The owner has five custom boards in production
and wants exactly ONE of them gone -- the other four were verified working and must
survive untouched. So this script is scoped by COMPANY ID, and it has an explicit,
loudly-named way to run somewhere that is not localhost.

THE PRIMARY, EXPECTED USE IS ONE COMPANY::

    python scripts/one_off/purge_custom_companies.py --company-id u-746utmpsko

``--all`` exists for the rare "clear every user-added board" case. It is not the
default and there is no bare invocation that means it: a scope flag is REQUIRED.

WHAT IT DELETES
---------------
For each target company, in ``purge_custom_company``'s single ordering (job_locations
-> job_tags -> job_enrichment -> job_listings -> company_harvests / scrape_runs /
company_scripts -> companies, with the queued Procrastinate work cancelled first, and
``job_freshness`` cascading off ``job_listings``), plus the two rows that ordering
deliberately leaves to its caller:

* ``user_companies`` -- the ownership link, scoped ``company_id = ANY(targets)``;
* ``company_add_attempts`` -- the add audit, scoped the same way. Cleared because it
  is what ``services/add_quota`` counts the monthly cap off: leaving it would remove
  the board but not the budget to add it again, and the demo would hit the cap
  instead of the flow being filmed.

Those two DELETEs are the only statements here that are not ``purge_custom_company``.
They are the same two ``dev_reset.reset_custom_companies`` runs, re-scoped from "this
user" to "these companies" -- which is the whole point of this script, and is also
strictly narrower. That matters: ``company_add_attempts.company_id`` can name a
PUBLISHED company (production holds one such row, for ``togetherai``), so a
user-scoped delete would take an audit row for a board this script must never touch.
The company-scoped predicate cannot, because every target is proven
``visibility='user'`` before anything runs.

THE SAFETY MODEL
----------------
1. **Dry run by default.** No ``--commit``, no writes -- the real statements run and
   the real numbers are reported, then the transaction is rolled back. (A dry run
   that counted through some other query would be reporting on a different statement
   than the one that deletes.)
2. **A scope flag is required.** ``--company-id`` (repeatable) or ``--all``. There is
   no bare invocation, and no default, that means "delete everything".
3. **Every target is proven ``visibility='user'`` first.** An id that does not exist,
   or that resolves to a published company, ABORTS before any delete -- it is not
   silently skipped.
4. **Local-only unless you say otherwise, out loud.** Without
   ``--yes-this-is-production`` this refuses any database that
   ``dev_reset.assert_local_database`` / ``assert_local_connection`` cannot prove is
   loopback. Those two functions are imported and used UNCHANGED; this script does
   not weaken them for anyone. ``--yes-this-is-production`` is a separate opt-out
   path around them, not a hole in them.
5. **Production needs more than a flag.** With ``--yes-this-is-production --commit``
   the script prints the host it actually dialed and the exact row counts, then makes
   you type the host back and type the number of job rows that will be deleted.
   ``--yes`` does NOT skip that. One mistyped flag cannot delete anything.
6. **Invariants, checked before AND after, inside the transaction.** Published
   companies, published jobs, and -- first among equals for the demo -- the OTHER
   custom companies and their jobs must all be byte-identical: not just the same
   count, the same ``md5`` of the same ordered key set. Any drift raises, which rolls
   back.
7. **One transaction, at REPEATABLE READ.** All-or-nothing. The isolation level is
   load-bearing rather than tidy: production runs a live harvest worker, and under
   READ COMMITTED a published job inserted by that worker *between* the before and
   after snapshots would look exactly like this script having damaged something, and
   would abort a correct run. REPEATABLE READ pins one snapshot for the whole
   transaction, so the comparison can only reflect what THIS transaction did -- a
   transaction always sees its own writes.

EXIT CODES: 0 done, 1 aborted by the operator, 2 refused by a guard, 3 an invariant
was violated and everything was rolled back.
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

from scripts.shared.constants import CUSTOM_SOURCE_PREFIX, custom  # noqa: E402
from src.backend.api.services.custom_companies_service import (  # noqa: E402
    purge_custom_company,
)
from src.backend.api.services.dev_reset import (  # noqa: E402
    NonLocalDatabaseError,
    assert_local_connection,
    assert_local_database,
)

_CUSTOM_LIKE = CUSTOM_SOURCE_PREFIX + "%"

EXIT_OK = 0
EXIT_ABORTED = 1
EXIT_REFUSED = 2
EXIT_INVARIANT = 3


class Refusal(RuntimeError):
    """A guard said no BEFORE anything was deleted. Roll back, report, exit 2."""


class InvariantViolation(RuntimeError):
    """Something outside the purge's scope changed. Roll back, report, exit 3."""


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def _scalar(cursor: Any, query: str, params: Sequence[Any] = ()) -> Any:
    cursor.execute(query, tuple(params))
    row = cursor.fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _count(cursor: Any, query: str, params: Sequence[Any] = ()) -> int:
    return int(_scalar(cursor, query, params) or 0)


def _pair(cursor: Any, query: str, params: Sequence[Any] = ()) -> tuple[int, str]:
    """Run a ``count(*) AS n, md5(...) AS fp`` query and return both."""
    cursor.execute(query, tuple(params))
    row = cursor.fetchone()
    if row is None:
        return 0, ""
    return int(row["n"]), str(row["fp"])


@dataclass(frozen=True)
class Target:
    """One ``visibility='user'`` company this run will destroy."""

    company_id: str
    display_name: str
    board_token: Optional[str]
    owner_user_id: Optional[str]
    jobs: int

    @property
    def source_id(self) -> str:
        return custom(self.company_id)


# ``count(*)`` alone cannot tell "nothing changed" from "deleted one row, inserted
# another"; the md5 over the ordered key set can, and that second case is exactly the
# failure that would otherwise be silent. ``job_listings``' key is its composite PK
# ``(source_id, id)``.
_Q_OTHER_CUSTOM_COMPANIES = """
    SELECT count(*) AS n,
           coalesce(md5(string_agg(id, ',' ORDER BY id)), '') AS fp
    FROM companies
    WHERE visibility = 'user' AND id <> ALL(%s)
"""
_Q_OTHER_CUSTOM_JOBS = """
    SELECT count(*) AS n,
           coalesce(
               md5(string_agg(source_id || '|' || id, ',' ORDER BY source_id, id)),
               ''
           ) AS fp
    FROM job_listings
    WHERE source_id LIKE %s AND source_id <> ALL(%s)
"""
_Q_PUBLISHED_COMPANIES = """
    SELECT count(*) AS n,
           coalesce(md5(string_agg(id, ',' ORDER BY id)), '') AS fp
    FROM companies
    WHERE visibility <> 'user'
"""
_Q_PUBLISHED_JOBS = """
    SELECT count(*) AS n,
           coalesce(
               md5(string_agg(source_id || '|' || id, ',' ORDER BY source_id, id)),
               ''
           ) AS fp
    FROM job_listings
    WHERE source_id NOT LIKE %s
"""


@dataclass(frozen=True)
class Invariants:
    """The rows that MUST be identical before and after.

    ``other_custom_*`` is listed first because it is the property the demo run turns
    on: purging Oracle must leave Atlassian, Github, handshake and chime exactly as
    they were.
    """

    other_custom_companies: int
    other_custom_companies_fp: str
    other_custom_jobs: int
    other_custom_jobs_fp: str
    published_companies: int
    published_companies_fp: str
    published_jobs: int
    published_jobs_fp: str

    def rows(
        self, after: "Invariants"
    ) -> list[tuple[str, int, int, str, str]]:
        """``(label, before_count, after_count, before_md5, after_md5)`` per check."""
        return [
            (
                "other custom companies",
                self.other_custom_companies,
                after.other_custom_companies,
                self.other_custom_companies_fp,
                after.other_custom_companies_fp,
            ),
            (
                "other custom job rows",
                self.other_custom_jobs,
                after.other_custom_jobs,
                self.other_custom_jobs_fp,
                after.other_custom_jobs_fp,
            ),
            (
                "published companies",
                self.published_companies,
                after.published_companies,
                self.published_companies_fp,
                after.published_companies_fp,
            ),
            (
                "published job rows",
                self.published_jobs,
                after.published_jobs,
                self.published_jobs_fp,
                after.published_jobs_fp,
            ),
        ]

    def compare(self, after: "Invariants") -> list[str]:
        """One human-readable line per invariant that moved (empty list == clean)."""
        problems = []
        for label, before_n, after_n, before_fp, after_fp in self.rows(after):
            if before_n != after_n:
                problems.append(f"{label}: count changed {before_n} -> {after_n}")
            elif before_fp != after_fp:
                problems.append(
                    f"{label}: count held at {before_n} but the row set changed "
                    f"(md5 {before_fp[:12]} -> {after_fp[:12]})"
                )
        return problems


def _read_invariants(cursor: Any, sources: list[str], ids: list[str]) -> Invariants:
    """Snapshot everything this purge is forbidden from touching.

    ``sources`` / ``ids`` are the TARGETS and appear only NEGATED: every query is
    "the custom rows that are not being purged" or "the published rows", so the
    snapshot is by construction disjoint from anything the purge may delete.
    """
    other_companies_n, other_companies_fp = _pair(
        cursor, _Q_OTHER_CUSTOM_COMPANIES, (ids,)
    )
    other_jobs_n, other_jobs_fp = _pair(
        cursor, _Q_OTHER_CUSTOM_JOBS, (_CUSTOM_LIKE, sources)
    )
    published_companies_n, published_companies_fp = _pair(
        cursor, _Q_PUBLISHED_COMPANIES
    )
    published_jobs_n, published_jobs_fp = _pair(
        cursor, _Q_PUBLISHED_JOBS, (_CUSTOM_LIKE,)
    )
    return Invariants(
        other_custom_companies=other_companies_n,
        other_custom_companies_fp=other_companies_fp,
        other_custom_jobs=other_jobs_n,
        other_custom_jobs_fp=other_jobs_fp,
        published_companies=published_companies_n,
        published_companies_fp=published_companies_fp,
        published_jobs=published_jobs_n,
        published_jobs_fp=published_jobs_fp,
    )


def _table_counts(cursor: Any) -> dict[str, int]:
    """Global row counts for every table the purge can reach.

    GLOBAL on purpose. A per-target count reports what the purge BELIEVES it touched;
    the whole table's count before and after is what actually happened, and is the
    number that catches a predicate reaching further than intended.
    """
    return {
        "companies (all)": _count(cursor, "SELECT count(*) AS n FROM companies"),
        "companies (visibility='user')": _count(
            cursor, "SELECT count(*) AS n FROM companies WHERE visibility = 'user'"
        ),
        "companies (published)": _count(
            cursor, "SELECT count(*) AS n FROM companies WHERE visibility <> 'user'"
        ),
        "job_listings (all)": _count(
            cursor, "SELECT count(*) AS n FROM job_listings"
        ),
        "job_listings (custom:%)": _count(
            cursor,
            "SELECT count(*) AS n FROM job_listings WHERE source_id LIKE %s",
            (_CUSTOM_LIKE,),
        ),
        "job_listings (published)": _count(
            cursor,
            "SELECT count(*) AS n FROM job_listings WHERE source_id NOT LIKE %s",
            (_CUSTOM_LIKE,),
        ),
        "job_freshness": _count(cursor, "SELECT count(*) AS n FROM job_freshness"),
        "job_tags": _count(cursor, "SELECT count(*) AS n FROM job_tags"),
        "job_enrichment": _count(cursor, "SELECT count(*) AS n FROM job_enrichment"),
        "job_locations": _count(cursor, "SELECT count(*) AS n FROM job_locations"),
        "company_scripts": _count(cursor, "SELECT count(*) AS n FROM company_scripts"),
        "company_harvests": _count(
            cursor, "SELECT count(*) AS n FROM company_harvests"
        ),
        "scrape_runs": _count(cursor, "SELECT count(*) AS n FROM scrape_runs"),
        "user_companies": _count(cursor, "SELECT count(*) AS n FROM user_companies"),
        "company_add_attempts": _count(
            cursor, "SELECT count(*) AS n FROM company_add_attempts"
        ),
    }


def _resolve_targets(cursor: Any, requested_ids: Optional[list[str]]) -> list[Target]:
    """The companies to purge -- every one proven ``visibility='user'``.

    ``requested_ids=None`` means ``--all``. Otherwise an id that is missing, or that
    resolves to a company which is not ``visibility='user'``, is an ABORT and not a
    skip: "purge these three" quietly becoming "purge these two" is how an operator
    ends up believing a board is gone when it is not, and a published id arriving
    here at all means the operator's model of the database is wrong.
    """
    if requested_ids is None:
        cursor.execute(
            """
            SELECT c.id, c.display_name, c.board_token, c.visibility,
                   (SELECT uc.user_id FROM user_companies uc
                     WHERE uc.company_id = c.id LIMIT 1) AS owner_user_id
            FROM companies c
            WHERE c.visibility = 'user'
            ORDER BY c.id
            """
        )
    else:
        cursor.execute(
            """
            SELECT c.id, c.display_name, c.board_token, c.visibility,
                   (SELECT uc.user_id FROM user_companies uc
                     WHERE uc.company_id = c.id LIMIT 1) AS owner_user_id
            FROM companies c
            WHERE c.id = ANY(%s)
            ORDER BY c.id
            """,
            (requested_ids,),
        )
    rows = [dict(row) for row in cursor.fetchall()]

    if requested_ids is not None:
        found = {str(row["id"]): row for row in rows}
        missing = [i for i in requested_ids if i not in found]
        if missing:
            raise Refusal(
                f"no companies row for {missing}. Nothing was changed."
            )
        not_custom = [
            f"{i} (visibility={found[i]['visibility']!r})"
            for i in requested_ids
            if found[i]["visibility"] != "user"
        ]
        if not_custom:
            raise Refusal(
                "these are not user-added companies, and this script only "
                "ever deletes user-added companies: "
                + ", ".join(not_custom)
                + ". Nothing was changed."
            )

    targets: list[Target] = []
    for row in rows:
        company_id = str(row["id"])
        # ``custom()`` rejects an id we could not have minted, and such a row owns no
        # ``custom:<id>`` namespace. Surfaced rather than swallowed: it means the id
        # typed cannot be the one that was meant.
        try:
            source_id = custom(company_id)
        except ValueError as exc:
            raise Refusal(f"{exc} Nothing was changed.") from None
        targets.append(
            Target(
                company_id=company_id,
                display_name=str(row["display_name"] or ""),
                board_token=str(row["board_token"]) if row["board_token"] else None,
                owner_user_id=(
                    str(row["owner_user_id"]) if row["owner_user_id"] else None
                ),
                jobs=_count(
                    cursor,
                    "SELECT count(*) AS n FROM job_listings WHERE source_id = %s",
                    (source_id,),
                ),
            )
        )
    return targets


def _remaining_custom(cursor: Any) -> list[tuple[str, str, int]]:
    """``(id, display_name, jobs)`` for every custom company still tracked."""
    cursor.execute(
        """
        SELECT c.id, c.display_name,
               (SELECT count(*) FROM job_listings j
                 WHERE j.source_id = %s || c.id) AS jobs
        FROM companies c
        WHERE c.visibility = 'user'
        ORDER BY c.id
        """,
        (CUSTOM_SOURCE_PREFIX,),
    )
    return [
        (str(row["id"]), str(row["display_name"] or ""), int(row["jobs"]))
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------


def _print_counts_table(before: dict[str, int], after: dict[str, int]) -> None:
    width = max(len(key) for key in before)
    print(f"  {'table':<{width}}  {'before':>10}  {'after':>10}  {'delta':>10}")
    print(f"  {'-' * width}  {'-' * 10}  {'-' * 10}  {'-' * 10}")
    for key, before_n in before.items():
        delta = after[key] - before_n
        print(
            f"  {key:<{width}}  {before_n:>10,}  {after[key]:>10,}  {delta:>+10,}"
        )


def _print_invariants(before: Invariants, after: Invariants) -> None:
    rows = before.rows(after)
    width = max(len(row[0]) for row in rows)
    print(
        f"  {'invariant':<{width}}  {'before':>9}  {'after':>9}  "
        f"{'md5 before':<12}  {'md5 after':<12}  verdict"
    )
    print(
        f"  {'-' * width}  {'-' * 9}  {'-' * 9}  {'-' * 12}  {'-' * 12}  -------"
    )
    for label, before_n, after_n, before_fp, after_fp in rows:
        identical = before_n == after_n and before_fp == after_fp
        print(
            f"  {label:<{width}}  {before_n:>9,}  {after_n:>9,}  "
            f"{before_fp[:12]:<12}  {after_fp[:12]:<12}  "
            f"{'IDENTICAL' if identical else '*** CHANGED ***'}"
        )


# ---------------------------------------------------------------------------
# confirmation
# ---------------------------------------------------------------------------


def _confirm_production(
    *,
    host: str,
    targets: list[Target],
    custom_jobs: int,
    args: argparse.Namespace,
) -> bool:
    """Make the operator restate the host and the row count before anything commits.

    ``--yes`` is deliberately not consulted here. ``--yes`` means "I have already
    read this, for a local database"; production is the case where reading it is the
    entire point. The non-interactive escape (``--confirm-host`` /
    ``--confirm-custom-jobs``) is not a shortcut either: both must be supplied, and
    both must match values this script MEASURED, so writing them down requires having
    looked at them.
    """
    print()
    print("=" * 74)
    print("  THIS IS NOT A LOCAL DATABASE.")
    print(f"  host                      : {host}")
    print(f"  companies to delete       : {len(targets)}")
    for target in targets:
        print(
            f"      {target.company_id}  {target.display_name!r}  "
            f"({target.jobs:,} job rows)"
        )
    print(f"  custom job rows to delete : {custom_jobs:,}")
    print("=" * 74)

    if args.confirm_host is not None or args.confirm_custom_jobs is not None:
        if args.confirm_host is None or args.confirm_custom_jobs is None:
            print(
                "REFUSED: --confirm-host and --confirm-custom-jobs must be given "
                "together.",
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
        if args.confirm_custom_jobs != custom_jobs:
            print(
                f"REFUSED: --confirm-custom-jobs {args.confirm_custom_jobs} does not "
                f"match the {custom_jobs} custom job rows this would delete.",
                file=sys.stderr,
            )
            return False
        print("non-interactive confirmation matched the measured host and counts.")
        return True

    if input(f"Type the host exactly ({host}): ").strip() != host:
        print("aborted: host did not match.")
        return False
    if input("Type the number of custom job rows to delete: ").strip() != str(
        custom_jobs
    ):
        print("aborted: count did not match.")
        return False
    if input("Type DELETE to proceed: ").strip() != "DELETE":
        print("aborted.")
        return False
    return True


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="purge_custom_companies.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Delete user-added (visibility='user') companies and every row they "
            "own. Dry run unless --commit. Local databases only unless "
            "--yes-this-is-production."
        ),
        epilog=(
            "EXAMPLES\n"
            "  # the usual case - what purging ONE board would do (no writes):\n"
            "  python scripts/one_off/purge_custom_companies.py"
            " --company-id u-746utmpsko\n"
            "\n"
            "  # ...and do it, on a local database:\n"
            "  python scripts/one_off/purge_custom_companies.py"
            " --company-id u-746utmpsko --commit\n"
            "\n"
            "  # ...on production (prints the host + counts, then makes you retype"
            " them):\n"
            "  python scripts/one_off/purge_custom_companies.py"
            " --company-id u-746utmpsko \\\n"
            "      --dsn \"$PROD_DATABASE_URL\" --commit --yes-this-is-production\n"
            "\n"
            "  # every user-added board (rare - prefer --company-id):\n"
            "  python scripts/one_off/purge_custom_companies.py --all --commit\n"
        ),
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--company-id",
        action="append",
        dest="company_ids",
        metavar="ID",
        help=(
            "Purge this custom company (e.g. u-746utmpsko). Repeatable. This is the "
            "usual way to run the script."
        ),
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="Purge EVERY visibility='user' company. Rare; prefer --company-id.",
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help=(
            "Database to target. Defaults to the backend's configured database_url "
            "(.env.local / .env), the same as the rest of the repo."
        ),
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write. Without it this is a dry run that rolls back.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Skip the interactive confirmation for a LOCAL commit. Has no effect on "
            "the production confirmation, which is never skippable."
        ),
    )
    parser.add_argument(
        "--yes-this-is-production",
        action="store_true",
        dest="production",
        help=(
            "Opt out of the localhost-only guard. With --commit this additionally "
            "requires the host + row-count confirmation."
        ),
    )
    parser.add_argument(
        "--confirm-host",
        default=None,
        metavar="HOST:PORT",
        help="Non-interactive production confirmation: must equal the host dialed.",
    )
    parser.add_argument(
        "--confirm-custom-jobs",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Non-interactive production confirmation: must equal the number of "
            "custom job rows this run would delete."
        ),
    )
    return parser


def _resolve_dsn(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    # Imported lazily so a run with an explicit --dsn never needs the backend's
    # settings (and its .env discovery) to load at all.
    from src.backend.api.config import settings

    return str(settings.database_url)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    dsn = _resolve_dsn(args.dsn)

    if not args.production:
        # UNCHANGED, and deliberately run BEFORE connecting: a DSN that cannot be
        # proven loopback should not even open a socket.
        try:
            assert_local_database(dsn)
        except NonLocalDatabaseError as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            print(
                "\nIf you really do mean to run this against a remote database, pass "
                "--yes-this-is-production. That is a separate path around this guard, "
                "and it will make you retype the host and the row count.",
                file=sys.stderr,
            )
            return EXIT_REFUSED

    conn = psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    remaining: list[tuple[str, str, int]] = []
    targets: list[Target] = []
    try:
        # See the module docstring: this is what stops a live production harvest
        # worker from making a correct run look like a violated invariant.
        conn.set_session(isolation_level="REPEATABLE READ", readonly=False)
        if not args.production:
            try:
                assert_local_connection(conn)
            except NonLocalDatabaseError as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return EXIT_REFUSED

        host = f"{conn.info.host or '?'}:{conn.info.port or '?'}"
        cursor = conn.cursor()

        targets = _resolve_targets(cursor, None if args.all else args.company_ids)
        if not targets:
            print("no visibility='user' companies matched. Nothing to do.")
            return EXIT_OK
        ids = [target.company_id for target in targets]
        sources = [target.source_id for target in targets]
        target_jobs = sum(target.jobs for target in targets)

        print(f"database : {host} / {conn.info.dbname}")
        print(f"scope    : {'--all' if args.all else '--company-id'}")
        print(f"mode     : {'COMMIT' if args.commit else 'DRY RUN (rolls back)'}")
        print(
            f"guard    : "
            f"{'PRODUCTION OPT-OUT' if args.production else 'localhost-only'}"
        )
        print("targets  :")
        for target in targets:
            print(
                f"    {target.company_id}  {target.display_name!r}  "
                f"{target.jobs:,} job rows"
            )

        before_counts = _table_counts(cursor)
        before_inv = _read_invariants(cursor, sources, ids)

        if args.commit:
            if args.production:
                if not _confirm_production(
                    host=host, targets=targets, custom_jobs=target_jobs, args=args
                ):
                    conn.rollback()
                    return EXIT_ABORTED
            elif not args.yes:
                answer = input(
                    f"Delete {len(targets)} custom company/companies and "
                    f"{target_jobs:,} job rows? Type 'yes': "
                )
                if answer.strip().lower() != "yes":
                    conn.rollback()
                    print("aborted.")
                    return EXIT_ABORTED

        # ---- the purge ----------------------------------------------------
        for target in targets:
            purge_custom_company(
                cursor,
                company_id=target.company_id,
                board_token=target.board_token,
                owner_user_id=target.owner_user_id,
            )
        cursor.execute("DELETE FROM user_companies WHERE company_id = ANY(%s)", (ids,))
        cursor.execute(
            "DELETE FROM company_add_attempts WHERE company_id = ANY(%s)", (ids,)
        )

        after_counts = _table_counts(cursor)
        after_inv = _read_invariants(cursor, sources, ids)

        # ---- the safety net -----------------------------------------------
        problems = before_inv.compare(after_inv)
        # The fingerprints above prove nothing NEW was destroyed. These prove the
        # totals moved by exactly the amount the targets account for -- the same
        # statement made from the other side, so a delete that reached wider AND
        # somehow matched a fingerprint still cannot pass both.
        expected_deltas = {
            "companies (all)": -len(targets),
            "companies (published)": 0,
            "job_listings (all)": -target_jobs,
            "job_listings (custom:%)": -target_jobs,
            "job_listings (published)": 0,
        }
        for key, want in expected_deltas.items():
            got = after_counts[key] - before_counts[key]
            if got != want:
                problems.append(f"{key}: expected delta {want:+,}, got {got:+,}")

        still_there = _count(
            cursor, "SELECT count(*) AS n FROM companies WHERE id = ANY(%s)", (ids,)
        )
        if still_there:
            problems.append(
                f"{still_there} target companies row(s) survived the purge"
            )
        stray_jobs = _count(
            cursor,
            "SELECT count(*) AS n FROM job_listings WHERE source_id = ANY(%s)",
            (sources,),
        )
        if stray_jobs:
            problems.append(f"{stray_jobs} target job row(s) survived the purge")

        print()
        print("per-table row counts")
        _print_counts_table(before_counts, after_counts)
        print()
        print("invariants (must be identical)")
        _print_invariants(before_inv, after_inv)

        if problems:
            raise InvariantViolation("; ".join(problems))

        remaining = _remaining_custom(cursor)
        if args.commit:
            conn.commit()
        else:
            conn.rollback()
    except Refusal as exc:
        conn.rollback()
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except InvariantViolation as exc:
        conn.rollback()
        print()
        # The tables above went to stdout and the banner goes to stderr; without
        # this the operator sees the verdict before the evidence.
        sys.stdout.flush()
        print("*" * 74, file=sys.stderr)
        print(
            "INVARIANT VIOLATED - ROLLED BACK, NOTHING WAS WRITTEN", file=sys.stderr
        )
        for line in str(exc).split("; "):
            print(f"  - {line}", file=sys.stderr)
        print("*" * 74, file=sys.stderr)
        return EXIT_INVARIANT
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print()
    if args.commit:
        print(f"COMMITTED. Purged {len(targets)} custom company/companies.")
    else:
        print("DRY RUN - rolled back, nothing was written. Re-run with --commit.")
    # Read inside the transaction, so on a dry run it describes the state that WOULD
    # have been left rather than the one on disk. Worded accordingly -- "still
    # tracked" after a run that wrote nothing would be a lie.
    verb = "still tracked" if args.commit else "would still be tracked"
    if remaining:
        listed = ", ".join(
            f"{cid} ({name}, {jobs:,} jobs)" for cid, name, jobs in remaining
        )
        print(f"{len(remaining)} custom companies {verb}: {listed}")
    else:
        print(f"0 custom companies {verb}.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
