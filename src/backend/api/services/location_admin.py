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
from typing import Any, Sequence

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

from ..models import LocationSpec
from .db_rows import scalar
from .location_canonicalize import canonicalize
from .location_normalization import normalize_string

logger = logging.getLogger(__name__)

_JOB_LISTINGS = sql.Identifier("job_listings")
_LOCATIONS = sql.Identifier("locations")
_LOCATION_ALIASES = sql.Identifier("location_aliases")
_ALIAS_LOCATIONS = sql.Identifier("alias_locations")

# alias_originals() prefilters candidate job rows in SQL before the Python SSOT
# verify. Bounded so a hot alias key (e.g. "remote") can't pull an unbounded set
# into memory. Saturating this cap means some originals may be omitted — a
# display-only limitation we log (see alias_originals).
_ALIAS_ORIGINALS_PREFILTER_CAP = 500


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
        return bool(matched)
    except psycopg2.Error:
        conn.rollback()
        logger.exception("reset_job_normalization failed for job_id=%r", job_id)
        raise


# --- manual override: upsert a source='manual' alias mapping (manual wins) ----

def _upsert_location(cur: Any, spec: LocationSpec) -> int:
    """Upsert one location spec, return its locations.id.

    Same shape as services.location_normalization.persist_llm_result: insert
    with ON CONFLICT ON CONSTRAINT uq_locations_canonical DO NOTHING RETURNING
    id; on conflict (DO NOTHING returns no row) resolve the existing id with an
    IS NOT DISTINCT FROM lookup (required because uq_locations_canonical is
    NULLS NOT DISTINCT and several cols are nullable).

    `spec` is a models.LocationSpec (has .canonical_name/.kind/.city/.region/
    .country/.remote_scope). The spec is canonicalized first (same pass as the
    LLM write path) so manual overrides land on the same canonical codes/labels.
    """
    c = canonicalize(spec)
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (canonical_name, kind, city, region, country, remote_scope) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT ON CONSTRAINT uq_locations_canonical DO NOTHING RETURNING id"
        ).format(_LOCATIONS),
        (c.canonical_name, c.kind, c.city, c.region, c.country, c.remote_scope),
    )
    row = cur.fetchone()
    if row is not None:
        return int(scalar(row, "id"))
    cur.execute(
        sql.SQL(
            "SELECT id FROM {} WHERE kind = %s "
            "AND city IS NOT DISTINCT FROM %s AND region IS NOT DISTINCT FROM %s "
            "AND country IS NOT DISTINCT FROM %s AND remote_scope IS NOT DISTINCT FROM %s"
        ).format(_LOCATIONS),
        (c.kind, c.city, c.region, c.country, c.remote_scope),
    )
    existing = cur.fetchone()
    if existing is None:
        raise RuntimeError(
            "locations upsert conflicted but no matching row found for "
            f"kind={c.kind!r} city={c.city!r} region={c.region!r} "
            f"country={c.country!r} remote_scope={c.remote_scope!r}"
        )
    return int(scalar(existing, "id"))


def upsert_manual_alias(
    conn: Connection, raw_text_key: str, location_specs: Sequence[LocationSpec]
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
            # Dedup preserving first-seen order (mirrors persist_llm_result): two
            # specs resolving to the same locations.id (same canonical identity,
            # possibly different canonical_name) must not double-insert — the
            # alias_locations INSERT below has no ON CONFLICT, so a duplicate
            # would PK-violate and turn the whole override into a 500.
            seen: set[int] = set()
            deduped: list[int] = []
            for lid in location_ids:
                if lid not in seen:
                    seen.add(lid)
                    deduped.append(lid)
            location_ids = deduped

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
        "raw_text": scalar(alias, "raw_text"),
        "source": scalar(alias, "source"),
        "confidence": (alias["confidence"] if isinstance(alias, dict) else alias[2]),
        "locations": [_row_to_loc(r) for r in locs],
    }


def _row_to_loc(r: Any) -> dict:
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
    conn: Connection, contains: str | None, limit: int, offset: int = 0
) -> list[dict]:
    """List aliases (bounded), optionally filtered by raw_text ILIKE %contains%.

    READ-ONLY: only SELECTs, no commit. `limit` is ALWAYS applied (caller caps
    it; the root CLAUDE.md memory rule forbids unbounded reads). `offset`
    paginates (default 0). The ILIKE parameter is parameterized (never
    string-formatted): the pattern is built in Python as f"%{contains}%" and
    passed as a bind param against a plain `WHERE raw_text ILIKE %s` — fully
    parameterized (the value, not the column, is bound), sidestepping any
    literal-`%` quoting ambiguity in sql.SQL.
    Returns a list of the same dict shape as _read_alias's result.
    """
    with conn.cursor() as cur:
        if contains:
            cur.execute(
                sql.SQL(
                    "SELECT raw_text FROM {} WHERE raw_text ILIKE %s "
                    "ORDER BY created_at DESC LIMIT %s OFFSET %s"
                ).format(_LOCATION_ALIASES),
                (f"%{contains}%", limit, offset),
            )
        else:
            cur.execute(
                sql.SQL(
                    "SELECT raw_text FROM {} ORDER BY created_at DESC LIMIT %s OFFSET %s"
                ).format(_LOCATION_ALIASES),
                (limit, offset),
            )
        keys = [scalar(r, "raw_text") for r in cur.fetchall()]
    return [a for k in keys if (a := _read_alias(conn, k)) is not None]


