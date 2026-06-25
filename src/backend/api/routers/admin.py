"""Admin-only API endpoints — platform oversight surface."""

import asyncio
import logging
from urllib.parse import unquote

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from procrastinate import exceptions as procrastinate_exceptions
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, require_admin
from ..config import settings
from ..dependencies import get_db
from ..models import (
    AdminAliasListResponse,
    AdminAliasOriginal,
    AdminAliasOriginalsResponse,
    AdminAliasOverrideRequest,
    AdminAliasResponse,
    AdminFeedbackListResponse,
    AdminLocationHealthResponse,
    AdminLocationIntegrityCheck,
    AdminLocationIntegrityResponse,
    AdminLocationResponse,
    AdminLocationReverseListResponse,
    AdminLocationReverseRow,
    AdminNormalizeJobResponse,
    AdminProblemJob,
    AdminProblemJobsResponse,
    AdminReNormalizeAllResponse,
    AdminReverseLocation,
    AdminUserRow,
    AdminUsersListResponse,
    AdminUserVisitsResponse,
    AdminUsersStatsResponse,
    FeedbackResponse,
)
from ..services.admin_service import (
    LastAdminError,
    get_users_stats,
    grant_admin,
    list_users_with_admin_flag,
    revoke_admin,
)
from ..services.feedback_service import count_feedback, list_feedback
from ..services.location_admin import (
    alias_originals,
    count_aliases,
    list_aliases,
    list_problem_jobs,
    reset_all_normalization,
    reset_job_normalization,
    reverse_lookup_locations,
    upsert_manual_alias,
)
from ..services.location_monitor import get_health, get_integrity
from ..services.location_normalization import normalize_string
from ..services.user_service import (
    get_user_by_email,
    get_user_visit_count,
    list_user_visits,
)
from ..tasks.normalize_location import normalize_location
from ..tasks.scan_unnormalized import scan_unnormalized

logger = logging.getLogger(__name__)

router = APIRouter()

# Hard cap on the alias-inspect page size. The root CLAUDE.md memory rule
# forbids unbounded reads, so the GET endpoint enforces this both via the
# Query(le=...) validator (422 above cap) and the service's always-applied LIMIT.
_ALIAS_LIST_CAP = 200

# Hard cap on the admin feedback page size (same unbounded-reads memory rule).
_FEEDBACK_LIST_CAP = 200


@router.get("/users", response_model=AdminUsersListResponse)
def list_admin_users(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
) -> AdminUsersListResponse:
    """Full user roster with derived signup provider and admin flag."""
    try:
        rows = list_users_with_admin_flag(conn)
    except psycopg2.Error:
        logger.exception("Failed to list users for admin dashboard")
        raise HTTPException(status_code=500, detail="Failed to load users")
    return AdminUsersListResponse(users=[AdminUserRow(**r) for r in rows])


@router.get("/users/stats", response_model=AdminUsersStatsResponse)
def get_admin_users_stats(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
) -> AdminUsersStatsResponse:
    """Aggregate user growth + signup-provider breakdown."""
    try:
        stats = get_users_stats(conn)
    except psycopg2.Error:
        logger.exception("Failed to compute user stats for admin dashboard")
        raise HTTPException(status_code=500, detail="Failed to load user stats")
    return AdminUsersStatsResponse(**stats)


@router.get("/users/{user_id}/visits", response_model=AdminUserVisitsResponse)
def get_admin_user_visits(
    user_id: str,
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
) -> AdminUserVisitsResponse:
    """A single user's individual visit timestamps, most-recent first.

    Backs the roster's clickable Visits cell → modal. Server-side capped at
    ``_USER_VISITS_LIMIT`` (unbounded-reads memory rule). Also returns the
    denormalized total ``visit_count`` so the modal can flag the count-vs-
    history gap (per-visit history only began when the ``user_visits`` table
    shipped; earlier visits beyond the seeded ``last_visit_at`` have no rows).
    Registered after the static ``/users/stats`` route so the ``{user_id}``
    path param can't shadow it.
    """
    try:
        count = get_user_visit_count(conn, user_id)
        if count is None:
            raise HTTPException(status_code=404, detail="User not found")
        # The service owns the cap + truncation decision (fetches LIMIT+1 and
        # reports whether rows were actually dropped), so the router doesn't
        # re-derive it with an off-by-one ``>=`` against the private cap.
        visits, truncated = list_user_visits(conn, user_id)
    except psycopg2.Error:
        logger.exception("Failed to load visits for user_id=%s", user_id)
        raise HTTPException(status_code=500, detail="Failed to load user visits")
    return AdminUserVisitsResponse(
        visits=visits,
        total_visit_count=count,
        truncated=truncated,
    )


