"""Admin-side write/read helpers for the location-normalization tables.

Kept separate from services.location_normalization (which is the Tier-1/Tier-2
pipeline path) so that module stays focused on the cache + worker writers. These
helpers back the admin endpoints in routers/admin.py:

* reset_job_normalization      -> POST /api/admin/jobs/{job_id}/normalize
* upsert_manual_alias          -> PUT  /api/admin/locations/aliases/{raw_text}
* list_aliases                 -> GET  /api/admin/locations/aliases
* reset_all_normalization      -> POST /api/admin/locations/re-normalize-all

Connection contract: the WRITE helpers commit internally (mirroring
services.admin_service.grant_admin/revoke_admin); the READ helper (list_aliases)
issues only SELECTs and does not commit. On psycopg2 error the write helpers
roll back and re-raise; the router translates to an HTTP status.

OVERWRITE / MANUAL-WINS semantics (Decision #10) live in upsert_manual_alias and
are documented at that function. The reset helpers feed the async (defer)
endpoints: the router resets status via these (sync) then awaits defer_async.
"""

from __future__ import annotations

import logging
from typing import Sequence

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

from .location_normalization import normalize_string  # noqa: F401  (re-export convenience)

logger = logging.getLogger(__name__)

_JOB_LISTINGS = sql.Identifier("job_listings")
_LOCATIONS = sql.Identifier("locations")
_LOCATION_ALIASES = sql.Identifier("location_aliases")
_ALIAS_LOCATIONS = sql.Identifier("alias_locations")


def _scalar(row, key: str):
    """Read a column from a RealDict row or a plain tuple (first col)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row[key]
    return row[0]


# --- reset one job's normalization status (feeds the per-job defer endpoint) --

def reset_job_normalization(conn: Connection, job_id: str) -> bool:
    """Reset job_listings.normalization_status to NULL for one job.

    Returns True if a row matched (job exists), False otherwise (router -> 404).
    Keys on `id` alone — globally unique in practice; normalize_location does
    likewise. Commits on success. Rolls back + re-raises on psycopg2 error.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "UPDATE {} SET normalization_status = NULL WHERE id = %s"
                ).format(_JOB_LISTINGS),
                (job_id,),
            )
            matched = cur.rowcount > 0
        conn.commit()
        return matched
    except psycopg2.Error:
        conn.rollback()
        logger.exception("reset_job_normalization failed for job_id=%r", job_id)
        raise


# --- manual override: upsert a source='manual' alias mapping (manual wins) ----

def _upsert_location(cur, spec) -> int:
    """Upsert one location spec, return its locations.id.

    Same shape as services.location_normalization.persist_llm_result: insert
    with ON CONFLICT ON CONSTRAINT uq_locations_canonical DO NOTHING RETURNING
    id; on conflict (DO NOTHING returns no row) resolve the existing id with an
    IS NOT DISTINCT FROM lookup (required because uq_locations_canonical is
    NULLS NOT DISTINCT and several cols are nullable).

    `spec` is a models.LocationSpec (has .canonical_name/.kind/.city/.region/
    .country/.remote_scope).
    """
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (canonical_name, kind, city, region, country, remote_scope) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT ON CONSTRAINT uq_locations_canonical DO NOTHING RETURNING id"
        ).format(_LOCATIONS),
        (spec.canonical_name, spec.kind, spec.city, spec.region,
         spec.country, spec.remote_scope),
    )
    row = cur.fetchone()
    if row is not None:
        return int(_scalar(row, "id"))
    cur.execute(
        sql.SQL(
            "SELECT id FROM {} WHERE kind = %s "
            "AND city IS NOT DISTINCT FROM %s AND region IS NOT DISTINCT FROM %s "
            "AND country IS NOT DISTINCT FROM %s AND remote_scope IS NOT DISTINCT FROM %s"
        ).format(_LOCATIONS),
        (spec.kind, spec.city, spec.region, spec.country, spec.remote_scope),
    )
    existing = cur.fetchone()
    if existing is None:
        raise RuntimeError(
            "locations upsert conflicted but no matching row found for "
            f"kind={spec.kind!r} city={spec.city!r} region={spec.region!r} "
            f"country={spec.country!r} remote_scope={spec.remote_scope!r}"
        )
    return int(_scalar(existing, "id"))


