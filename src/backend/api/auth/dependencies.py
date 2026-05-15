"""FastAPI authentication dependencies."""

import logging
from typing import TypedDict

import jwt
from jwt import PyJWKClientError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .jwt import validate_token
from ..dependencies import get_db
from ..services.admin_service import is_admin_by_email

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


class TokenClaims(TypedDict, total=False):
    sub: str
    email: str
    given_name: str | None
    family_name: str | None
    picture: str | None


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenClaims | None:
    """Extract and validate a JWT token if present, returning claims or None."""
    if credentials is None:
        return None
    try:
        return validate_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        raise HTTPException(status_code=401, detail="Token expired")
    except PyJWKClientError:
        # JWKS endpoint unreachable (IdP outage, DNS failure, cache miss
        # coinciding with network blip). Not a credential problem — return
        # 503 so callers and monitoring don't mistake this for a bad token.
        logger.exception("JWKS fetch failed while validating JWT")
        raise HTTPException(
            status_code=503,
            detail="Authorization service temporarily unavailable",
        )
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid JWT token: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    user: TokenClaims | None = Depends(get_optional_user),
) -> TokenClaims:
    """Require a valid authenticated user, raising 401 if absent."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> TokenClaims:
    """Require an admin grant for the authenticated user.

    Keyed by ``email`` (the stable identifier across provider switches) per the
    same convention as the user-profile endpoints. Raises 403 if the user is
    signed in but has no row in ``admins``.
    """
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    if not is_admin_by_email(conn, email):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