@router.get("/feedback", response_model=AdminFeedbackListResponse)
def list_admin_feedback(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
    # Server-side pagination: the UI requests one page at a time and reads
    # ``total`` to drive the pager, so it can reach all feedback rather than a
    # single fetched slice. Page size is hard-bounded at 200 (unbounded-reads
    # memory rule) and defaults to one screenful.
    limit: int = Query(default=25, ge=1, le=_FEEDBACK_LIST_CAP),
    offset: int = Query(default=0, ge=0),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> AdminFeedbackListResponse:
    """One page of user feedback (ordered by ``created_at``) plus the total."""
    try:
        rows = list_feedback(conn, limit, offset, sort_dir)
        total = count_feedback(conn)
    except psycopg2.Error:
        conn.rollback()
        logger.exception("Failed to list feedback for admin dashboard")
        raise HTTPException(status_code=500, detail="Failed to load feedback")
    return AdminFeedbackListResponse(
        feedback=[
            FeedbackResponse(
                id=r["id"],
                message=r["message"],
                user_id=r["user_id"],
                user_email=r["user_email"],
                display_name=r["display_name"],
                created_at=r["created_at"],
            )
            for r in rows
        ],
        total=total,
    )


def _resolve_granter_id(conn: Connection, admin_claims: TokenClaims) -> str:
    """Look up the calling admin's ``users.id`` for audit fields.

    ``require_admin`` has already verified the caller is signed in and holds
    an admin grant. The grant is keyed by email, but the ``admins.granted_by``
    FK is keyed by ``users.id`` — so we re-resolve via the email claim.
    """
    email = admin_claims.get("email")
    if not email:
        # require_admin would have already 401'd on this, but stay defensive.
        raise HTTPException(status_code=401, detail="Token missing 'email' claim")
    granter = get_user_by_email(conn, email)
    if granter is None:
        # Admin has a grant by email but no users row — schema is inconsistent.
        logger.error("Admin %s has no users row; cannot resolve granter id", email)
        raise HTTPException(status_code=500, detail="Granter user record missing")
    return granter["id"]


@router.post("/users/{user_id}/admin", status_code=204)
def grant_user_admin(
    user_id: str,
    conn: Connection = Depends(get_db),
    admin: TokenClaims = Depends(require_admin),
) -> Response:
    """Grant admin status to ``user_id``. Idempotent (204 even if already admin)."""
    granter_id = _resolve_granter_id(conn, admin)
    try:
        grant_admin(conn, user_id, granted_by_id=granter_id)
    except psycopg2.errors.ForeignKeyViolation as exc:
        # admins has two FKs to users.id:
        #   - admins_user_id_fkey: the target — translate to 404.
        #   - admins_granted_by_fkey: the granter's row was deleted between
        #     resolve and insert (rare race). Translate to 500 so admins
        #     don't get a misleading 404 pointing at the wrong record.
        conn.rollback()
        constraint = getattr(getattr(exc, "diag", None), "constraint_name", None)
        if constraint == "admins_granted_by_fkey":
            # Log the granter identity (email + resolved id) so on-call can
            # tell WHICH admin was deleted mid-grant. The target user_id is
            # intentionally omitted from this branch's log — including it
            # would be misleading (the FK violation isn't about the target).
            logger.error(
                "granted_by FK violation during grant (granter race): "
                "granter_email=%s granter_id=%s",
                admin.get("email"),
                granter_id,
            )
            raise HTTPException(
                status_code=500,
                detail="Granter user record changed during grant — please retry.",
            )
        # Default: target user_id doesn't exist (or constraint name is
        # unrecognized; safer to surface as the more specific error).
        raise HTTPException(status_code=404, detail="User not found")
    except psycopg2.Error:
        conn.rollback()
        logger.exception("Failed to grant admin to user_id=%s", user_id)
        raise HTTPException(status_code=500, detail="Failed to grant admin")
    return Response(status_code=204)


@router.delete("/users/{user_id}/admin", status_code=204)
def revoke_user_admin(
    user_id: str,
    conn: Connection = Depends(get_db),
    admin: TokenClaims = Depends(require_admin),
) -> Response:
    """Revoke admin status from ``user_id``. Idempotent.

    Guardrail: an admin cannot revoke their own grant — that's the single
    fastest way to lock the whole platform out of the admin surface. The UI
    disables the menu item too, but the server is the source of truth.
    """
    granter_id = _resolve_granter_id(conn, admin)
    if granter_id == user_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot revoke your own admin grant",
        )
    try:
        revoke_admin(conn, user_id)
    except LastAdminError:
        # ``revoke_admin`` already rolled back its transaction. Translate
        # to 409 so the UI can show a distinguishable "promote another
        # admin first" message instead of a generic 500.
        raise HTTPException(
            status_code=409,
            detail="Cannot revoke the last admin — promote another user first.",
        )
    except psycopg2.Error:
        conn.rollback()
        logger.exception("Failed to revoke admin from user_id=%s", user_id)
        raise HTTPException(status_code=500, detail="Failed to revoke admin")
    return Response(status_code=204)


