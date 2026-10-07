"""LOCAL-ONLY admin auth bypass (``DEV_AUTH_BYPASS_EMAIL``).

Lets a developer open the admin dashboard on their own laptop without Auth0.
When the setting is on, a request that carries NO ``Authorization`` header and
comes from a LOOPBACK client is treated as the configured email. Nothing else
about authorization changes: ``require_admin`` still looks that email up in the
``admins`` table, and any request that does send an ``Authorization`` header
takes the normal JWT path (a bad token is still a 401).

It must be impossible to activate in production, so it is fenced five ways:

1. ``enforce_dev_auth_bypass_guard`` runs as the FIRST line of the FastAPI
   lifespan and raises when the setting is on while any Railway env marker is
   present. Fail loud: the deploy never comes up, rather than coming up with the
   bypass silently ignored (or silently honoured).
2. The same guard raises when ``DATABASE_URL`` names a host that is not local:
   a laptop backend pointed at the PRODUCTION database with the bypass on would
   otherwise act as the real admin on real rows, and the first ``/api/users``
   call would rewrite the real admin's ``users`` row (``get_or_create_user``
   matches it by email and overwrites ``auth0_id`` with the bypass ``sub``).
   Every host libpq would read is checked, including a ``host=`` / ``hostaddr=``
   query parameter, which overrides the URL authority (the trap
   ``services/dev_reset.assert_local_database`` documents). Local means
   ``localhost``, a loopback IP, or the docker-compose service name
   (``postgres``); anything else, an unparseable URL or one naming no host at
   all, refuses. ``settings.database_url`` is read once and the pool is built
   from it, so this is a startup check only.
3. ``dev_bypass_claims`` re-checks the Railway markers on EVERY request, so an
   env var added to a running process after boot still cannot turn it on.
4. The client address must be loopback. Behind a REMOTE proxy (Vercel,
   Railway's edge) the client is the proxy's address, never 127.0.0.1.
   A LOCAL proxy is different: anything forwarded by a process on this machine
   (``vercel dev``, the vite dev proxy) arrives from 127.0.0.1, whoever sent it
   to that proxy. That is why the run skill requires those to listen on
   127.0.0.1 only (``vercel dev --listen 127.0.0.1:3000``; vite.config.ts
   already binds 127.0.0.1) - a dev server on 0.0.0.0 would hand the bypass to
   anyone on the same network.
5. The ``Host`` header must name this machine (localhost / 127.0.0.1 / ::1),
   which keeps a DNS-rebinding page in the developer's own browser out.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from urllib.parse import urlsplit

import psycopg2
from fastapi import Request
from psycopg2.extensions import parse_dsn

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


# Database hosts that are this machine (plus any loopback IP, checked with
# ``ipaddress``) or the docker-compose service (``docker-compose.yml`` names it
# ``postgres``; a backend run inside that compose network dials it by name).
# Compared with ``==`` after parsing, never as a substring: ``localhost.evil.com``
# and ``postgres.railway.internal`` are not local.
_LOCAL_DATABASE_HOSTNAMES = frozenset({"localhost", "postgres"})


def _is_local_database_host(host: str) -> bool:
    name = host.strip().lower()
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return name in _LOCAL_DATABASE_HOSTNAMES


def non_local_database_reason(database_url: str) -> str | None:
    """None when every host ``database_url`` names is local, else why it is not
    (naming the host, never the URL itself: that carries the password).

    Parsed the way libpq parses it: the URL authority AND any ``host=`` /
    ``hostaddr=`` query parameter, which libpq lets override the authority, must
    each be local. Fails closed: an unparseable URL, or one naming no host (a
    Unix-socket DSN), is not provably local.
    """
    try:
        url_host = urlsplit(database_url).hostname
        # libpq has no SQLAlchemy "+driver" scheme spelling; drop it before parsing.
        scheme, sep, rest = database_url.partition("://")
        dsn = parse_dsn(f"{scheme.split('+', 1)[0]}{sep}{rest}" if sep else database_url)
    except (ValueError, psycopg2.Error):
        return "it could not be parsed"
    hosts = [h for h in (url_host, dsn.get("host"), dsn.get("hostaddr")) if h]
    if not hosts:
        return "it names no host"
    for host in hosts:
        if not _is_local_database_host(host):
            return f"its host {host.strip().lower()!r} is not local"
    return None


def enforce_dev_auth_bypass_guard() -> None:
    """Refuse to start with the bypass on in a Railway deployment, or against a
    database that is not on this machine.

    Raises ``RuntimeError`` naming the variable and the marker or the database
    host (never the email, never the URL). When the bypass is on locally, logs a
    loud warning instead.
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
    reason = non_local_database_reason(settings.database_url)
    if reason:
        raise RuntimeError(
            f"{_ENV_VAR} is set but DATABASE_URL is not a local database ({reason}; "
            f"local means localhost, a loopback IP, or the docker-compose 'postgres' "
            f"service). The local-only admin auth bypass must never run against a "
            f"shared or production database; unset {_ENV_VAR} or point "
            f"DATABASE_URL at your local Postgres."
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
    "non_local_database_reason",
    "running_on_railway",
]
