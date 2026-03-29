"""Auth API endpoints — POST /api/auth/google, GET /api/auth/me."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..middleware.auth import get_current_user
from ..models import AuthResponse, GoogleAuthRequest, UserResponse
from ..services.auth import create_jwt, verify_google_token
from ..services.users import find_or_create_user

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/google", response_model=AuthResponse)
def google_login(
    body: GoogleAuthRequest,
    request: Request,
    conn: Connection = Depends(get_db),
):
    """Verify Google ID token, create/find user, return JWT."""
    config = request.app.state.config

    if not config.google_client_id:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    try:
        google_user = verify_google_token(body.credential, config.google_client_id)
    except ValueError as exc:
        logger.warning("Google token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid Google token")

    user = find_or_create_user(
        conn,
        provider="google",
        provider_id=google_user["sub"],
        email=google_user["email"],
        name=google_user["name"],
        picture=google_user["picture"],
    )

    token = create_jwt(user, config.jwt_secret)

    return AuthResponse(
        token=token,
        user=UserResponse(**user),
    )


@router.get("/me", response_model=UserResponse)
def get_me(
    user: dict | None = Depends(get_current_user),
):
    """Return the current user from JWT in Authorization header."""
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return UserResponse(**user)
