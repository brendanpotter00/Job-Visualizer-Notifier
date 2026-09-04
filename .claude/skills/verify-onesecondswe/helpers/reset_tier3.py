#!/usr/bin/env python3
"""verify-onesecondswe :: reset the Tier-3 side-effect state ``reset_user`` misses.

``e2e.shared.db.reset_user`` sweeps only the companies a fixture user OWNS (through
the product's own DELETE path). The Tier-3 tools this skill drives write four MORE
durable rows that nothing then clears, so a re-run against a NON-refreshed
``jobscraper_e2e`` accumulates them and lets one run's state change what a later
authenticated run observes:

* ``submit_feedback`` inserts a durable ``feedback`` row — and the drive submits it
  ANONYMOUSLY (``user_id`` NULL), so it is not owned by anyone ``reset_user`` could
  hand it to. Matched here by the drive's own marker prefix.
* ``set_enabled_companies`` writes ``user_enabled_companies``; the saved-filter and
  voting playbooks write ``user_saved_filters`` and ``feature_upvotes``. Cleared here
  for BOTH fixture identities.

Reuses ``assertions.connect`` (which REFUSES any database but ``jobscraper_e2e`` by
construction) and ``user_id_for_email`` — the "never point at the owner's DB" guard
is inherited, not re-implemented — and the fixture identities from ``auth.mint``, so
the emails cannot drift from the tokens the drive actually signs in as.

Idempotent: every DELETE is a no-op when there is nothing to remove. Run with the
repo-root ``.venv`` python; an absolute path works from anywhere.

    .venv/bin/python .claude/skills/verify-onesecondswe/helpers/reset_tier3.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo root on sys.path so `import e2e.shared.*` resolves regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from e2e.shared.auth.mint import OTHER_USER, PRIMARY_USER  # noqa: E402
from e2e.shared.db.assertions import connect, user_id_for_email  # noqa: E402

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/jobscraper_e2e"

# The prefix helpers/drive.spec.ts stamps on every feedback message it submits
# (`verify-onesecondswe smoke <ISO timestamp>`). Scoped to this skill's own rows.
_FEEDBACK_MARKER = "verify-onesecondswe smoke"

# The per-user Tier-3 tables reset_user does not touch, all keyed by `user_id`.
_USER_SCOPED_TABLES = (
    "user_enabled_companies",
    "user_saved_filters",
    "feature_upvotes",
)


def _table_exists(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) AS oid", (name,))
    row = cur.fetchone()
    return row is not None and row["oid"] is not None


def main() -> int:
    dsn = os.environ.get("DATABASE_URL", _DEFAULT_DSN)
    conn = connect(dsn)  # refuses anything but jobscraper_e2e
    try:
        with conn.cursor() as cur:
            # 1. The drive's anonymous feedback rows.
            if _table_exists(cur, "feedback"):
                cur.execute(
                    "DELETE FROM feedback WHERE message ILIKE %s",
                    (f"{_FEEDBACK_MARKER}%",),
                )
                print(f"reset_tier3: deleted {cur.rowcount} drive feedback row(s)")

            # 2. Per-user Tier-3 state for BOTH fixture identities.
            for user in (PRIMARY_USER, OTHER_USER):
                email = user["email"]
                uid = user_id_for_email(conn, email)
                if uid is None:
                    print(f"reset_tier3: no users row for {email} — nothing to reset")
                    continue
                for table in _USER_SCOPED_TABLES:
                    if not _table_exists(cur, table):
                        continue
                    # Table names come from a fixed in-source allowlist, never input.
                    cur.execute(
                        f"DELETE FROM {table} WHERE user_id = %s", (uid,)  # noqa: S608
                    )
                    print(
                        f"reset_tier3: deleted {cur.rowcount} {table} row(s) for {email}"
                    )
        conn.commit()
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
