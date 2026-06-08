"""Admin-only API endpoints — platform oversight surface."""

import asyncio
import logging
from urllib.parse import unquote

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from procrastinate import exceptions as procrastinate_exceptions
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, require_admin
from ..dependencies import get_db
from ..models import (
    AdminAliasListResponse,
    AdminAliasOverrideRequest,
    AdminAliasResponse,
    AdminLocationResponse,
    AdminNormalizeJobResponse,
    AdminReNormalizeAllResponse,
    AdminUserRow,
    AdminUsersListResponse,
    AdminUsersStatsResponse,
)
from ..services.admin_service import (
    LastAdminError,
    get_users_stats,
    grant_admin,
    list_users_with_admin_flag,
    revoke_admin,
)
from ..services.location_admin import (
    list_aliases,
    reset_all_normalization,
    reset_job_normalization,
    upsert_manual_alias,
)
from ..services.location_normalization import normalize_string
from ..services.user_service import get_user_by_email
from ..tasks.normalize_location import normalize_location
from ..tasks.scan_unnormalized import scan_unnormalized

logger = logging.getLogger(__name__)

router = APIRouter()

# Hard cap on the alias-inspect page size. The root CLAUDE.md memory rule
# forbids unbounded reads, so the GET endpoint enforces this both via the
# Query(le=...) validator (422 above cap) and the service's always-applied LIMIT.
_ALIAS_LIST_CAP = 200


@router.get("/users", response_model=AdminUsersListResponse)
def list_admin_users(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
):
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
):
    """Aggregate user growth + signup-provider breakdown."""
    try:
        stats = get_users_stats(conn)
    except psycopg2.Error:
        logger.exception("Failed to compute user stats for admin dashboard")
        raise HTTPException(status_code=500, detail="Failed to load user stats")
    return AdminUsersStatsResponse(**stats)


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
):
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
):
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
):
    """Reset one job's normalization_status to NULL and re-defer normalize_location.

    The audit agent's per-job fix (Decision #10). Keys on `id` alone (globally
    unique in practice; the task does likewise). 404 if no such job. Returns
    200 with {jobId, status: "queued"} on a successful defer.

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
    return AdminNormalizeJobResponse(job_id=job_id, status="queued")


@router.put("/locations/aliases/{raw_text}", response_model=AdminAliasResponse)
def admin_override_alias(
    raw_text: str,
    body: AdminAliasOverrideRequest,
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
):
    """Manual alias override — the PRIMARY correction primitive (Decision #10).

    OVERWRITE / manual-wins semantics:
      * key = normalize_string(raw_text)  (the URL path segment is the raw
        string; we URL-decode then normalize it to the cache key).
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
):
    """Inspect/debug the alias cache. Bounded (limit <= 200 — memory rule).

    Filters raw_text by case-insensitive substring when `contains` is given
    (parameterized ILIKE; never string-formatted), else returns the most recent
    `limit` aliases. Each row includes the mapped canonical locations (ordered).
    """
    try:
        rows = list_aliases(conn, contains, limit)
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
        ]
    )


@router.post(
    "/locations/re-normalize-all", response_model=AdminReNormalizeAllResponse
)
async def admin_re_normalize_all(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
):
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

    return AdminReNormalizeAllResponse(
        reset_count=reset_count,
        scan_deferred=scan_deferred,
        note=(
            "Re-applies the normalization pipeline against the current alias "
            "cache (manual overrides preserved). Does NOT force fresh LLM "
            "re-normalization; clear the alias tables manually to do that."
        ),
    )
