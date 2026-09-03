#!/usr/bin/env python3
"""LOCAL-DEVELOPMENT-ONLY: clear the user-added (custom) company tables.

WHY
---
The add-a-company flow can only be tested once per board: after the first add,
``POST /api/users/companies`` answers "you already track this" or "we already
publish this", and the 20/month quota has spent a slot. This puts the database
back to the state where the board was never added, so the real code path can be
run again.

The QA page (``/qa``) has a button for the same thing. This script is the escape
hatch for when the frontend is not running — or when you would rather not have a
browser involved in a destructive operation at all.

SAFETY
------
It shares ONE implementation with the endpoint
(``src/backend/api/services/dev_reset.py``), guards included, so there is no
second delete ordering to drift:

* it REFUSES unless ``DATABASE_URL`` parses to a loopback host, and fails closed
  on anything it cannot parse;
* it is DRY-RUN by default — it prints what would go and rolls back;
* ``--apply`` requires an interactive "yes" unless ``--yes`` is also given.

It never touches published companies: every delete is scoped to
``visibility='user'``. The counts printed at the end include the published rows
left standing, so you can see that for yourself.

USAGE
-----
    # what would be deleted for one user (no writes):
    python scripts/one_off/dev_reset_custom_companies.py --email you@example.com

    # do it:
    python scripts/one_off/dev_reset_custom_companies.py --email you@example.com --apply

    # every user's custom companies (a single-developer laptop; still local-only):
    python scripts/one_off/dev_reset_custom_companies.py --all --apply --yes

``DATABASE_URL`` is read from the environment, falling back to the repo's
``.env.local`` / ``.env`` exactly as the backend does — so running this from the
repo root targets the same database the backend is using.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# Make `src.backend.api...` importable when run from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.backend.api.config import settings  # noqa: E402
from src.backend.api.services.dev_reset import (  # noqa: E402
    NonLocalDatabaseError,
    assert_local_database,
    reset_custom_companies,
)


def _resolve_user_id(conn, email: str) -> str:
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(
            f"no users row with email {email!r}. Sign in once at "
            f"http://localhost:3000 first, or pass --all."
        )
    return str(row["id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clear the local custom-company tables so the add flow can be "
            "re-tested from scratch. Local databases only."
        )
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--email",
        help="Clear only this user's custom companies (the safer, usual choice).",
    )
    target.add_argument(
        "--all",
        action="store_true",
        help="Clear EVERY user's custom companies.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually commit. Without it this is a dry run that rolls back.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation (for scripts).",
    )
    args = parser.parse_args()

    database_url = settings.database_url
    try:
        host = assert_local_database(database_url)
    except NonLocalDatabaseError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    scope = "ALL users" if args.all else f"user {args.email}"
    print(f"database host : {host}")
    print(f"scope         : {scope}")
    print(f"mode          : {'APPLY (commits)' if args.apply else 'DRY RUN (rolls back)'}")

    if args.apply and not args.yes:
        answer = input(f"Delete the custom companies of {scope}? Type 'yes': ")
        if answer.strip().lower() != "yes":
            print("aborted.")
            return 1

    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    try:
        user_id = None if args.all else _resolve_user_id(conn, args.email)
        # commit=False runs the REAL deletes and returns the REAL counts, then
        # leaves the transaction open for the rollback below. A dry run that
        # counted rows through some other query would be reporting on a different
        # statement than the one that deletes, which is how a dry run lies.
        outcome = reset_custom_companies(conn, user_id=user_id, commit=args.apply)
        if not args.apply:
            conn.rollback()
    finally:
        conn.close()

    print()
    print(f"companies      : {outcome.company_ids or '(none)'}")
    for table, count in sorted(outcome.deleted.items()):
        print(f"  {table:<22} {count}")
    print(f"published companies kept : {outcome.published_companies_kept}")
    print(f"published job rows kept  : {outcome.published_jobs_kept}")
    if not args.apply:
        print()
        print("DRY RUN — nothing was committed. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
