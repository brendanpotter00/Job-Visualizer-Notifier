"""Server-side filtered search for the Recent Jobs page (``GET /api/jobs/search``).

WHY THIS EXISTS
---------------
Until this module, the Recent Jobs page walked ``/api/jobs`` **unfiltered** — three
parallel company-chunk keyset cursors at 1000 rows a page — merged the chunks
client-side, clamped them to a "complete prefix" horizon, and then applied every
filter in JavaScript. That architecture has one structural defect: a filter can
match nothing in the prefix the client happens to hold while matches sit deeper in
the corpus, so the UI must keep *guessing* how much further to walk. The machinery
built to make that guess (empty-fetch budgets, a manual "search older jobs"
affordance, window widening, horizon math) is what deadlocked in production on
2026-08-10 — see ``docs/incidents/2026-08-10-recent-jobs-empty-filter-deadlock.md``.

Filtering in SQL removes the guess. Every page this module returns contains only
rows the user asked for, so "the page came back empty" means "there are no more",
full stop, and the client needs no deepening logic to be correct.

PARITY IS THE CONTRACT
----------------------
The predicates below are a deliberate, clause-for-clause port of the frontend's
``filterJobsByFilters`` (``src/frontend/src/features/filters/utils/jobFilteringUtils.ts``).
Where the port intentionally diverges it is called out at the predicate. Anything
NOT called out is meant to be identical, and
``api/tests/test_jobs_search_filters.py::test_server_results_match_client_filter_oracle``
holds that line by running a Python translation of the client matcher against the
same corpus.
"""

import logging
import re
from datetime import datetime
from typing import TypedDict, Unpack

from psycopg2 import sql

from scripts.shared.database import Connection

from ..pagination import JobCursor
from .database import (
    _CURSOR_PREDICATE,
    _FRESHNESS_JOIN,
    _HIDDEN_COMPANY_PREDICATE,
    _JOBS_TABLE,
    _KEYSET_ORDER_BY,
    _LEVEL_FILTER_EXPANSION,
    _LIST_COLUMNS,
    _SINCE_PREDICATE,
    _USER_COMPANY_PREDICATE,
    _row_to_job_dict,
)

logger = logging.getLogger(__name__)


class SearchFilters(TypedDict):
    """The filter set shared by the page query and the count query.

    A TypedDict rather than a long keyword list repeated three times: the router
    builds it once and unpacks it into both, so a filter added here is a type
    error at every site that forgot it instead of a silently unfiltered count.

    TOTALITY IS THE ENFORCEMENT, and it is why this is not ``total=False``. Under
    ``total=False`` a literal may omit any key and still type-check at both
    ``**filters`` sites — including ``status``, which
    :func:`build_search_where` takes as a REQUIRED keyword with no default, so the
    omission is a runtime ``TypeError`` that mypy is happy with. That made the
    guarantee in the paragraph above false. "No filter on this dimension" is
    spelled ``None``, never an absent key.
    """

    status: str
    since: datetime | None
    categories: list[str] | None
    levels: list[str] | None
    companies: list[str] | None
    locations: list[str] | None
    # The ``locations.id`` set for every location selection EXCEPT the country
    # TIER of a country-tier selection — i.e. the exact-canonical-name branch of
    # every selection plus the full match group of region/city/remote selections,
    # pre-resolved once per request by :func:`resolve_location_filter`. The
    # country tier is split out into :data:`location_country_paths` so it can seek
    # on the denormalized ``primary_country`` (Perf Wave 2, C2). ``locations`` is
    # kept alongside these two only to tell whether a location filter is ACTIVE (a
    # non-empty ``locations`` that resolves to neither an id nor a country path is
    # a name-miss that must still match nothing, not "no filter"). See
    # :func:`_location_predicate` for why ids replaced the per-row cross-table
    # ``EXISTS (… JOIN locations …)`` the descriptors used to drive.
    location_ids: list[int] | None
    # Per country-tier selection: ``(ISO country code, member locations.id set)``.
    # The code drives the ``primary_country = %s`` fast path; the id set is the
    # NULL-``primary_country`` fallback's ``job_locations`` probe (the country
    # tier's own rows). See :func:`build_search_where` / WAVE2-PLAN.md §5a.
    location_country_paths: list[tuple[str, list[int]]] | None
    include: list[str] | None
    exclude: list[str] | None


class SearchCounts(TypedDict):
    """Header metrics, computed once per walk alongside page 1.

    ``filtered_total`` is ``None`` since Wave-1 B1 deferred the exact count off the
    page-1 critical path (owner decision ①: fast searches beat exact counts). The
    key is kept — the meta envelope has always allowed it to be null — so the wire
    contract is unchanged; the client approximates the total from the rows it has
    walked. The two recency tiles stay exact: they are windowed over the cheap 24 h
    slice of the keyset index, not a full-corpus count.
    """

    filtered_total: int | None
    count_last_24h: int
    count_last_3h: int


# ---------------------------------------------------------------------------
# Keyword search
# ---------------------------------------------------------------------------