def upsert_manual_alias(
    conn: Connection, raw_text_key: str, location_specs: Sequence
) -> dict:
    """Create/overwrite a source='manual' alias mapping. Manual WINS.

    `raw_text_key` MUST be the normalize_string()'d key (router normalizes the
    URL path segment before calling). `location_specs` is a non-empty ordered
    list of models.LocationSpec.

    Semantics (Decision #10 — spelled out):
      1. Upsert each location into `locations` (NULLS-NOT-DISTINCT dedup).
      2. Upsert the alias row as source='manual', confidence=1.0 with
         ON CONFLICT (raw_text) DO UPDATE SET source='manual', confidence=1.0.
         DO UPDATE (NOT DO NOTHING like persist_llm_result) is deliberate:
         manual must PROMOTE/overwrite a previously-cached 'llm' alias for the
         same key so the operator's correction wins.
      3. REPLACE the mapping: DELETE all alias_locations rows for the key, then
         INSERT the new ordered rows (position = index). This overwrites a
         previous (possibly wrong) llm mapping wholesale.
    Manual persistence guarantee: a later LLM run for the same string calls
    persist_llm_result, whose `location_aliases` INSERT is ON CONFLICT (raw_text)
    DO NOTHING — so it will NOT clobber the manual alias. Manual persists.

    Commits on success. Rolls back + re-raises on psycopg2 error.
    Returns a dict {raw_text, source, confidence, locations:[{...,position}]}.
    """
    try:
        with conn.cursor() as cur:
            location_ids: list[int] = []
            for spec in location_specs:
                location_ids.append(_upsert_location(cur, spec))

            cur.execute(
                sql.SQL(
                    "INSERT INTO {} (raw_text, source, confidence) "
                    "VALUES (%s, 'manual', 1.0) "
                    "ON CONFLICT (raw_text) DO UPDATE "
                    "SET source = 'manual', confidence = 1.0"
                ).format(_LOCATION_ALIASES),
                (raw_text_key,),
            )

            cur.execute(
                sql.SQL("DELETE FROM {} WHERE raw_text = %s").format(_ALIAS_LOCATIONS),
                (raw_text_key,),
            )
            for position, loc_id in enumerate(location_ids):
                cur.execute(
                    sql.SQL(
                        "INSERT INTO {} (raw_text, normalized_location_id, position) "
                        "VALUES (%s, %s, %s)"
                    ).format(_ALIAS_LOCATIONS),
                    (raw_text_key, loc_id, position),
                )
        conn.commit()
        result = _read_alias(conn, raw_text_key)
        if result is None:
            # Should never happen: we just inserted the alias above.
            raise RuntimeError(
                f"upsert_manual_alias wrote key={raw_text_key!r} but read-back found nothing"
            )
        return result
    except psycopg2.Error:
        conn.rollback()
        logger.exception("upsert_manual_alias failed for key=%r", raw_text_key)
        raise


def _read_alias(conn: Connection, raw_text_key: str) -> dict | None:
    """Read one alias + its ordered mapped locations (read-only)."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT raw_text, source, confidence FROM {} WHERE raw_text = %s").format(
                _LOCATION_ALIASES
            ),
            (raw_text_key,),
        )
        alias = cur.fetchone()
        if alias is None:
            return None
        cur.execute(
            sql.SQL(
                "SELECT l.id, l.canonical_name, l.kind, l.city, l.region, "
                "l.country, l.remote_scope, al.position "
                "FROM {alias_locations} AS al "
                "JOIN {locations} AS l ON l.id = al.normalized_location_id "
                "WHERE al.raw_text = %s ORDER BY al.position"
            ).format(alias_locations=_ALIAS_LOCATIONS, locations=_LOCATIONS),
            (raw_text_key,),
        )
        locs = cur.fetchall()
    return {
        "raw_text": _scalar(alias, "raw_text"),
        "source": _scalar(alias, "source"),
        "confidence": (alias["confidence"] if isinstance(alias, dict) else alias[2]),
        "locations": [_row_to_loc(r) for r in locs],
    }


def _row_to_loc(r) -> dict:
    if isinstance(r, dict):
        return {
            "id": r["id"], "canonical_name": r["canonical_name"], "kind": r["kind"],
            "city": r["city"], "region": r["region"], "country": r["country"],
            "remote_scope": r["remote_scope"], "position": r["position"],
        }
    return {
        "id": r[0], "canonical_name": r[1], "kind": r[2], "city": r[3],
        "region": r[4], "country": r[5], "remote_scope": r[6], "position": r[7],
    }


# --- inspect: list aliases (bounded) -----------------------------------------

def list_aliases(
    conn: Connection, contains: str | None, limit: int
) -> list[dict]:
    """List aliases (bounded), optionally filtered by raw_text ILIKE %contains%.

    READ-ONLY: only SELECTs, no commit. `limit` is ALWAYS applied (caller caps
    it; the root CLAUDE.md memory rule forbids unbounded reads). The ILIKE
    parameter is parameterized (never string-formatted): the pattern is built in
    Python as f"%{contains}%" and passed as a bind param against a plain
    `WHERE raw_text ILIKE %s` — fully parameterized (the value, not the column,
    is bound), sidestepping any literal-`%` quoting ambiguity in sql.SQL.
    Returns a list of the same dict shape as _read_alias's result.
    """
    with conn.cursor() as cur:
        if contains:
            cur.execute(
                sql.SQL(
                    "SELECT raw_text FROM {} WHERE raw_text ILIKE %s "
                    "ORDER BY created_at DESC LIMIT %s"
                ).format(_LOCATION_ALIASES),
                (f"%{contains}%", limit),
            )
        else:
            cur.execute(
                sql.SQL(
                    "SELECT raw_text FROM {} ORDER BY created_at DESC LIMIT %s"
                ).format(_LOCATION_ALIASES),
                (limit,),
            )
        keys = [_scalar(r, "raw_text") for r in cur.fetchall()]
    return [a for k in keys if (a := _read_alias(conn, k)) is not None]


# --- break-glass: reset all normalization (feeds re-normalize-all) ------------

def reset_all_normalization(conn: Connection) -> int:
    """Reset every non-NULL normalization_status back to NULL. Returns count.

    Break-glass (Decision #10 / F3). Conservative: only flips done/failed rows
    back to NULL (WHERE normalization_status IS NOT NULL) so the pipeline
    re-runs them. Does NOT clear the alias cache — re-linking uses the current
    cache (incl. manual overrides), which is cheap (mostly Tier-1 hits) and
    PRESERVES manual corrections. Commits. Rolls back + re-raises on error.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "UPDATE {} SET normalization_status = NULL "
                    "WHERE normalization_status IS NOT NULL"
                ).format(_JOB_LISTINGS),
            )
            count = cur.rowcount
        conn.commit()
        return count
    except psycopg2.Error:
        conn.rollback()
        logger.exception("reset_all_normalization failed")
        raise
