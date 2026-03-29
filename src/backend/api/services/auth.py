"""JWT and Google OAuth token utilities.

Pure functions with no FastAPI or database dependencies.
"""

import logging
from datetime import datetime, timedelta, timezone

import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

logger = logging.getLogger(__name__)


def create_jwt(user_data: dict, secret: str, expires_hours: int = 168) -> str:
    """Create an HS256 JWT with user claims.

    Args:
        user_data: Must contain keys: id, email, name, picture, is_admin.
        secret: HMAC secret for signing.
        expires_hours: Token lifetime in hours (default 7 days).

    Returns:
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_data["id"]),
        "email": user_data["email"],
        "name": user_data["name"],
        "picture": user_data.get("picture"),
        "is_admin": user_data.get("is_admin", False),
        "iat": now,
        "exp": now + timedelta(hours=expires_hours),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, secret: str) -> dict:
    """Decode and verify an HS256 JWT.

    Raises:
        jwt.ExpiredSignatureError: Token has expired.
        jwt.InvalidTokenError: Token is malformed or signature invalid.
    """
    return jwt.decode(token, secret, algorithms=["HS256"])


def verify_google_token(credential: str, client_id: str) -> dict:
    """Verify a Google ID token and extract user info.

    Returns:
        Dict with keys: sub, email, name, picture.

    Raises:
        ValueError: Token is invalid, expired, or not issued for this client.
    """
    idinfo = google_id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        client_id,
    )
    return {
        "sub": idinfo["sub"],
        "email": idinfo["email"],
        "name": idinfo.get("name", idinfo.get("email", "")),
        "picture": idinfo.get("picture"),
    }
