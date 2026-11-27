"""Identities for the onboarding section: make one, read its DB state, purge it.

PLAN.md §4: every case signs in as a BRAND-NEW identity, so "first sign-in"
means *no `users` row exists*, which every case asserts before its first call.
This module is the one place that knows the identity shape, and the one place
allowed to delete a `users` row — and it refuses any `sub` that is not this
section's (`fixtures.IDENTITY_PREFIX`).

Used by the API tier directly and by the UI tier through the CLI:

    python -m e2e.onboarding.identities state <sub>   # JSON: row + saved filters
    python -m e2e.onboarding.identities purge         # every e2e|onboarding-* row

Every connection goes through `shared/db/assertions.connect`, which refuses any
database but `E2E_EXPECTED_DB` (`jobscraper_e2e_onboarding` under run.sh).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from e2e.onboarding import fixtures  # noqa: E402
from e2e.shared.db import assertions as db  # noqa: E402

DEFAULT_DSN = os.environ.get(
    "E2E_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/jobscraper_e2e_onboarding",
)

#: Exported by run.sh so every identity of one run shares a recognisable tag.
RUN_ID = os.environ.get("E2E_RUN_ID") or f"local{int(datetime.now().timestamp())}"


@dataclass(frozen=True)
class Identity:
    sub: str
    email: str


def new_identity(case: str) -> Identity:
    """A never-seen identity for `case` (e.g. ``"OB-03"``)."""
    tag = uuid.uuid4().hex[:8]
    slug = f"{case}-{RUN_ID}-{tag}"
    return Identity(
        sub=f"{fixtures.IDENTITY_PREFIX}{slug}",
        email=f"{fixtures.EMAIL_PREFIX}{slug.lower()}@{fixtures.EMAIL_DOMAIN}",
    )


def _refuse_foreign(subs: Iterable[str]) -> list[str]:
    subs = list(subs)
    foreign = [s for s in subs if not s.startswith(fixtures.IDENTITY_PREFIX)]
    if foreign:
        raise ValueError(
            f"identities.purge refuses {foreign}: only subs starting with "
            f"{fixtures.IDENTITY_PREFIX!r} belong to this section"
        )
    return subs


def purge(conn: Any, subs: Iterable[str] | None = None) -> int:
    """Delete identities and everything they own. Returns the users deleted.

    With `subs`, exactly those (each must carry the prefix). Without, EVERY
    row whose sub or email carries this section's prefix — the pre-clean an
    aborted run needs. `user_saved_filters` (and every other per-user table) is
    `ON DELETE CASCADE` from `users`; the saved filters are deleted explicitly
    first anyway, because they are what this section asserts on.
    """
    if subs is None:
        where = "left(auth0_id, %s) = %s OR left(email, %s) = %s"
        params: list[Any] = [
            len(fixtures.IDENTITY_PREFIX), fixtures.IDENTITY_PREFIX,
            len(fixtures.EMAIL_PREFIX), fixtures.EMAIL_PREFIX,
        ]
    else:
        wanted = _refuse_foreign(subs)
        if not wanted:
            return 0
        where = "auth0_id = ANY(%s)"
        params = [wanted]
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM user_saved_filters WHERE user_id IN (SELECT id FROM users WHERE {where})",  # noqa: S608
            params,
        )
        cur.execute(f"DELETE FROM users WHERE {where}", params)  # noqa: S608
        deleted = cur.rowcount
    conn.commit()
    return int(deleted)


def user_rows(conn: Any, ident: Identity) -> list[dict[str, Any]]:
    """Every `users` row matching the identity by EITHER key — the same
    two-key lookup `get_or_create_user` does, so a duplicate shows up here."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM users WHERE auth0_id = %s OR email = %s ORDER BY created_at",
            (ident.sub, ident.email),
        )
        return [dict(r) for r in cur.fetchall()]


def user_row(conn: Any, ident: Identity) -> dict[str, Any] | None:
    rows = user_rows(conn, ident)
    if len(rows) > 1:
        raise AssertionError(f"{len(rows)} users rows for {ident} — one identity, one row")
    return rows[0] if rows else None


def saved_filters_row(conn: Any, user_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM user_saved_filters WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def state(conn: Any, ident: Identity) -> dict[str, Any]:
    """The identity's DB state, JSON-ready (the UI tier's oracle)."""
    rows = user_rows(conn, ident)
    out: dict[str, Any] = {"rowCount": len(rows), "exists": bool(rows)}
    if not rows:
        return out
    row = rows[0]
    stamp = row["onboarding_completed_at"]
    out["userId"] = row["id"]
    out["onboardingCompletedAt"] = stamp.isoformat() if stamp is not None else None
    sf = saved_filters_row(conn, row["id"])
    out["savedFilters"] = (
        None
        if sf is None
        else {
            "recentTimeWindow": sf["recent_time_window"],
            "trendTimeWindow": sf["trend_time_window"],
            "category": sf["category"],
            "subcategory": sf["subcategory"],
            "level": sf["level"],
            "locations": sf["locations"],
            "companyCategory": sf.get("company_category"),
            "recentActiveKeywordListId": sf["recent_active_keyword_list_id"],
            "trendActiveKeywordListId": sf["trend_active_keyword_list_id"],
        }
    )
    return out


def _main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "state":
        sub = argv[1]
        _refuse_foreign([sub])
        conn = db.connect(DEFAULT_DSN)
        try:
            # The email is looked up from the sub's own row; a sub with no row
            # reports exists=false. The UI tier passes the email too when it has
            # one, so a row created under the email alone still counts.
            email = argv[2] if len(argv) >= 3 else ""
            print(json.dumps(state(conn, Identity(sub=sub, email=email))))
        finally:
            conn.close()
        return 0
    if argv[:1] == ["purge"]:
        conn = db.connect(DEFAULT_DSN)
        try:
            print(f"identities: purged {purge(conn)} e2e|onboarding-* users")
        finally:
            conn.close()
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
