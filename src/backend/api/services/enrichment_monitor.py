"""Admin + internal SQL for observing/steering the external-enrichment pipeline.

Backs the admin enrichment endpoints (health / needs-human queue / ticks /
recent / correct / re-enrich) and the internal corrections feed. Read functions
are SELECT-only and never commit (``conn.rollback()`` in a ``finally`` so the
pooled connection is never left mid-transaction); the two mutation functions
(``apply_correction`` / ``request_reenrich``) own their commit/rollback like
``location_admin``.

Search-path correctness: table-existence guards use ``to_regclass`` so they
behave identically inside the per-worker test schema and prod (mirrors
``location_monitor`` — see that module's docstring for why the probe must be
non-raising on a non-autocommit connection).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from psycopg2.extensions import connection as Connection

from ..config import settings
from .db_rows import scalar
from .enrichment_writer import CATEGORY_SLUGS, LEVEL_SLUGS, MAX_TAGS_PER_JOB

logger = logging.getLogger(__name__)

# The claimable-description predicate, shared by /pending, /sample and the
# eligible-backlog health count. COALESCE across the real per-ATS storage shapes
# (verified against prod 2026-07-12): Ashby/Lever store description_html,
# Greenhouse under 'content', Gem under 'content_html', the Apple/Microsoft
# scrapers under 'description', and the Google scraper's "About the job" narrative
# under 'about_the_job' (NULLIF drops the empties so they fall through to
# title-only rather than a blank description). Workday carries a description_html
# key whose VALUE is JSON null (->> maps it to SQL NULL, falling through).
# Without the COALESCE only ~17% of OPEN prod rows were claimable; missing
# content_html/about_the_job left gem_api + google_scraper permanently invisible.
DESCRIPTION_SQL = (
    "COALESCE(details->>'description_html', details->>'content', "
    "details->>'content_html', details->>'description', "
    "NULLIF(details->>'about_the_job', ''))"
)


class CorrectionError(Exception):
    """Invalid correction input (unknown slug / unknown job). Router maps to
    409/404 — an admin in a stale UI deserves an explicit error, never the
    agent-path's silent soft-nulling."""

    def __init__(self, message: str, *, not_found: bool = False) -> None:
        super().__init__(message)
        self.not_found = not_found


def _regclass(cur: Any, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) AS oid", (name,))
    return scalar(cur.fetchone(), "oid") is not None


def _schema_present(cur: Any) -> bool:
    """All enrichment relations resolve on the active search_path."""
    return all(
        _regclass(cur, t)
        for t in ("job_listings", "job_enrichment", "job_categories", "job_levels")
    )


