"""JWT token validation against Google JWKS endpoint for One Tap tokens."""

import logging
import threading
from typing import cast

import jwt
from jwt import PyJWKClient, PyJWTError

from ..config import settings
from .claims import TokenClaims

logger = logging.getLogger(__name__)

_google_jwks_client: PyJWKClient | None = None
_google_jwks_lock = threading.Lock()
_GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})


def _get_google_jwks_client() -> PyJWKClient:
    global _google_jwks_client
    if _google_jwks_client is None:
        with _google_jwks_lock:
            if _google_jwks_client is None:
                if not settings.google_client_id:
                    raise RuntimeError(
                        "GOOGLE_CLIENT_ID environment variable is not set. "
                        "Google One Tap validation requires Google configuration."
                    )
                logger.info(
                    "Initializing Google JWKS client with URL: %s", _GOOGLE_JWKS_URL
                )
                _google_jwks_client = PyJWKClient(
                    _GOOGLE_JWKS_URL, cache_keys=True, lifespan=3600
                )
    return _google_jwks_client


def validate_google_token(token: str) -> TokenClaims:
    """Validate a Google ID token against Google's JWKS endpoint."""
    client = _get_google_jwks_client()
    try:
        signing_key = client.get_signing_key_from_jwt(token)
    except PyJWTError:
        logger.warning("Failed to get signing key from Google JWT", exc_info=True)
        raise
    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=GOOGLE_ISSUERS,
        )
    except jwt.InvalidTokenError:
        logger.warning("Google token decode failed", exc_info=True)
        raise
    logger.debug("Google token validated for sub=%s", claims.get("sub"))
    # cast at the decode boundary (jwt.decode is untyped) so callers get the
    # precise TokenClaims type without a cast of their own.
    return cast(TokenClaims, claims)