# Escapes the three characters LIKE treats specially, so a user searching for
# "C++ (100% remote)" or "senior_swe" gets a literal match instead of a wildcard.
# The backslash must be substituted FIRST — running it after '%'/'_' would
# double-escape the backslashes this very substitution just inserted.
_LIKE_SPECIALS = re.compile(r"([\\%_])")


def _like_pattern(term: str) -> str:
    """Wrap a user term as an escaped ``%…%`` LIKE pattern (substring semantics)."""
    return "%" + _LIKE_SPECIALS.sub(r"\\\1", term) + "%"


# One keyword term against the searchable text of a job.
#
# FAST PATH + FALLBACK (Perf Wave 2, C3). ``job_listings.search_text`` is a
# denormalized, lower-cased ``title ‖ raw location ‖ company ‖ tags`` haystack
# (migration ``e3b1a4c9d7f2``), covered by a GIN trigram index — so
# ``search_text ILIKE '%term%'`` is one bitmap probe instead of the 4-way OR that
# spans ``job_listings`` and ``job_tags`` and no per-column trigram can serve.
# But ``search_text`` is nullable and populated lazily (write path + a bounded
# post-deploy backfill), so a row whose value is NULL has NOT been computed yet
# and seeking on it would DROP the row. The predicate therefore keeps the
# ORIGINAL 4-way OR verbatim as a fallback for exactly those NULL rows:
#
#   (search_text IS NOT NULL AND search_text ILIKE %s)    -- backfilled: fast path
#   OR (search_text IS NULL AND <original 4-way OR>)       -- not-yet-filled
#
# This is provably parity-exact with the old predicate for any population state
# (WAVE2-PLAN.md §5b): ``search_text`` is built with the SAME field set the OR
# tested, so a backfilled row matches iff the OR would, and a NULL row runs the
# OR itself. As the backfill drains NULLs the fast branch fires more and the
# fallback less. The one already-documented divergence persists on the fast
# branch — matching against one space-joined string can match a term straddling a
# field boundary that per-field matching would miss (a superset the audit noted,
# harmless). NULL rows keep the exact per-field semantics.
#
# WHY THE ``IS NOT NULL`` GUARD ON THE FAST BRANCH, not the plan's bare
# ``search_text ILIKE %s OR (…)``: on the EXCLUDE path the whole predicate is
# wrapped in ``NOT (…)``, and for a NULL-``search_text`` row ``NULL ILIKE %s`` is
# NULL — ``NULL OR (NULL IS NULL AND <false OR>)`` collapses to NULL, and
# ``NOT (NULL)`` is NULL, which Postgres drops. That is the very
# null-drops-the-row hazard the ``COALESCE(location,'')`` below guards against,
# reintroduced one level up. Gating the fast branch on ``search_text IS NOT
# NULL`` and the fallback on ``search_text IS NULL`` makes the whole expression
# total (each branch is boolean under its guard, so the OR is boolean, never
# NULL) — safe under both include and exclude.
#
# The original 4-way OR, now the fallback, unchanged. Its field set:
# * ``department`` is NOT matched, and the history here is worth keeping because
#   it reversed twice. It used to be ``details.experience_level`` on the frontend
#   (``backendScraperTransformer.ts``), mirrored into the denormalized
#   ``experience_level`` column, so an earlier revision matched that column to
#   preserve parity — dropping it back then genuinely narrowed terms like
#   "intern" or "senior" that users type. E7 Phase 3 (#248) then deleted the
#   field from the frontend model outright: ``Job.department`` is gone and
#   ``matchesSearchTags`` now builds its haystack from
#   ``[title, team, location, ...tags]``. So as of that commit the CLIENT no
#   longer matches it, and keeping the clause would make this endpoint WIDER
#   than the page it replaces rather than equal to it — typing "senior" would
#   return jobs whose title says nothing about seniority, which is exactly the
#   ATS-assigned noise #260 removed from the job card. Matching the deployed
#   client is the whole contract of this predicate, so the column is dropped.
#   ``search_text`` is derived from the same fields, so it excludes it too.
# * ``team`` is never populated by any transformer, so it contributes nothing.
# * ``company`` IS searched, which the frontend does not do. Typing "stripe" into
#   a keyword box and getting Stripe's jobs is what users expect.
#
# ``COALESCE(..., '')`` on ``location`` (the one nullable column in the OR) is
# load-bearing and NOT defensive noise. Without it, a NULL-location row that
# matches none of the other fields makes the OR evaluate to NULL rather than
# false — and on the exclude path ``AND NOT (NULL)`` is NULL, which drops the
# row. A negative keyword would then silently hide every location-less job.
# ``title`` and ``company`` are NOT NULL. (``search_text`` on the fast branch is
# built with ``coalesce``s too, so it is never NULL for a backfilled row.)
#
# ``ESCAPE '\'`` is stated explicitly rather than relying on LIKE's default, so
# the escape character is part of the query text.
_KEYWORD_PREDICATE = sql.SQL(
    "("
    " (job_listings.search_text IS NOT NULL"
    "  AND job_listings.search_text ILIKE %s ESCAPE '\\')"
    " OR (job_listings.search_text IS NULL AND ("
    "   job_listings.title ILIKE %s ESCAPE '\\'"
    "   OR COALESCE(job_listings.location, '') ILIKE %s ESCAPE '\\'"
    "   OR job_listings.company ILIKE %s ESCAPE '\\'"
    "   OR EXISTS ("
    "     SELECT 1 FROM job_tags t"
    "     WHERE t.source_id = job_listings.source_id"
    "       AND t.job_listing_id = job_listings.id"
    "       AND t.tag ILIKE %s ESCAPE '\\')"
    " ))"
    ")"
)