def get_admin_health(conn: Connection, window_hours: int = 24) -> dict[str, Any]:
    """Health snapshot for the admin enrichment page (snake_case keys; the
    router's Pydantic model camelCases them)."""
    cur = conn.cursor()
    try:
        if not _schema_present(cur):
            return {
                "schema_present": False,
                "enabled": settings.enrichment_use_external,
                "open_by_status": {},
                "eligible_unenriched": 0,
                "stale_claims": 0,
                "claim_ttl_minutes": settings.enrichment_claim_ttl_minutes,
                "needs_human_open": 0,
                "human_corrected_total": 0,
                "last_enriched_at": None,
                "last_enriched_age_s": None,
                "last_tick_uuid": None,
                "last_tick_status": None,
                "last_tick_started_at": None,
                "last_tick_age_s": None,
                "last_tick_drift_suspected": False,
                "window_hours": window_hours,
                "enriched_in_window": 0,
                "error_ticks_in_window": 0,
            }

        cur.execute(
            "SELECT COALESCE(enrichment_status, 'unenriched') AS status, COUNT(*) AS n "
            "FROM job_listings WHERE status = 'OPEN' GROUP BY 1"
        )
        open_by_status = {r["status"]: r["n"] for r in cur.fetchall()}

        # Of the unenriched OPEN rows, how many /pending could actually hand out.
        # Mirrors /pending's claim guard: description-present when title-only
        # claiming is OFF, else ALL OPEN unenriched (description-less rows are
        # claimable title-only). The gap vs 'unenriched' is the
        # permanently-invisible backlog when the flag is OFF — without this an
        # idle laptop and a starved one look identical.
        desc_guard = (
            "" if settings.enrichment_claim_without_description
            else f"AND {DESCRIPTION_SQL} IS NOT NULL"
        )
        cur.execute(
            "SELECT COUNT(*) AS n FROM job_listings "
            "WHERE enrichment_status IS NULL AND status = 'OPEN' "
            f"{desc_guard}"
        )
        eligible_unenriched = int(scalar(cur.fetchone(), "n") or 0)

        cur.execute(
            "SELECT COUNT(*) AS n FROM job_listings "
            "WHERE enrichment_status = 'claimed' "
            "AND enrichment_claimed_at < now() - make_interval(mins => %s)",
            (settings.enrichment_claim_ttl_minutes,),
        )
        stale_claims = int(scalar(cur.fetchone(), "n") or 0)

        # The ACTIONABLE queue depth: flagged rows on OPEN jobs not yet
        # corrected by a human (the internal /health's raw count includes
        # CLOSED jobs and corrected rows, so it only ever grows).
        cur.execute(
            "SELECT COUNT(*) AS n FROM job_enrichment je "
            "JOIN job_listings jl ON jl.source_id = je.source_id AND jl.id = je.job_listing_id "
            "WHERE je.needs_human AND je.human_corrected_at IS NULL AND jl.status = 'OPEN'"
        )
        needs_human_open = int(scalar(cur.fetchone(), "n") or 0)

        cur.execute(
            "SELECT COUNT(*) AS n FROM job_enrichment WHERE human_corrected_at IS NOT NULL"
        )
        human_corrected_total = int(scalar(cur.fetchone(), "n") or 0)

        cur.execute(
            "SELECT MAX(enriched_at) AS last, "
            "EXTRACT(EPOCH FROM now() - MAX(enriched_at))::float AS age_s "
            "FROM job_enrichment"
        )
        last_row = cur.fetchone()

        cur.execute(
            "SELECT COUNT(*) AS n FROM job_enrichment "
            "WHERE enriched_at > now() - make_interval(hours => %s)",
            (window_hours,),
        )
        enriched_in_window = int(scalar(cur.fetchone(), "n") or 0)

        # Latest pushed tick + windowed error count (enrichment_ticks may be
        # absent mid-deploy — guard like the procrastinate tables in
        # location_monitor).
        last_tick: dict[str, Any] | None = None
        error_ticks_in_window = 0
        if _regclass(cur, "enrichment_ticks"):
            cur.execute(
                "SELECT tick_uuid, status, started_at, drift_suspected, "
                "EXTRACT(EPOCH FROM now() - started_at)::float AS age_s "
                "FROM enrichment_ticks ORDER BY started_at DESC LIMIT 1"
            )
            last_tick = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS n FROM enrichment_ticks "
                "WHERE status = 'error' "
                "AND started_at > now() - make_interval(hours => %s)",
                (window_hours,),
            )
            error_ticks_in_window = int(scalar(cur.fetchone(), "n") or 0)

        return {
            "schema_present": True,
            "enabled": settings.enrichment_use_external,
            "open_by_status": open_by_status,
            "eligible_unenriched": eligible_unenriched,
            "stale_claims": stale_claims,
            "claim_ttl_minutes": settings.enrichment_claim_ttl_minutes,
            "needs_human_open": needs_human_open,
            "human_corrected_total": human_corrected_total,
            "last_enriched_at": last_row["last"],
            "last_enriched_age_s": last_row["age_s"],
            "last_tick_uuid": last_tick["tick_uuid"] if last_tick else None,
            "last_tick_status": last_tick["status"] if last_tick else None,
            "last_tick_started_at": last_tick["started_at"] if last_tick else None,
            "last_tick_age_s": last_tick["age_s"] if last_tick else None,
            "last_tick_drift_suspected": bool(last_tick["drift_suspected"]) if last_tick else False,
            "window_hours": window_hours,
            "enriched_in_window": enriched_in_window,
            "error_ticks_in_window": error_ticks_in_window,
        }
    finally:
        cur.close()
        conn.rollback()