# --- Location-normalization admin endpoints (Unit 8) -------------------------


@router.post("/jobs/{job_id}/normalize", response_model=AdminNormalizeJobResponse)
async def admin_normalize_job(
    job_id: str,
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
) -> AdminNormalizeJobResponse:
    """Reset one job's normalization_status to NULL and re-defer normalize_location.

    The audit agent's per-job fix (Decision #10). Keys on `id` alone (globally
    unique in practice; the task does likewise). 404 if no such job. Returns
    200 with status "queued" on a successful defer (or when an equivalent
    normalize is already enqueued — queueing_lock collapse), or status
    "reset_defer_failed" when the defer fails after the reset committed (the
    safety-net scan picks the NULL row up within ~5 minutes). `keyConfigured`
    is False when ANTHROPIC_API_KEY is unset — a Tier-1 miss will then stay
    NULL until the key is set.

    The DB reset is a short sync write via the request connection; the defer is
    awaited on the app connector (opened in the FastAPI lifespan) — mirrors the
    defer-from-handler pattern in routers/jobs_qa.py. Because this handler is
    ``async`` (it awaits ``defer_async``), the sync psycopg2 write is wrapped in
    ``asyncio.to_thread`` so it doesn't block the event loop.
    """
    try:
        matched = await asyncio.to_thread(reset_job_normalization, conn, job_id)
    except psycopg2.Error:
        logger.exception("admin_normalize_job: reset failed for job_id=%s", job_id)
        raise HTTPException(status_code=500, detail="Failed to reset job status")
    if not matched:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        await normalize_location.configure(
            queueing_lock=f"normalize:{job_id}",
        ).defer_async(job_id=job_id)
    except procrastinate_exceptions.AlreadyEnqueued:
        # A normalize for this job is already in flight (queueing_lock dedup).
        # The status reset still applies; the in-flight task will pick it up.
        logger.info(
            "admin_normalize_job: normalize_location already enqueued for %s; "
            "reset applied, defer collapsed by queueing_lock", job_id,
        )
    except (procrastinate_exceptions.ConnectorException, psycopg2.Error):
        # The reset already committed; a failed defer must NOT 500 after a
        # successful reset (that hides the partial success — mirrors
        # admin_re_normalize_all). The row is NULL now, so the periodic
        # scan_unnormalized tick normalizes it within ~5 minutes anyway.
        logger.exception(
            "admin_normalize_job: defer failed after reset committed for %s; "
            "returning 200 (safety-net will normalize the job)", job_id,
        )
        return AdminNormalizeJobResponse(
            job_id=job_id, status="reset_defer_failed",
            key_configured=bool(settings.anthropic_api_key),
        )
    return AdminNormalizeJobResponse(
        job_id=job_id, status="queued",
        key_configured=bool(settings.anthropic_api_key),
    )


