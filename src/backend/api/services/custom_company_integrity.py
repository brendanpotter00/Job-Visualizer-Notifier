"""Consistency check: a ``visibility='user'`` company with no owner cannot exist.

Why this exists
---------------
Every path that creates a private company creates its ``user_companies`` row in the
same statement block (``add_custom_company``, ``add_discovering_placeholder``,
``add_discovered_company``, ``record_discovery_refusal``), and
``remove_owned_company`` purges the company outright once the last owner goes. So the
model says "private company, zero owners" is unreachable. The dev database holds
``u-6hkpc6fh0z`` ("Amazon (live check)"): **100 job rows, zero owners** — produced by a
test path, ``enabled=false``, invisible to every UI (the list JOINs
``user_companies``), and un-deletable through the API, because the only delete route
first proves the caller owns it. Nothing would ever have reported it.

That matters beyond tidiness. The question this whole surface has to answer is *how
many private boards are actually being used by users*, and an ownerless row is counted
by every naive ``visibility='user'`` query while belonging to nobody. Worse, an
ownerless row that is still ``enabled`` keeps drawing a nightly harvest — real requests
to a stranger's board, real job rows, real enrichment claim budget — on behalf of no
account.

Why a check and not a foreign key
---------------------------------
``user_companies.company_id`` is a soft link with no FK **on purpose** (house style;
see :class:`api.db_models.UserCompany`): ``companies`` is truncated freely in tests and
the ownership row's lifecycle is owned by the delete endpoint. A FK or trigger would
make the state unrepresentable at the cost of a schema constraint the rest of the
codebase deliberately does not have. Reporting is also the reversible half — a reaper
is a delete path, and any reaper written later must reuse ``remove_owned_company``'s
purge ORDER (job_locations with its NOT EXISTS guard → job_tags → job_enrichment →
job_listings → company_harvests / scrape_runs / company_scripts → companies), never
invent a second one.

Connection contract: SELECT-only, never commits, always rolls back so the caller's
pooled connection is never left idle-in-transaction (that pins the xmin horizon and
blocks vacuum — cf. ``docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md``).
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg2
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)

# Bounded read (root CLAUDE.md memory rule). The COUNT is computed separately from the
# listing, so a truncated list still reports an honest total rather than "100".
ORPHAN_LIST_CAP = 100

# ``NOT EXISTS`` rather than a LEFT JOIN + ``HAVING count(uc.*) = 0``: it stops at the
# first ownership row instead of aggregating over all of them, and it cannot be broken
# by someone later adding a second join to the query.
#
# ``visibility = 'user'`` is the whole predicate. A ``visibility='public'`` company has
# no owner BY DESIGN — all 129 curated rows would otherwise be reported as orphans,
# which would make this check useless on its first run and get it switched off.
#
# Jobs are counted by ``source_id = 'custom:' || c.id``, the private namespace, and not
# by ``company = c.id``. That is the same scoping ``remove_owned_company`` purges on, so
# the blast radius reported here is exactly the blast radius a cleanup would remove.
_ORPHAN_WHERE = """
    FROM companies c
    WHERE c.visibility = 'user'
      AND NOT EXISTS (
            SELECT 1 FROM user_companies uc WHERE uc.company_id = c.id
          )
"""

_ORPHAN_COUNT_SQL = f"SELECT count(*) AS n {_ORPHAN_WHERE}"

_ORPHAN_LIST_SQL = f"""
    SELECT c.id                AS company_id,
           c.display_name      AS display_name,
           c.enabled           AS enabled,
           c.created_at        AS created_at,
           (SELECT count(*) FROM job_listings j
             WHERE j.source_id = 'custom:' || c.id)                       AS job_count,
           (SELECT count(*) FROM job_listings j
             WHERE j.source_id = 'custom:' || c.id AND j.status = 'OPEN')  AS open_job_count
    {_ORPHAN_WHERE}
    ORDER BY c.enabled DESC, c.created_at ASC, c.id ASC
    LIMIT %s
"""


def _regclass(cur: Any, name: str) -> bool:
    """True when ``to_regclass(name)`` resolves (table exists on the search_path).

    Resolved against the search_path, never hardcoded to ``public``: tests run inside a
    per-worker schema, and ``user_companies`` is absent entirely in any environment
    where E7 has not been deployed yet — production, today.
    """
    cur.execute("SELECT to_regclass(%s) AS oid", (name,))
    row = cur.fetchone()
    return (row["oid"] if isinstance(row, dict) else row[0]) is not None


def get_ownerless_custom_companies(
    conn: Connection, limit: int = ORPHAN_LIST_CAP
) -> dict[str, Any]:
    """Report every ``visibility='user'`` company with zero ``user_companies`` rows.

    Returns ``{schemaPresent, ownerlessCount, ownerless: [...]}`` with camelCase keys
    (serialized straight to JSON by the route). ``ownerless`` is capped at ``limit`` and
    ordered worst-first: still-``enabled`` rows lead, because those are the ones burning
    a nightly harvest for nobody, then oldest first.

    ``schemaPresent`` is false — with an empty list, not an error — when
    ``user_companies`` does not exist. Without that guard this endpoint 500s in every
    environment where E7 has not shipped, which is every environment that most needs a
    green health check.
    """
    try:
        with conn.cursor() as cursor:
            if not _regclass(cursor, "user_companies"):
                return {"schemaPresent": False, "ownerlessCount": 0, "ownerless": []}

            cursor.execute(_ORPHAN_COUNT_SQL)
            count_row = cursor.fetchone()
            total = int((count_row["n"] if count_row else 0) or 0)

            cursor.execute(_ORPHAN_LIST_SQL, (limit,))
            rows = cursor.fetchall()
    except psycopg2.Error:
        conn.rollback()
        logger.exception("get_ownerless_custom_companies failed")
        raise
    finally:
        try:
            conn.rollback()
        except psycopg2.Error:
            pass

    ownerless = [
        {
            "companyId": r["company_id"],
            "displayName": r["display_name"],
            "enabled": bool(r["enabled"]),
            "createdAt": r["created_at"].isoformat() if r["created_at"] else None,
            "jobCount": int(r["job_count"] or 0),
            "openJobCount": int(r["open_job_count"] or 0),
        }
        for r in rows
    ]

    if total:
        # WARNING, not info: this is an unreachable state that was reached. The log line
        # is the signal for anyone not polling the endpoint.
        logger.warning(
            "custom-company integrity: %d private company/companies have zero owners "
            "(%d still enabled): %s",
            total,
            sum(1 for c in ownerless if c["enabled"]),
            ", ".join(c["companyId"] for c in ownerless[:10]),
        )

    return {"schemaPresent": True, "ownerlessCount": total, "ownerless": ownerless}
