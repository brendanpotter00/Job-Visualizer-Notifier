"""Read-only SQL behind the admin Custom Companies page (E7 oversight).

Answers four questions about user-added boards: which custom scrapers are
actually harvesting, what every add attempt did, who is submitting, and how
often we refuse. SELECT-only — the page has no actions, and neither does this
module. Every function follows ``enrichment_monitor``'s shape: a plain
``conn.cursor()`` with ``try/finally: cur.close(); conn.rollback()`` so a pooled
connection is never handed back mid-transaction.

Keys returned are **snake_case**; the router's Pydantic models camelCase them.
Cursors are ``RealDictCursor`` (``api/dependencies.py``), and psycopg2 parses
JSONB into Python objects, so ``discovery_steps`` arrives as a ``list[dict]``.

Search-path correctness: relation guards use ``to_regclass`` so they behave
identically inside the per-worker pytest schema and in production. Production
has *none* of the E7 tables and its ``companies`` predates the E7 columns, so
the guard is load-bearing: without it this page is a 500 on prod from day one.
Both public functions degrade to a zeroed envelope with ``schema_present=False``.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg2.extensions import connection as Connection

from .db_rows import scalar

logger = logging.getLogger(__name__)

# Grace before a still-'discovery_pending' attempt is called STUCK rather than
# in-flight: reconcile_discovering's 30-minute _STALL_GRACE_SECONDS plus its
# 10-minute sweep cron (api/tasks/reconcile_discovering.py). Past that the
# sweeper SHOULD have refused the row and did not — which is exactly the thing
# the admin wants to see, so it is surfaced rather than smoothed over.
#
# WHY NOTHING SWEEPS 'stuck' ATTEMPTS THE WAY reconcile_discovering SWEEPS ROWS.
# It was considered and rejected: after the ``_readd_attempt_fields`` fix in
# ``routers/user_companies`` there is no case left for such a sweep to catch.
# An unpaired 'discovery_pending' row is now exactly one of three things:
#
#   1. genuinely in flight  -> inside the grace, renders 'pending'. Correct.
#   2. genuinely wedged, company row still there -> reconcile_discovering reaps it
#      and ``record_discovery_refusal`` writes the terminal 'refused' row that
#      PAIRS with the pending one. Already handled, synchronously, by the sweep
#      that owns that state.
#   3. genuinely wedged, then REMOVED by the user -> the company row is gone, so
#      there is nothing left to refuse. This is the only permanently-unpaired
#      shape, and it is REAL HISTORY: the two rows in the owner's dev database
#      are the 2026-08-26 dead-interactive-worker incident. A sweep that wrote a
#      synthetic terminal row for them would be inventing history in an
#      append-only audit and erasing the evidence of a failure that happened.
#
# So 'stuck' now means what it says. If this count is non-zero, either a wedge
# really is outstanding or a board was removed mid-setup — both worth seeing.
_STUCK_AFTER_SECONDS = 40 * 60

# The DERIVED outcomes that count against the "Failed" tile. 'stuck' belongs
# here and 'pending' does not: a submission still inside the grace window is
# legitimately in flight.
_FAILED_OUTCOMES = ("refused", "unsupported", "empty", "probe_failed", "stuck")

# Every derived outcome, in display order. Emitted explicitly (via FILTER) so
# ``by_outcome`` has deterministic keys even when a bucket is empty.
_ALL_OUTCOMES = (
    "added",
    "already_public",
    "refused",
    "unsupported",
    "empty",
    "probe_failed",
    "pending",
    "stuck",
)

# Hard cap on the per-user rollup (root CLAUDE.md's unbounded-reads rule). The
# query fetches cap+1 so a full page can be reported as truncated.
_USER_ROLLUP_CAP = 200

# The agreed definition of LIVE, written ONCE. Both the row query and the
# summary aggregate interpolate this same fragment, so a tile can never
# disagree with a chip. Requires aliases: c (companies), o (owner CTE),
# h (latest_harvest CTE).
_LIVE_STATUS_SQL = """
    CASE
      WHEN o.company_id IS NULL THEN 'orphan'
      WHEN h.company_id IS NULL THEN 'never_harvested'
      WHEN NOT c.enabled OR h.verdict = 'FAILED' OR h.records_harvested <= 0 THEN 'failing'
      WHEN h.started_at < now() - make_interval(hours => COALESCE(c.cadence_hours, 24) * 2)
           THEN 'stale'
      ELSE 'live'
    END
