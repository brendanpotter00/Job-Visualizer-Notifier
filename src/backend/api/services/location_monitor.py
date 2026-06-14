"""Self-contained health + integrity SQL for the admin Location-Normalization Monitor.

This module is the READ-ONLY backing for two admin endpoints:

* get_health    -> GET /api/admin/locations/health
* get_integrity -> GET /api/admin/locations/integrity

Why self-contained: the operational runbook ships a separate ``monitor_prod.py``
script, but that script is NOT on this branch. Rather than import from it (and
couple the live admin surface to an ops-only tool that may not exist), the exact
health/integrity SQL is embedded here verbatim as module data.

Connection contract (SELECT-only): every function issues only ``SELECT``
statements and NEVER commits. ``conn.rollback()`` runs in a ``finally`` so the
caller's connection is never left mid-transaction. On a ``psycopg2.Error`` the
error propagates to the router, which logs + 500s.

Search-path correctness (load-bearing): tests run inside a per-worker Postgres
schema via ``SET search_path`` (see conftest.db_conn). ALL table-existence
checks use ``to_regclass('<name>')`` — which resolves against the active
search_path — so the guards work identically in the test schema and in prod.
We never hardcode ``public``. ``procrastinate_jobs`` / ``procrastinate_events``
are NOT ORM tables and are ABSENT in the default test schema; the to_regclass
guard around the queue/throughput queries is what keeps the endpoint green
there (returning ``normalizeQueue={}`` and ``throughputInWindow=None``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import psycopg2

from ..config import settings

logger = logging.getLogger(__name__)


# --- integrity checks (module data; embedded SQL is the source of truth) ------


@dataclass(frozen=True)
class IntegrityCheck:
    """One integrity probe. ``sql`` returns a single column ``n`` (a count).

    ``severity_when_nonzero`` is the severity reported when ``n > 0``; when
    ``n == 0`` the reported severity is always ``"ok"`` (the router maps this).
    """

    id: str
    label: str
    sql: str
    severity_when_nonzero: str  # "warn" | "crit"


# C1..C9, in id order. C1 and C3 are crit; the rest are warn.
INTEGRITY_CHECKS: list[IntegrityCheck] = [
    IntegrityCheck(
        id="C1",
        label="Done jobs without locations",
        sql=(
            "SELECT count(*) AS n FROM job_listings jl "
            "WHERE jl.normalization_status='done' "
            "AND NOT EXISTS (SELECT 1 FROM job_locations l "
            "WHERE l.job_listing_id = jl.id)"
        ),
        severity_when_nonzero="crit",
    ),
    IntegrityCheck(
        id="C2",
        label="Aliases without children",
        sql=(
            "SELECT count(*) AS n FROM location_aliases a "
            "WHERE NOT EXISTS (SELECT 1 FROM alias_locations al "
            "WHERE al.raw_text = a.raw_text)"
        ),
        severity_when_nonzero="warn",
    ),
    IntegrityCheck(
        id="C3",
        label="Job ID collisions",
        sql=(
            "SELECT count(*) AS n FROM "
            "(SELECT id FROM job_listings GROUP BY id HAVING count(*) > 1) t"
        ),
        severity_when_nonzero="crit",
    ),
    IntegrityCheck(
        id="C4",
        label="Orphan job_locations",
        sql=(
            "SELECT count(*) AS n FROM job_locations l "
            "WHERE NOT EXISTS (SELECT 1 FROM job_listings jl "
            "WHERE jl.id = l.job_listing_id)"
        ),
        severity_when_nonzero="warn",
    ),
    IntegrityCheck(
        id="C5",
        label="Remote locations with a city",
        sql="SELECT count(*) AS n FROM locations WHERE kind='remote' AND city IS NOT NULL",
        severity_when_nonzero="warn",
    ),
    IntegrityCheck(
        id="C6",
        label="City-kind locations missing city",
        sql="SELECT count(*) AS n FROM locations WHERE kind='city' AND city IS NULL",
        severity_when_nonzero="warn",
    ),
    IntegrityCheck(
        id="C7",
        label="Low-confidence LLM aliases",
        sql=(
            "SELECT count(*) AS n FROM location_aliases "
            "WHERE source='llm' AND confidence IS NOT NULL AND confidence < 0.5"
        ),
        severity_when_nonzero="warn",
    ),
    IntegrityCheck(
        id="C8",
        label="Geo populated (should be NULL in v1)",
        sql="SELECT count(*) AS n FROM locations WHERE lat IS NOT NULL OR lng IS NOT NULL",
        severity_when_nonzero="warn",
    ),
    IntegrityCheck(
        id="C9",
        label="Jobs with multiple primary locations",
        sql=(
            "SELECT count(*) AS n FROM "
            "(SELECT job_listing_id FROM job_locations WHERE is_primary "
            "GROUP BY job_listing_id HAVING count(*) > 1) t"
        ),
        severity_when_nonzero="warn",
    ),
]


# --- embedded health SQL ------------------------------------------------------

_SQL_A2_HEARTBEAT = (
    "SELECT extract(epoch FROM (now() - max(at)))/60.0 AS minutes_since_heartbeat "
    "FROM worker_heartbeats"
)

_SQL_B1_BACKLOG = (
    "SELECT "
    "count(*) FILTER (WHERE normalization_status IS NULL) AS null_backlog, "
    "count(*) FILTER (WHERE normalization_status IS NULL "
    "AND first_seen_at < now() - make_interval(hours => %(window_hours)s)) AS null_aged, "
    "count(*) FILTER (WHERE normalization_status='done') AS done, "
    "count(*) FILTER (WHERE normalization_status='failed') AS failed, "
    "count(*) AS total "
    "FROM job_listings"
)

_SQL_B2_FAILED = (
    "SELECT "
    "count(*) FILTER (WHERE normalization_status='failed' "
    "AND (location IS NULL OR btrim(location)='')) AS failed_blank, "
    "count(*) FILTER (WHERE normalization_status='failed' "
    "AND location IS NOT NULL AND btrim(location)<>'') AS failed_nonblank, "
    "count(*) FILTER (WHERE normalization_status='done') AS done "
    "FROM job_listings"
)

_SQL_D_NORMALIZE_QUEUE = (
    "SELECT status, count(*) AS n FROM procrastinate_jobs "
    "WHERE queue_name='normalize' GROUP BY status ORDER BY status"
)

_SQL_D_THROUGHPUT = (
    "SELECT count(*) AS n FROM procrastinate_events e "
    "JOIN procrastinate_jobs j ON j.id = e.job_id "
    "WHERE j.queue_name='normalize' AND e.type='succeeded' "
    "AND e.at > now() - make_interval(hours => %(window_hours)s)"
)


def _scalar(row, key: str):
    """Read a column from a RealDict row or a plain tuple (first col)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row[key]
    return row[0]


