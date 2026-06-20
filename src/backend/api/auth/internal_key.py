"""Infrastructure-level gate: require X-Internal-Key on every request.

This middleware proves "the call came from our Vercel proxy" — not "who the
user is." JWT-based per-route auth (Auth0/Google) still layers on top via
the existing Depends(get_current_user) / require_admin chain.

Future extension point: a second branch checking
``Authorization: Bearer <api_key>`` against a DB-backed ``api_keys`` table
will slot in here when the MCP/external-API surface comes online.
"""

import logging
import secrets

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from ..config import settings

logger = logging.getLogger(__name__)

# Paths that bypass the gate entirely. Railway's container healthcheck hits
# /health/worker and external uptime monitors hit /health — both arrive
# without the key (the prober can't send it), so neither can ever be gated or
# the deploy fails its healthcheck and never goes live. Keep this in sync with
# railway.toml's healthcheckPath.
_EXEMPT_PATHS = frozenset({"/health", "/health/worker"})

_HEADER_NAME = "X-Internal-Key"


async def require_internal_key(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Reject requests missing or mismatching the configured shared secret.

    - When ``settings.internal_api_key`` is None (local dev with no env var),
      pass every request through. A one-shot startup warning advertises that
      the backend is open.
    - Otherwise, require the header match exactly. ``secrets.compare_digest``
      makes the comparison constant-time so an attacker can't probe byte by
      byte via response timing.
    """
    if request.url.path in _EXEMPT_PATHS:
        return await call_next(request)

    expected = settings.internal_api_key
    if expected is None:
        return await call_next(request)

    presented = request.headers.get(_HEADER_NAME)
    # Compare as UTF-8 bytes, not str: secrets.compare_digest raises TypeError
    # on a str containing non-ASCII characters, so a header like
    # "X-Internal-Key: café" would surface as a 500 instead of a clean 401.
    # Encoding first keeps the comparison constant-time and makes any malformed
    # or mismatched key deterministically Unauthorized.
    if presented is None or not secrets.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
        )

    return await call_next(request)


def warn_if_unset() -> None:
    """Emit a single WARNING at startup if the gate is open.

    Called from the FastAPI lifespan so production deployments without
    INTERNAL_API_KEY surface immediately in logs instead of silently serving
    an unauthenticated backend.
    """
    if settings.internal_api_key is None:
        logger.warning(
            "INTERNAL_API_KEY is unset — backend is accepting requests from "
            "any caller. This is OK for local dev; in production, set the "
            "env var so the require_internal_key middleware is enforced."
        )


__all__ = ["require_internal_key", "warn_if_unset"]