# One copy of the pattern for the fast ``search_text`` branch, plus the four the
# original OR bound (title / location / company / tag).
_KEYWORD_PARAM_COUNT = 5


def _keyword_condition(term: str) -> tuple[sql.Composable, list[str]]:
    """One escaped keyword term plus the five copies of its pattern it binds."""
    pattern = _like_pattern(term)
    return _KEYWORD_PREDICATE, [pattern] * _KEYWORD_PARAM_COUNT


# ---------------------------------------------------------------------------
# Location hierarchy
# ---------------------------------------------------------------------------

# Port of ``US_STATE_NAMES`` (src/frontend/src/lib/location.ts), reversed to
# upper-cased name -> code. It resolves a "<State>, US" option the user can pick
# even though no ``locations`` row carries it — the frontend synthesizes those
# labels, so a name-based contract has to be able to resolve them too.
_US_STATE_NAME_TO_CODE: dict[str, str] = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT",
    "DISTRICT OF COLUMBIA": "DC", "DELAWARE": "DE", "FLORIDA": "FL",
    "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL",
    "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY",
    "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
    "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO",
    "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH",
    "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH",
    "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA",
    "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY",
}

# The frontend's hard-coded meta-option: a single "United States" entry that is
# not a ``locations`` row but stands for the whole country.
_UNITED_STATES_OPTION = "United States"

_US_SUFFIX_RE = re.compile(r",\s*US\Z", re.IGNORECASE)


class LocationDescriptor(TypedDict):
    """Structured form of a selected location — mirror of the frontend type."""

    tier: str  # 'country' | 'region' | 'city' | 'remote'
    city: str | None
    region: str | None
    country: str | None
    remote_scope: str | None


def _norm_code(value: str | None) -> str | None:
    """Trim + upper-case a code; empty becomes NULL so comparisons stay strict.

    Mirrors the frontend's ``normCode``. The empty-to-NULL step matters: a blank
    ``region`` must compare equal to a missing one, or a location row written with
    ``''`` would never match the same place written as NULL.
    """
    if value is None:
        return None
    trimmed = value.strip().upper()
    return trimmed or None


def _fields_to_descriptor(
    kind: str,
    city: str | None,
    region: str | None,
    country: str | None,
    remote_scope: str | None,
) -> LocationDescriptor:
    """Normalize one ``locations`` row into a descriptor (frontend ``fieldsToDescriptor``)."""
    tier = kind if kind in ("country", "region", "remote") else "city"
    return LocationDescriptor(
        tier=tier,
        city=city.strip() if city else None,
        region=_norm_code(region),
        country=_norm_code(country),
        remote_scope=_norm_code(remote_scope),
    )


# Resolves each selected canonical name to exactly ONE ``locations`` row.
#
# ``canonical_name`` has no UNIQUE constraint — uniqueness is on the structured
# tuple (kind, city, region, country, remote_scope) — so a display name can map to
# several rows. In practice those duplicates are NOT spellings of one place; they
# are inconsistently-normalized *different* places that happen to render the same
# label (prod carries 48 such names, e.g. "Remote (US)" across six different
# ``remote_scope`` values, and "New York, NY, US" as both a city and a region).
#
# Taking the union of their predicates is therefore badly wrong, not a harmless
# superset: one "Remote (US)" duplicate has a NULL ``remote_scope``, whose
# predicate degenerates to "any remote tag at all", so selecting Remote (US)
# would return Remote (Canada), Remote (India), Remote (Germany) and the rest.
# The frontend resolves a selection to exactly one descriptor, and so must this.
#
# The winner is the row the most jobs are actually tagged with — the one the
# reader most likely saw in the picker — with the lowest id as a stable
# tie-break so the choice never depends on physical row order.
_RESOLVE_LOCATIONS_SQL = """
    SELECT canonical_name, kind, city, region, country, remote_scope
    FROM (
        SELECT l.canonical_name, l.kind, l.city, l.region, l.country,
               l.remote_scope,
               row_number() OVER (
                   PARTITION BY l.canonical_name
                   ORDER BY (
                       SELECT count(*) FROM job_locations jl
                       WHERE jl.normalized_location_id = l.id
                   ) DESC, l.id ASC
               ) AS rank
        FROM locations l
        WHERE l.canonical_name = ANY(%s::text[])
    ) ranked
    WHERE rank = 1
"""


