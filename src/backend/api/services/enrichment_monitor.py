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
from .enrichment_writer import (
    CATEGORY_SLUGS,
    LEVEL_SLUGS,
    MAX_SUBCATEGORIES,
    MAX_TAGS_PER_JOB,
    SUBCATEGORY_PARENT,
    SUBCATEGORY_SLUGS,
    SUBCATEGORY_SOURCES,
)

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
#
# The WRITE side of the same question is ``job_details.has_description``, which is what
# the ATS clients now set ``details_scraped`` from. Kept as a literal here rather than
# generated from ``DESCRIPTION_KEYS`` (this string is the claim predicate for the whole
# enrichment pipeline and is not worth making computed);
# ``test_details_scraped_truthfulness.py`` fails if the two key sets drift apart.
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
                "swe_open_total": 0,
                "swe_subcategorized": 0,
                "swe_subcategory_labelled": 0,
                "subcategory_unknown_slugs": 0,
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

        # --- Subcategory coverage: the number the 90% reveal is read off ------
        #
        # THE GUARD IS LOAD-BEARING. `_schema_present` above does not cover the
        # new relations, and the table and the columns ship in the SAME revision,
        # so the table's presence is a sound proxy for the columns'. Without it,
        # a process running against a pre-migration database raises
        # `UndefinedColumn`, the router turns that into a 500 on the ENTIRE
        # health endpoint, and the whole verdict banner goes blank — not just the
        # new tile.
        swe_open_total = 0
        swe_subcategorized = 0
        swe_subcategory_labelled = 0
        subcategory_unknown_slugs = 0
        if _regclass(cur, "job_subcategories"):
            # COVERAGE COUNTS **EVALUATED** ROWS (`IS NOT NULL`), NOT non-empty
            # ones. `'{}'` is a legitimate terminal answer — "we looked, no
            # specialty applies" — and roughly 9% of the corpus is expected to
            # land there. Defining coverage as non-empty asymptotes near 91% and
            # can therefore NEVER cross the 90% reveal threshold.
            #
            # The denominator is OPEN + enrichment_category='software_engineering'
            # and it MUST match the backfill's PARAM_BACKFILL_DENOMINATOR, or the
            # tile and the backfill disagree about what 90% means. One index scan
            # over the OPEN slice per poll (idx_job_listings_status_category).
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE enrichment_subcategories IS NOT NULL) "
                "  AS evaluated, "
                "COUNT(*) FILTER (WHERE cardinality(enrichment_subcategories) > 0) "
                "  AS labelled "
                "FROM job_listings "
                "WHERE status = 'OPEN' AND enrichment_category = 'software_engineering'"
            )
            cov = cur.fetchone() or {}
            swe_open_total = int(cov.get("total") or 0)
            swe_subcategorized = int(cov.get("evaluated") or 0)
            swe_subcategory_labelled = int(cov.get("labelled") or 0)

            # The compensating control for the array having NO foreign key:
            # persisted slugs that are absent from the dimension table. THIS
            # MUST BE PERMANENTLY 0. Anything else means a producer is writing
            # slugs the taxonomy does not contain, and the facet dropdown will
            # never offer them — so those jobs are unreachable through the UI.
            cur.execute(
                "SELECT COUNT(*) AS n FROM ("
                "  SELECT DISTINCT unnest(jl.enrichment_subcategories) AS slug "
                "  FROM job_listings jl "
                "  WHERE jl.enrichment_subcategories IS NOT NULL"
                ") s "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM job_subcategories d WHERE d.slug = s.slug"
                ")"
            )
            subcategory_unknown_slugs = int(scalar(cur.fetchone(), "n") or 0)

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
            "swe_open_total": swe_open_total,
            "swe_subcategorized": swe_subcategorized,
            "swe_subcategory_labelled": swe_subcategory_labelled,
            "subcategory_unknown_slugs": subcategory_unknown_slugs,
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
    "je.human_decision, "
    "jl.enrichment_subcategories AS subcategories, je.subcategory_confidence"
)

# Sort allowlist for the triage queue. A whitelist, not string interpolation of
# whatever the client sent — these values are concatenated into the ORDER BY.
#
# `subcategory_confidence` is unconditional: SCHEMA-1 ships the column in the
# same revision as everything else here, so there is no window where it is
# missing.
_NEEDS_HUMAN_SORTS = {
    "enriched_at": "je.enriched_at",
    "classify_confidence": "je.classify_confidence",
    "judge_confidence": "je.judge_confidence",
    "subcategory_confidence": "je.subcategory_confidence",
}