def count_aliases(conn: Connection, contains: str | None) -> int:
    """Count aliases matching the same (optional) ILIKE filter as list_aliases.

    READ-ONLY: a single bounded `SELECT count(*)`. The ILIKE pattern is
    parameterized exactly as in list_aliases. Feeds AdminAliasListResponse.total
    so the UI can paginate (total is independent of the page `limit`).
    """
    with conn.cursor() as cur:
        if contains:
            cur.execute(
                sql.SQL("SELECT count(*) AS n FROM {} WHERE raw_text ILIKE %s").format(
                    _LOCATION_ALIASES
                ),
                (f"%{contains}%",),
            )
        else:
            cur.execute(
                sql.SQL("SELECT count(*) AS n FROM {}").format(_LOCATION_ALIASES),
            )
        return int(scalar(cur.fetchone(), "n") or 0)


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
        return int(count)
    except psycopg2.Error:
        conn.rollback()
        logger.exception("reset_all_normalization failed")
        raise


# --- monitor read helpers (SELECT-only; never commit; rollback on error) ------
#
# These three back the inspection panels of the admin Location-Normalization
# Monitor. They read the alias/job/location cache and NEVER write. On a
# psycopg2 error each rolls back (so the caller's connection is never left
# mid-transaction) and re-raises; the router logs + 500s.


def reverse_lookup_locations(
    conn: Connection, contains: str | None, limit: int
) -> list[dict]:
    """Canonical locations (optionally filtered) + every raw_text mapping to each.

    Searches `locations.canonical_name ILIKE %contains%` (parameterized) when
    `contains` is given, else returns up to `limit` recent locations. Bounded by
    `limit` (caller caps it). Then one `alias_locations` query resolves the
    raw_texts for the matched location ids; rawTexts are grouped per location in
    Python.

    READ-ONLY. Returns a list of
    ``{"location": {id,canonical_name,kind,city,region,country,remote_scope},
       "raw_texts": [str, ...]}`` ordered by the location query (newest first).
    """
    try:
        with conn.cursor() as cur:
            if contains:
                cur.execute(
                    sql.SQL(
                        "SELECT id, canonical_name, kind, city, region, country, "
                        "remote_scope FROM {} WHERE canonical_name ILIKE %s "
                        "ORDER BY created_at DESC, id DESC LIMIT %s"
                    ).format(_LOCATIONS),
                    (f"%{contains}%", limit),
                )
            else:
                cur.execute(
                    sql.SQL(
                        "SELECT id, canonical_name, kind, city, region, country, "
                        "remote_scope FROM {} ORDER BY created_at DESC, id DESC LIMIT %s"
                    ).format(_LOCATIONS),
                    (limit,),
                )
            loc_rows = cur.fetchall()
            locations: list[dict[str, Any]] = []
            id_order: list[int] = []
            by_id: dict[int, dict[str, Any]] = {}
            for r in loc_rows:
                loc = {
                    "id": int(scalar(r, "id")),
                    "canonical_name": r["canonical_name"] if isinstance(r, dict) else r[1],
                    "kind": r["kind"] if isinstance(r, dict) else r[2],
                    "city": r["city"] if isinstance(r, dict) else r[3],
                    "region": r["region"] if isinstance(r, dict) else r[4],
                    "country": r["country"] if isinstance(r, dict) else r[5],
                    "remote_scope": r["remote_scope"] if isinstance(r, dict) else r[6],
                }
                entry: dict[str, Any] = {"location": loc, "raw_texts": []}
                locations.append(entry)
                id_order.append(loc["id"])
                by_id[loc["id"]] = entry

            if id_order:
                cur.execute(
                    sql.SQL(
                        "SELECT normalized_location_id, raw_text FROM {} "
                        "WHERE normalized_location_id = ANY(%s) "
                        "ORDER BY normalized_location_id, raw_text"
                    ).format(_ALIAS_LOCATIONS),
                    (id_order,),
                )
                for r in cur.fetchall():
                    loc_id = int(scalar(r, "normalized_location_id"))
                    raw = r["raw_text"] if isinstance(r, dict) else r[1]
                    target = by_id.get(loc_id)
                    if target is not None:
                        target["raw_texts"].append(raw)
        return locations
    except psycopg2.Error:
        conn.rollback()
        logger.exception("reverse_lookup_locations failed (contains=%r)", contains)
        raise