def resolve_location_selections(
    conn: Connection, selections: list[str]
) -> dict[str, LocationDescriptor]:
    """Resolve canonical-name selections to one structured descriptor each.

    Port of the frontend's ``resolveSelectedDescriptor``, in its exact precedence
    order: the "United States" meta-option, then the catalog, then the
    "<State>, US" fallback. A selection that resolves to nothing is simply absent
    from the returned mapping — it can still match by exact canonical name (see
    :func:`_location_condition`), which is also what the frontend does.

    WHY NAMES AND NOT IDS: the frontend filter state and the persisted
    ``user_saved_filters.locations`` column both hold canonical-name strings today,
    and two of the pickable options ("United States" and the synthesized state
    labels) have no ``locations`` row to take an id from. An id-based contract
    would force a saved-filters migration and still could not express those two.
    """
    resolved: dict[str, LocationDescriptor] = {}
    if not selections:
        return resolved

    # One batched lookup for every selection, rather than a query per name.
    with conn.cursor() as cursor:
        cursor.execute(_RESOLVE_LOCATIONS_SQL, (list(selections),))
        for row in cursor.fetchall():
            resolved[row["canonical_name"]] = _fields_to_descriptor(
                row["kind"], row["city"], row["region"],
                row["country"], row["remote_scope"],
            )

    for selection in selections:
        if selection == _UNITED_STATES_OPTION:
            # Precedence: the meta-option wins even if a row happens to share the
            # name, matching the frontend's ordering.
            resolved[selection] = LocationDescriptor(
                tier="country", city=None, region=None,
                country="US", remote_scope=None,
            )
            continue
        if selection in resolved:
            continue
        state_code = _US_STATE_NAME_TO_CODE.get(
            _US_SUFFIX_RE.sub("", selection).strip().upper()
        )
        if state_code:
            resolved[selection] = LocationDescriptor(
                tier="region", city=None, region=state_code,
                country="US", remote_scope=None,
            )
    return resolved


def _tier_condition(want: LocationDescriptor) -> tuple[sql.Composable, list] | None:
    """The hierarchical-containment predicate for one resolved selection.

    Clause-for-clause port of ``matchesLocation``'s switch. Two subtleties carried
    over deliberately:

    * ``IS NOT DISTINCT FROM``, not ``=``, wherever the frontend compares two
      possibly-null fields with ``===``. In JS ``null === null`` is **true**, so a
      city tag with no region must match a wanted city with no region; SQL ``=``
      would yield NULL there and drop the row.
    * Remote is opt-in on both sides. Geographic selections exclude ``kind =
      'remote'`` tags (so "United States" returns on-site roles, and "Remote (US)"
      stays its own option); a remote selection with no scope matches ANY remote
      tag, while a scoped one requires equality — so "Remote (US)" does not match
      an unscoped global-remote tag.
    """
    tier = want["tier"]
    if tier == "country":
        if want["country"] is None:
            return None
        return (
            sql.SQL("(l.kind <> 'remote' AND upper(l.country) = %s)"),
            [want["country"]],
        )
    if tier == "region":
        if want["region"] is None:
            return None
        return (
            sql.SQL(
                "(l.kind <> 'remote' AND upper(l.region) = %s"
                " AND upper(l.country) IS NOT DISTINCT FROM %s)"
            ),
            [want["region"], want["country"]],
        )
    if tier == "city":
        if want["city"] is None:
            return None
        return (
            sql.SQL(
                "(upper(l.city) = %s"
                " AND upper(l.region) IS NOT DISTINCT FROM %s"
                " AND upper(l.country) IS NOT DISTINCT FROM %s)"
            ),
            [want["city"].upper(), want["region"], want["country"]],
        )
    if tier == "remote":
        return (
            sql.SQL(
                "(l.kind = 'remote'"
                " AND (%s::text IS NULL OR upper(l.remote_scope) = %s))"
            ),
            [want["remote_scope"], want["remote_scope"]],
        )
    return None


def _location_match_group(
    selection: str, descriptor: LocationDescriptor | None
) -> tuple[sql.Composable, list]:
    """One selection's match test against the ``locations`` catalog: ``(name OR tier)``.

    Exactly the predicate the old per-row ``_location_condition`` EXISTS carried,
    but lifted OUT of the correlated subquery so it can be evaluated ONCE against
    the 1,186-row ``locations`` table at resolve time (see
    :func:`resolve_location_ids`) instead of once per candidate job row.

    The ``canonical_name = %s`` branch is always present — the exact-name fallback
    the frontend requires for a selection that resolves to no descriptor (e.g. a
    catalog row with no usable structure, or a name the catalog does not know) —
    and the tier branch is appended only when the descriptor yields one. Both read
    the same ``l.*`` columns and use the same ``upper()`` / ``IS NOT DISTINCT
    FROM`` null-equality as before, so the id set this gathers is identical to the
    set of ``locations`` rows the old EXISTS would have joined against.
    """
    branches: list[sql.Composable] = [sql.SQL("l.canonical_name = %s")]
    params: list = [selection]
    built = _tier_condition(descriptor) if descriptor is not None else None
    if built is not None:
        clause, clause_params = built
        branches.append(clause)
        params.extend(clause_params)
    return sql.SQL("(") + sql.SQL(" OR ").join(branches) + sql.SQL(")"), params


