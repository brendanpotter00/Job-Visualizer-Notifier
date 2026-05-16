"""Admin-only API endpoints — platform oversight surface."""

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, require_admin
from ..dependencies import get_db
from ..models import (
    AdminUserRow,
    AdminUsersListResponse,
    AdminUsersStatsResponse,
)
from ..services.admin_service import (
    get_users_stats,
    list_users_with_admin_flag,
)

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