"""

# Newest harvest per company. DISTINCT ON is safe here: company_harvests.company_id
# is NOT NULL.
_LATEST_HARVEST_CTE = """
latest_harvest AS (
    SELECT DISTINCT ON (company_id)
           company_id, started_at, completed_at, verdict, verdict_reason,
           records_harvested, declared_total, oracle_total, cap_hit
    FROM company_harvests
    ORDER BY company_id, started_at DESC, id DESC
)"""

# First (earliest) owner of each board, plus that user's identity. LEFT JOIN to
# users because user_companies is FK'd but the join must survive any future
# soft-link; and because a NULL email must render as the raw id, not a blank.
_OWNER_CTE = """
owner AS (
    SELECT DISTINCT ON (uc.company_id)
           uc.company_id, uc.user_id,
           u.email AS owner_email, u.display_name AS owner_display_name
    FROM user_companies uc
    LEFT JOIN users u ON u.id = uc.user_id
    ORDER BY uc.company_id, uc.created_at ASC, uc.user_id ASC
)"""

_OWNER_COUNTS_CTE = """
owner_counts AS (
    SELECT company_id, COUNT(*)::int AS owner_count FROM user_companies GROUP BY company_id
)"""

# The attempt-collapsing CTE chain. Shared verbatim by the attempts page, the
# by_outcome tally, the per-user rollup, and the four headline tiles, so all
# four agree on what "an attempt" is.
_ATTEMPTS_CTE = f"""
keyed AS (
    -- Attempt identity. COALESCE, not bare company_id: the column is NULLABLE
    -- (unsupported/empty/probe_failed write none) and DISTINCT ON would fold
    -- every NULL row into a single phantom attempt.
    SELECT a.*, COALESCE(a.company_id, 'attempt#' || a.id::text) AS attempt_key
    FROM company_add_attempts a
),
seq AS (
    SELECT k.*,
           LAG(k.outcome)    OVER w AS prev_outcome,
           LAG(k.created_at) OVER w AS prev_created_at
    FROM keyed k
    WINDOW w AS (PARTITION BY k.attempt_key ORDER BY k.id)
),
latest AS (
    -- ONE row per attempt: the newest audit row.
    SELECT DISTINCT ON (attempt_key) * FROM seq ORDER BY attempt_key, id DESC
),
spans AS (
    SELECT attempt_key, MIN(created_at) AS first_seen_at, COUNT(*)::int AS audit_row_count
    FROM keyed GROUP BY attempt_key
),
resolved AS (
    SELECT l.*, sp.first_seen_at, sp.audit_row_count,
        CASE WHEN l.outcome <> 'discovery_pending' THEN l.outcome
             WHEN l.created_at < now() - make_interval(secs => %(stuck_after_s)s) THEN 'stuck'
             ELSE 'pending' END AS derived_outcome,
        -- Duration only when the row IMMEDIATELY before this one was the pending
        -- row. MAX(pending) would pair an idempotent re-add with a pending row
        -- from days earlier and report a multi-day "time to decide".
        CASE WHEN l.prev_outcome = 'discovery_pending'
             THEN EXTRACT(EPOCH FROM (l.created_at - l.prev_created_at))::int END AS decided_in_s
    FROM latest l JOIN spans sp ON sp.attempt_key = l.attempt_key
)"""


def _regclass(cur: Any, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) AS oid", (name,))
    return scalar(cur.fetchone(), "oid") is not None


def _schema_present(cur: Any) -> bool:
    """Every relation AND column this module reads resolves on the search_path.

    Production runs a pre-E7 schema: none of the four custom-company tables
    exist, and ``companies`` has no ``visibility`` / ``health_state`` /
    ``cadence_hours``. Both checks are needed — the table probe alone would pass
    on a database that has the tables but an older ``companies``.
    """
    if not all(
        _regclass(cur, t)
        for t in (
            "companies",
            "users",
            "user_companies",
            "company_add_attempts",
            "company_harvests",
            "company_scripts",
        )
    ):
        return False
    cur.execute(
        "SELECT COUNT(*) AS n FROM pg_attribute "
        "WHERE attrelid = to_regclass('companies') AND NOT attisdropped "
        "AND attname IN ('visibility', 'health_state', 'cadence_hours')"
    )
    return int(scalar(cur.fetchone(), "n")) == 3


def _clean(value: str | None) -> str | None:
    """Treat a blank/whitespace-only query param as "no filter"."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _empty_summary() -> dict[str, Any]:
    return {
        "tracked_count": 0,
        "live_count": 0,
        "by_live_status": {},
        "by_health_state": {},
        "attempt_count": 0,
        "user_count": 0,
        "failed_count": 0,
        "refused_count": 0,
        "stuck_count": 0,
    }


