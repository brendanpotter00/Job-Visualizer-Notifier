"""Database query functions for the API layer.

Reuses connection management and table naming from scripts/shared/database.py.
Adds read-only query functions needed by the API endpoints.
"""

import json
import logging
from datetime import datetime

from psycopg2 import sql

from scripts.shared.database import Connection

from ..pagination import JobCursor
from .enrichment_writer import SUBCATEGORY_FILTER_EXPANSION

logger = logging.getLogger(__name__)


def _ensure_json_string(value: object) -> str:
    """Ensure a value is a JSON string (not a parsed dict/list).

    psycopg2 with RealDictCursor auto-parses JSONB columns into Python dicts.
    The frontend expects these as JSON strings, not parsed objects.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    logger.warning(
        "Unexpected type %s in _ensure_json_string, falling back to str()",
        type(value).__name__,
    )
    return json.dumps(value)


_JOB_TIMESTAMP_FIELDS = (
    "created_at",
    "posted_on",
    "closed_on",
    "first_seen_at",
    "last_seen_at",
)


def _row_to_job_dict(row: dict) -> dict:
    """Convert a database row to a dict with JSON string and ISO timestamp fields."""
    d = dict(row)
    d["details"] = _ensure_json_string(d.get("details"))
    d["ai_metadata"] = _ensure_json_string(d.get("ai_metadata"))
    # ``locations`` is a real array (canonical location tags), unlike
    # details/ai_metadata which the frontend wants as JSON strings. RealDictCursor
    # parses the ``json_agg`` column into a Python list; tolerate a raw string and
    # a missing key (single-job SELECT * paths that omit the column) defensively.
    locations = d.get("locations")
    if isinstance(locations, str):
        locations = json.loads(locations)
    d["locations"] = locations or []
    # Enrichment facets: the list query aliases to category/level, but the
    # single-job SELECT * path returns the raw enrichment_* column names — map
    # them so both paths feed JobListingResponse's category/level fields.
    if "enrichment_category" in d and "category" not in d:
        d["category"] = d.pop("enrichment_category")
    if "enrichment_level" in d and "level" not in d:
        d["level"] = d.pop("enrichment_level")
    # Same rename shim, REQUIRED because the detail route returns raw column
    # names. Deliberately NOT `setdefault(..., [])` — `None` means "never
    # evaluated" (the backfill queue) and `[]` means "evaluated, nothing
    # applies", and coercing here would destroy the distinction one layer below
    # the API that ships it as `list[str] | None`.
    if "enrichment_subcategories" in d and "subcategories" not in d:
        d["subcategories"] = d.pop("enrichment_subcategories")
    tags = d.get("tags")
    if isinstance(tags, str):
        tags = json.loads(tags)
    d["tags"] = tags or []
    for field in _JOB_TIMESTAMP_FIELDS:
        value = d.get(field)
        if isinstance(value, datetime):
            d[field] = value.isoformat()
    return d


_JOBS_TABLE = sql.Identifier("job_listings")
_RUNS_TABLE = sql.Identifier("scrape_runs")


# Level filter expansion — the load-bearing new_grad⊂entry contract. Clicking
# "entry" surfaces new-grad roles too; clicking "new_grad" stays exact. Kept in
# code (fast, no join) as the read-side mirror of the job_levels.parent_slug data.
_LEVEL_FILTER_EXPANSION: dict[str, list[str]] = {"entry": ["entry", "new_grad"]}

# The subcategory equivalent, IMPORTED rather than re-declared. `enrichment_writer`
# is the code arbiter for the taxonomy (`SUBCATEGORY_SLUGS` and friends live
# there), and the read->write import direction already has precedent —
# `enrichment_monitor.py` imports the facet slug sets from the same module. A
# local literal here would be a second expansion rule free to drift from the one
# the frontend's oracle fixture is generated against.
#
# Selecting Frontend also matches Full Stack; selecting Full Stack stays exact.
_SUBCATEGORY_FILTER_EXPANSION = SUBCATEGORY_FILTER_EXPANSION


# Hidden-company guard for the PUBLIC job read paths.
#
# ``companies.enabled = FALSE`` is this codebase's soft-deactivation switch
# (``db_models.py`` ``Company.enabled``). It already gates the worker fan-out
# (``scripts/shared/database.py`` ``list_enabled_companies``), the curated
# directory (``services/companies_service.py``) and auto-enroll
# (``services/user_preferences_service.py``) — but NOT ``/api/jobs``, which
# reads ``job_listings`` with no reference to ``companies``. Before this guard,
# ``GET /api/jobs?company=<deactivated-id>`` (public, forwarded verbatim by
# ``api/jobs.ts``) still served every row of a retired company.
#
# ANTI-join (``NOT EXISTS ... AND NOT enabled``), deliberately, NOT
# ``company IN (SELECT id FROM companies WHERE enabled)``: a job whose company
# has NO ``companies`` row must stay VISIBLE. This makes the predicate mean
# "explicitly deactivated", not "registered", which (a) preserves today's
# behavior for any legacy/unregistered company value and (b) leaves every
# existing test fixture untouched — ``api/tests/conftest.py`` truncates
# ``companies`` before each test, so its seeded job rows have no companies row
# at all.
#
# ``companies`` is ~133 rows, and the planner satisfies the probe from
# ``ix_companies_ats_enabled`` (``Index Cond: enabled = false``), so this
# collapses to a hash anti-join against the handful of deactivated rows.
# Measured on prod against the real 50-company batched query: 355ms -> 427ms
# over 15,544 rows, no plan regression. Applied to the list and detail reads ONLY.
#
# DO NOT pass ``exclude_hidden_companies=True`` from ``get_scrape_runs()``:
# that query's FROM is ``scrape_runs``, so the correlated
# ``job_listings.company`` reference would not resolve. And deliberately NOT
# from ``get_stats()``: ``/api/jobs-qa/stats`` and ``/scrape-runs`` are
# ``require_admin`` diagnostics — deactivation hides a company from users, it
# does not erase it from operator tooling.
#
# CAVEAT, so nobody is misled by the line above: the exemption covers the
# jobs-qa *stats* and *scrape-runs* endpoints only. The admin QA page's Jobs
# table (``QAPage.tsx``) fetches the public ``/api/jobs``, so it IS subject to
# this filter. An operator therefore sees a deactivated company's rows in the
# stats card but not in the table beneath it. Deliberate for now — closing that
# gap means an admin-gated jobs read, which is out of scope here.
_HIDDEN_COMPANY_PREDICATE = sql.SQL(
    "NOT EXISTS ("
    " SELECT 1 FROM companies c"
    " WHERE c.id = job_listings.company AND NOT c.enabled)"
)


# UNCONDITIONAL private-company guard for the PUBLIC job read paths (E7).
#
# ``/api/jobs`` (list + single-job detail) is entirely unauthenticated and
# forwarded verbatim by ``api/jobs.ts``. A ``visibility='user'`` company is one
# user's private board; its jobs must NEVER be served here regardless of who is
# asking. This predicate is therefore applied UNCONDITIONALLY on both public read
# paths — deliberately NOT viewer-scoped. A viewer-scoped predicate ("hide
# private companies unless YOU own them") would turn an unconditional leak into a
# conditional one — the kind that passes review and ships — and private jobs are
# served ONLY by the authed, owner-scoped ``GET /api/users/companies/{id}/jobs``.
#
# Like ``_HIDDEN_COMPANY_PREDICATE`` this is an ANTI-join keyed on the private
# subset, so the planner satisfies it from ``ix_companies_visibility`` (the
# partial index over just the ``visibility <> 'public'`` rows).
_USER_COMPANY_PREDICATE = sql.SQL(
    "NOT EXISTS ("
    " SELECT 1 FROM companies c"
    " WHERE c.id = job_listings.company AND c.visibility = 'user')"
)


# Recency lower bound for the keyset-paged read path. INCLUSIVE (``>=``): the
# caller's window is "everything first seen at or after this instant", so a job
# whose ``first_seen_at`` equals the bound exactly is IN. Qualified to
# ``job_listings`` for symmetry with the cursor predicate below (``job_freshness``
# has no ``first_seen_at`` column, so it is not strictly ambiguous today).
_SINCE_PREDICATE = sql.SQL("job_listings.first_seen_at >= %s")

# Keyset predicate: "strictly after the cursor row" under
# ``ORDER BY first_seen_at DESC, source_id DESC, id DESC``.
#
# This is a Postgres ROW-VALUE comparison, not three chained AND/OR clauses, and
# that matters twice over. Correctness: row comparison is lexicographic, so
# ``(a,b,c) < (ca,cb,cc)`` is *exactly* "sorts after (ca,cb,cc) in the DESC
# ordering" — the hand-expanded ``a < ca OR (a = ca AND (b < cb OR ...))`` form is
# the classic place a tiebreak gets dropped and rows go missing. Performance: the
# planner can turn a row comparison over a matching composite btree into a single
# index seek + scan, which the OR-expansion does not reliably get.
#
# ``source_id`` and ``id`` MUST be qualified — ``job_freshness`` (aliased ``f``)
# carries same-named join keys, so a bare reference is ambiguous and errors out.
#
# All three columns are NOT NULL (``first_seen_at`` on the table, the other two by
# virtue of being the composite PK), so there is no NULL-ordering hazard here.
_CURSOR_PREDICATE = sql.SQL(
    "(job_listings.first_seen_at, job_listings.source_id, job_listings.id)"
    " < (%s, %s, %s)"
)

# Keyset ORDER BY. Every column DESC and in the same order as
# ``idx_job_listings_open_first_seen_keyset`` (plain ASC columns), so Postgres
# serves it with a BACKWARD index scan and no Sort node.
_KEYSET_ORDER_BY = sql.SQL(
    "ORDER BY job_listings.first_seen_at DESC, job_listings.source_id DESC,"
    " job_listings.id DESC"
)

# The pre-keyset ordering, kept byte-for-byte for the legacy (no ``since``, no
# ``cursor``) request shape. Every existing caller — the frontend's batched
# per-company fetch, the admin QA table — still lands here unchanged.
_LEGACY_ORDER_BY = sql.SQL("ORDER BY f.last_seen_at DESC")


def _build_where(
    company: str | None = None,
    status: str | None = None,
    companies: list[str] | None = None,
    category: str | None = None,
    level: str | None = None,
    exclude_hidden_companies: bool = False,
    exclude_user_companies: bool = False,
    since: datetime | None = None,
    cursor: JobCursor | None = None,
) -> tuple[sql.Composable, list]:
    """Build a WHERE clause and parameter list from optional filters.

    ``companies`` (set membership via ``company = ANY(%s::text[])``) takes
    precedence over the singular ``company``. Callers are expected to enforce
    mutual-exclusivity at the request boundary. ``level`` expands per the
    new_grad⊂entry hierarchy (``entry`` -> {entry, new_grad}).
    ``exclude_hidden_companies`` appends :data:`_HIDDEN_COMPANY_PREDICATE`,
    dropping jobs whose company row is soft-deactivated (``enabled = FALSE``);
    it defaults to ``False`` so admin/diagnostic callers keep seeing them.

    **THERE IS DELIBERATELY NO ``subcategory`` PARAMETER HERE.** ``/api/jobs``
    is the windowed dump the company hiring-trend page filters client-side; the
    SERVER-side subcategory filter belongs to ``/api/jobs/search``
    (``services/job_search.py``), which is the only path that applies the user's
    whole filter set in SQL. Adding a scalar ``?subcategory=`` to this endpoint
    would create a SECOND expansion site for ``full_stack`` — and double
    expansion is what persists ``['backend','full_stack']`` into saved filters
    and chips. ``_LIST_COLUMNS`` still SERIALIZES the array on both read paths;
    serializing and filtering are different questions.

    ``since`` and ``cursor`` are the keyset-paging bounds (see
    :data:`_SINCE_PREDICATE` / :data:`_CURSOR_PREDICATE`). Like
    ``exclude_hidden_companies`` they emit ``job_listings``-qualified SQL, so they
    are only valid for callers whose FROM is ``job_listings`` — i.e. ``get_jobs``.
    ``get_scrape_runs`` must never pass them.
    """
    conditions: list[sql.Composable] = []
    params: list = []
    if companies:
        conditions.append(sql.SQL("company = ANY(%s::text[])"))
        params.append(list(companies))
    elif company:
        conditions.append(sql.SQL("company = %s"))
        params.append(company)
    if status:
        conditions.append(sql.SQL("status = %s"))
        params.append(status)
    if category:
        conditions.append(sql.SQL("enrichment_category = %s"))
        params.append(category)
    if level:
        expanded = _LEVEL_FILTER_EXPANSION.get(level, [level])
        conditions.append(sql.SQL("enrichment_level = ANY(%s::text[])"))
        params.append(expanded)
    if exclude_hidden_companies:
        # Contributes no params — a static correlated subquery.
        conditions.append(_HIDDEN_COMPANY_PREDICATE)
    if exclude_user_companies:
        # Contributes no params — a static correlated subquery (E7 leak guard).
        conditions.append(_USER_COMPANY_PREDICATE)
    if since is not None:
        conditions.append(_SINCE_PREDICATE)
        params.append(since)
    if cursor is not None:
        conditions.append(_CURSOR_PREDICATE)
        params.extend([cursor.first_seen_at, cursor.source_id, cursor.job_id])
    where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
    return where, params


# Normalized canonical location tags for a job, aggregated as a camelCase JSON
# array (keys match ``JobLocationResponse`` aliases). Correlated on
# ``job_listings.id``: ``job_locations`` is keyed by ``job_listing_id`` alone
# (no source_id column) and indexed (``idx_job_locations_job_listing_id`` plus
# the composite PK's leading column), so this is an index probe per row. Empty
# ``[]`` for jobs that are unnormalized or failed. Primary tag sorts first.
_LOCATIONS_SUBQUERY = sql.SQL(
    "COALESCE(("
    "  SELECT json_agg(json_build_object("
    "    'canonicalName', l.canonical_name, 'kind', l.kind, 'city', l.city,"
    "    'region', l.region, 'country', l.country, 'remoteScope', l.remote_scope,"
    "    'isPrimary', jl.is_primary"
    "  ) ORDER BY jl.is_primary DESC, l.canonical_name)"
    "  FROM job_locations jl"
    "  JOIN locations l ON l.id = jl.normalized_location_id"
    "  WHERE jl.job_listing_id = job_listings.id"
    "), '[]'::json) AS locations"
)

# Lightweight column list for the list endpoint.  Returns only the
# two ``details`` sub-fields the frontend transformer actually uses
# (experience_level, is_remote_eligible) and an empty ai_metadata,
# cutting per-row size from ~10 KB to ~500 bytes.
# Must be updated if the schema changes.
#
# Both sub-fields are read from the denormalized ``experience_level`` /
# ``is_remote_eligible`` columns, NOT from ``details->'…'``: a JSONB key access
# detoasts the full ~10 KB ``details`` value per row, and on the batched list
# query (~12k rows) that ~100 MB of TOAST reads timed out (2026-07-13 outage).
# This SELECT therefore never touches ``details``/TOAST. Anything added here
# must come from a real column for the same reason — a ``details->>'…'`` in this
# projection re-creates that outage.
# Free-form enrichment tags for a job, as a JSON array of strings. Correlated on
# the FULL composite identity (source_id, id): job_tags is keyed by
# (source_id, job_listing_id, tag) — `id` is NOT globally unique, so a job must
# only see its OWN tags, not a same-id row from another source. The composite PK's
# leading (source_id, job_listing_id) prefix serves this probe. '[]' when unenriched.
_TAGS_SUBQUERY = sql.SQL(
    "COALESCE(("
    "  SELECT json_agg(tag ORDER BY tag) FROM job_tags"
    "  WHERE job_tags.source_id = job_listings.source_id"
    "    AND job_tags.job_listing_id = job_listings.id"
    "), '[]'::json) AS tags"
)

# ``last_seen_at`` / ``consecutive_misses`` are sourced from the ``job_freshness``
# sidecar (aliased ``f`` in the query) — see get_jobs. ``id`` and ``source_id``
# are qualified to ``job_listings`` because the sidecar carries same-named join
# keys and a bare reference would be ambiguous.
_LIST_COLUMNS = sql.SQL(
    "job_listings.id, title, company, location, url, job_listings.source_id,"
    " jsonb_build_object("
    "   'experience_level', experience_level,"
    "   'is_remote_eligible', is_remote_eligible"
    " ) AS details,"
    " created_at, posted_on, closed_on, status,"
    " has_matched, jsonb_build_object() AS ai_metadata,"
    " first_seen_at, f.last_seen_at, f.consecutive_misses, details_scraped,"
    " enrichment_category AS category, enrichment_level AS level,"
    " enrichment_subcategories AS subcategories, enrichment_status, "
) + _TAGS_SUBQUERY + sql.SQL(", ") + _LOCATIONS_SUBQUERY

# INNER JOIN onto the freshness sidecar. Lossless by construction: the AFTER
# INSERT trigger + backfill + composite FK guarantee every job_listings row has
# exactly one job_freshness row, so this never drops a listing.
_FRESHNESS_JOIN = sql.SQL(
    " JOIN job_freshness f"
    " ON f.source_id = job_listings.source_id AND f.id = job_listings.id"
)


def get_jobs(
    conn: Connection,
    company: str | None = None,
    status: str | None = None,
    limit: int = 5000,
    offset: int = 0,
    companies: list[str] | None = None,
    category: str | None = None,
    level: str | None = None,
    since: datetime | None = None,
    cursor: JobCursor | None = None,
) -> list[dict]:
    """List jobs with optional filters.

    Two ordering modes, selected by whether the caller asked for keyset paging:

    * **Legacy (neither ``since`` nor ``cursor``)** — ``ORDER BY f.last_seen_at
      DESC``, exactly as before keyset paging existed. Every pre-existing caller
      lands here and gets byte-identical SQL and results.
    * **Keyset (``since`` and/or ``cursor``)** — ``ORDER BY first_seen_at DESC,
      source_id DESC, id DESC``, bounded by :data:`_SINCE_PREDICATE` and/or
      :data:`_CURSOR_PREDICATE`. See ``api/pagination.py`` for why this key and
      not ``last_seen_at``: it is immutable, so a concurrent scrape cannot
      reshuffle the ordering mid-walk, and the PK tiebreak makes it unique.

    The two modes are mutually exclusive by construction — a keyset cursor
    describes a position in the ``first_seen_at`` ordering and is meaningless
    against the ``last_seen_at`` one, so the ORDER BY must switch with it or the
    page boundary lands in the wrong place and rows go missing without an error.

    Pass ``companies`` for batched per-company fetches (used by the Recent
    Jobs page to avoid fanning out N requests against the connection pool).
    ``level`` expands per the new_grad⊂entry hierarchy.

    This is a PUBLIC read path, so jobs belonging to a soft-deactivated
    company (``companies.enabled = FALSE``) are filtered out — see
    :data:`_HIDDEN_COMPANY_PREDICATE`.
    """
    keyset = since is not None or cursor is not None
    with conn.cursor() as db_cursor:
        where, params = _build_where(
            company=company, status=status, companies=companies,
            category=category, level=level,
            exclude_hidden_companies=True,
            exclude_user_companies=True,
            since=since, cursor=cursor,
        )

        query = sql.SQL(
            "SELECT {} FROM {}{} {} {} LIMIT %s OFFSET %s"
        ).format(
            _LIST_COLUMNS, _JOBS_TABLE, _FRESHNESS_JOIN, where,
            _KEYSET_ORDER_BY if keyset else _LEGACY_ORDER_BY,
        )
        params.extend([limit, offset])
        db_cursor.execute(query, params)

        return [_row_to_job_dict(row) for row in db_cursor.fetchall()]


def get_job_by_id(conn: Connection, source_id: str, job_id: str) -> dict | None:
    """Get a single job by composite (source_id, id) key.

    ``source_id`` must be non-empty. An empty value would silently 404
    every lookup with no signal at the call site — fail fast instead.
    The router's ``Path`` matcher already prevents ``/api/jobs//<id>``
    from routing here, but we guard at the service boundary to catch any
    future caller that bypasses the router.

    This is a PUBLIC read path, so a job belonging to a soft-deactivated
    company (``companies.enabled = FALSE``) reads as missing and the router
    turns that into a 404 — see :data:`_HIDDEN_COMPANY_PREDICATE`.
    """
    if not source_id:
        raise ValueError("get_job_by_id requires a non-empty source_id")
    with conn.cursor() as cursor:
        # ``job_listings.*`` no longer carries last_seen_at / consecutive_misses
        # — the Unit-4 contract migration (18fe9c20a8fd) dropped both — so the
        # appended ``f.last_seen_at`` / ``f.consecutive_misses`` are the only
        # source of those two keys in the row dict.
        cursor.execute(
            sql.SQL(
                "SELECT job_listings.*, f.last_seen_at, f.consecutive_misses, {}, {} "
                "FROM {}{} "
                "WHERE job_listings.source_id = %s AND job_listings.id = %s "
                "AND {} AND {}"
            ).format(
                _TAGS_SUBQUERY,
                _LOCATIONS_SUBQUERY,
                _JOBS_TABLE,
                _FRESHNESS_JOIN,
                _HIDDEN_COMPANY_PREDICATE,
                # E7 leak guard: a private company's job reads as missing here
                # (the router turns None into a 404), so the public detail path
                # cannot serve it. Private jobs come only from the owner endpoint.
                _USER_COMPANY_PREDICATE,
            ),
            (source_id, job_id),
        )
        row = cursor.fetchone()

        if row:
            return _row_to_job_dict(row)
        return None


def get_user_company_jobs(
    conn: Connection,
    company_id: str,
    source_id: str,
    limit: int = 5000,
) -> list[dict]:
    """Owner-scoped read of a private custom company's jobs (E7).

    The ONLY read path that returns ``visibility='user'`` jobs. Authorization
    (the caller owns this company) is enforced by the router BEFORE calling this
    — there is no viewer arg here. Scoped by BOTH ``company`` and
    ``source_id = custom:<id>`` so the query can only ever surface this one
    company's rows even if a company id were somehow reused.

    Same column list + freshness join + row shape as ``get_jobs`` (so it feeds
    the identical ``JobListingResponse``), ordered by the immutable keyset tuple
    ``(first_seen_at DESC, source_id DESC, id DESC)``. Returns every status —
    Phase 1 closes nothing, but a CLOSED row must still render on the trend page
    when later phases begin closing.
    """
    with conn.cursor() as db_cursor:
        query = sql.SQL(
            "SELECT {} FROM {}{} "
            "WHERE company = %s AND job_listings.source_id = %s {} LIMIT %s"
        ).format(
            _LIST_COLUMNS, _JOBS_TABLE, _FRESHNESS_JOIN, _KEYSET_ORDER_BY,
        )
        db_cursor.execute(query, [company_id, source_id, limit])
        return [_row_to_job_dict(row) for row in db_cursor.fetchall()]


def get_owned_custom_jobs(
    conn: Connection,
    source_ids: list[str],
    *,
    status: str | None = None,
    since: datetime | None = None,
    cursor: JobCursor | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Owner-scoped read across ALL of one user's private companies at once (E7).

    The Recent Jobs feed's counterpart to :func:`get_user_company_jobs`, which is
    per-company and therefore only ever reachable from a company's own trend
    page. Without this, a user's custom boards were invisible on the page they
    actually read jobs on.

    AUTHORIZATION IS BY CONSTRUCTION, and that is the whole design. ``source_ids``
    is never taken from the request — the router derives it from the caller's
    ``user_companies`` rows — so there is no company-id parameter for a caller to
    tamper with, no ownership check that a future edit could drop, and an
    anonymous caller never reaches here at all (``get_current_user`` 401s first).
    A user with no custom companies passes ``[]`` and gets ``[]`` back, which is
    exactly the correct answer rather than a special case. This deliberately does
    NOT relax :data:`_USER_COMPANY_PREDICATE` on ``/api/jobs``: that guard stays
    unconditional, and private jobs keep being served only by authed,
    owner-derived paths.

    Same columns / freshness join / row shape as :func:`get_jobs`, and the same
    immutable keyset ordering + ``since``/``cursor`` predicates, so a page from
    here is mergeable with a page from ``/api/jobs`` by the client's existing
    keyset walk instead of needing a second, bespoke paging protocol.
    """
    if not source_ids:
        # Short-circuit: ``= ANY('{}')`` is a legal query that always returns zero
        # rows, but skipping the round trip keeps the common signed-in-user-with-
        # no-custom-boards case free.
        return []
    conditions: list[sql.Composable] = [sql.SQL("job_listings.source_id = ANY(%s::text[])")]
    params: list = [source_ids]
    if status:
        conditions.append(sql.SQL("status = %s"))
        params.append(status)
    if since is not None:
        conditions.append(_SINCE_PREDICATE)
        params.append(since)
    if cursor is not None:
        conditions.append(_CURSOR_PREDICATE)
        params.extend([cursor.first_seen_at, cursor.source_id, cursor.job_id])
    params.append(limit)

    with conn.cursor() as db_cursor:
        query = sql.SQL("SELECT {} FROM {}{} WHERE {} {} LIMIT %s").format(
            _LIST_COLUMNS,
            _JOBS_TABLE,
            _FRESHNESS_JOIN,
            sql.SQL(" AND ").join(conditions),
            _KEYSET_ORDER_BY,
        )
        db_cursor.execute(query, params)
        return [_row_to_job_dict(row) for row in db_cursor.fetchall()]