# The country tier's own ``locations`` rows: the exact predicate the country
# branch of :func:`_tier_condition` carries, resolved to an id set at request
# time so the NULL-``primary_country`` fallback probes ``job_locations`` with the
# same join-free int-array test :func:`_location_predicate` uses.
_COUNTRY_TIER_IDS_SQL = sql.SQL(
    "SELECT id FROM locations l WHERE l.kind <> 'remote' AND upper(l.country) = %s"
)


def resolve_location_filter(
    conn: Connection,
    selections: list[str],
    descriptors: dict[str, LocationDescriptor],
) -> tuple[list[tuple[str, list[int]]], list[int], list[int]]:
    """Resolve active location selections into the country fast path + the id-set path.

    Returns ``(country_paths, other_ids, all_ids)``:

    * ``country_paths`` — for each DISTINCT country-tier selection, ``(ISO code,
      member locations.id set)``. The code feeds the ``primary_country = %s`` seek
      (Perf Wave 2, C2); the id set is the fallback ``job_locations`` probe for
      rows whose ``primary_country IS NULL`` (its own country-tier rows only).
    * ``other_ids`` — the UNION of every selection's exact-``canonical_name``
      branch plus the FULL match group of every NON-country selection
      (region/city/remote), probed by :func:`_location_predicate` exactly as
      before. Region/city/remote tiers are unchanged — they match far fewer rows,
      so the planner never mis-estimated them.
    * ``all_ids`` — ``other_ids`` ∪ every country tier's ids, i.e. the SAME set
      the pre-Wave-2 single-union resolver returned. It exists solely for the
      cursor fingerprint, so splitting the WHERE clause does not perturb which
      catalog growth invalidates a walk.

    WHY THE SPLIT IS PARITY-EXACT (WAVE2-PLAN.md §5a). The whole location filter
    is ``loc(sel₁) OR loc(sel₂) OR …`` and EXISTS distributes over OR, so the old
    single ``EXISTS(id ∈ ⋃ ids(sel))`` equals ``OR_sel [NameExists(sel) OR
    TierExists(sel)]``. This function keeps every ``NameExists`` and every
    non-country ``TierExists`` in ``other_ids`` untouched; it only lifts a
    country selection's ``TierExists(sel)`` out, and :func:`build_search_where`
    replaces it with ``primary_country = code OR (primary_country IS NULL AND
    TierExists(sel))`` — which is row-for-row equal to ``TierExists(sel)`` because
    ``primary_country = code`` is a strict subset of it (a job whose single
    non-remote country is ``code`` necessarily carries a country-tier row) and a
    non-matching or NULL value falls through to the identical EXISTS. So the
    result set is unchanged for ANY population state of ``primary_country``,
    including entirely un-backfilled.

    Returns ``([], [], [])`` when nothing resolves. A caller with an active
    ``locations`` filter that resolves to neither a country path nor an id must
    still emit a predicate matching nothing (a name-miss) — handled at the call
    site (:func:`build_search_where`), not by skipping the filter.
    """
    if not selections:
        return [], [], []
    other_groups: list[sql.Composable] = []
    other_params: list = []
    # Keyed by ISO code so two selections resolving to the same country (e.g.
    # "United States" and a catalog "USA" row) contribute one fast path, and the
    # order stays the selections' first-seen order for stable SQL.
    country_ids: dict[str, list[int]] = {}
    with conn.cursor() as cursor:
        for selection in selections:
            descriptor = descriptors.get(selection)
            if (
                descriptor is not None
                and descriptor["tier"] == "country"
                and descriptor["country"] is not None
            ):
                country = descriptor["country"]
                # Only the country TIER moves to the fast path; the exact-name
                # branch stays in the id-set union, exactly as before — so a
                # (pathological) job tagged with a same-named remote row still
                # matches through ``other_ids``.
                other_groups.append(sql.SQL("l.canonical_name = %s"))
                other_params.append(selection)
                if country not in country_ids:
                    cursor.execute(_COUNTRY_TIER_IDS_SQL, (country,))
                    country_ids[country] = sorted(
                        {int(row["id"]) for row in cursor.fetchall()}
                    )
            else:
                clause, clause_params = _location_match_group(selection, descriptor)
                other_groups.append(clause)
                other_params.extend(clause_params)

        if other_groups:
            query = sql.SQL("SELECT id FROM locations l WHERE ") + sql.SQL(
                " OR "
            ).join(other_groups)
            cursor.execute(query, other_params)
            other_ids = sorted({int(row["id"]) for row in cursor.fetchall()})
        else:  # pragma: no cover - every selection contributes at least a name branch
            other_ids = []

    country_paths = [(code, ids) for code, ids in country_ids.items()]
    all_id_set = set(other_ids)
    for ids in country_ids.values():
        all_id_set.update(ids)
    return country_paths, other_ids, sorted(all_id_set)


