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
import time
from collections.abc import Mapping
from typing import NoReturn
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
    StaleCursorError,
    JobCursor,
    compute_filter_fingerprint,
    decode_search_cursor,
    encode_search_cursor,
    parse_utc_timestamp,
)
from ..services.job_search import (
    LocationDescriptor,
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
# Keyword terms are the one filter whose cost is linear in the number of VALUES,
# and the mechanism is NOT the one you would guess from reading
# ``_KEYWORD_PREDICATE``. Each term adds four ILIKEs plus an ``EXISTS`` over
# ``job_tags`` — but Postgres DE-CORRELATES that EXISTS into a hashed ``SubPlan``,
# so it is not evaluated per candidate row at all. It is executed ONCE
# (``loops=1``) and then probed, which makes it **independent of LIMIT**: a 50-row
# page pays the same tag work as a count over the whole corpus. And PAGE 1 PAYS IT
# TWICE — ``get_search_counts``' ``filtered_total`` subquery applies the identical
# predicate alongside the page query, on the SAME pooled connection, against
# ``DB_POOL_MAX=15`` / ``DB_POOL_TIMEOUT=5s``. This database already has a
# pool-exhaustion incident
# (docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md).
#
# WHAT THAT SUBPLAN COSTS IS NOW BOUNDED BY AN INDEX. Migration ``536c1cddcd28``
# added ``idx_job_tags_tag_trgm``, a GIN trigram index on ``job_tags(tag)``, so the
# per-term ``t.tag ILIKE '%…%'`` is a ``Bitmap Index Scan`` instead of the full
# ``Seq Scan`` the plain btree ``idx_job_tags_tag`` could never serve (a btree
# cannot answer a LEADING wildcard).
#
# MEASURED at prod scale (76,030 listings / 31,941 OPEN / 111,831 tags; the
# endpoint's own statements, ``SET LOCAL jit = off`` in force, ``limit=50``,
# 133-company roster, ``since`` = epoch), BEFORE -> AFTER that index:
#   * per term, ``job_tags`` work:  ~43 ms  ->  ~1.5 ms   (~25x)
#   * 1 term    page + counts:    116.5 ms  ->   50.0 ms
#   * 6 terms   page + counts:    617.5 ms  ->  208.6 ms   (the built-in list)
#   * 20 terms  page + counts:   1806.6 ms  ->  441.9 ms   (this cap)
# Prod's absolute numbers run ~2.5-4x these (round 5 measured the 6-term list
# UNindexed at 1.73 s counts + 0.52 s page on prod, 2026-08-20); the plan shape —
# which is what the index changes — is the same. See the migration for the full
# table and for the measurement method.
#
# So a full 20-term set now costs LESS than the 6-term built-in list did, and the
# residual is no longer in ``job_tags`` at all — it is the four un-indexed ILIKEs
# per term over the OPEN ``job_listings`` rows. That is the thing to attack next if
# this cap ever needs to rise; do NOT raise it on the strength of the trigram index
# alone.
#
# 20 is still above any observed use — the built-in list is 6 terms and the widest
# saved list in prod is 11 (2026-08-19).
#
# NOT covered by the index: a term shorter than THREE characters yields no complete
# trigram, so pg_trgm can extract no key and the planner keeps the ``Seq Scan``.
# ``go``, ``ai`` and ``ml`` are all real, popular tags. Measured, ONE such term
# costs 110-118 ms of page-1 DB time against 50 ms for a 3+ character term, over a
# 13 ms no-keyword floor — so its marginal cost is ~2.5x a long term's, and it is
# the only shape of this filter the index cannot bound.
#
# It is also the SAME number as ``models._MAX_TAGS_PER_LIST``, and that identity
# is load-bearing rather than tidy. A saved keyword list auto-hydrates into the
# Recent page's filter chips on page load, which become these very parameters, so
# a list the user is allowed to STORE but not to QUERY breaks Recent Jobs on
# arrival for that user, with no client-side clamp anywhere to save them. Raise
# both together or neither.
_MAX_KEYWORDS = 20
_MAX_KEYWORD_LENGTH = 100

# Half of prod's DB_POOL_TIMEOUT (5s). A request past this has not failed, but it
# is holding a pooled connection long enough that a few concurrent ones would
# start queueing — which is the shape the 2026-08-19 checkout-timeout burst took.
_SLOW_SEARCH_MS = 2500.0

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


def _reject(status_code: int, detail: str, **context: object) -> NoReturn:
    """Log a rejection, then raise it.

    Every rejection on this endpoint goes through here instead of raising
    ``HTTPException`` directly, so that adding a new one without logging it is
    not something you can do by accident. Before this, both new modules on the
    Recent page's primary read path bound a module logger and never called it —
    a cap that started firing in production was a bare 400 in the access log and
    nothing else, which is the wrong thing to discover from a user report.

    WARNING, not ERROR: a rejection is the endpoint working. It becomes
    interesting when the RATE changes — a cap suddenly firing means either a
    client regression or a bound that reality has outgrown, and both are
    invisible without a line to count.

    ``detail`` is already reader-safe (it is surfaced verbatim to the browser for
    400/422), so logging it verbatim leaks nothing that the caller did not send.
    """
    if context:
        extras = " ".join(f"{k}={v!r}" for k, v in sorted(context.items()))
        logger.warning("jobs-search rejected %d: %s (%s)", status_code, detail, extras)
    else:
        logger.warning("jobs-search rejected %d: %s", status_code, detail)
    raise HTTPException(status_code=status_code, detail=detail)


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
        _reject(400, f"'{field}' accepts at most {_MAX_FACET_VALUES} values.",
                field=field, received=len(values))
    for value in values:
        if not pattern.match(value):
            _reject(422, f"Invalid '{field}' value: {value!r}", field=field)
    return _dedupe(values)


def _validate_companies(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    if len(values) > _MAX_COMPANIES:
        _reject(400, f"'company' accepts at most {_MAX_COMPANIES} IDs.",
                received=len(values), cap=_MAX_COMPANIES)
    for value in values:
        if not _COMPANY_ID_RE.match(value):
            _reject(400, f"Invalid company id in 'company': {value!r}")
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
        _reject(400, f"'{field}' accepts at most {max_values} values.",
                field=field, received=len(values), partner=len(combined_with or []),
                cap=max_values)
    for value in values:
        if not value:
            _reject(422, f"'{field}' values must not be empty.", field=field)
        if len(value) > max_length:
            _reject(422, f"'{field}' values must be at most {max_length} characters.",
                    field=field, length=len(value))
        if _CONTROL_CHARS_RE.search(value):
            _reject(422, f"'{field}' values must not contain control characters.",
                    field=field)
    return _dedupe(values)


def _fingerprint_location_descriptors(
    descriptors: Mapping[str, LocationDescriptor],
) -> list[str]:
    """Canonical, order-independent rendering of a resolved location mapping.

    One entry per selection that resolved, ``name>tier|city|region|country|scope``,
    sorted by name. Returned as a LIST so ``compute_filter_fingerprint`` applies
    its own NUL join — the fields can contain commas ("Austin, TX, US") and a
    comma join would let two different mappings serialize identically, which is a
    hole in the one mechanism whose whole job is spotting a changed filter set.

    A selection that resolves to nothing is absent here, exactly as it is absent
    from the mapping: it still matches by exact canonical name via
    ``_location_condition``, and that path does not depend on live ranking, so it
    has nothing to drift.
    """
    return [
        "{}>{}|{}|{}|{}|{}".format(
            name,
            d["tier"],
            d["city"] or "",
            d["region"] or "",
            d["country"] or "",
            d["remote_scope"] or "",
        )
        for name, d in sorted(descriptors.items())
    ]


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
            "recomputing it per page is a 409."
        ),
    ),
    cursor: str | None = Query(
        default=None,
        max_length=MAX_CURSOR_LENGTH,
        description=(
            "Opaque token from the previous response's `nextCursor`. Echo it back "
            "verbatim. Only valid under the exact filter set that minted it: a "
            "cursor from a different filter set (or an older cursor format) is a "
            "409, which means DROP THE CURSOR AND RE-REQUEST PAGE 1. A malformed "
            "token is a 422, which means fix the caller."
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
            "title, raw location, company, tags, or experience level (the field the "
            "UI labels 'department') — case-insensitive substring."
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
    minted it, and replaying it against a different filter set is a **409**. On an
    endpoint that filters server-side, a cursor carried across a filter change
    produces a plausible 200 whose pages enumerate neither filter set completely —
    silent, and the exact failure mode keyset paging exists to eliminate. The
    fingerprint covers ``status``, ``since`` and every filter list; it deliberately
    excludes ``limit``, so changing page size mid-walk stays legal.

    **409 vs 422 on ``cursor``** is a contract, not a detail. 409 = the token is
    well-formed but names a different query (fingerprint moved, or the format tag
    did): the fix is mechanical and belongs to the client — drop the cursor and
    restart from page 1. 422 = the token is malformed: nothing downstream can
    repair it. A client that cannot tell them apart has to either replay a cursor
    that will never be accepted or restart on every cursor error; both are wrong.
    See ``StaleCursorError`` in ``api/pagination.py``.

    FILTER SEMANTICS (parity with the client matcher this replaced)
    --------------------------------------------------------------
    Dimensions AND together; values within a dimension OR. An active ``category``
    or ``level`` filter **hides unenriched rows** (NULL category/level) — 65% of
    OPEN rows at the time of writing. Keyword terms match title, raw location,
    company, tags and ``experience_level`` — the column the UI labels ``department``
    — while ``team`` is unsearched only because no transformer populates it; see
    ``services/job_search.py`` for the field-by-field parity argument. A job with no normalized location tags
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
            _reject(422, f"Invalid 'since': {exc}")

    # Resolved BEFORE the fingerprint, and folded into it — see below. Also
    # shared by the page query and the count query, so a single request never
    # resolves the same names twice.
    location_descriptors = (
        resolve_location_selections(conn, locations) if locations else {}
    )

    # Fingerprint the EFFECTIVE filter set (post-validation, post-dedupe) so two
    # requests that mean the same thing hash the same way. ``since`` uses the
    # normalized UTC form rather than the raw string, so an equivalent offset
    # (+00:00 vs Z) does not invalidate a walk.
    #
    # ``location_resolved`` is in here, and the ordering above exists for it.
    # A location SELECTION is a canonical name, but what actually reaches the
    # WHERE clause is the DESCRIPTOR that name resolves to, and that resolution
    # reads live data: ``_RESOLVE_LOCATIONS_SQL`` ranks duplicate
    # ``canonical_name`` rows with ``row_number()`` over a per-row
    # ``job_locations`` count, and prod carries 48 duplicated canonical names.
    # A scrape that moves one job between two same-named rows can therefore flip
    # which descriptor wins BETWEEN page 1 and page N — the reader keeps paging,
    # every cursor still validates, and the filter set has silently changed
    # underneath them. Fingerprinting the raw names cannot see that; fingerprinting
    # what they resolved to can, and turns it into the 409 restart below.
    fingerprint = compute_filter_fingerprint(
        {
            "status": status,
            "since": parsed_since.isoformat() if parsed_since else None,
            "category": categories or [],
            "level": levels or [],
            "company": companies or [],
            "location": locations or [],
            "location_resolved": _fingerprint_location_descriptors(location_descriptors),
            "include": include_terms or [],
            "exclude": exclude_terms or [],
        }
    )

    parsed_cursor: JobCursor | None = None
    if cursor is not None:
        try:
            parsed_cursor = decode_search_cursor(cursor, expected_fingerprint=fingerprint)
        except StaleCursorError as exc:
            # 409, not 422, and the split is about WHO can act on it. Every other
            # rejection on this endpoint names something the caller's filter set
            # got wrong, which is why the client surfaces 400/422 `detail` to the
            # reader verbatim. This one decoded perfectly and says "restart the
            # walk from page 1" — an instruction to the CLIENT that no reader can
            # carry out, arriving in a next-page error box whose only affordance
            # replays the SAME stale cursor. Ordered before the InvalidCursorError
            # arm because StaleCursorError subclasses it.
            _reject(409, f"Stale 'cursor': {exc}")
        except InvalidCursorError as exc:
            _reject(422, f"Invalid 'cursor': {exc}")

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

    started = time.monotonic()
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

    # One line per slow request, on the endpoint that owns the Recent page's
    # entire read path. The keyword predicate runs four un-indexed ILIKEs per
    # term over job_listings on top of the (now trigram-indexed) job_tags probe,
    # and page 1 pays the whole predicate twice — so DB time here scales with the
    # reader's keyword count, against prod's DB_POOL_TIMEOUT of 5s. A checkout
    # timeout is the failure mode; this is the number that predicts it, and
    # without it the first sign would be users reporting a dead page.
    elapsed_ms = (time.monotonic() - started) * 1000
    if elapsed_ms >= _SLOW_SEARCH_MS:
        logger.warning(
            "jobs-search slow: %.0fms page=%s keywords=%d companies=%d locations=%d",
            elapsed_ms,
            "1" if parsed_cursor is None else "n",
            len(include_terms or []) + len(exclude_terms or []),
            len(companies or []),
            len(locations or []),
        )

    return JobSearchResponse(
        jobs=[JobListingResponse(**job) for job in jobs],
        next_cursor=next_cursor,
        meta=meta,
    )