def alias_originals(conn: Connection, raw_text: str, limit: int) -> dict:
    """Verbatim job `location` strings that normalize to the alias key `raw_text`.

    There is NO stored job->alias link: the link is implicit via
    ``normalize_string(job_listings.location) == raw_text``. This reconstructs
    it for display.

    Implementation:
      1. SQL prefilter (bounded to 500): rows whose location, after a SQL-side
         case+whitespace fold, equals `raw_text`. This narrows the candidate set
         cheaply.
      2. Python verify: keep only rows where ``normalize_string(location)``
         exactly equals `raw_text` (the SSOT normalizer) — guarantees no false
         positives.
      3. Group distinct verbatim location strings -> their jobIds; cap the number
         of distinct originals at `limit`.

    ``total`` is the count of distinct originals actually RETURNED — i.e. it
    always equals ``len(originals)``, bounded by both `limit` and the
    ``_ALIAS_ORIGINALS_PREFILTER_CAP``-row SQL prefilter. It is NOT a
    filter-independent grand total (unlike list_aliases/list_problem_jobs
    ``total``); this is a display feature, so there is no full count to report.

    Caveats (both display-only, never integrity guarantees):
      * The SQL prefilter folds case and whitespace but NOT exotic NFKC or
        dash-only Unicode variants. An original differing from `raw_text` ONLY by
        such a variant may be missed by the prefilter and so not appear here. The
        alias key itself is always produced by the full normalize_string SSOT.
      * If the prefilter saturates its row cap, some originals may be omitted;
        we log a warning so the truncation is visible rather than silent.

    READ-ONLY. Returns ``{"raw_text", "total", "originals": [{"original",
    "job_ids": [str, ...]}, ...]}``.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT id, location FROM {} "
                    "WHERE location IS NOT NULL AND btrim(location) <> '' "
                    "AND lower(btrim(regexp_replace(location, '\\s+', ' ', 'g'))) = %(key)s "
                    "LIMIT %(cap)s"
                ).format(_JOB_LISTINGS),
                {"key": raw_text, "cap": _ALIAS_ORIGINALS_PREFILTER_CAP},
            )
            rows = cur.fetchall()
    except psycopg2.Error:
        conn.rollback()
        logger.exception("alias_originals prefilter failed (raw_text=%r)", raw_text)
        raise

    if len(rows) >= _ALIAS_ORIGINALS_PREFILTER_CAP:
        logger.warning(
            "alias_originals prefilter hit the %d-row cap for raw_text=%r; some "
            "originals may be omitted (display-only feature)",
            _ALIAS_ORIGINALS_PREFILTER_CAP,
            raw_text,
        )

    # Group distinct verbatim location strings -> jobIds, preserving first-seen
    # order. Verify each candidate with the SSOT normalizer (no false positives).
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for r in rows:
        job_id = r["id"] if isinstance(r, dict) else r[0]
        location = r["location"] if isinstance(r, dict) else r[1]
        if normalize_string(location) != raw_text:
            continue
        if location not in grouped:
            grouped[location] = []
            order.append(location)
        grouped[location].append(str(job_id))

    capped = order[:limit]
    originals = [{"original": loc, "job_ids": grouped[loc]} for loc in capped]
    return {"raw_text": raw_text, "total": len(capped), "originals": originals}


def list_problem_jobs(conn: Connection, limit: int, offset: int) -> dict:
    """Actionable failed jobs: failed status with a NON-blank location.

    Filter: ``normalization_status='failed' AND location IS NOT NULL AND
    btrim(location) <> ''`` — blank-location failures are excluded (nothing to
    fix there). Ordered by ``last_seen_at DESC``, paginated by limit/offset.
    ``total`` is a bounded count of the same filter (independent of the page).

    READ-ONLY. Returns ``{"jobs": [{id, title, company, location,
    normalization_status, last_seen_at}, ...], "total": int}``.
    """
    _filter = (
        "normalization_status='failed' AND location IS NOT NULL "
        "AND btrim(location) <> ''"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT id, title, company, location, normalization_status, "
                    "last_seen_at FROM {} WHERE " + _filter +
                    " ORDER BY last_seen_at DESC LIMIT %s OFFSET %s"
                ).format(_JOB_LISTINGS),
                (limit, offset),
            )
            rows = cur.fetchall()
            cur.execute(
                sql.SQL("SELECT count(*) AS n FROM {} WHERE " + _filter).format(
                    _JOB_LISTINGS
                ),
            )
            total = int(scalar(cur.fetchone(), "n") or 0)
    except psycopg2.Error:
        conn.rollback()
        logger.exception("list_problem_jobs failed (limit=%s offset=%s)", limit, offset)
        raise

    jobs = []
    for r in rows:
        if isinstance(r, dict):
            last_seen = r["last_seen_at"]
            jobs.append(
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "company": r["company"],
                    "location": r["location"],
                    "normalization_status": r["normalization_status"],
                    "last_seen_at": last_seen.isoformat() if last_seen is not None else None,
                }
            )
        else:
            last_seen = r[5]
            jobs.append(
                {
                    "id": str(r[0]),
                    "title": r[1],
                    "company": r[2],
                    "location": r[3],
                    "normalization_status": r[4],
                    "last_seen_at": last_seen.isoformat() if last_seen is not None else None,
                }
            )
    return {"jobs": jobs, "total": total}