# `subcategory_state` lenses.
#   any            - no predicate
#   unlabelled_swe - SWE rows the classifier never evaluated. THIS IS THE LENS
#                    THAT SURFACES HUMAN-LOCKED SWE ROWS, which the backfill's
#                    per-field unlock can reach but which are invisible in every
#                    other view.
#   labelled       - a non-empty array
_NEEDS_HUMAN_SUBCATEGORY_STATES = {
    "any": None,
    "unlabelled_swe": (
        "jl.enrichment_category = 'software_engineering' "
        "AND jl.enrichment_subcategories IS NULL"
    ),
    "labelled": "cardinality(jl.enrichment_subcategories) > 0",
}


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
    sort: str = "enriched_at",
    sort_dir: str = "desc",
    subcategory: str | None = None,
    subcategory_state: str = "any",
) -> tuple[list[dict[str, Any]], int]:
    """Paginated needs-human queue (rows, total). Filters compose with AND;
    ``category``/``level`` filter on the enricher's PROPOSED facet only when a
    row was published (demoted rows have NULL facets — they match no facet
    filter, by design: the human decides).

    SORTING — two details that are not cosmetic
    -------------------------------------------
    **``NULLS LAST`` IN BOTH DIRECTIONS.** Postgres defaults to ``NULLS FIRST``
    on DESC, so a descending confidence sort would open with a wall of unscored
    rows — defeating the only query an auditor actually runs ("show me the
    labels we are least sure about"). Ascending gets the same treatment for
    symmetry: an unscored row is not a low-confidence row.

    **THE COMPOSITE-PK TAIL IS REQUIRED FOR CORRECTNESS, not tidiness.** Without
    ``, je.source_id ASC, je.job_listing_id ASC`` the order over ties is
    unspecified, and OFFSET paging across an unspecified order silently
    duplicates some rows and HIDES others. Confidences tie constantly (0.5 is a
    common value), so this is the normal case, not an edge one.

    ``sort`` is resolved through the ``_NEEDS_HUMAN_SORTS`` allowlist — the value
    lands in an ORDER BY, so an unknown key falls back to ``enriched_at`` rather
    than being interpolated.
    """
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
    if subcategory:
        # `= ANY(NULL)` is NULL, not false — so this predicate ALSO excludes
        # every never-evaluated row, which is the intended reading of "show me
        # the rows proposed as backend".
        conditions.append("%s = ANY(jl.enrichment_subcategories)")
        params.append(subcategory)
    state_predicate = _NEEDS_HUMAN_SUBCATEGORY_STATES.get(subcategory_state)
    if state_predicate:
        conditions.append(f"({state_predicate})")
    where = " AND ".join(conditions)

    sort_column = _NEEDS_HUMAN_SORTS.get(sort, _NEEDS_HUMAN_SORTS["enriched_at"])
    direction = "ASC" if str(sort_dir).lower() == "asc" else "DESC"
    order_by = f"{sort_column} {direction} NULLS LAST"
    if sort_column != _NEEDS_HUMAN_SORTS["enriched_at"]:
        # Secondary recency ordering so a page of ties is still meaningful.
        order_by += ", je.enriched_at DESC"
    # Total order. See the docstring — without this, OFFSET paging over ties
    # duplicates rows and hides others.
    order_by += ", je.source_id ASC, je.job_listing_id ASC"

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
            f"ORDER BY {order_by} LIMIT %s OFFSET %s",
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
            "jl.enrichment_subcategories AS subcategories, "
            "je.classify_confidence, je.classify_reasoning, je.judged, je.judge_passed, "
            "je.judge_confidence, je.judge_notes, je.taxonomy_version, je.needs_human, "
            "je.subcategory_confidence, "
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


