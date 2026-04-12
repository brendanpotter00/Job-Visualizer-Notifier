"""User profile endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.dependencies import get_current_user
from ..dependencies import get_db
from ..models import UserResponse, UserUpdateRequest
from ..services.user_service import get_or_create_user, update_user

router = APIRouter()


@router.get("", response_model=UserResponse)
async def get_current_user_profile(
    request: Request,
    conn=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get or create the authenticated user's profile."""
    env = request.app.state.env
    result = get_or_create_user(
        conn,
        env,
        kinde_id=user["sub"],
        email=user.get("email", ""),
        given_name=user.get("given_name"),
        family_name=user.get("family_name"),
        picture_url=user.get("picture"),
    )
    return UserResponse(**result)


@router.put("", response_model=UserResponse)
async def update_current_user_profile(
    request: Request,
    body: UserUpdateRequest,
    conn=Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Update the authenticated user's display name."""
    env = request.app.state.env
    result = update_user(conn, env, kinde_id=user["sub"], display_name=body.display_name)
    if result is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**result)
