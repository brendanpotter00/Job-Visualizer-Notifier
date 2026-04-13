"""User profile endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.dependencies import TokenClaims, get_current_user
from ..dependencies import get_db
from ..models import UserResponse, UserUpdateRequest
from ..services.user_service import get_or_create_user, update_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=UserResponse)
async def get_current_user_profile(
    request: Request,
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    """Get or create the authenticated user's profile."""
    env = request.app.state.env
    sub = user.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    try:
        result = get_or_create_user(
            conn,
            env,
            auth0_id=sub,
            email=user.get("email", ""),
            given_name=user.get("given_name"),
            family_name=user.get("family_name"),
            picture_url=user.get("picture"),
        )
    except Exception:
        logger.exception("Failed to get/create user profile for sub=%s", sub)
        raise HTTPException(status_code=500, detail="Failed to load user profile")
    return UserResponse(**result)


@router.put("", response_model=UserResponse)
async def update_current_user_profile(
    request: Request,
    body: UserUpdateRequest,
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    """Update the authenticated user's display name."""
    env = request.app.state.env
    sub = user.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    try:
        result = update_user(conn, env, auth0_id=sub, display_name=body.display_name)
    except Exception:
        logger.exception("Failed to update user profile for sub=%s", sub)
        raise HTTPException(status_code=500, detail="Failed to update user profile")
    if result is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**result)
