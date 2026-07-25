"""SSRF egress guard for user-supplied URLs.

The "add your own company" flow accepts an arbitrary careers-page URL from a
logged-in user and then fetches it — at onboarding (HTML sniff + Playwright
navigation), during Workday/custom probing, and **forever after** on every
recurring ``custom_json`` scrape (the recipe endpoint is user-controlled). Every
one of those outbound calls must go through this guard so a user cannot point us
at ``http://169.254.169.254/…`` (cloud metadata), ``http://localhost:8000/…``
(our own API), or any other internal host.

Precedent: ``services/eightfold_client.py`` has a narrow host allowlist for the
one data-driven ATS host. This module generalizes that idea to *deny* the
private/loopback/link-local/reserved ranges for arbitrary user URLs.

Design:

* :func:`validate_public_url` — scheme must be http/https, host must be present,
  and **every** IP the host resolves to (A + AAAA) must be globally routable.
  Raises :class:`BlockedURLError` otherwise. This is the load-bearing check.
* :func:`safe_get` — validate, then issue the request with redirects disabled and
  **re-validate every hop** manually (an allowed host can 302 to a private one),
  capping both the hop count and the response body size.

Residual risk (documented, not closed here): DNS rebinding — the name is
re-resolved by the OS when httpx opens the socket, so a host that resolves
public at check time and private a millisecond later at connect time could slip
through. Fully closing it requires pinning the validated IP into the connection
(a custom transport). Out of scope for this iteration; the check still blocks the
overwhelming majority of SSRF attempts (literal IPs, static internal names).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Bounds for guarded fetches.
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
# 8 MiB: a job-board listing/HTML page is comfortably under this; the cap stops a
# malicious endpoint from streaming gigabytes into the worker.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class BlockedURLError(ValueError):
    """Raised when a URL is not allowed to be fetched (bad scheme/host/IP).

    Subclasses ``ValueError`` so existing ``except ValueError`` handlers in the
    fetch tasks record it as a normal recorded error rather than crashing.
    """


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True only for globally-routable unicast addresses.

    Rejects private, loopback, link-local (incl. 169.254.0.0/16 cloud metadata),
    unique-local (fc00::/7), multicast, unspecified, and reserved ranges. IPv6
    v4-mapped addresses (``::ffff:a.b.c.d``) are unwrapped so an internal IPv4
    can't be smuggled through the v6 form.
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    )


def _resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve ``host`` to every A/AAAA address, or raise BlockedURLError.

    A literal IP host skips DNS. A resolution failure is treated as blocked
    (fail closed) rather than surfaced as a transport error.
    """
    # Literal IP? validate it directly (no DNS).
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedURLError(f"host {host!r} did not resolve: {exc}") from exc

    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        try:
            addrs.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    if not addrs:
        raise BlockedURLError(f"host {host!r} produced no usable IP addresses")
    return addrs


def validate_public_url(url: str) -> None:
    """Raise :class:`BlockedURLError` unless ``url`` is safe to fetch.

    Checks: parseable, http(s) scheme, has a hostname, and every resolved IP is
    globally routable. No return value — call for its side effect.
    """
    if not isinstance(url, str) or not url.strip():
        raise BlockedURLError("empty URL")

    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise BlockedURLError(
            f"scheme {parts.scheme!r} not allowed (must be http or https)"
        )
    host = parts.hostname
    if not host:
        raise BlockedURLError("URL has no host")

    for ip in _resolve_host(host):
        if not _ip_is_public(ip):
            raise BlockedURLError(
                f"host {host!r} resolves to non-public address {ip} — blocked"
            )


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_redirects: int = MAX_REDIRECTS,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET ``url`` with SSRF validation on the initial URL and every redirect hop.

    Redirects are followed manually (httpx ``follow_redirects=False``) so each
    ``Location`` is re-validated before we connect to it — an allowed host that
    302s to ``http://169.254.169.254`` is caught. Caps hops and response size.

    Raises
    ------
    BlockedURLError
        Any hop fails validation, too many redirects, or the body exceeds
        ``MAX_RESPONSE_BYTES``.
    httpx.HTTPError
        Underlying transport errors propagate for the caller to handle.
    """
    current = url
    for _ in range(max_redirects + 1):
        validate_public_url(current)
        response = await client.get(
            current,
            timeout=timeout,
            follow_redirects=False,
            headers=headers,
        )
        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                return response
            current = urljoin(current, location)
            continue
        # Enforce the body cap. httpx has already buffered the body for a
        # non-streaming get(); reject oversized payloads rather than pass them on.
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise BlockedURLError(
                f"response body from {current!r} exceeds "
                f"{MAX_RESPONSE_BYTES} bytes"
            )
        return response
    raise BlockedURLError(f"too many redirects fetching {url!r}")
