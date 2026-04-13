"""FastAPI authentication dependencies."""

import logging
from typing import TypedDict

import jwt
from jwt import PyJWKClientError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .jwt import validate_token

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
    except (jwt.InvalidTokenError, PyJWKClientError) as exc:
        logger.warning("Invalid JWT token: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    user: TokenClaims | None = Depends(get_optional_user),
) -> TokenClaims:
    """Require a valid authenticated user, raising 401 if absent."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