def get_stats(conn: Connection, company: str | None = None) -> dict:
    """Get job statistics with optional company filter."""
    with conn.cursor() as cursor:
        where, params = _build_where(company=company)

        # Single query: per-company counts plus totals via window functions
        cursor.execute(
            sql.SQL("""
            SELECT
                company,
                COUNT(*) AS count,
                SUM(COUNT(*)) OVER () AS total_jobs,
                SUM(COUNT(*) FILTER (WHERE status = 'OPEN')) OVER () AS open_jobs,
                SUM(COUNT(*) FILTER (WHERE status = 'CLOSED')) OVER () AS closed_jobs
            FROM {} {}
            GROUP BY company
            ORDER BY company
            """).format(_JOBS_TABLE, where),
            params if params else None,
        )
        rows = cursor.fetchall()

        if rows:
            first = rows[0]
            total_jobs = first["total_jobs"]
            open_jobs = first["open_jobs"]
            closed_jobs = first["closed_jobs"]
        else:
            total_jobs = open_jobs = closed_jobs = 0

        return {
            "total_jobs": total_jobs,
            "open_jobs": open_jobs,
            "closed_jobs": closed_jobs,
            "company_counts": [{"company": r["company"], "count": r["count"]} for r in rows],
        }


def get_scrape_runs(
    conn: Connection,
    company: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Get scrape run history, ordered by started_at DESC."""
    with conn.cursor() as cursor:
        where, params = _build_where(company=company)

        params.append(limit)
        cursor.execute(
            sql.SQL("SELECT * FROM {} {} ORDER BY started_at DESC LIMIT %s").format(_RUNS_TABLE, where),
            params,
        )

        return [dict(row) for row in cursor.fetchall()]
