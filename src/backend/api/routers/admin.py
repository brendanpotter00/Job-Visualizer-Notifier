"""Admin-only API endpoints — platform oversight surface."""

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, require_admin
from ..dependencies import get_db
from ..models import (
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
from ..services.user_service import get_user_by_email

logger = logging.getLogger(__name__)

router = APIRouter()


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
            logger.error(
                "granted_by FK violation when granting admin to user_id=%s (granter race)",
                user_id,
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