@router.put("/locations/aliases/{raw_text:path}", response_model=AdminAliasResponse)
def admin_override_alias(
    raw_text: str,
    body: AdminAliasOverrideRequest,
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
) -> AdminAliasResponse:
    """Manual alias override — the PRIMARY correction primitive (Decision #10).

    OVERWRITE / manual-wins semantics:
      * key = normalize_string(raw_text)  (the URL path segment is the raw
        string; we URL-decode then normalize it to the cache key). The
        `:path` converter lets the segment carry literal slashes — real
        location strings like "EMEA / Remote" are exactly the messy
        multi-location inputs this override exists to correct.
      * Upsert each location spec into `locations` (NULLS-NOT-DISTINCT dedup).
      * Upsert the alias as source='manual', confidence=1.0 with
        ON CONFLICT (raw_text) DO UPDATE — promotes a cached 'llm' alias to
        'manual' so the correction wins.
      * REPLACE the mapping (DELETE alias_locations for the key, INSERT the new
        ordered rows). A later LLM run can't clobber it: persist_llm_result's
        alias INSERT is ON CONFLICT (raw_text) DO NOTHING, so manual persists.

    The admin applies this correction to jobs by calling endpoint #1 (per job)
    or #4 (break-glass) afterwards; this endpoint does no re-linking itself.

    Plain ``def`` (no defer), so FastAPI runs it in a threadpool — no
    ``asyncio.to_thread`` needed for the sync DB write.
    """
    key = normalize_string(unquote(raw_text))
    if not key:
        raise HTTPException(status_code=400, detail="raw_text normalizes to empty")
    try:
        result = upsert_manual_alias(conn, key, body.locations)
    except psycopg2.Error:
        logger.exception("admin_override_alias: write failed for key=%r", key)
        raise HTTPException(status_code=500, detail="Failed to write alias override")
    return AdminAliasResponse(
        raw_text=result["raw_text"],
        source=result["source"],
        confidence=result["confidence"],
        locations=[AdminLocationResponse(**loc) for loc in result["locations"]],
    )


@router.get("/locations/aliases", response_model=AdminAliasListResponse)
def admin_list_aliases(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
    contains: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=_ALIAS_LIST_CAP),
    offset: int = Query(default=0, ge=0),
) -> AdminAliasListResponse:
    """Inspect/debug the alias cache. Bounded (limit <= 200 — memory rule).

    Filters raw_text by case-insensitive substring when `contains` is given
    (parameterized ILIKE; never string-formatted), else returns the most recent
    `limit` aliases. `offset` paginates. Each row includes the mapped canonical
    locations (ordered). `total` is a bounded count under the same filter,
    independent of `limit`, so the UI can paginate.
    """
    try:
        rows = list_aliases(conn, contains, limit, offset)
        total = count_aliases(conn, contains)
    except psycopg2.Error:
        logger.exception("admin_list_aliases failed (contains=%r)", contains)
        raise HTTPException(status_code=500, detail="Failed to list aliases")
    return AdminAliasListResponse(
        aliases=[
            AdminAliasResponse(
                raw_text=a["raw_text"],
                source=a["source"],
                confidence=a["confidence"],
                locations=[AdminLocationResponse(**loc) for loc in a["locations"]],
            )
            for a in rows
        ],
        total=total,
    )


