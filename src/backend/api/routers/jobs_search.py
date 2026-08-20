"""Server-side filtered job search — ``GET /api/jobs/search``.

The Recent Jobs page's read path. Where ``GET /api/jobs`` is a raw windowed dump
that the client filters, this endpoint applies the user's whole filter set in SQL
and pages the *result*, so every page it returns is made of rows the user asked
for and an empty page means "no more matches" rather than "keep digging".

That distinction is the point of the endpoint: see
``services/job_search.py`` for why the client-side arrangement was structurally
deadlock-prone, and
``docs/incidents/2026-08-10-recent-jobs-empty-filter-deadlock.md`` for the
production failure that made the case.

FUTURE: a semantic ``?q=`` search ranked by vector similarity belongs in this
router as an additional ordering mode. Note it cannot reuse these cursors as-is:
a relevance ordering has no immutable, unique sort key to seek on.
"""

import logging
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..models import (
    ENABLED_COMPANY_ID_PATTERN,
    JobListingResponse,
    JobSearchMeta,
    JobSearchResponse,
)
from ..pagination import (
    MAX_CURSOR_LENGTH,
    MAX_TIMESTAMP_LENGTH,
    InvalidCursorError,
    JobCursor,
    compute_filter_fingerprint,
    decode_search_cursor,
    encode_search_cursor,
    parse_utc_timestamp,
)
from ..services.job_search import (
    SearchFilters,
    get_search_counts,
    resolve_location_selections,
    search_jobs,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Caps. Each mirrors an existing bound elsewhere in the codebase rather than
# inventing a new number: locations and keywords match the saved-filters models'
# ``_MAX_LOCATIONS`` / ``_MAX_TAGS_PER_LIST`` / ``_MAX_TAG_TEXT_LEN``, which is
# where these same values are persisted.
#
# ``company`` is the exception, and it must NOT mirror ``jobs.py``'s
# ``_MAX_COMPANIES_PER_REQUEST`` (150) the way it originally did. That endpoint is
# walked in chunks of 50 ids per request, so its cap was unreachable in practice;
# here the client sends the reader's WHOLE enabled set in one request, and
# ``auto_enroll_new_companies`` defaults to true — so the default signed-in user
# sends one id per company on the roster (133 enabled of 135 rows in prod on
# 2026-08-19). A cap anywhere near the roster is a cliff: the release that pushes
# the roster past it turns Recent Jobs into a hard 400 for every "all companies"
# reader at once. This is a denial-of-service bound, not a product bound, so it
# sits far above the roster and the correct response to the roster approaching it
# is to raise it — never to truncate the list, which would silently hide
# companies the reader follows.
_MAX_COMPANIES = 500
_MAX_FACET_VALUES = 20
_MAX_LOCATIONS = 100
_MAX_LOCATION_LENGTH = 200
# Keyword terms are the one filter whose cost is linear in the number of VALUES:
# each term adds four ILIKEs plus a correlated EXISTS over job_tags, evaluated per
# candidate row, on BOTH the page query and the page-1 count. Measured at prod
# scale, 100 terms takes ~8.8s per query — two of those would pin a pooled
# connection for ~18s, and with DB_POOL_MAX=15 that starves every other route.
# This database already has a pool-exhaustion incident
# (docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md).
#
# 20 is comfortably above any real use — the built-in "Software Engineering" list
# is 6 terms and the widest list in prod is 11 (2026-08-19) — while keeping the
# worst case in the hundreds of milliseconds.
#
# It is also the SAME number as ``models._MAX_TAGS_PER_LIST``, and that identity
# is load-bearing rather than tidy. A saved keyword list auto-hydrates into the
# Recent page's filter chips on page load, which become these very parameters, so
# a list the user is allowed to STORE but not to QUERY breaks Recent Jobs on
# arrival for that user, with no client-side clamp anywhere to save them. Raise
# both together or neither.
_MAX_KEYWORDS = 20
_MAX_KEYWORD_LENGTH = 100

# ``\Z``, never ``$``. In Python ``$`` also matches immediately before a trailing
# newline, so ``?category=software_engineering%0A`` or ``?company=stripe%0A`` would
# validate here and then be compared against the column as a different string —
# matching no row, so the caller gets a silent 200 with zero results instead of the
# 400/422 the contract promises. Exactly the hazard ``pagination.py`` documents at
# ``_SOURCE_ID_RE``, where the same fix applies.
_COMPANY_ID_RE = re.compile(ENABLED_COMPANY_ID_PATTERN.rstrip("$") + r"\Z")
_CATEGORY_RE = re.compile(r"\A[a-z_]{1,40}\Z")
_LEVEL_RE = re.compile(r"\A[a-z_]{1,20}\Z")

# Control characters have no business in a filter value and would corrupt the
# fingerprint's NUL-separated canonical form if one ever slipped through.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _dedupe(values: list[str]) -> list[str]:
    """Drop duplicates, preserving first-seen order.

    Order preservation is not cosmetic: it keeps the generated SQL (and therefore
    EXPLAIN output and the captured-SQL tests) stable for a given request.
    """
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _validate_slugs(
    values: list[str] | None, *, pattern: re.Pattern[str], field: str
) -> list[str] | None:
    """Validate a repeated slug parameter (``category`` / ``level``).

    A well-formed slug that is not in the seeded taxonomy is NOT an error — it
    simply matches nothing, exactly as an unknown value does client-side. Only
    malformed input (which signals a broken caller, not an empty result) is
    rejected.
    """
    if not values:
        return None
    if len(values) > _MAX_FACET_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"'{field}' accepts at most {_MAX_FACET_VALUES} values.",
        )
    for value in values:
        if not pattern.match(value):
            raise HTTPException(
                status_code=422, detail=f"Invalid '{field}' value: {value!r}"
            )
    return _dedupe(values)