def _regclass(cur, name: str) -> bool:
    """True when ``to_regclass(name)`` resolves (table exists on search_path)."""
    cur.execute("SELECT to_regclass(%s) AS oid", (name,))
    return _scalar(cur.fetchone(), "oid") is not None


def _normalization_column_present(cur) -> bool:
    """True when job_listings exists AND has a normalization_status column.

    Search-path-correct (no hardcoded ``public``) AND non-raising: resolves the
    table via ``to_regclass`` (NULL off the active search_path) and looks the
    column up in ``pg_attribute`` by that oid. A missing table or column yields
    0 rows -> False without ever issuing a statement that errors.

    Non-raising is load-bearing: get_db hands out NON-autocommit connections, so
    a probe that raises (the old ``SELECT normalization_status ... LIMIT 0``)
    would abort the whole transaction and poison every subsequent health query
    — a fresh cursor does NOT clear an aborted transaction, that state is
    per-connection — turning a not-deployed schema into a 500 instead of a clean
    schema_present=False.
    """
    cur.execute(
        "SELECT count(*) AS n FROM pg_attribute "
        "WHERE attrelid = to_regclass('job_listings') "
        "AND attname = 'normalization_status' "
        "AND NOT attisdropped AND attnum > 0"
    )
    return int(_scalar(cur.fetchone(), "n") or 0) > 0