def _location_predicate(location_ids: list[int]) -> tuple[sql.Composable, list]:
    """The location filter as one EXISTS over the pre-resolved ``normalized_location_id`` set.

    Replaces the per-row ``EXISTS (… JOIN locations l ON l.id =
    jl.normalized_location_id WHERE … AND (canonical_name = … OR <tier>))`` with a
    join-free integer-set probe. Correlated on ``job_listings.id`` alone, the way
    ``job_locations`` is keyed.

    An EMPTY id set yields ``= ANY('{}')`` → matches nothing, identical to the old
    name-miss behaviour (an EXISTS whose inner predicate no ``locations`` row
    satisfied). A job with NO location tags matches no active location filter,
    unchanged — the frontend's ``matchesLocation`` returns false on an empty tag
    list too, so an unnormalized job is never treated as "everywhere".
    """
    return (
        sql.SQL(
            "EXISTS ("
            " SELECT 1 FROM job_locations jl"
            " WHERE jl.job_listing_id = job_listings.id"
            " AND jl.normalized_location_id = ANY(%s::int[]))"
        ),
        [location_ids],
    )


# One country-tier selection's predicate (Perf Wave 2, C2). The fast branch seeks
# the denormalized ``primary_country`` — which carries real column stats, so the
# planner keeps the ordered ``idx_job_listings_open_country_keyset`` walk and
# early-stops at the LIMIT instead of top-N sorting ~25k rows. The fallback fires
# ONLY for rows whose ``primary_country IS NULL`` (multi-country, remote-only,
# untagged, or not-yet-backfilled) and re-runs the ORIGINAL country-tier test as
# a join-free int-array probe over that selection's own ``locations`` rows, so a
# not-yet-filled value is never a wrong answer. Binds ``[country_code,
# tier_ids]``. Never negated (the location filter is inclusion-only), so a NULL
# result on a NULL-``primary_country`` non-match is indistinguishable from false
# under the AND — exactly as the plain EXISTS was.
_COUNTRY_TIER_PREDICATE = sql.SQL(
    "("
    " job_listings.primary_country = %s"
    " OR ("
    "  job_listings.primary_country IS NULL AND EXISTS ("
    "   SELECT 1 FROM job_locations jl"
    "   WHERE jl.job_listing_id = job_listings.id"
    "   AND jl.normalized_location_id = ANY(%s::int[]))"
    " )"
    ")"
)


# ---------------------------------------------------------------------------
# WHERE composition
# ---------------------------------------------------------------------------


def expand_levels(levels: list[str]) -> list[str]:
    """Apply the new_grad⊂entry hierarchy to a multi-select level filter.

    Selecting "entry" surfaces new-grad roles too; selecting "new_grad" stays
    exact. Same table as the single-value path in ``database._build_where`` — kept
    in code rather than joined from ``job_levels.parent_slug`` for the same reason
    stated there.
    """
    expanded: list[str] = []
    for level in levels:
        for slug in _LEVEL_FILTER_EXPANSION.get(level, [level]):
            if slug not in expanded:
                expanded.append(slug)
    return expanded


def build_search_where(
    *,
    status: str,
    since: datetime | None = None,
    categories: list[str] | None = None,
    levels: list[str] | None = None,
    companies: list[str] | None = None,
    location_ids: list[int] | None = None,
    location_country_paths: list[tuple[str, list[int]]] | None = None,
    locations: list[str] | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    cursor: JobCursor | None = None,
) -> tuple[sql.Composable, list]:
    """Compose the full filter set into one WHERE clause.

    Every dimension ANDs with the others, and multi-value dimensions OR within
    themselves — the same shape as the frontend's ``filterJobsByFilters``.

    NULL-HIDING: ``enrichment_category = ANY(...)`` evaluates to NULL for an
    unenriched row, so an active category or level filter excludes the 65% of OPEN
    rows the enricher has not labelled yet. That is deliberate and matches the
    client matcher (``matchesCategory`` / ``matchesLevel`` both require a non-null
    value). It is stated here because the type docs in ``types/index.ts`` claimed
    the opposite for months.
    """
    conditions: list[sql.Composable] = []
    params: list = []

    conditions.append(sql.SQL("job_listings.status = %s"))
    params.append(status)

    if companies:
        conditions.append(sql.SQL("job_listings.company = ANY(%s::text[])"))
        params.append(list(companies))

    if categories:
        if len(categories) == 1:
            # Plain equality on a single value, not ``= ANY(ARRAY[x])``: it is what
            # lets the planner take ``idx_job_listings_open_category_keyset`` as an
            # ordered equality seek rather than a bitmap + sort.
            conditions.append(sql.SQL("job_listings.enrichment_category = %s"))
            params.append(categories[0])
        else:
            conditions.append(sql.SQL("job_listings.enrichment_category = ANY(%s::text[])"))
            params.append(list(categories))

    if levels:
        conditions.append(sql.SQL("job_listings.enrichment_level = ANY(%s::text[])"))
        params.append(expand_levels(levels))

    # Globally deactivated companies stay hidden regardless of what the caller
    # asked for — same public-read-path guard as ``/api/jobs``.
    conditions.append(_HIDDEN_COMPANY_PREDICATE)

    # ...and so do PRIVATE companies. This endpoint is unauthenticated
    # (``routers/jobs_search.search`` takes only ``Depends(get_db)``) and is
    # allow-listed through the public Vercel proxy, so it is a public read path
    # in exactly the sense :data:`_USER_COMPANY_PREDICATE` means. It was written
    # before ``visibility`` existed and mirrored only the OTHER guard, which left
    # one user's private board readable by anyone the moment E7 landed — rows,
    # ``filtered_total`` and both recency tiles alike.
    #
    # UNCONDITIONAL, never viewer-scoped, for the reason the predicate's own
    # docstring gives: a "hide private companies unless YOU own them" variant
    # turns an unconditional leak into a conditional one. A signed-in reader's
    # own boards are served only by the authed, owner-scoped
    # ``GET /api/users/companies/{id}/jobs``.
    conditions.append(_USER_COMPANY_PREDICATE)

    if since is not None:
        conditions.append(_SINCE_PREDICATE)
        params.append(since)

    if locations:
        # The location filter is ``loc(sel₁) OR loc(sel₂) OR …``. Country-tier
        # selections take the ``primary_country`` fast path (Perf Wave 2, C2);
        # every other selection and every selection's exact-name branch stay on
        # the pre-resolved id-set EXISTS (owner decision ③, app half). ``locations``
        # gates the filter as ACTIVE; the split is what it resolved to (see
        # :func:`resolve_location_filter`).
        location_branches: list[sql.Composable] = []
        for country_code, tier_ids in location_country_paths or []:
            location_branches.append(_COUNTRY_TIER_PREDICATE)
            params.append(country_code)
            params.append(tier_ids)
        other_ids = location_ids or []
        # Emit the id-set EXISTS whenever it carries rows, OR when there is no
        # country path at all — the latter keeps the name-miss case (an active
        # filter that resolved to nothing) matching NOTHING via ``= ANY('{}')``,
        # exactly as before. When country paths do the work and there are no other
        # ids, it is skipped so no dead empty-array semi-join is planned.
        if other_ids or not location_country_paths:
            clause, clause_params = _location_predicate(other_ids)
            location_branches.append(clause)
            params.extend(clause_params)
        conditions.append(
            sql.SQL("(") + sql.SQL(" OR ").join(location_branches) + sql.SQL(")")
        )

    if include:
        branches: list[sql.Composable] = []
        for term in include:
            clause, clause_params = _keyword_condition(term)
            branches.append(clause)
            params.extend(clause_params)
        conditions.append(sql.SQL("(") + sql.SQL(" OR ").join(branches) + sql.SQL(")"))

    for term in exclude or []:
        clause, clause_params = _keyword_condition(term)
        conditions.append(sql.SQL("NOT ") + clause)
        params.extend(clause_params)

    if cursor is not None:
        conditions.append(_CURSOR_PREDICATE)
        params.extend([cursor.first_seen_at, cursor.source_id, cursor.job_id])

    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions), params


