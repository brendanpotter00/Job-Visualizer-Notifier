"""Jobs API endpoints - GET /api/jobs, GET /api/jobs/{source_id}/{id}."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..models import (
    COMPANY_PATTERN,
    ENABLED_COMPANY_ID_PATTERN,
    FacetOption,
    JobFacetsResponse,
    JobListingResponse,
)
from ..pagination import (
    MAX_CURSOR_LENGTH,
    MAX_TIMESTAMP_LENGTH,
    InvalidCursorError,
    JobCursor,
    decode_job_cursor,
    encode_job_cursor,
    parse_utc_timestamp,
)
from ..services.database import get_jobs, get_job_by_id
from ..services.enrichment_monitor import get_facets

router = APIRouter()

# Response header carrying the opaque cursor for the NEXT page.
#
# Deliberately a header and not a body field: the response is a bare JSON array
# and has been since the endpoint shipped. Wrapping it in
# ``{"items": [...], "nextCursor": ...}`` would break every existing consumer
# (the frontend transformer, the admin QA table, any direct API user) in one go,
# for a field only the paging caller needs. The header keeps the body contract
# untouched and makes cursor support purely additive.
#
# Delivery path, all THREE hops of which are handled in this PR. Any one of them
# missing means the header silently never reaches the client:
#   * ``api/jobs.ts`` (the Vercel proxy) explicitly re-emits it — ``forwardResponse``
#     copies status + body only, so without that line the header dies at the proxy.
#   * ``CORSMiddleware`` in ``api/main.py`` lists it in ``expose_headers`` — a
#     browser cannot read a non-safelisted response header cross-origin otherwise.
#   * ``vercel.json``'s ``/api/(.*)`` header block adds
#     ``Access-Control-Expose-Headers`` for cross-origin callers of the PROXY,
#     which never touch the FastAPI CORS middleware at all.
NEXT_CURSOR_HEADER = "X-Next-Cursor"

# Max IDs accepted in `?companies=a,b,c` to bound query size and prevent
# unbounded `IN`-list scans. Recent Jobs fans out across all backend-scraper
# companies — 102 today (Greenhouse + Ashby + Lever + Gem + Eightfold +
# Google/Apple/Microsoft). 150 keeps the original ~50% headroom posture
# (cap was 100 against 49 companies when added). The frontend chunks
# requests at 50 IDs/call so this server-side cap is a defense-in-depth
# bound, not the hot path.
_MAX_COMPANIES_PER_REQUEST = 150
_COMPANY_ID_RE = re.compile(ENABLED_COMPANY_ID_PATTERN)


@router.get(
    "",
    response_model=list[JobListingResponse],
    # Declared so /docs and the generated OpenAPI schema show the end-of-walk
    # signal. A paging client that does not know the header exists cannot page at
    # all, and the header is the ONLY thing that tells it when to stop — leaving it
    # undocumented would make the contract discoverable only by reading this file.
    responses={
        200: {
            "headers": {
                NEXT_CURSOR_HEADER: {
                    "description": (
                        "Opaque token for the next page. Present iff this page came "
                        "back full (len == limit) and keyset paging was requested "
                        "(`since` and/or `cursor`). ABSENT means end of results — "
                        "it is the only termination signal. Echo it back verbatim "
                        "as `?cursor=`."
                    ),
                    "schema": {"type": "string"},
                }
            }
        }
    },
)
def list_jobs(
    response: Response,
    conn: Connection = Depends(get_db),
    company: str | None = Query(default=None, pattern=COMPANY_PATTERN),
    companies: str | None = Query(
        default=None,
        description=(
            "Comma-separated list of company IDs. Mutually exclusive with "
            "`company`. Max 150 IDs."
        ),
        max_length=4096,
    ),
    status: str | None = Query(default=None, pattern=r"^(OPEN|CLOSED)$"),
    category: str | None = Query(
        default=None, pattern=r"^[a-z_]{1,40}$",
        description="Enrichment category slug (e.g. software_engineering).",
    ),
    level: str | None = Query(
        default=None, pattern=r"^[a-z_]{1,20}$",
        description="Enrichment level slug; 'entry' also matches new_grad (new_grad⊂entry).",
    ),
    # Cap accommodates the Recent Jobs page's batched fetch across all
    # backend-scraper companies (~16k+ OPEN rows at the time of writing) in
    # one round trip. The per-company default remains 5000.
    limit: int = Query(default=5000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
    since: str | None = Query(
        default=None,
        max_length=MAX_TIMESTAMP_LENGTH,
        description=(
            "Recency lower bound, INCLUSIVE: only jobs with "
            "`first_seen_at >= since`. ISO-8601 with a UTC offset "
            "(e.g. 2026-05-07T00:00:00Z). No server default — omitting it means "
            "no lower bound, i.e. today's behaviour. Presence switches the "
            "endpoint into keyset-paging mode."
        ),
    ),
    cursor: str | None = Query(
        default=None,
        max_length=MAX_CURSOR_LENGTH,
        description=(
            "Opaque page token echoed back from a previous response's "
            "`X-Next-Cursor` header. Treat it as a blob. Presence switches the "
            "endpoint into keyset-paging mode."
        ),
    ),
) -> list[JobListingResponse]:
    """List jobs with optional filtering by company and status.

    Accepts either a single ``company`` or a comma-separated ``companies``
    list (for batched per-company fetches from the Recent Jobs page).
    Passing both is a 400.

    KEYSET PAGINATION (``since`` / ``cursor``)
    ------------------------------------------
    Passing either parameter switches this endpoint from ``ORDER BY
    last_seen_at DESC`` to the bounded keyset ordering ``(first_seen_at DESC,
    source_id DESC, id DESC)``. Passing NEITHER is byte-identical to the
    pre-keyset behaviour — same SQL, same ordering, same response, no new header
    — so every existing caller is untouched.

    Response shape is unchanged either way: a **bare JSON array**. The token for
    the next page rides in the ``X-Next-Cursor`` response header:

    * **Present** when the page came back full (``len(page) == limit``), meaning
      more rows may exist. Re-issue the same request with ``cursor`` set to that
      value.
    * **Absent** when the page came back short — that is the end of the walk, and
      the only end signal. A trailing exactly-full page therefore costs one extra
      round trip that returns an empty array; that is the standard keyset
      trade-off, and it is preferred over guessing (a ``LIMIT limit + 1`` probe
      would make the endpoint over-fetch on every single page).
    * Never emitted on the legacy (no ``since``, no ``cursor``) path — a cursor
      minted from a ``last_seen_at``-ordered page would point at the wrong
      boundary in the ``first_seen_at`` ordering and silently skip rows.

    To page the full corpus with no recency bound, pass a floor such as
    ``since=1970-01-01T00:00:00Z``; there is no separate "enable paging" switch.

    Both parameters are validated **fail-loud**: anything malformed is a 422 with
    a specific reason, never a silently-ignored parameter. A dropped cursor would
    restart the walk at page 1 with no signal to the client.

    ``offset`` is **rejected (422) in keyset mode**. The two are different answers
    to the same question — "where does this page start?" — and applying both means
    the cursor seeks to the boundary and ``OFFSET n`` then throws away the first
    ``n`` rows *after* it. That is silent row loss with a 200, the exact failure
    keyset paging exists to remove. ``offset=0`` is fine (it is the default and a
    no-op); the legacy path is untouched and still supports ``offset`` normally.

    A cursor is only meaningful **under the same filter set it was minted with**.
    Changing ``companies`` / ``status`` / ``category`` / ``level`` / ``since``
    partway through a walk is not an error and does not corrupt anything — the
    cursor names a position in the sort order, which is filter-independent — but
    the resulting pages are relative to the NEW filters, so the walk is no longer
    a complete enumeration of either set. Treat a filter change as starting a new
    walk and drop the cursor.

    ``status`` composes with cursors normally (the predicates simply AND
    together). Note that ``idx_job_listings_open_first_seen_keyset`` is partial on
    ``status = 'OPEN'``, so **any request that does not filter to OPEN — including
    one that omits ``status`` entirely, not just ``status=CLOSED`` — falls off it**
    and sorts instead of seeking. Still correct, just unindexed for the ordering.
    Accepted deliberately: every real caller of the paged path filters to OPEN, and
    a full index over both statuses would carry the bloat cost this table's whole
    2026 index history is about.
    """
    parsed_cursor: JobCursor | None = None
    if cursor is not None:
        try:
            parsed_cursor = decode_job_cursor(cursor)
        except InvalidCursorError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid 'cursor': {exc}")

    parsed_since: datetime | None = None
    if since is not None:
        try:
            parsed_since = parse_utc_timestamp(since, field="'since'")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid 'since': {exc}")

    # See the docstring: offset and a keyset cursor are competing definitions of
    # "where this page starts", and get_jobs applies BOTH (the LIMIT/OFFSET tail is
    # shared by either ordering). The combination therefore skips `offset` rows past
    # the cursor boundary and returns a 200 — silent loss. Reject instead of
    # silently ignoring `offset`, per this router's fail-loud posture.
    if offset and (parsed_cursor is not None or parsed_since is not None):
        raise HTTPException(
            status_code=422,
            detail=(
                "'offset' is incompatible with keyset paging ('cursor'/'since') — "
                "the cursor already determines where the page starts, and applying "
                "both would silently skip rows. Follow 'X-Next-Cursor' instead."
            ),
        )

    company_list: list[str] | None = None
    if companies is not None:
        if company is not None:
            raise HTTPException(
                status_code=400,
                detail="Use either 'company' or 'companies', not both.",
            )
        # Reject empty / whitespace-only values rather than silently treating
        # them as "no filter" — that would be surprising behavior on a typo.
        raw_ids = [c.strip() for c in companies.split(",")]
        if not raw_ids or any(not c for c in raw_ids):
            raise HTTPException(
                status_code=400,
                detail="'companies' must be a non-empty comma-separated list.",
            )
        if len(raw_ids) > _MAX_COMPANIES_PER_REQUEST:
            raise HTTPException(
                status_code=400,
                detail=f"'companies' accepts at most {_MAX_COMPANIES_PER_REQUEST} IDs.",
            )
        for cid in raw_ids:
            if not _COMPANY_ID_RE.match(cid):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid company id in 'companies': {cid!r}",
                )
        company_list = raw_ids

    jobs = get_jobs(
        conn,
        company=company,
        companies=company_list,
        status=status,
        limit=limit,
        offset=offset,
        category=category,
        level=level,
        since=parsed_since,
        cursor=parsed_cursor,
    )

    # Mint the next-page token only in keyset mode, and only off a FULL page —
    # see the docstring. ``jobs[-1]`` is the last row of the current page in the
    # keyset ordering, so it is exactly the boundary the next request resumes
    # after.
    keyset_mode = parsed_since is not None or parsed_cursor is not None
    if keyset_mode and len(jobs) == limit:
        tail = jobs[-1]
        response.headers[NEXT_CURSOR_HEADER] = encode_job_cursor(
            tail["first_seen_at"], tail["source_id"], tail["id"]
        )

    return [JobListingResponse(**job) for job in jobs]


@router.get("/facets", response_model=JobFacetsResponse)
def list_facets(conn: Connection = Depends(get_db)) -> JobFacetsResponse:
    """Dropdown catalog for the enrichment facets, straight from the seeded
    job_categories / job_levels dimensions — labels, ordering and the
    new_grad->entry parent all stay data-driven, so a taxonomy change ships as
    a migration without a frontend redeploy. Declared above the parametrized
    detail route by convention (different segment count, so no actual overlap).
    """
    data = get_facets(conn)
    return JobFacetsResponse(
        categories=[FacetOption(**row) for row in data["categories"]],
        levels=[FacetOption(**row) for row in data["levels"]],
    )


@router.get("/{source_id}/{job_id}", response_model=JobListingResponse)
def get_job(
    source_id: str = Path(max_length=100),
    job_id: str = Path(max_length=200),
    conn: Connection = Depends(get_db),
) -> JobListingResponse:
    """Get a single job by composite ``(source_id, id)`` key.

    Returns 404 if no row matches the composite key.
    """
    job = get_job_by_id(conn, source_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobListingResponse(**job)
