#!/usr/bin/env python3
"""verify-onesecondswe :: read a Tier-3 side-effect row from jobscraper_e2e.

The e2e shared helpers (``e2e/shared/db/assertions.py``) are company-shape aware
and carry NO helpers for the four Tier-3 tables this skill's tools write
(``feedback``, ``feature_upvotes``, ``user_enabled_companies``,
``user_saved_filters``). Rather than hand-roll a psycopg2 connection here, this
CLI reuses that module's :func:`connect` — which REFUSES any database but
``jobscraper_e2e`` by construction — and its :func:`user_id_for_email`, so the
"never point at the owner's DB" guard is inherited, not re-implemented.

Prints a JSON object ``{"table", "where", "count", "sample": [...]}`` and exits 0
if ``count > 0`` (something was written), 1 otherwise — so it doubles as an
assertion in a shell pipeline.

Run with the repo-root ``.venv`` python; an absolute path works from anywhere
(this file adds the repo root to sys.path itself):

    .venv/bin/python .claude/skills/verify-onesecondswe/helpers/db_assert.py \
        --table feedback --contains "verify-onesecondswe smoke"
    .venv/bin/python .claude/skills/verify-onesecondswe/helpers/db_assert.py \
        --table user_enabled_companies --email 'e2e+add-companies@jvn.test'
    .claude/.../db_assert.py --table feature_upvotes --email … --feature-id mcp-server
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Repo root on sys.path so `import e2e.shared.db.assertions` resolves regardless
# of cwd (assertions.py's connect() is the ONE seam that can touch a database).
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from e2e.shared.db.assertions import connect, user_id_for_email  # noqa: E402

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/jobscraper_e2e"

# Each table -> (email-linked user column | None). None means the table is not
# user-scoped (feedback can be anonymous).
_USER_COLUMN = {
    "feedback": "user_id",  # nullable — anonymous feedback has NULL here
    "feature_upvotes": "user_id",
    "user_enabled_companies": "user_id",
    "user_saved_filters": "user_id",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--table",
        required=True,
        choices=sorted(_USER_COLUMN),
        help="Tier-3 side-effect table to read.",
    )
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL", _DEFAULT_DSN))
    ap.add_argument("--email", help="Scope to this user (resolved to users.id).")
    ap.add_argument("--feature-id", help="feature_upvotes: scope to this feature.")
    ap.add_argument(
        "--contains", help="feedback: require message to ILIKE %%<contains>%%."
    )
    args = ap.parse_args()

    conn = connect(args.dsn)  # refuses anything but jobscraper_e2e
    try:
        clauses: list[str] = []
        params: list[Any] = []

        if args.email:
            uid = user_id_for_email(conn, args.email)
            if uid is None:
                print(
                    json.dumps(
                        {
                            "table": args.table,
                            "where": {"email": args.email},
                            "count": 0,
                            "sample": [],
                            "note": "no users row for that email",
                        },
                        indent=2,
                    )
                )
                return 1
            clauses.append(f"{_USER_COLUMN[args.table]} = %s")
            params.append(uid)

        if args.feature_id and args.table == "feature_upvotes":
            clauses.append("feature_id = %s")
            params.append(args.feature_id)

        if args.contains and args.table == "feedback":
            clauses.append("message ILIKE %s")
            params.append(f"%{args.contains}%")

        where_sql = " AND ".join(clauses) or "TRUE"
        with conn.cursor() as cur:
            # noqa: S608 — table name is from a fixed allowlist (choices=), never user input.
            cur.execute(
                f"SELECT count(*) AS n FROM {args.table} WHERE {where_sql}", params  # noqa: S608
            )
            count = int(cur.fetchone()["n"])
            cur.execute(
                f"SELECT * FROM {args.table} WHERE {where_sql} LIMIT 5", params  # noqa: S608
            )
            sample = [dict(r) for r in cur.fetchall()]

        print(
            json.dumps(
                {
                    "table": args.table,
                    "where": {
                        k: v
                        for k, v in {
                            "email": args.email,
                            "feature_id": args.feature_id,
                            "contains": args.contains,
                        }.items()
                        if v is not None
                    },
                    "count": count,
                    "sample": sample,
                },
                indent=2,
                default=str,
            )
        )
        return 0 if count > 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