def _validate_companies(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    if len(values) > _MAX_COMPANIES:
        raise HTTPException(
            status_code=400, detail=f"'company' accepts at most {_MAX_COMPANIES} IDs."
        )
    for value in values:
        if not _COMPANY_ID_RE.match(value):
            raise HTTPException(
                status_code=400, detail=f"Invalid company id in 'company': {value!r}"
            )
    return _dedupe(values)


def _validate_text_list(
    values: list[str] | None,
    *,
    field: str,
    max_values: int,
    max_length: int,
    combined_with: list[str] | None = None,
) -> list[str] | None:
    """Validate a repeated free-text parameter (``location`` / ``include`` / ``exclude``).

    Empty strings are rejected rather than dropped. A caller that sends
    ``?include=`` has a bug — most likely an un-guarded template — and silently
    treating it as "no keyword filter" hands back a result set the caller believes
    was filtered.
    """
    if not values:
        return None
    total = len(values) + len(combined_with or [])
    if total > max_values:
        raise HTTPException(
            status_code=400,
            detail=f"'{field}' accepts at most {max_values} values.",
        )
    for value in values:
        if not value:
            raise HTTPException(
                status_code=422, detail=f"'{field}' values must not be empty."
            )
        if len(value) > max_length:
            raise HTTPException(
                status_code=422,
                detail=f"'{field}' values must be at most {max_length} characters.",
            )
        if _CONTROL_CHARS_RE.search(value):
            raise HTTPException(
                status_code=422,
                detail=f"'{field}' values must not contain control characters.",
            )
    return _dedupe(values)


@router.get("", response_model=JobSearchResponse)
def search(
    conn: Connection = Depends(get_db),
    status: str = Query(
        default="OPEN",
        pattern=r"^(OPEN|CLOSED)$",
        description=(
            "Listing status. Defaults to OPEN — unlike /api/jobs, which has no "
            "default — because this endpoint exists to serve the live job feed and "
            "the keyset indexes are partial on status = 'OPEN'."
        ),
    ),
    since: str | None = Query(
        default=None,
        max_length=MAX_TIMESTAMP_LENGTH,
        description=(
            "Recency lower bound, INCLUSIVE (first_seen_at >= since). ISO-8601 with "
            "a UTC offset. MUST be frozen for the duration of a walk and replayed "
            "verbatim on every page — it participates in the cursor fingerprint, so "
            "recomputing it per page is a 422."
        ),
    ),
    cursor: str | None = Query(
        default=None,
        max_length=MAX_CURSOR_LENGTH,
        description=(
            "Opaque token from the previous response's `nextCursor`. Echo it back "
            "verbatim. Only valid under the exact filter set that minted it."
        ),
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Page size. Changing it mid-walk is legal and does not invalidate a cursor.",
    ),
    category: list[str] | None = Query(
        default=None,
        description="Repeatable enrichment category slug. Multiple values OR together.",
    ),
    level: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable enrichment level slug. Multiple values OR together; "
            "'entry' also matches new_grad (new_grad ⊂ entry)."
        ),
    ),
    company: list[str] | None = Query(
        default=None,
        description="Repeatable company id. Multiple values OR together. Omit for all.",
    ),
    location: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable canonical location name, matched HIERARCHICALLY: a country "
            "matches its regions and cities, a region matches its cities. "
            "'United States' and '<State>, US' are resolvable even though no "
            "locations row carries them."
        ),
    ),
    include: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable keyword. A job matches if ANY include term appears in its "
            "title, raw location, company, or tags (case-insensitive substring)."
        ),
    ),
    exclude: list[str] | None = Query(
        default=None,
        description="Repeatable keyword. A job is dropped if ANY exclude term matches.",
    ),
) -> JobSearchResponse:
    """Search jobs with the Recent page's full filter set applied server-side.

    RESPONSE ENVELOPE
    -----------------
    ``{jobs, nextCursor, meta}``. ``nextCursor`` is present iff the page came back
    full (``len(jobs) == limit``); its **absence is the only end-of-walk signal**.
    A trailing exactly-full page therefore costs one extra round trip that returns
    an empty ``jobs`` array — the standard keyset trade-off, preferred over a
    ``LIMIT limit + 1`` probe that would over-fetch on every page.

    ``meta`` is computed on page 1 only (no ``cursor``) and is ``null`` afterwards:
    the counts describe the whole filter set, so recomputing them per page is pure
    waste. ``filteredTotal`` counts the active filters. ``countLast24h`` /
    ``countLast3h`` honour ``company`` and NOTHING else — they answer "how busy is
    the market I follow", which is what the Recent page's recency tiles have always
    shown (client-side they came off the enabled-companies prefilter, before any
    other filter was applied).

    CURSORS ARE FILTER-BOUND
    ------------------------
    Unlike ``/api/jobs``, a cursor here embeds a fingerprint of the filters that
    minted it, and replaying it against a different filter set is a **422**. On an
    endpoint that filters server-side, a cursor carried across a filter change
    produces a plausible 200 whose pages enumerate neither filter set completely —
    silent, and the exact failure mode keyset paging exists to eliminate. The
    fingerprint covers ``status``, ``since`` and every filter list; it deliberately
    excludes ``limit``, so changing page size mid-walk stays legal.

    FILTER SEMANTICS (parity with the client matcher this replaced)
    --------------------------------------------------------------
    Dimensions AND together; values within a dimension OR. An active ``category``
    or ``level`` filter **hides unenriched rows** (NULL category/level) — 65% of
    OPEN rows at the time of writing. Keyword terms match a narrowed haystack
    (title, raw location, company, tags) — see ``services/job_search.py`` for why
    ``department``/``team`` are excluded. A job with no normalized location tags
    matches no active location filter.
    """
    categories = _validate_slugs(category, pattern=_CATEGORY_RE, field="category")
    levels = _validate_slugs(level, pattern=_LEVEL_RE, field="level")
    companies = _validate_companies(company)
    locations = _validate_text_list(
        location,
        field="location",
        max_values=_MAX_LOCATIONS,
        max_length=_MAX_LOCATION_LENGTH,
    )
    include_terms = _validate_text_list(
        include,
        field="include",
        max_values=_MAX_KEYWORDS,
        max_length=_MAX_KEYWORD_LENGTH,
        combined_with=exclude,
    )
    exclude_terms = _validate_text_list(
        exclude,
        field="exclude",
        max_values=_MAX_KEYWORDS,
        max_length=_MAX_KEYWORD_LENGTH,
        combined_with=include,
    )

    parsed_since: datetime | None = None
    if since is not None:
        try:
            parsed_since = parse_utc_timestamp(since, field="'since'")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid 'since': {exc}")

    # Fingerprint the EFFECTIVE filter set (post-validation, post-dedupe) so two
    # requests that mean the same thing hash the same way. ``since`` uses the
    # normalized UTC form rather than the raw string, so an equivalent offset
    # (+00:00 vs Z) does not invalidate a walk.
    fingerprint = compute_filter_fingerprint(
        {
            "status": status,
            "since": parsed_since.isoformat() if parsed_since else None,
            "category": categories or [],
            "level": levels or [],
            "company": companies or [],
            "location": locations or [],
            "include": include_terms or [],
            "exclude": exclude_terms or [],
        }
    )

    parsed_cursor: JobCursor | None = None
    if cursor is not None:
        try:
            parsed_cursor = decode_search_cursor(cursor, expected_fingerprint=fingerprint)
        except InvalidCursorError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid 'cursor': {exc}")

    # Resolved once and shared by the page query and the count query below, so a
    # single request never resolves the same names twice.
    location_descriptors = (
        resolve_location_selections(conn, locations) if locations else {}
    )

    # Annotated, not inferred: a bare dict literal widens to
    # dict[str, <union of everything>] and the two unpack sites below stop being
    # type-checked at all.
    filters: SearchFilters = {
        "status": status,
        "since": parsed_since,
        "categories": categories,
        "levels": levels,
        "companies": companies,
        "locations": locations,
        "location_descriptors": location_descriptors,
        "include": include_terms,
        "exclude": exclude_terms,
    }

    jobs = search_jobs(conn, limit=limit, cursor=parsed_cursor, **filters)

    next_cursor: str | None = None
    if len(jobs) == limit:
        tail = jobs[-1]
        next_cursor = encode_search_cursor(
            tail["first_seen_at"], tail["source_id"], tail["id"], fingerprint
        )

    meta: JobSearchMeta | None = None
    if parsed_cursor is None:
        # One statement for all three numbers. Page 1 already spends this
        # request's single pooled connection on the row query (and on a location
        # resolve when a location filter is active); splitting the counts back
        # into two statements adds a round trip to the checkout that prod's
        # DB_POOL_MAX=15 / 5s timeout has already been seen to run out of.
        counts = get_search_counts(conn, **filters)
        meta = JobSearchMeta(
            filtered_total=counts["filtered_total"],
            count_last_24h=counts["count_last_24h"],
            count_last_3h=counts["count_last_3h"],
        )

    return JobSearchResponse(
        jobs=[JobListingResponse(**job) for job in jobs],
        next_cursor=next_cursor,
        meta=meta,
    )