def _live_reason(row: dict[str, Any]) -> str | None:
    """Short human explanation for a non-live board. ``None`` IFF status is live.

    Mirrors ``_LIVE_STATUS_SQL``'s branch order so the sentence always names the
    same condition the SQL matched on.
    """
    status = str(row["live_status"])
    if status == "live":
        return None
    if status == "orphan":
        return "no owner row"
    if status == "never_harvested":
        return "never harvested"
    if status == "failing":
        if not row["enabled"]:
            return "disabled"
        if row["verdict"] == "FAILED":
            return "last harvest FAILED"
        return "harvested 0 records"
    if status == "stale":
        cadence = row["cadence_hours"] or 24
        age_s = row["last_harvest_age_s"]
        if age_s is None:
            return f"last harvest older than 2 x cadence ({cadence} h)"
        return f"last harvest {int(age_s // 3600)} h ago (cadence {cadence} h)"
    # Unknown status: echo it rather than returning None, which would make the
    # UI claim the board is live.
    return status


def _split_error_detail(detail: str | None) -> tuple[str | None, str | None]:
    """Split ``"<step>: <reason>"`` on the FIRST ``": "`` only.

    Done in Python rather than ``split_part``, which truncates at a second
    ``": "`` — and real reasons contain colons (``"HTTP 412 ... (body starts:
    '{...}')"``). With no separator the whole string is the reason: an
    error_detail that never got a step prefix is still worth showing.
    """
    if not detail:
        return None, None
    step, sep, reason = detail.partition(": ")
    if not sep:
        return None, detail
    return step, reason


def _normalize_steps(value: Any) -> list[dict[str, Any]] | None:
    """Coerce ``provider_config->'discovery'->'steps'`` to the wire shape.

    The column is free-form JSONB, so a legacy or hand-edited row could hold
    anything. Anything that is not a list of ``{key, status}`` objects degrades
    to ``None`` (the UI already falls back to ``error_detail``) rather than
    failing response validation and 500-ing the whole page.
    """
    if not isinstance(value, list):
        return None
    steps: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or "key" not in item or "status" not in item:
            return None
        steps.append(
            {
                "key": str(item["key"]),
                "status": str(item["status"]),
                "result": item.get("result"),
            }
        )
    return steps


# ---------------------------------------------------------------------------
# GET /api/admin/custom-companies
# ---------------------------------------------------------------------------