def search_jobs(
    conn: Connection,
    *,
    limit: int,
    cursor: JobCursor | None = None,
    **filters: Unpack[SearchFilters],
) -> list[dict]:
    """One page of the filtered keyset walk, newest ``first_seen_at`` first.

    Same column list, freshness join and ordering as ``database.get_jobs``' keyset
    mode, so a row serialized by this endpoint is byte-identical to the same row
    from ``/api/jobs`` and the frontend transformer is shared.

    ``cursor`` is an explicit parameter and deliberately NOT part of
    :class:`SearchFilters`: a page position belongs to the reader, not to the
    query, and keeping it out of the shared filter set is what makes it
    impossible to hand one to :func:`get_search_counts` — which would silently
    return "rows after here" instead of a total.
    """
    where, params = build_search_where(cursor=cursor, **filters)
    # ``db_cursor``, not ``cursor``: the keyset position parameter owns that name
    # here, and shadowing it would make the two silently interchangeable to a
    # reader. Matches ``database.get_jobs``.
    with conn.cursor() as db_cursor:
        db_cursor.execute(_DISABLE_JIT)
        query = sql.SQL("SELECT {} FROM {}{} {} {} LIMIT %s").format(
            _LIST_COLUMNS, _JOBS_TABLE, _FRESHNESS_JOIN, where, _KEYSET_ORDER_BY
        )
        db_cursor.execute(query, [*params, limit])
        return [_row_to_job_dict(row) for row in db_cursor.fetchall()]


# Disables Postgres' JIT for the statement that follows, for the rest of the
# transaction (``get_db`` rolls back at the end of every request, so the scope is
# exactly this request).
#
# Measured on prod: the built-in "Software Engineering" keyword set is six terms,
# each expanding to three ILIKEs plus an EXISTS, and the resulting OR-chain makes
# the planner emit 94 JIT-compiled functions — 1,044 ms of inlining/optimisation/
# emission on top of ~620 ms of actual work. The compiled code is then thrown away
# with the connection. JIT pays off for long analytical scans, not for a
# sub-second OLTP predicate evaluated once, so the cost here is pure overhead.
_DISABLE_JIT = sql.SQL("SET LOCAL jit = off")


