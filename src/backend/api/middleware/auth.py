"""Auth dependency for protected endpoints."""

import logging

from fastapi import Depends, Request
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..services.auth import decode_jwt
from ..services.users import get_user_by_id

logger = logging.getLogger(__name__)


def get_current_user(
    request: Request,
    conn: Connection = Depends(get_db),
) -> dict | None:
    """Extract and verify JWT from Authorization header, return user or None.

    Returns None (rather than raising) to support optional auth — endpoints
    can check the return value and decide whether to require auth.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    config = request.app.state.config

    try:
        payload = decode_jwt(token, config.jwt_secret)
        user_id = int(payload["sub"])
    except Exception:
        return None

    return get_user_by_id(conn, user_id)