# Filters live on the OUTER query, after every join, so the owner-email search
# can see the owner CTE. ``total`` rides along as COUNT(*) OVER (): a window
# function runs before LIMIT, so one round trip yields both the page and the
# pre-pagination count.
_COMPANIES_ROWS_SQL = f"""
WITH {_LATEST_HARVEST_CTE},
{_OWNER_CTE},
{_OWNER_COUNTS_CTE}
SELECT
    COUNT(*) OVER ()::int                       AS total,
    c.id, c.display_name, c.ats, c.board_token, c.enabled, c.health_state,
    c.cadence_hours, c.created_at, c.last_success_at, c.consecutive_failures,
    o.user_id AS owner_user_id, o.owner_email, o.owner_display_name,
    COALESCE(oc.owner_count, 0)                 AS owner_count,
    s.transport, s.oracle_kind, s.script_version,
    h.started_at                                AS last_harvest_at,
    EXTRACT(EPOCH FROM (now() - h.started_at))::int AS last_harvest_age_s,
    h.verdict, h.verdict_reason, h.records_harvested,
    h.declared_total, h.oracle_total, h.cap_hit,
    {_LIVE_STATUS_SQL}                          AS live_status
FROM companies c
LEFT JOIN owner        o  ON o.company_id  = c.id
LEFT JOIN owner_counts oc ON oc.company_id = c.id
LEFT JOIN company_scripts s ON s.company_id = c.id
LEFT JOIN latest_harvest  h ON h.company_id = c.id
WHERE c.visibility = 'user'
  AND (%(health)s IS NULL OR c.health_state = %(health)s)
  AND (%(search)s IS NULL
       OR c.display_name ILIKE '%%' || %(search)s || '%%'
       OR c.id           ILIKE '%%' || %(search)s || '%%'
       OR COALESCE(o.owner_email, '') ILIKE '%%' || %(search)s || '%%')
ORDER BY h.started_at DESC NULLS LAST, c.created_at DESC
LIMIT %(limit)s OFFSET %(offset)s
"""

# Deliberately UNFILTERED: the tiles are a fixed reference point, and the
# health-state dropdown is fed from this rollup, so it must not depend on the
# filter currently applied.
_COMPANIES_SUMMARY_SQL = f"""
WITH {_LATEST_HARVEST_CTE},
{_OWNER_CTE},
scored AS (
    SELECT c.health_state, {_LIVE_STATUS_SQL} AS live_status
    FROM companies c
    LEFT JOIN owner o ON o.company_id = c.id
    LEFT JOIN latest_harvest h ON h.company_id = c.id
    WHERE c.visibility = 'user'
)
SELECT live_status, COALESCE(health_state, '') AS health_state, COUNT(*)::int AS n
FROM scored GROUP BY 1, 2
"""

_OUTCOME_TILES_SQL = f"""
WITH {_ATTEMPTS_CTE}
SELECT
  COUNT(*)::int                                                    AS attempt_count,
  COUNT(DISTINCT user_id)::int                                     AS user_count,
  COUNT(*) FILTER (WHERE derived_outcome='added')::int             AS added,
  COUNT(*) FILTER (WHERE derived_outcome='already_public')::int    AS already_public,
  COUNT(*) FILTER (WHERE derived_outcome='refused')::int           AS refused,
  COUNT(*) FILTER (WHERE derived_outcome='unsupported')::int       AS unsupported,
  COUNT(*) FILTER (WHERE derived_outcome='empty')::int             AS empty,
  COUNT(*) FILTER (WHERE derived_outcome='probe_failed')::int      AS probe_failed,
  COUNT(*) FILTER (WHERE derived_outcome='pending')::int           AS pending,
  COUNT(*) FILTER (WHERE derived_outcome='stuck')::int             AS stuck
FROM resolved
"""


def _outcome_tally(cur: Any) -> dict[str, int]:
    """Attempt counts per DERIVED outcome, over the whole table."""
    cur.execute(_OUTCOME_TILES_SQL, {"stuck_after_s": _STUCK_AFTER_SECONDS})
    row = cur.fetchone()
    return {k: int(row[k]) for k in ("attempt_count", "user_count", *_ALL_OUTCOMES)}