# --- Location-normalization MONITOR endpoints (read-only oversight) -----------
#
# These STATIC GET paths are registered AFTER the catch-all
# PUT /locations/aliases/{raw_text:path} (defined earlier in this file), but
# order is irrelevant here: that route is a PUT under a different path prefix
# (/locations/aliases/...), so it can never match these GETs on /locations/health,
# /integrity, /reverse, /alias-originals, or /problem-jobs — the method AND the
# prefix both differ. (If a future `:path` GET on /locations/... is ever added,
# register it LAST so it can't shadow these static GETs.)


@router.get("/locations/health", response_model=AdminLocationHealthResponse)
def admin_locations_health(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
    window_hours: int = Query(default=24, ge=1, le=168, alias="windowHours"),
) -> AdminLocationHealthResponse:
    """Operational health snapshot for the location-normalization pipeline.

    Pure SELECTs (sync def → FastAPI threadpool). `windowHours` bounds the
    backlog-aging + throughput windows (1..168; 422 outside).
    """
    try:
        result = get_health(conn, window_hours)
    except psycopg2.Error:
        logger.exception("admin_locations_health failed (window_hours=%s)", window_hours)
        raise HTTPException(status_code=500, detail="Failed to load location health")
    return AdminLocationHealthResponse(**result)


@router.get("/locations/integrity", response_model=AdminLocationIntegrityResponse)
def admin_locations_integrity(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
) -> AdminLocationIntegrityResponse:
    """Run the C1..C9 data-integrity checks. Pure SELECTs."""
    try:
        result = get_integrity(conn)
    except psycopg2.Error:
        logger.exception("admin_locations_integrity failed")
        raise HTTPException(status_code=500, detail="Failed to run integrity checks")
    return AdminLocationIntegrityResponse(
        schema_present=result["schema_present"],
        checks=[AdminLocationIntegrityCheck(**c) for c in result["checks"]],
    )


@router.get("/locations/reverse", response_model=AdminLocationReverseListResponse)
def admin_locations_reverse(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
    contains: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=_ALIAS_LIST_CAP),
) -> AdminLocationReverseListResponse:
    """Reverse lookup: canonical locations + every raw_text that maps to each.

    Searches `canonical_name ILIKE %contains%` (parameterized) when `contains`
    is given, else returns up to `limit` recent locations. Bounded (limit <=
    200 — memory rule).
    """
    try:
        rows = reverse_lookup_locations(conn, contains, limit)
    except psycopg2.Error:
        logger.exception("admin_locations_reverse failed (contains=%r)", contains)
        raise HTTPException(status_code=500, detail="Failed to reverse-lookup locations")
    return AdminLocationReverseListResponse(
        results=[
            AdminLocationReverseRow(
                location=AdminReverseLocation(**r["location"]),
                raw_texts=r["raw_texts"],
            )
            for r in rows
        ]
    )


@router.get("/locations/alias-originals", response_model=AdminAliasOriginalsResponse)
def admin_locations_alias_originals(
    raw_text: str = Query(..., max_length=400, alias="rawText"),
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=_ALIAS_LIST_CAP),
) -> AdminAliasOriginalsResponse:
    """Verbatim job-location strings that normalize to the given alias key.

    `rawText` is the (already-normalized) alias key. Reconstructs the implicit
    job→alias link via `normalize_string(job_listings.location) == rawText`
    (SQL prefilter + Python SSOT verify). Bounded (limit <= 200).
    """
    try:
        result = alias_originals(conn, raw_text, limit)
    except psycopg2.Error:
        logger.exception("admin_locations_alias_originals failed (raw_text=%r)", raw_text)
        raise HTTPException(status_code=500, detail="Failed to load alias originals")
    return AdminAliasOriginalsResponse(
        raw_text=result["raw_text"],
        total=result["total"],
        originals=[AdminAliasOriginal(**o) for o in result["originals"]],
    )