_NEEDS_HUMAN_COLUMNS = (
    "je.source_id, je.job_listing_id, jl.title, jl.company, jl.url, "
    "jl.status AS job_status, jl.enrichment_status, "
    "jl.enrichment_category AS category, jl.enrichment_level AS level, "
    "COALESCE((SELECT json_agg(tag ORDER BY tag) FROM job_tags "
    "  WHERE job_tags.source_id = je.source_id "
    "  AND job_tags.job_listing_id = je.job_listing_id), '[]'::json) AS tags, "
    "je.clean_description, je.classify_confidence, je.classify_reasoning, "
    "je.taxonomy_version, je.judged, je.judge_passed, je.judge_confidence, "
    "je.judge_notes, je.enriched_at, je.human_corrected_at, je.human_corrected_by, "
    "je.human_decision"
)


def list_needs_human(
    conn: Connection,
    *,
    limit: int,
    offset: int,
    company: str | None = None,
    category: str | None = None,
    level: str | None = None,
    include_corrected: bool = False,
    only_open: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Paginated needs-human queue (rows, total). Filters compose with AND;
    ``category``/``level`` filter on the enricher's PROPOSED facet only when a
    row was published (demoted rows have NULL facets — they match no facet
    filter, by design: the human decides)."""
    conditions = ["je.needs_human"]
    params: list[Any] = []
    if not include_corrected:
        conditions.append("je.human_corrected_at IS NULL")
    if only_open:
        conditions.append("jl.status = 'OPEN'")
    if company:
        conditions.append("jl.company = %s")
        params.append(company)
    if category:
        conditions.append("jl.enrichment_category = %s")
        params.append(category)
    if level:
        conditions.append("jl.enrichment_level = %s")
        params.append(level)
    where = " AND ".join(conditions)

    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) AS n FROM job_enrichment je "
            "JOIN job_listings jl ON jl.source_id = je.source_id AND jl.id = je.job_listing_id "
            f"WHERE {where}",
            tuple(params),
        )
        total = int(scalar(cur.fetchone(), "n") or 0)
        cur.execute(
            f"SELECT {_NEEDS_HUMAN_COLUMNS} FROM job_enrichment je "
            "JOIN job_listings jl ON jl.source_id = je.source_id AND jl.id = je.job_listing_id "
            f"WHERE {where} "
            "ORDER BY je.enriched_at DESC LIMIT %s OFFSET %s",
            tuple(params) + (limit, offset),
        )
        rows = [dict(r) for r in cur.fetchall()]
        return rows, total
    finally:
        cur.close()
        conn.rollback()


def list_ticks(conn: Connection, window_hours: int = 24) -> dict[str, Any]:
    """Trailing-window tick series (ascending by started_at, for charts) plus
    the latest scorecard/knobs pushed in ANY tick (scorecards only ride along
    when new, so the latest one may be older than the window)."""
    cur = conn.cursor()
    try:
        if not _regclass(cur, "enrichment_ticks"):
            return {
                "ticks": [],
                "window_hours": window_hours,
                "latest_scorecard": None,
                "latest_scorecard_tick_uuid": None,
                "latest_knobs": None,
            }
        cur.execute(
            "SELECT tick_uuid, started_at, ended_at, status, notes, claimed, cleaned, "
            "classified, judged, corrected, needs_human, sent, errors, nulled_facets, "
            "duration_s, taxonomy_version, stage_timings, heartbeat_age_s, "
            "drift_suspected, received_at "
            "FROM enrichment_ticks "
            "WHERE started_at > now() - make_interval(hours => %s) "
            "ORDER BY started_at ASC",
            (window_hours,),
        )
        ticks = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT tick_uuid, scorecard FROM enrichment_ticks "
            "WHERE scorecard IS NOT NULL ORDER BY started_at DESC LIMIT 1"
        )
        score_row = cur.fetchone()
        cur.execute(
            "SELECT knobs FROM enrichment_ticks "
            "WHERE knobs IS NOT NULL ORDER BY started_at DESC LIMIT 1"
        )
        knobs_row = cur.fetchone()
        return {
            "ticks": ticks,
            "window_hours": window_hours,
            "latest_scorecard": score_row["scorecard"] if score_row else None,
            "latest_scorecard_tick_uuid": score_row["tick_uuid"] if score_row else None,
            "latest_knobs": knobs_row["knobs"] if knobs_row else None,
        }
    finally:
        cur.close()
        conn.rollback()


def list_recent(conn: Connection, limit: int = 25) -> list[dict[str, Any]]:
    """Latest enrichment writes — eyeball-the-results table for the admin page."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT je.source_id, je.job_listing_id, jl.title, jl.company, jl.url, "
            "jl.enrichment_status, jl.enrichment_category AS category, "
            "jl.enrichment_level AS level, "
            "COALESCE((SELECT json_agg(tag ORDER BY tag) FROM job_tags "
            "  WHERE job_tags.source_id = je.source_id "
            "  AND job_tags.job_listing_id = je.job_listing_id), '[]'::json) AS tags, "
            "je.classify_confidence, je.classify_reasoning, je.judged, je.judge_passed, "
            "je.judge_confidence, je.judge_notes, je.taxonomy_version, je.needs_human, "
            "je.human_corrected_at, je.human_decision, je.enriched_at "
            "FROM job_enrichment je "
            "JOIN job_listings jl ON jl.source_id = je.source_id AND jl.id = je.job_listing_id "
            "ORDER BY je.enriched_at DESC LIMIT %s",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.rollback()


def _facet_slugs(cur: Any, table: str) -> set[str]:
    cur.execute(f"SELECT slug FROM {table}")  # noqa: S608 — table is a literal below
    return {r["slug"] for r in cur.fetchall()}


def apply_correction(
    conn: Connection,
    *,
    source_id: str,
    job_listing_id: str,
    category: str | None,
    level: str | None,
    tags: list[str],
    note: str | None,
    admin_email: str,
) -> dict[str, Any]:
    """Apply a human facet correction. Owns commit/rollback (location_admin
    convention). Publishes the corrected facets (enrichment_status='done'),
    replaces the tag set, clears needs_human, and stamps human_corrected_at/by —
    which locks the row against later automated overwrite (see apply_result's
    guard). Validates slugs against the LIVE dimension tables so a stale admin
    UI gets a CorrectionError (409), never a silent null."""
    cur = conn.cursor()
    try:
        # Validate against live dims (they may be ahead of the code constants
        # mid-taxonomy-migration; the DB is the source of truth for what the FK
        # will accept). Code constants are a fallback if dims are empty.
        cat_slugs = _facet_slugs(cur, "job_categories") or set(CATEGORY_SLUGS)
        lvl_slugs = _facet_slugs(cur, "job_levels") or set(LEVEL_SLUGS)
        if category is not None and category not in cat_slugs:
            raise CorrectionError(f"unknown category slug {category!r}")
        if level is not None and level not in lvl_slugs:
            raise CorrectionError(f"unknown level slug {level!r}")
        if len(tags) > MAX_TAGS_PER_JOB:
            raise CorrectionError(f"more than {MAX_TAGS_PER_JOB} tags")

        cur.execute(
            "UPDATE job_listings SET enrichment_category = %s, enrichment_level = %s, "
            "enrichment_status = 'done', enrichment_claimed_at = NULL "
            "WHERE source_id = %s AND id = %s",
            (category, level, source_id, job_listing_id),
        )
        if cur.rowcount == 0:
            raise CorrectionError(
                f"no job_listings row for (source_id={source_id!r}, id={job_listing_id!r})",
                not_found=True,
            )
        cur.execute(
            "DELETE FROM job_tags WHERE source_id = %s AND job_listing_id = %s",
            (source_id, job_listing_id),
        )
        for tag in tags:
            cur.execute(
                "INSERT INTO job_tags (source_id, job_listing_id, tag) VALUES (%s, %s, %s) "
                "ON CONFLICT (source_id, job_listing_id, tag) DO NOTHING",
                (source_id, job_listing_id, tag),
            )
        # The audit row may not exist (e.g. correcting a never-enriched job an
        # admin found by hand) — upsert so the lock + provenance always land.
        # The correction note rides in judge_notes with an explicit [human]
        # prefix (kept distinct from the judge's own text by the marker; a
        # dedicated column isn't worth a second migration).
        note_sql = (
            "CASE WHEN %s::text IS NULL THEN job_enrichment.judge_notes "
            "ELSE COALESCE(job_enrichment.judge_notes || E'\\n', '') || '[human] ' || %s::text END"
        )
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id, needs_human, "
            "human_corrected_at, human_corrected_by, human_decision, judge_notes) "
            "VALUES (%s, %s, false, now(), %s, 'corrected', "
            "CASE WHEN %s::text IS NULL THEN NULL "
            "ELSE '[human] ' || %s::text END) "
            "ON CONFLICT (source_id, job_listing_id) DO UPDATE SET "
            "needs_human = false, human_corrected_at = now(), human_corrected_by = %s, "
            "human_decision = 'corrected', "
            f"judge_notes = {note_sql}",
            (
                source_id, job_listing_id, admin_email, note, note,
                admin_email, note, note,
            ),
        )
        cur.execute(
            "SELECT jl.enrichment_status, jl.enrichment_category AS category, "
            "jl.enrichment_level AS level, je.human_corrected_at, je.human_corrected_by, "
            "je.human_decision "
            "FROM job_listings jl "
            "JOIN job_enrichment je ON je.source_id = jl.source_id AND je.job_listing_id = jl.id "
            "WHERE jl.source_id = %s AND jl.id = %s",
            (source_id, job_listing_id),
        )
        row = cur.fetchone()
        conn.commit()
        return {
            "source_id": source_id,
            "job_listing_id": job_listing_id,
            "enrichment_status": row["enrichment_status"],
            "category": row["category"],
            "level": row["level"],
            "tags": tags,
            "human_corrected_at": row["human_corrected_at"],
            "human_corrected_by": row["human_corrected_by"],
            "human_decision": row["human_decision"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def apply_confirmation(
    conn: Connection,
    *,
    source_id: str,
    job_listing_id: str,
    admin_email: str,
) -> dict[str, Any]:
    """Confirm a needs-human row's proposal as correct WITHOUT changing labels —
    the one-click "this is right" action. Keeps the enricher's published facets,
    clears needs_human, and stamps human_corrected_at/by + human_decision=
    'confirmed_correct'. That stamp locks the row exactly like a correction (the
    writer's guard keys on human_corrected_at) and records, for the golden-merge
    feed, that a flagged row was VALIDATED rather than fixed. Refuses (409) a row
    with no published facets — a demoted needs_human row has NULL facets, so
    there is nothing to validate; the human must use Correct to set them. Owns
    commit/rollback (apply_correction convention)."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT enrichment_category FROM job_listings "
            "WHERE source_id = %s AND id = %s",
            (source_id, job_listing_id),
        )
        current = cur.fetchone()
        if current is None:
            raise CorrectionError(
                f"no job_listings row for (source_id={source_id!r}, id={job_listing_id!r})",
                not_found=True,
            )
        if current["enrichment_category"] is None:
            raise CorrectionError(
                "no proposed labels to confirm — use Correct to set them"
            )
        # Facets/tags are left exactly as the enricher published them; we only
        # promote the lifecycle to 'done' (a flag-off needs_human row is already
        # 'done', but be explicit) and clear any stale claim stamp.
        cur.execute(
            "UPDATE job_listings SET enrichment_status = 'done', "
            "enrichment_claimed_at = NULL WHERE source_id = %s AND id = %s",
            (source_id, job_listing_id),
        )
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id, needs_human, "
            "human_corrected_at, human_corrected_by, human_decision) "
            "VALUES (%s, %s, false, now(), %s, 'confirmed_correct') "
            "ON CONFLICT (source_id, job_listing_id) DO UPDATE SET "
            "needs_human = false, human_corrected_at = now(), "
            "human_corrected_by = %s, human_decision = 'confirmed_correct'",
            (source_id, job_listing_id, admin_email, admin_email),
        )
        cur.execute(
            "SELECT jl.enrichment_status, jl.enrichment_category AS category, "
            "jl.enrichment_level AS level, "
            "COALESCE((SELECT json_agg(tag ORDER BY tag) FROM job_tags "
            "  WHERE job_tags.source_id = jl.source_id "
            "  AND job_tags.job_listing_id = jl.id), '[]'::json) AS tags, "
            "je.human_corrected_at, je.human_corrected_by, je.human_decision "
            "FROM job_listings jl "
            "JOIN job_enrichment je ON je.source_id = jl.source_id AND je.job_listing_id = jl.id "
            "WHERE jl.source_id = %s AND jl.id = %s",
            (source_id, job_listing_id),
        )
        row = cur.fetchone()
        conn.commit()
        return {
            "source_id": source_id,
            "job_listing_id": job_listing_id,
            "enrichment_status": row["enrichment_status"],
            "category": row["category"],
            "level": row["level"],
            "tags": row["tags"],
            "human_corrected_at": row["human_corrected_at"],
            "human_corrected_by": row["human_corrected_by"],
            "human_decision": row["human_decision"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def request_reenrich(
    conn: Connection, *, source_id: str, job_listing_id: str
) -> dict[str, Any]:
    """Reset a job to unenriched so the next /pending hands it out again. Fully
    reopens the row: facets/tags cleared, needs_human cleared, and the
    human-correction lock LIFTED (an explicit re-enrich is the one sanctioned
    way to let the agent overwrite a human label). The enricher treats a
    re-handed already-sent row as a fresh classify (paired store change)."""
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE job_listings SET enrichment_status = NULL, enrichment_category = NULL, "
            "enrichment_level = NULL, enrichment_claimed_at = NULL "
            "WHERE source_id = %s AND id = %s",
            (source_id, job_listing_id),
        )
        if cur.rowcount == 0:
            raise CorrectionError(
                f"no job_listings row for (source_id={source_id!r}, id={job_listing_id!r})",
                not_found=True,
            )
        cur.execute(
            "DELETE FROM job_tags WHERE source_id = %s AND job_listing_id = %s",
            (source_id, job_listing_id),
        )
        cur.execute(
            "UPDATE job_enrichment SET needs_human = false, "
            "human_corrected_at = NULL, human_corrected_by = NULL, "
            "human_decision = NULL "
            "WHERE source_id = %s AND job_listing_id = %s",
            (source_id, job_listing_id),
        )
        conn.commit()
        return {
            "source_id": source_id,
            "job_listing_id": job_listing_id,
            "enrichment_status": None,
            "category": None,
            "level": None,
            "tags": [],
            "human_corrected_at": None,
            "human_corrected_by": None,
            "human_decision": None,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def list_corrections_since(
    conn: Connection, *, since: datetime | None, limit: int = 500
) -> list[dict[str, Any]]:
    """Human-review feed for the enricher's ``cli golden-merge`` — admin-resolved
    rows become ``label_source='human'`` gold rows, closing the loop between the
    needs-human queue and the eval harness. Each row carries ``decision``
    ('corrected' | 'confirmed_correct') so the consumer can weight a fixed label
    differently from a flagged-but-validated one (the raised-yet-correct signal
    a future memory layer wants). Both decisions set human_corrected_at, so both
    flow through this feed."""
    conditions = ["je.human_corrected_at IS NOT NULL"]
    params: list[Any] = []
    if since is not None:
        conditions.append("je.human_corrected_at > %s")
        params.append(since)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT je.source_id, je.job_listing_id, jl.title, jl.company, "
            "jl.enrichment_category AS category, jl.enrichment_level AS level, "
            "COALESCE((SELECT json_agg(tag ORDER BY tag) FROM job_tags "
            "  WHERE job_tags.source_id = je.source_id "
            "  AND job_tags.job_listing_id = je.job_listing_id), '[]'::json) AS tags, "
            "je.human_corrected_at AS corrected_at, je.human_decision AS decision "
            "FROM job_enrichment je "
            "JOIN job_listings jl ON jl.source_id = je.source_id AND jl.id = je.job_listing_id "
            f"WHERE {' AND '.join(conditions)} "
            "ORDER BY je.human_corrected_at ASC LIMIT %s",
            tuple(params) + (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        cur.close()
        conn.rollback()


def record_tick(conn: Connection, payload: dict[str, Any]) -> None:
    """Upsert one pushed tick (idempotent on tick_uuid; a re-push wins so the
    'running' → 'ok' final push updates the row in place). Owns commit."""
    counters = payload.get("counters") or {}
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO enrichment_ticks (
                tick_uuid, started_at, ended_at, status, notes,
                claimed, cleaned, classified, judged, corrected, needs_human,
                sent, errors, nulled_facets, duration_s, taxonomy_version,
                knobs, stage_timings, heartbeat_age_s, scorecard,
                enricher_version, drift_suspected
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (tick_uuid) DO UPDATE SET
                started_at = EXCLUDED.started_at,
                ended_at = EXCLUDED.ended_at,
                status = EXCLUDED.status,
                notes = EXCLUDED.notes,
                claimed = EXCLUDED.claimed,
                cleaned = EXCLUDED.cleaned,
                classified = EXCLUDED.classified,
                judged = EXCLUDED.judged,
                corrected = EXCLUDED.corrected,
                needs_human = EXCLUDED.needs_human,
                sent = EXCLUDED.sent,
                errors = EXCLUDED.errors,
                nulled_facets = EXCLUDED.nulled_facets,
                duration_s = EXCLUDED.duration_s,
                taxonomy_version = EXCLUDED.taxonomy_version,
                knobs = COALESCE(EXCLUDED.knobs, enrichment_ticks.knobs),
                stage_timings = COALESCE(EXCLUDED.stage_timings, enrichment_ticks.stage_timings),
                heartbeat_age_s = EXCLUDED.heartbeat_age_s,
                scorecard = COALESCE(EXCLUDED.scorecard, enrichment_ticks.scorecard),
                enricher_version = EXCLUDED.enricher_version,
                drift_suspected = EXCLUDED.drift_suspected,
                received_at = now()
            """,
            (
                payload["tick_uuid"],
                payload["started_at"],
                payload.get("ended_at"),
                payload["status"],
                payload.get("notes"),
                counters.get("claimed", 0),
                counters.get("cleaned", 0),
                counters.get("classified", 0),
                counters.get("judged", 0),
                counters.get("corrected", 0),
                counters.get("needs_human", 0),
                counters.get("sent", 0),
                counters.get("errors", 0),
                counters.get("nulled_facets", 0),
                payload.get("duration_s"),
                payload.get("taxonomy_version"),
                _jsonb(payload.get("knobs")),
                _jsonb(payload.get("stage_timings")),
                payload.get("heartbeat_age_s"),
                _jsonb(payload.get("scorecard")),
                payload.get("enricher_version"),
                bool(payload.get("drift_suspected", False)),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def _jsonb(value: Any) -> Any:
    """psycopg2 adapts dict/list only via Json; None passes through."""
    if value is None:
        return None
    from psycopg2.extras import Json

    return Json(value)


def get_facets(conn: Connection) -> dict[str, list[dict[str, Any]]]:
    """Dropdown catalog from the seeded dimensions (GET /api/jobs/facets)."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT slug, label, sort_order, NULL AS parent_slug "
            "FROM job_categories ORDER BY sort_order"
        )
        categories = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT slug, label, rank AS sort_order, parent_slug "
            "FROM job_levels ORDER BY rank"
        )
        levels = [dict(r) for r in cur.fetchall()]
        return {"categories": categories, "levels": levels}
    finally:
        cur.close()
        conn.rollback()
