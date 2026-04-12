"""JWT token validation against Kinde JWKS endpoint."""

import jwt
from jwt import PyJWKClient

from ..config import settings

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    """Lazily initialize and return the JWKS client (singleton)."""
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"https://{settings.kinde_domain}/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
    return _jwks_client


def validate_token(token: str) -> dict:
    """Validate a JWT access token against Kinde's JWKS endpoint.

    Returns the decoded token payload dict on success.
    Raises jwt.ExpiredSignatureError, jwt.InvalidTokenError, or PyJWKClientError on failure.
    """
    client = _get_jwks_client()
    signing_key = client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.kinde_audience,
        issuer=f"https://{settings.kinde_domain}",
    )