@router.get("/locations/problem-jobs", response_model=AdminProblemJobsResponse)
def admin_locations_problem_jobs(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=_ALIAS_LIST_CAP),
    offset: int = Query(default=0, ge=0),
) -> AdminProblemJobsResponse:
    """Actionable failed jobs: failed status with a NON-blank location.

    Blank-location failures are excluded (nothing to fix). Ordered by
    last_seen_at DESC; paginated by limit/offset. Bounded (limit <= 200).
    """
    try:
        result = list_problem_jobs(conn, limit, offset)
    except psycopg2.Error:
        logger.exception(
            "admin_locations_problem_jobs failed (limit=%s offset=%s)", limit, offset
        )
        raise HTTPException(status_code=500, detail="Failed to load problem jobs")
    return AdminProblemJobsResponse(
        jobs=[AdminProblemJob(**j) for j in result["jobs"]],
        total=result["total"],
    )


@router.post(
    "/locations/re-normalize-all", response_model=AdminReNormalizeAllResponse
)
async def admin_re_normalize_all(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
) -> AdminReNormalizeAllResponse:
    """BREAK-GLASS (Decision #10 / Risk F3). Gated + bounded.

    Conservative behavior (deliberate deviation from F3's "bypass the cache /
    fan thousands of Haiku calls" framing — see the note below for why this is
    safer):
      1. UPDATE job_listings SET normalization_status = NULL
         WHERE normalization_status IS NOT NULL  (reset done/failed so they
         re-process).
      2. await scan_unnormalized.defer_async(timestamp=0) to kick off draining.
         The periodic scan_unnormalized task + its SCAN_LIMIT throttle bound the
         re-processing rate, so this can't fan thousands of concurrent Haiku
         calls at once.

    Does NOT clear the alias cache: re-linking uses the current cache (incl.
    manual overrides), so it is cheap (mostly Tier-1 hits), spends no new LLM
    money, and PRESERVES manual corrections. This is "correctness over flashy /
    destructive shortcuts": to FORCE fresh LLM re-normalization an operator must
    clear the alias tables manually — deliberately not a one-click destructive
    op. The response `note` surfaces this to the caller.

    ``async`` (awaits ``defer_async``), so the sync reset is wrapped in
    ``asyncio.to_thread``.
    """
    try:
        reset_count = await asyncio.to_thread(reset_all_normalization, conn)
    except psycopg2.Error:
        logger.exception("admin_re_normalize_all: reset failed")
        raise HTTPException(status_code=500, detail="Failed to reset statuses")

    scan_deferred = True
    try:
        await scan_unnormalized.defer_async(timestamp=0)
    except procrastinate_exceptions.AlreadyEnqueued:
        scan_deferred = False
        logger.info(
            "admin_re_normalize_all: scan_unnormalized already enqueued; "
            "reset applied, defer collapsed"
        )
    except (procrastinate_exceptions.ConnectorException, psycopg2.Error):
        # The destructive reset already committed; a failed defer must NOT 500
        # after a successful reset (that hides the partial success). Return 200
        # with scanDeferred=False — the periodic scan_unnormalized tick (every
        # 5 min) will pick up the now-NULL rows, as the response `note` explains.
        scan_deferred = False
        logger.exception(
            "admin_re_normalize_all: scan_unnormalized defer failed after reset "
            "committed; returning 200 (periodic scan will drain the backlog)"
        )

    key_configured = bool(settings.anthropic_api_key)
    note = (
        "Re-applies the normalization pipeline against the current alias "
        "cache (manual overrides preserved). Does NOT force fresh LLM "
        "re-normalization; clear the alias tables manually to do that."
    )
    if not key_configured:
        # The reset committed, but the deferred scan skips while the key is
        # absent — without this the break-glass action would claim progress
        # that won't happen until someone sets the key.
        note += (
            " WARNING: ANTHROPIC_API_KEY is not configured — draining is "
            "PAUSED until the key is set (it then auto-resumes on the next "
            "periodic scan tick)."
        )
        logger.warning(
            "admin_re_normalize_all: reset %d row(s) but ANTHROPIC_API_KEY is "
            "unset; draining paused until the key is configured", reset_count,
        )
    return AdminReNormalizeAllResponse(
        reset_count=reset_count,
        scan_deferred=scan_deferred,
        key_configured=key_configured,
        note=note,
    )