def get_health(conn, window_hours: int) -> dict:
    """Health snapshot for the monitor page. SELECT-only; never commits.

    Returns the AdminLocationHealthResponse dict (snake_case keys; the router's
    Pydantic model camelCases them). All table-existence checks are
    search-path-aware via ``to_regclass`` so they work inside the per-worker
    test schema and in prod alike.

    ``schemaPresent`` requires all four location tables to resolve AND
    job_listings to carry a normalization_status column. ``heartbeatAgeMinutes``
    is None when worker_heartbeats is absent or empty. ``normalizeQueue`` is {}
    and ``throughputInWindow`` is None when the procrastinate tables are absent
    (they are NOT ORM tables — absent in the default test schema). ``dormant``
    mirrors the runbook's dormancy inference: no key configured AND a large NULL
    backlog with nothing processed yet.
    """
    key_configured = bool(settings.anthropic_api_key)
    try:
        with conn.cursor() as cur:
            # Schema presence: all four location tables + normalization_status col.
            # Both probes are non-raising (see _normalization_column_present and
            # _regclass), so neither can abort the transaction.
            norm_col = _normalization_column_present(cur)
            schema_present = norm_col and all(
                _regclass(cur, t)
                for t in ("locations", "location_aliases", "alias_locations", "job_locations")
            )

            # Not deployed: the B1/B2 queries below reference normalization_status,
            # so running them now would raise UndefinedColumn — and on a
            # non-autocommit connection that 500s the request. Return a clean
            # zeroed snapshot instead; schema_present=False is the signal.
            if not schema_present:
                return {
                    "schema_present": False,
                    "window_hours": window_hours,
                    "null_backlog": 0,
                    "null_aged": 0,
                    "done": 0,
                    "failed": 0,
                    "total": 0,
                    "failed_blank": 0,
                    "failed_nonblank": 0,
                    "failed_nonblank_ratio": 0.0,
                    "heartbeat_age_minutes": None,
                    "normalize_queue": {},
                    "throughput_in_window": None,
                    "key_configured": key_configured,
                    "dormant": False,
                }

            # B1 backlog
            cur.execute(_SQL_B1_BACKLOG, {"window_hours": window_hours})
            b1 = cur.fetchone()
            null_backlog = int(_scalar(b1, "null_backlog") or 0)
            null_aged = int(_scalar(b1, "null_aged") or 0)
            done = int(_scalar(b1, "done") or 0)
            failed = int(_scalar(b1, "failed") or 0)
            total = int(_scalar(b1, "total") or 0)

            # B2 failed-blank / failed-nonblank
            cur.execute(_SQL_B2_FAILED)
            b2 = cur.fetchone()
            failed_blank = int(_scalar(b2, "failed_blank") or 0)
            failed_nonblank = int(_scalar(b2, "failed_nonblank") or 0)

            denom = done + failed_nonblank
            failed_nonblank_ratio = (
                100.0 * failed_nonblank / denom if denom > 0 else 0.0
            )

            # A2 heartbeat (guarded — worker_heartbeats may be absent)
            heartbeat_age_minutes = None
            if _regclass(cur, "worker_heartbeats"):
                cur.execute(_SQL_A2_HEARTBEAT)
                heartbeat_age_minutes = _scalar(cur.fetchone(), "minutes_since_heartbeat")
                if heartbeat_age_minutes is not None:
                    heartbeat_age_minutes = float(heartbeat_age_minutes)

            # D normalize queue + throughput (guarded — procrastinate tables are
            # NOT ORM tables and absent in the default test schema).
            normalize_queue: dict[str, int] = {}
            throughput_in_window = None
            if _regclass(cur, "procrastinate_jobs"):
                cur.execute(_SQL_D_NORMALIZE_QUEUE)
                for r in cur.fetchall():
                    normalize_queue[str(_scalar(r, "status"))] = int(_scalar(r, "n"))
                if _regclass(cur, "procrastinate_events"):
                    cur.execute(_SQL_D_THROUGHPUT, {"window_hours": window_hours})
                    throughput_in_window = int(_scalar(cur.fetchone(), "n") or 0)

        # dormant: no key AND a large NULL backlog with nothing processed yet
        # (done==0 and failed_nonblank==0) — the runbook's dormancy inference.
        dormant = (
            not key_configured
            and null_backlog > 0
            and done == 0
            and failed_nonblank == 0
        )

        return {
            "schema_present": schema_present,
            "window_hours": window_hours,
            "null_backlog": null_backlog,
            "null_aged": null_aged,
            "done": done,
            "failed": failed,
            "total": total,
            "failed_blank": failed_blank,
            "failed_nonblank": failed_nonblank,
            "failed_nonblank_ratio": failed_nonblank_ratio,
            "heartbeat_age_minutes": heartbeat_age_minutes,
            "normalize_queue": normalize_queue,
            "throughput_in_window": throughput_in_window,
            "key_configured": key_configured,
            "dormant": dormant,
        }
    except psycopg2.Error:
        conn.rollback()
        logger.exception("get_health failed (window_hours=%s)", window_hours)
        raise
    finally:
        # Read-only: always roll back so the caller's connection is never left
        # mid-transaction (mirrors location_admin.list_aliases discipline).
        try:
            conn.rollback()
        except psycopg2.Error:
            pass


def get_integrity(conn) -> dict:
    """Run every C1..C9 integrity check. SELECT-only; never commits.

    Returns {schemaPresent, checks:[{id,label,count,severity}]}. ``severity`` is
    "ok" when count==0, else the check's configured severity. ``schemaPresent``
    requires the four location tables to resolve AND job_listings to carry a
    normalization_status column (C1 references it). When the schema isn't
    deployed we return an empty check list rather than running the C1..C9 SQL,
    which would raise against the missing schema — and 500 the request on a
    non-autocommit connection.
    """
    try:
        with conn.cursor() as cur:
            schema_present = _normalization_column_present(cur) and all(
                _regclass(cur, t)
                for t in ("locations", "location_aliases", "alias_locations", "job_locations")
            )
            if not schema_present:
                return {"schema_present": False, "checks": []}
            checks = []
            for chk in INTEGRITY_CHECKS:
                cur.execute(chk.sql)
                count = int(_scalar(cur.fetchone(), "n") or 0)
                severity = "ok" if count == 0 else chk.severity_when_nonzero
                checks.append(
                    {"id": chk.id, "label": chk.label, "count": count, "severity": severity}
                )
        return {"schema_present": schema_present, "checks": checks}
    except psycopg2.Error:
        conn.rollback()
        logger.exception("get_integrity failed")
        raise
    finally:
        try:
            conn.rollback()
        except psycopg2.Error:
            pass