def _header_counts_where(companies: list[str] | None) -> tuple[sql.Composable, list]:
    """WHERE for the two recency tiles: the visible OPEN corpus the reader FOLLOWS.

    COMPANY-SCOPED, AND ONLY COMPANY-SCOPED. The tiles ignore category, level,
    keywords, locations, ``since`` and ``status`` — a "Past 24 Hours" number that
    shrank as the user typed in the keyword box would answer a different question
    while looking identical — but they have never counted companies the reader does
    not follow. On the client-side page this endpoint replaces, both figures came
    from ``selectRecentJobsTimeBasedCounts`` → ``selectAllJobsFromQuery`` →
    ``selectEnabledByCompanyId``, i.e. the enabled-companies prefilter and nothing
    else. Dropping that scope here would multiply the tiles by ~40x for a reader
    following 3 of 133 companies.

    The ``first_seen_at >= now() - interval '24 hours'`` bound is what keeps this
    cheap: it restricts the scan to a few hundred index entries of
    ``idx_job_listings_open_first_seen_keyset`` instead of counting all ~31k OPEN
    rows. The FILTERs at the call site then split that window into the two tiles.
    """
    conditions: list[sql.Composable] = [
        sql.SQL("job_listings.status = 'OPEN'"),
        sql.SQL("job_listings.first_seen_at >= now() - interval '24 hours'"),
        _HIDDEN_COMPANY_PREDICATE,
        # Same unconditional private-company guard as ``build_search_where``.
        # Without it the tiles COUNT rows the list cannot show, so the two
        # numbers disagree with the feed beneath them and leak the size of
        # someone else's private board.
        _USER_COMPANY_PREDICATE,
    ]
    params: list = []
    if companies:
        conditions.append(sql.SQL("job_listings.company = ANY(%s::text[])"))
        params.append(list(companies))
    return sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions), params


# The two recency tiles, in ONE round trip. Both are ``FILTER`` clauses over a
# single scan bounded at 24 h, so the 3 h number is a subset of the 24 h one by
# construction.
#
# WHAT USED TO BE HERE — the expensive half. Until Wave-1 B1 this statement also
# carried ``(SELECT count(*) FROM {jobs}{filtered_where}) AS filtered_total`` — an
# EXACT count over the WHOLE matching set, which cannot early-stop the way the
# LIMITed page query does. On a keyword search it re-ran ``_KEYWORD_PREDICATE`` (a
# de-correlated hashed ``SubPlan``, LIMIT-independent) over the entire OPEN corpus,
# so page 1 evaluated the whole keyword predicate TWICE on one pooled connection;
# on a location search it re-ran the 25 k-row materialize a second time (~444 ms).
# Measured on prod that count was the villain of nearly every filtered page-1
# search — keyword page 1 ~1.45 s, location ~2.08 s — and it bought little a reader
# uses on a feed. Owner decision ①: DEFER it. It is now returned ``None`` and the
# client approximates the total from the rows it walks. The exact count, if ever
# wanted back, belongs behind a separate lightweight async request, not on the
# page-1 critical path.
#
# So this statement is now ONLY the tiles. The ``first_seen_at >= now() - interval
# '24 hours'`` bound is what keeps it cheap — a few hundred index entries of
# ``idx_job_listings_open_first_seen_keyset`` rather than a full-corpus scan. It is
# company-scoped and nothing else (``_header_counts_where``): a "Past 24 Hours"
# tile answers "how busy is the market I follow", not "how many rows match my
# current chips".
_SEARCH_COUNTS_SQL = sql.SQL(
    "SELECT"
    " count(*) FILTER"
    "   (WHERE job_listings.first_seen_at >= now() - interval '24 hours')"
    "   AS count_last_24h,"
    " count(*) FILTER"
    "   (WHERE job_listings.first_seen_at >= now() - interval '3 hours')"
    "   AS count_last_3h"
    " FROM {jobs}{header_where}"
)


def get_search_counts(conn: Connection, **filters: Unpack[SearchFilters]) -> SearchCounts:
    """The ``meta`` block for page 1: the two recency tiles, with a deferred total.

    ``filtered_total`` is ``None`` — the exact count is off the page-1 critical path
    since Wave-1 B1 (owner decision ①). The client approximates it from the rows it
    has walked. This deletes the second, expensive predicate evaluation entirely:
    page 1 no longer runs the keyword / location predicate a second time, and the
    ``build_search_where`` call the filtered count needed is gone.

    The two recency figures answer "how busy is the market I follow" and are scoped
    to ``companies`` only; see :func:`_header_counts_where`. ``**filters`` is kept
    in the signature (rather than narrowing to ``companies``) so the router still
    unpacks one shared filter set into both the page and count queries — a filter
    added to :class:`SearchFilters` stays a type error at every site that forgot it.

    The caller must not pass ``cursor``: the tiles are a property of the filter set,
    not of where the reader happens to be, and there is no way to hand one in — the
    keyset position is not part of :class:`SearchFilters`.
    """
    header_where, header_params = _header_counts_where(filters.get("companies"))
    query = _SEARCH_COUNTS_SQL.format(jobs=_JOBS_TABLE, header_where=header_where)
    with conn.cursor() as cursor:
        cursor.execute(_DISABLE_JIT)
        cursor.execute(query, header_params)
        row = cursor.fetchone()
        if not row:
            return SearchCounts(
                filtered_total=None, count_last_24h=0, count_last_3h=0
            )
        return SearchCounts(
            filtered_total=None,
            count_last_24h=int(row["count_last_24h"] or 0),
            count_last_3h=int(row["count_last_3h"] or 0),
        )
