"""LOCAL-ONLY admin auth bypass (``DEV_AUTH_BYPASS_EMAIL``).

Lets a developer open the admin dashboard on their own laptop without Auth0.
When the setting is on, a request that carries NO ``Authorization`` header and
comes from a LOOPBACK client is treated as the configured email. Nothing else
about authorization changes: ``require_admin`` still looks that email up in the
``admins`` table, and any request that does send an ``Authorization`` header
takes the normal JWT path (a bad token is still a 401).

It must be impossible to activate in production, so it is fenced four ways:

1. ``enforce_dev_auth_bypass_guard`` runs as the FIRST line of the FastAPI
   lifespan and raises when the setting is on while any Railway env marker is
   present. Fail loud: the deploy never comes up, rather than coming up with the
   bypass silently ignored (or silently honoured).
2. ``dev_bypass_claims`` re-checks the Railway markers on EVERY request, so an
   env var added to a running process after boot still cannot turn it on.
3. The client address must be loopback. Behind a REMOTE proxy (Vercel,
   Railway's edge) the client is the proxy's address, never 127.0.0.1.
   A LOCAL proxy is different: anything forwarded by a process on this machine
   (``vercel dev``, the vite dev proxy) arrives from 127.0.0.1, whoever sent it
   to that proxy. That is why the run skill requires those to listen on
   127.0.0.1 only (``vercel dev --listen 127.0.0.1:3000``; vite.config.ts
   already binds 127.0.0.1) - a dev server on 0.0.0.0 would hand the bypass to
   anyone on the same network.
4. The ``Host`` header must name this machine (localhost / 127.0.0.1 / ::1),
   which keeps a DNS-rebinding page in the developer's own browser out.
"""

from __future__ import annotations

import ipaddress
import logging
import os

from fastapi import Request

from ..config import settings
from .claims import TokenClaims

logger = logging.getLogger(__name__)

# Variables Railway injects into every deployment. Any one of them, non-empty,
# means "this process is running on Railway".
RAILWAY_MARKERS: tuple[str, ...] = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_DEPLOYMENT_ID",
)

_ENV_VAR = "DEV_AUTH_BYPASS_EMAIL"


def _present_railway_markers() -> list[str]:
    return [name for name in RAILWAY_MARKERS if os.environ.get(name)]


def running_on_railway() -> bool:
    """True when any Railway marker is set to a non-empty value."""
    return bool(_present_railway_markers())


def enforce_dev_auth_bypass_guard() -> None:
    """Refuse to start with the bypass on in a Railway deployment.

    Raises ``RuntimeError`` naming the variable and the marker (never the
    email). When the bypass is on locally, logs a loud warning instead.
    """
    email = settings.dev_auth_bypass_email
    if not email:
        return
    markers = _present_railway_markers()
    if markers:
        raise RuntimeError(
            f"{_ENV_VAR} is set but this process is running on Railway "
            f"({', '.join(markers)} present). The local-only admin auth bypass "
            f"must never be enabled in a deployment; unset {_ENV_VAR}."
        )
    logger.warning(
        "%s is ON: unauthenticated loopback requests are treated as %s. "
        "Never set this outside local development.",
        _ENV_VAR,
        email,
    )


def _is_loopback_client(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    try:
        return ipaddress.ip_address(client.host).is_loopback
    except ValueError:
        # Not an IP literal at all (e.g. Starlette's TestClient default
        # "testclient"), so not provably loopback.
        return False


_LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def _host_is_local(request: Request) -> bool:
    host = request.headers.get("host", "")
    if host.startswith("["):  # [::1]:8000
        name = host[1:].split("]", 1)[0]
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name.lower() in _LOCAL_HOSTNAMES


def dev_bypass_claims(request: Request) -> TokenClaims | None:
    """Bypass claims for this request, or None when the bypass does not apply.

    Applies only when ALL hold: the setting is on, the process is not on
    Railway (re-checked per request), the request has no ``Authorization``
    header at all (checked on the raw header, because ``HTTPBearer`` also yields
    None for a malformed one), the client address is loopback and the ``Host``
    header names this machine.
    """
    email = settings.dev_auth_bypass_email
    if not email:
        return None
    if running_on_railway():
        return None
    if "authorization" in request.headers:
        return None
    if not _is_loopback_client(request):
        return None
    if not _host_is_local(request):
        return None
    return {
        "sub": f"dev-bypass|{email}",
        "email": email,
        "given_name": None,
        "family_name": None,
        "picture": None,
    }


__all__ = [
    "RAILWAY_MARKERS",
    "dev_bypass_claims",
    "enforce_dev_auth_bypass_guard",
    "running_on_railway",
]
