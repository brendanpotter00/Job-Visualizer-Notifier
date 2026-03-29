"""Auth API endpoints — POST /api/auth/google, GET /api/auth/me."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..models import AuthResponse, GoogleAuthRequest, UserResponse
from ..services.auth import create_jwt, decode_jwt, verify_google_token
from ..services.users import find_or_create_user, get_user_by_id

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
    request: Request,
    conn: Connection = Depends(get_db),
):
    """Return the current user from JWT in Authorization header."""
    config = request.app.state.config

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[7:]

    try:
        payload = decode_jwt(token, config.jwt_secret)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload["sub"])
    user = get_user_by_id(conn, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    return UserResponse(**user)