class _Unset:
    """Sentinel for "the client did not send this key at all"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<UNSET>"


_UNSET = _Unset()


def _validate_subcategories(
    cur: Any, value: list[str] | None, category: str | None
) -> list[str] | None:
    """Validate an EXPLICITLY SENT subcategory array for a correction.

    Never called for the absent-key case — that is handled by the caller, and
    keeping the two apart is the whole point (see `apply_correction`).

    Order is PRESERVED and dedupe is order-preserving: index 0 is the primary
    specialty, so `set()` anywhere in this function would be a bug.
    """
    if value is None:
        return None
    if category != SUBCATEGORY_PARENT:
        # The parent constraint an array column has no FK to express.
        raise CorrectionError(
            f"subcategories are only valid for category {SUBCATEGORY_PARENT!r}, "
            f"got {category!r}"
        )
    # Live dims first — the same pattern as the category/level validation two
    # lines above. Phase 1 ships job_subcategories EMPTY, so the code constants
    # are what actually answer until SCHEMA-7 seeds it.
    allowed = _facet_slugs(cur, "job_subcategories") or set(SUBCATEGORY_SLUGS)
    cleaned: list[str] = []
    for raw in value:
        slug = str(raw).strip().lower()
        if not slug:
            continue
        if slug not in allowed:
            raise CorrectionError(f"unknown subcategory slug {slug!r}")
        if slug not in cleaned:      # order-preserving dedupe; NEVER set()
            cleaned.append(slug)
    if len(cleaned) > MAX_SUBCATEGORIES:
        raise CorrectionError(
            f"more than {MAX_SUBCATEGORIES} subcategories ({len(cleaned)})"
        )
    return cleaned


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
    subcategories: list[str] | None = None,
    subcategories_provided: bool = False,
) -> dict[str, Any]:
    """Apply a human facet correction. Owns commit/rollback (location_admin
    convention). Publishes the corrected facets (enrichment_status='done'),
    replaces the tag set, clears needs_human, and stamps human_corrected_at/by —
    which locks the row against later automated overwrite (see apply_result's
    guard). Validates slugs against the LIVE dimension tables so a stale admin
    UI gets a CorrectionError (409), never a silent null.

    THE SUBCATEGORY WRITE RULE, stated once, in full
    ------------------------------------------------
    `subcategories=None` and "the client did not send the key" are the SAME
    VALUE at this signature, so the caller MUST pass
    `subcategories_provided='subcategories' in body.model_fields_set`. Do not
    "simplify" the branch below into `if subcategories is None`.

    | resolved category | key sent?     | what happens to enrichment_subcategories |
    |-------------------|---------------|------------------------------------------|
    | SWE               | not sent      | **UNTOUCHED** — not in the SET list       |
    | SWE               | a list        | validated, order-preserving, primary first|
    | SWE               | explicit null | set to NULL — an explicit re-queue        |
    | another slug      | not sent      | forced to `'{}'`                          |
    | another slug      | null or `[]`  | forced to `'{}'`                          |
    | another slug      | non-empty     | **409** — CorrectionError                 |
    | NULL (unlabelled) | not sent      | **UNTOUCHED**                             |
    | NULL (unlabelled) | non-empty     | **409**                                   |
    | NULL (unlabelled) | null or `[]`  | written as sent                           |

    The UNTOUCHED row is the fix, and it is not cosmetic. Appending
    `enrichment_subcategories = %s` unconditionally would mean a LEVEL-ONLY
    correction NULLs the array and then stamps `human_corrected_at`, locking the
    row — so no backfill could ever repair it. Silent, permanent, and invisible
    in the response.

    The `category IS NULL` rows are deliberately UNTOUCHED rather than forced to
    `'{}'`. A NULL category means "not labelled", not "labelled as something
    other than software engineering", so writing the terminal empty array would
    be asserting a fact nobody established — and it would do so on exactly the
    level-only correction path this step exists to protect. Forcing only fires
    for an EXPLICIT non-SWE slug.

    `enrichment_subcategory_source` is written alongside, and only alongside:
    `'human'` whenever an array is written (including the forced `'{}'`), and
    NULL when the array is set to NULL, so an explicit re-queue really does
    re-enter the backfill queue instead of sitting there locked and empty.
    """
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

        # Resolve the subcategory write into (write_it?, value) per the table in
        # the docstring. `subcategories_provided` is the ONLY thing separating
        # "sent null" from "not sent".
        write_subcategories = False
        subcategory_value: list[str] | None = None
        if category == SUBCATEGORY_PARENT:
            if subcategories_provided:
                write_subcategories = True
                subcategory_value = _validate_subcategories(cur, subcategories, category)
            # else: NOT SENT -> leave the column out of the SET list entirely.
        elif subcategories_provided and subcategories:
            # A non-empty array under any other category is a client bug: the
            # parent constraint an array column has no FK to express.
            raise CorrectionError(
                f"subcategories are only valid for category "
                f"{SUBCATEGORY_PARENT!r}, got {category!r}"
            )
        elif category is not None:
            # An EXPLICIT non-SWE slug: "no SWE specialty" is a true and
            # permanent statement about this job, so write the terminal empty
            # array whether or not the client sent the key.
            write_subcategories = True
            subcategory_value = []
        elif subcategories_provided:
            # category IS NULL and the client sent null or [] — honour it.
            write_subcategories = True
            subcategory_value = subcategories
        # else: category IS NULL and the key was not sent -> UNTOUCHED.

        set_parts = [
            "enrichment_category = %s",
            "enrichment_level = %s",
            "enrichment_status = 'done'",
            "enrichment_claimed_at = NULL",
        ]
        params: list[Any] = [category, level]
        if write_subcategories:
            # The ::text[] cast is REQUIRED: psycopg2 renders [] untyped and
            # Postgres raises "cannot determine type of empty array".
            set_parts.append("enrichment_subcategories = %s::text[]")
            params.append(subcategory_value)
            set_parts.append("enrichment_subcategory_source = %s")
            params.append("human" if subcategory_value is not None else None)
        params.extend([source_id, job_listing_id])

        cur.execute(
            "UPDATE job_listings SET "  # noqa: S608 — set_parts is a literal allowlist
            + ", ".join(set_parts)
            + " WHERE source_id = %s AND id = %s",
            tuple(params),
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
            "jl.enrichment_level AS level, "
            "jl.enrichment_subcategories AS subcategories, "
            "je.human_corrected_at, je.human_corrected_by, "
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
            # Read BACK from the row, never echoed from the request — on the
            # not-sent path the request has nothing to echo, and echoing would
            # report a NULL the endpoint deliberately did not write.
            "subcategories": row["subcategories"],
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


def reset_subcategories(
    conn: Connection, *, source: str, dry_run: bool = True
) -> dict[str, Any]:
    """SCOPED, source-keyed reversal of automated subcategory labels.

    ``enrichment_subcategory_source`` exists specifically to make this possible.
    The only other JVN-side reversal on offer is SCHEMA-1's ``downgrade()``,
    whose own docstring admits a plain ``DROP COLUMN`` discards every backfilled
    label — a blunt instrument for backing the whole feature out, not for undoing
    one bad run. The enricher has its own run-scoped ``subcategory-reset``, but
    THE LABELS USERS ACTUALLY SEE LIVE IN POSTGRES, and nothing was clearing
    those.

    ``dry_run`` DEFAULTS TO TRUE. The destructive form needs an explicit
    ``false``, so the reflexive "just run it and see" produces a count and
    changes nothing.

    ``source='human'`` is only ever matched when passed EXPLICITLY. An unscoped
    variant of this function would destroy the only ground truth the eval gate
    has, and there is no code path here that can reach the human rows by
    accident.

    Owns commit/rollback, like the other mutations in this module.
    """
    if source not in SUBCATEGORY_SOURCES:
        raise CorrectionError(
            f"unknown subcategory source {source!r}; expected one of "
            f"{sorted(SUBCATEGORY_SOURCES)}"
        )
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT COUNT(*) AS n FROM job_listings "
            "WHERE enrichment_subcategory_source = %s",
            (source,),
        )
        matched = int(scalar(cur.fetchone(), "n") or 0)

        applied = 0
        if not dry_run:
            # Both columns in ONE SET list: a row whose array is NULL but whose
            # source still names the producer would be a lie the backfill queue
            # would then act on.
            cur.execute(
                "UPDATE job_listings SET enrichment_subcategories = NULL, "
                "enrichment_subcategory_source = NULL "
                "WHERE enrichment_subcategory_source = %s",
                (source,),
            )
            applied = cur.rowcount
        conn.commit()
        return {"source": source, "matched": matched, "applied": applied}
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
    flow through this feed.

    ``taxonomy_version`` RIDES THIS FEED, AND IT IS NOT OPTIONAL. Without it the
    consumer cannot tell a PRE-v7 ``confirmed_correct`` row — a human validating
    a label set that had no subcategory field in it at all — from a genuine
    subcategory confirmation. Every such row would otherwise become a false
    ``subcategories: []`` gold label, and the eval gate would be scored against
    facts nobody ever asserted.

    ``ORDER BY je.human_corrected_at ASC`` MUST STAY: ``cli golden-merge --since``
    walks this feed forward and relies on monotonic ordering to know where it
    got to.
    """
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
            "jl.enrichment_subcategories AS subcategories, "
            "je.taxonomy_version, "
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
        # The subcategory arm is guarded on the relation existing, because a
        # process running ahead of the migration must render today's flat
        # dropdown rather than 500 the catalog for every visitor.
        #
        # PHASE 1 RETURNS [] because the dimension ships EMPTY — seeding it IS
        # the user-visible publish. `parent_slug` here is a GROUPING edge
        # ('software_engineering' on every row), NOT the filter-expansion edge
        # job_levels uses; the frontend must never feed it to the level
        # expansion builder.
        subcategories: list[dict[str, Any]] = []
        if _regclass(cur, "job_subcategories"):
            cur.execute(
                "SELECT slug, label, sort_order, parent_slug "
                "FROM job_subcategories ORDER BY sort_order"
            )
            subcategories = [dict(r) for r in cur.fetchall()]
        return {
            "categories": categories,
            "levels": levels,
            "subcategories": subcategories,
        }
    finally:
        cur.close()
        conn.rollback()
