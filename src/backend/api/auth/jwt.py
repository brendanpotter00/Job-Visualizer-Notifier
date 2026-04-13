"""JWT token validation against Auth0 JWKS endpoint."""

import logging

import jwt
from jwt import PyJWKClient, PyJWTError

from ..config import settings

logger = logging.getLogger(__name__)

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not settings.auth0_domain:
            raise RuntimeError(
                "AUTH0_DOMAIN environment variable is not set. "
                "JWT validation requires Auth0 configuration."
            )
        if not settings.auth0_audience:
            raise RuntimeError(
                "AUTH0_AUDIENCE environment variable is not set. "
                "JWT validation requires Auth0 configuration."
            )
        jwks_url = f"https://{settings.auth0_domain}/.well-known/jwks.json"
        logger.info("Initializing JWKS client with URL: %s", jwks_url)
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
    return _jwks_client


def validate_token(token: str) -> dict:
    """Validate a JWT token against the Auth0 JWKS endpoint."""
    client = _get_jwks_client()
    try:
        signing_key = client.get_signing_key_from_jwt(token)
    except PyJWTError:
        logger.warning("Failed to get signing key from JWT", exc_info=True)
        raise
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.auth0_audience,
        issuer=f"https://{settings.auth0_domain}/",
    )
    logger.debug("Token validated for sub=%s", claims.get("sub"))
    return claims
