"""User profile endpoints."""

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.dependencies import TokenClaims, get_current_user
from ..auth.jwt import get_normalized_subject
from ..dependencies import get_db
from ..models import (
    EnabledCompaniesResponse,
    EnabledCompaniesUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)
from ..services.user_preferences_service import (
    list_enabled_companies,
    set_enabled_companies,
)
from ..services.user_service import get_or_create_user, get_user_by_email, update_user

logger = logging.getLogger(__name__)

router = APIRouter()


def _row_to_user_response(row: dict) -> UserResponse:
    """Map a DB row to the API response model.

    The DB column is ``auth0_id`` (legacy name) but the boundary field is
    ``provider_subject`` — see ``UserResponse`` docstring.
    """
    return UserResponse(
        id=row["id"],
        provider_subject=row["auth0_id"],
        email=row["email"],
        display_name=row.get("display_name"),
        given_name=row.get("given_name"),
        family_name=row.get("family_name"),
        picture_url=row.get("picture_url"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("", response_model=UserResponse)
async def get_current_user_profile(
    request: Request,
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    """Get or create the authenticated user's profile.

    Catches only ``psycopg2.Error`` — ``RuntimeError`` (raised by
    ``get_or_create_user`` on ambiguous identity) and ``HTTPException`` must
    propagate. The ambiguous-identity raise is load-bearing per
    ``docs/implementations/auth0/REVIEW_AUDIT.md``; swallowing it behind a
    generic 500 would hide a corrupted identity model.
    """
    env = request.app.state.env
    auth0_id = get_normalized_subject(user)
    if not auth0_id:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    try:
        result = get_or_create_user(
            conn,
            env,
            auth0_id=auth0_id,
            email=email,
            given_name=user.get("given_name"),
            family_name=user.get("family_name"),
            picture_url=user.get("picture"),
        )
    except psycopg2.Error:
        logger.exception("Failed to get/create user profile for sub=%s", auth0_id)
        raise HTTPException(status_code=500, detail="Failed to load user profile")
    return _row_to_user_response(result)


@router.put("", response_model=UserResponse)
async def update_current_user_profile(
    request: Request,
    body: UserUpdateRequest,
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    """Update the authenticated user's display name.

    Keyed by ``email`` (the stable identifier) rather than ``auth0_id`` — a
    user's ``auth0_id`` can legitimately change when they switch providers,
    while their verified email is stable per row.
    """
    env = request.app.state.env
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    try:
        result = update_user(conn, env, email=email, display_name=body.display_name)
    except psycopg2.Error:
        logger.exception("Failed to update user profile for email=%s", email)
        raise HTTPException(status_code=500, detail="Failed to update user profile")
    if result is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _row_to_user_response(result)


@router.get("/enabled-companies", response_model=EnabledCompaniesResponse)
async def get_enabled_companies(
    request: Request,
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    """Return the company IDs the authenticated user has enabled."""
    env = request.app.state.env
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    row = get_user_by_email(conn, env, email)
    if row is None:
        return EnabledCompaniesResponse(company_ids=[])
    try:
        ids = list_enabled_companies(conn, env, row["id"])
    except psycopg2.Error:
        logger.exception("Failed to list enabled companies for user=%s", row["id"])
        raise HTTPException(
            status_code=500, detail="Failed to load enabled companies"
        )
    return EnabledCompaniesResponse(company_ids=ids)


@router.put("/enabled-companies", response_model=EnabledCompaniesResponse)
async def update_enabled_companies(
    request: Request,
    body: EnabledCompaniesUpdateRequest,
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    """Replace the authenticated user's enabled-companies set."""
    env = request.app.state.env
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    row = get_user_by_email(conn, env, email)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        saved = set_enabled_companies(conn, env, row["id"], body.company_ids)
    except psycopg2.Error:
        logger.exception("Failed to save enabled companies for user=%s", row["id"])
        raise HTTPException(
            status_code=500, detail="Failed to save enabled companies"
        )
    return EnabledCompaniesResponse(company_ids=saved)
