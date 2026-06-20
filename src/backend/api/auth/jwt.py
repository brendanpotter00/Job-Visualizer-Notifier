"""JWT token validation against Auth0 and Google JWKS endpoints."""

import logging
import threading
from collections.abc import Mapping
from typing import Any, cast

import jwt
from jwt import PyJWKClient, PyJWTError

from ..config import settings
from .claims import TokenClaims
from .google_jwt import GOOGLE_ISSUERS

logger = logging.getLogger(__name__)

_jwks_client: PyJWKClient | None = None
_jwks_lock = threading.Lock()


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        with _jwks_lock:
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


def _validate_auth0_token(token: str) -> TokenClaims:
    """Validate a JWT token against the Auth0 JWKS endpoint."""
    client = _get_jwks_client()
    try:
        signing_key = client.get_signing_key_from_jwt(token)
    except PyJWTError:
        logger.warning("Failed to get signing key from JWT", exc_info=True)
        raise
    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
        )
    except jwt.InvalidTokenError:
        logger.warning("Auth0 token decode failed", exc_info=True)
        raise
    logger.debug("Auth0 token validated for sub=%s", claims.get("sub"))
    # cast at the decode boundary: jwt.decode is untyped (returns Any), and a
    # validated JWT's claim set is the TokenClaims shape. Doing it here means
    # callers get a precise type with no cast of their own.
    return cast(TokenClaims, claims)


def validate_token(token: str) -> TokenClaims:
    """Validate a JWT against Auth0 or Google JWKS based on the token issuer."""
    try:
        # Unverified decode — only used to extract the issuer for dispatcher
        # routing. The dispatched validator re-decodes with signature checking.
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.DecodeError:
        logger.warning("Failed to decode JWT for issuer routing", exc_info=True)
        raise

    issuer = unverified.get("iss", "")
    if issuer in GOOGLE_ISSUERS:
        # Split from the Auth0 branch so that a Google-issued token with
        # misconfigured GOOGLE_CLIENT_ID surfaces as a config error rather than
        # silently falling through to the Auth0 validator (which would produce
        # a confusing InvalidIssuer → 401).
        if not settings.google_client_id:
            raise RuntimeError(
                "Received a Google-issued token but GOOGLE_CLIENT_ID is not "
                "configured. Set the environment variable to enable Google "
                "One Tap validation."
            )
        from .google_jwt import validate_google_token

        return validate_google_token(token)
    return _validate_auth0_token(token)


def get_normalized_subject(claims: Mapping[str, Any]) -> str | None:
    """Return a provider-prefixed stable user identifier from JWT claims.

    Auth0 tokens already embed the provider (e.g. ``auth0|…``, ``google-oauth2|…``)
    in ``sub``, so we pass them through unchanged. Google One Tap tokens carry a
    bare numeric ``sub``; we prefix with ``google|`` to match the identity scheme
    in docs/implementations/auth0/PLAN.md and to prevent collisions across
    providers that happen to mint numeric subjects.
    """
    sub = claims.get("sub")
    if not sub:
        return None
    issuer = claims.get("iss", "")
    if issuer in GOOGLE_ISSUERS:
        return f"google|{sub}"
    # str() coerces (and can't lie the way cast(str, ...) can): a JWT `sub` is a
    # StringOrURI per RFC 7519, but `claims` is Mapping[str, Any] so `sub` is
    # statically Any. The `if not sub` guard above already excludes None/empty.
    return str(sub)