def list_custom_companies(
    conn: Connection,
    *,
    limit: int = 25,
    offset: int = 0,
    health: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """One page of user-added boards plus the always-unfiltered summary."""
    cur = conn.cursor()
    try:
        if not _schema_present(cur):
            return {
                "companies": [],
                "total": 0,
                "summary": _empty_summary(),
                "schema_present": False,
            }

        cur.execute(
            _COMPANIES_ROWS_SQL,
            {
                "limit": limit,
                "offset": offset,
                "health": _clean(health),
                "search": _clean(search),
            },
        )
        rows = [dict(r) for r in cur.fetchall()]
        total = int(rows[0]["total"]) if rows else 0
        for row in rows:
            row.pop("total", None)
            row["live_reason"] = _live_reason(row)

        cur.execute(_COMPANIES_SUMMARY_SQL)
        by_live_status: dict[str, int] = {}
        by_health_state: dict[str, int] = {}
        tracked = 0
        for r in cur.fetchall():
            n = int(r["n"])
            tracked += n
            by_live_status[r["live_status"]] = by_live_status.get(r["live_status"], 0) + n
            by_health_state[r["health_state"]] = by_health_state.get(r["health_state"], 0) + n

        tally = _outcome_tally(cur)
        summary = {
            "tracked_count": tracked,
            "live_count": by_live_status.get("live", 0),
            "by_live_status": by_live_status,
            "by_health_state": by_health_state,
            "attempt_count": tally["attempt_count"],
            "user_count": tally["user_count"],
            "failed_count": sum(tally[o] for o in _FAILED_OUTCOMES),
            "refused_count": tally["refused"],
            "stuck_count": tally["stuck"],
        }
        return {
            "companies": rows,
            "total": total,
            "summary": summary,
            "schema_present": True,
        }
    finally:
        cur.close()
        conn.rollback()


# ---------------------------------------------------------------------------
# GET /api/admin/custom-companies/attempts
# ---------------------------------------------------------------------------

# Every join to companies/users is a LEFT JOIN. Deleting a custom company
# HARD-deletes the companies row, so most historical attempts point at an id
# that no longer exists — an inner join would silently drop the bulk of the
# audit log, the exact opposite of what this page is for. The company-side
# joins reuse the SAME owner / latest_harvest CTEs and the SAME
# _LIVE_STATUS_SQL as endpoint 1 so company_live_status cannot drift from it.
_ATTEMPT_ROWS_SQL = f"""
WITH {_ATTEMPTS_CTE},
{_LATEST_HARVEST_CTE},
{_OWNER_CTE}
SELECT
    COUNT(*) OVER ()::int AS total,
    r.id, r.attempt_key, r.created_at, r.first_seen_at, r.audit_row_count, r.decided_in_s,
    r.user_id, u.email AS user_email, u.display_name AS user_display_name,
    r.submitted_url, r.normalized_url, r.resolved_ats, r.board_token,
    r.derived_outcome AS outcome, r.outcome AS raw_outcome, r.error_detail,
    r.company_id, (c.id IS NOT NULL) AS company_exists,
    c.display_name AS company_display_name, c.visibility AS company_visibility,
    c.health_state AS company_health_state,
    CASE WHEN c.visibility = 'user' THEN {_LIVE_STATUS_SQL} END AS company_live_status,
    -- steps ONLY. ->'network' is the full request log plus a payload sample
    -- (kilobytes per row, unbounded in general) and is never selected.
    (c.provider_config -> 'discovery' -> 'steps') AS discovery_steps
FROM resolved r
LEFT JOIN users     u ON u.id = r.user_id          -- soft link, no FK
LEFT JOIN companies c ON c.id = r.company_id       -- most are hard-deleted
LEFT JOIN owner         o ON o.company_id = c.id
LEFT JOIN latest_harvest h ON h.company_id = c.id
WHERE (%(outcome)s IS NULL OR r.derived_outcome = %(outcome)s)
  AND (%(user_id)s IS NULL OR r.user_id = %(user_id)s)
  AND (%(search)s  IS NULL
       OR r.submitted_url ILIKE '%%' || %(search)s || '%%'
       OR COALESCE(r.normalized_url, '') ILIKE '%%' || %(search)s || '%%')
ORDER BY r.created_at DESC, r.id DESC
LIMIT %(limit)s OFFSET %(offset)s
"""

# Unfiltered by construction — this rollup also populates the User dropdown, so
# narrowing it by the current user filter would erase every other option.
_USER_ROLLUP_SQL = f"""
WITH {_ATTEMPTS_CTE},
owns AS (
    SELECT uc.user_id, COUNT(*)::int AS owns_now
    FROM user_companies uc
    JOIN companies c ON c.id = uc.company_id AND c.visibility = 'user'
    GROUP BY uc.user_id
),
spans_by_user AS (
    -- Over ALL audit rows, not just terminal ones, so "first" is the real first submit.
    SELECT user_id, MIN(created_at) AS first_attempt_at, MAX(created_at) AS last_attempt_at
    FROM company_add_attempts GROUP BY user_id
)
SELECT r.user_id, u.email, u.display_name,
       COUNT(*)::int AS attempts,
       COUNT(*) FILTER (WHERE r.derived_outcome='added')::int          AS added,
       COUNT(*) FILTER (WHERE r.derived_outcome='refused')::int        AS refused,
       COUNT(*) FILTER (WHERE r.derived_outcome='stuck')::int          AS stuck,
       COUNT(*) FILTER (WHERE r.derived_outcome='pending')::int        AS pending,
       COUNT(*) FILTER (WHERE r.derived_outcome='already_public')::int AS already_public,
       COUNT(*) FILTER (WHERE r.derived_outcome
             IN ('unsupported','empty','probe_failed'))::int           AS other_failed,
       COALESCE(o.owns_now, 0) AS owns_now,
       sb.first_attempt_at, sb.last_attempt_at
FROM resolved r
LEFT JOIN users u  ON u.id = r.user_id
LEFT JOIN owns  o  ON o.user_id = r.user_id
JOIN spans_by_user sb ON sb.user_id = r.user_id
GROUP BY r.user_id, u.email, u.display_name, o.owns_now,
         sb.first_attempt_at, sb.last_attempt_at
ORDER BY attempts DESC, last_attempt_at DESC
LIMIT %(limit)s
"""


def list_add_attempts(
    conn: Connection,
    *,
    limit: int = 25,
    offset: int = 0,
    outcome: str | None = None,
    user_id: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    """One page of collapsed add attempts, plus the unfiltered outcome tally
    and per-user rollup.

    Filters run on the OUTER ``resolved`` CTE — i.e. AFTER the collapse.
    Filtering ``company_add_attempts`` first would surface superseded interim
    rows (a ``refused`` row that a later retry turned into an ``added``).
    """
    cur = conn.cursor()
    try:
        if not _schema_present(cur):
            return {
                "attempts": [],
                "total": 0,
                "by_outcome": {},
                "users": [],
                "users_truncated": False,
                "schema_present": False,
            }

        cur.execute(
            _ATTEMPT_ROWS_SQL,
            {
                "stuck_after_s": _STUCK_AFTER_SECONDS,
                "limit": limit,
                "offset": offset,
                "outcome": _clean(outcome),
                "user_id": _clean(user_id),
                "search": _clean(search),
            },
        )
        rows = [dict(r) for r in cur.fetchall()]
        total = int(rows[0]["total"]) if rows else 0
        for row in rows:
            row.pop("total", None)
            step, reason = _split_error_detail(row["error_detail"])
            row["failed_step"] = step
            row["failure_reason"] = reason
            row["discovery_steps"] = _normalize_steps(row["discovery_steps"])

        tally = _outcome_tally(cur)
        by_outcome = {o: tally[o] for o in _ALL_OUTCOMES}

        cur.execute(
            _USER_ROLLUP_SQL,
            {"stuck_after_s": _STUCK_AFTER_SECONDS, "limit": _USER_ROLLUP_CAP + 1},
        )
        users = [dict(r) for r in cur.fetchall()]
        users_truncated = len(users) > _USER_ROLLUP_CAP
        if users_truncated:
            users = users[:_USER_ROLLUP_CAP]

        return {
            "attempts": rows,
            "total": total,
            "by_outcome": by_outcome,
            "users": users,
            "users_truncated": users_truncated,
            "schema_present": True,
        }
    finally:
        cur.close()
        conn.rollback()
