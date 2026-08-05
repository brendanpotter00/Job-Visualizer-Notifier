"""SSRF boundary for user-supplied URLs.

Everything a user can point us at passes through this module before a socket
is opened. It is deliberately standalone (no DB, no FastAPI, no ATS
transform logic) so the recipe runtime (PR 2) and the self-serve add path
(PR 3) reuse the exact same checks.

Three surfaces:

1. ``validate_public_url(url)`` — the rule engine. Fail closed, explicit
   allow, checks applied in a fixed order so the reason code a caller sees is
   deterministic. Performs DNS and nothing else.
2. ``assert_ats_api_host(ats, url)`` — a candidate for a given ATS may only
   ever be fetched from that ATS's fixed API host. The permitted hosts are
   *derived* from the live client constants (``GREENHOUSE_BASE_URL`` and
   friends) rather than retyped, so re-pointing a client is a one-line change
   that cannot drift from the allowlist. Eightfold delegates to
   ``eightfold_client._is_allowed_eightfold_host`` and Workday to
   ``ats_link_resolver.WORKDAY_HOST_PATTERN`` — each pattern keeps exactly one
   home and this module copies neither.
3. ``guarded_get(...)`` — a manual redirect loop. ``follow_redirects=True`` is
   never used anywhere in this module, because httpx would follow a hop to
   ``169.254.169.254`` without ever handing us the chance to inspect it. Every
   hop is re-validated *before* its request is issued, and the response body is
   bounded while it streams rather than after it has already been buffered.

Reason codes
------------
``UrlGuardError.reason`` is a stable, machine-readable string. It is surfaced
to the client (the ``422`` body of ``POST /api/companies/resolve``), logged, and
persisted in PR 3's ``company_add_attempts`` audit log, so these values are an
API contract: add new ones, never rename or repurpose an existing one.

Accepted limitation: TOCTOU
---------------------------
DNS can change between ``validate_public_url``'s ``getaddrinfo`` and the kernel's
own resolution at connect time, so a hostile resolver can answer "public" to us
and "169.254.169.254" to the socket. **This is a known, accepted gap in v1 — it
was not missed.** Closing it properly means pinning the validated IP into the
connection (a custom transport / ``local_addr``-style connect hook), which is
out of scope here. What *is* in scope, and implemented:

- every redirect hop is re-validated, so a chain cannot launder a private host;
- the scrape path re-validates at execution time (PR 2), not just at add time;
- ATS candidates are pinned to fixed API hosts by ``assert_ats_api_host``, so
  the highest-value fetches never depend on user-controlled DNS at all;
- response bodies are size-bounded, so an SSRF that did land could not be used
  to exfiltrate an unbounded internal response.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Union
from urllib.parse import urlsplit, urlunsplit

import httpx

from .ashby_client import ASHBY_BASE_URL
from .ats_link_resolver import WORKDAY_HOST_PATTERN
from .eightfold_client import _is_allowed_eightfold_host
from .gem_client import GEM_BASE_URL
from .greenhouse_client import GREENHOUSE_BASE_URL
from .lever_client import LEVER_BASE_URL

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Stable reason codes
# -----------------------------------------------------------------------------
REASON_SCHEME = "scheme_not_https"
REASON_USERINFO = "userinfo_present"
REASON_PORT = "non_standard_port"
REASON_HOSTNAME = "invalid_hostname"
REASON_DNS = "dns_resolution_failed"
REASON_PRIVATE_ADDRESS = "resolves_to_private_address"
REASON_ATS_HOST = "not_an_allowed_ats_api_host"
REASON_TOO_MANY_HOPS = "too_many_redirects"
# Additions beyond the PLAN's table, for two cases the table did not name.
# Both are new codes rather than reuses so the audit log can tell them apart.
REASON_CROSS_HOST = "cross_host_redirect"   # only reachable with allow_cross_host=False
REASON_FETCH_FAILED = "fetch_failed"        # transport-level failure on a validated URL

MAX_HOSTNAME_LENGTH = 253

# 308/307 preserve the method; 301/302/303 may rewrite it. We re-issue the same
# method on every hop regardless — discovery only ever uses HEAD/GET, for which
# the distinction is moot.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Hostname suffixes that never name a public host. ``.local`` is mDNS,
# ``.internal`` is the GCP/AWS metadata convention, ``.localhost`` is reserved.
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")
_BLOCKED_HOSTS = frozenset({"localhost"})

# Belt-and-braces nets checked in addition to the ``ipaddress`` predicates.
# The predicates already cover all of these; listing them explicitly means a
# future Python release quietly narrowing ``is_reserved`` cannot open a hole.
_DENY_NETWORKS: tuple[
    Union[ipaddress.IPv4Network, ipaddress.IPv6Network], ...
] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),
)

_IpAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


class UrlGuardError(ValueError):
    """A URL was rejected. ``.reason`` is a stable machine-readable code.

    ``.hops`` carries the URLs already visited when the rejection happened, so
    a caller can report *where* in a redirect chain we stopped. It is empty for
    a rejection raised by ``validate_public_url`` on its own.
    """

    def __init__(
        self,
        reason: str,
        message: str,
        *,
        hops: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.hops = hops


@dataclass(frozen=True)
class GuardedUrl:
    """A URL that passed every check, plus what it resolved to."""

    url: str                        # normalized absolute https URL
    host: str                       # lowercased, IDNA-encoded hostname
    resolved_ips: tuple[str, ...]


# -----------------------------------------------------------------------------
# ATS API host allowlist — derived from the clients, never retyped.
# -----------------------------------------------------------------------------


def _host_of(base_url: str) -> str:
    host = urlsplit(base_url).hostname
    if not host:
        raise RuntimeError(f"ATS base URL {base_url!r} has no hostname")
    return host.lower()


_ATS_API_HOSTS: dict[str, str] = {
    "greenhouse": _host_of(GREENHOUSE_BASE_URL),   # boards-api.greenhouse.io
    "ashby": _host_of(ASHBY_BASE_URL),             # api.ashbyhq.com
    "lever": _host_of(LEVER_BASE_URL),             # api.lever.co
    "gem": _host_of(GEM_BASE_URL),                 # api.gem.com
}

# ``eightfold`` and ``workday`` are pattern-matched, not fixed strings, so they
# are handled in ``assert_ats_api_host`` rather than living in the dict above.
SUPPORTED_ATS: frozenset[str] = frozenset(
    set(_ATS_API_HOSTS) | {"eightfold", "workday"}
)


def assert_ats_api_host(ats: str, url: str) -> None:
    """Raise unless ``url`` is on ``ats``'s permitted API host.

    A candidate for a given ATS may only ever be fetched from that ATS's own
    API host. This is the check that makes a mis-resolved candidate harmless:
    even if the resolver produced a ``board_token`` from an attacker-chosen
    page, the fetch still goes to ``boards-api.greenhouse.io``.

    Workday has no host check in ``workday_client`` (E0 ticket 0.3 owns that
    gap and this PR deliberately does not touch that file), so the pattern
    lives here and is applied to user-supplied input only — existing seeded
    rows are unaffected.
    """
    if ats not in SUPPORTED_ATS:
        raise UrlGuardError(
            REASON_ATS_HOST,
            f"unknown ATS {ats!r}; expected one of {sorted(SUPPORTED_ATS)}",
        )

    parts = urlsplit(url)
    if parts.scheme != "https":
        raise UrlGuardError(
            REASON_SCHEME,
            f"{ats} API URL must be https, got {parts.scheme!r} in {url!r}",
        )
    host = (parts.hostname or "").lower()
    if not host:
        raise UrlGuardError(REASON_HOSTNAME, f"{url!r} has no hostname")

    if ats == "eightfold":
        if not _is_allowed_eightfold_host(host):
            raise UrlGuardError(
                REASON_ATS_HOST,
                f"eightfold host {host!r} is not on the eightfold_client "
                f"SSRF allowlist",
            )
        return

    if ats == "workday":
        if not WORKDAY_HOST_PATTERN.fullmatch(host):
            raise UrlGuardError(
                REASON_ATS_HOST,
                f"workday host {host!r} does not match "
                f"{WORKDAY_HOST_PATTERN.pattern}",
            )
        return

    expected = _ATS_API_HOSTS[ats]
    if host != expected:
        raise UrlGuardError(
            REASON_ATS_HOST,
            f"{ats} candidate must be fetched from {expected!r}, got {host!r}",
        )


# -----------------------------------------------------------------------------
# validate_public_url
# -----------------------------------------------------------------------------


def _unwrap_mapped(ip: _IpAddress) -> _IpAddress:
    """Collapse an IPv4-mapped IPv6 address (``::ffff:10.0.0.5``) to its IPv4 form."""
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return mapped
    return ip


def _is_public_address(raw: str) -> bool:
    """True iff ``raw`` parses as an address we are willing to connect to."""
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    ip = _unwrap_mapped(ip)
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False
    for net in _DENY_NETWORKS:
        if ip.version == net.version and ip in net:
            return False
    return True


def _normalize_hostname(hostname: str) -> str:
    """IDNA-encode and lowercase, so a Unicode homoglyph cannot bypass the checks.

    ``exаmple.com`` with a Cyrillic ``а`` must become ``xn--exmple-4nf.com``
    before any comparison happens — otherwise a lookalike host would sail past
    a suffix check written in ASCII.
    """
    try:
        return hostname.encode("idna").decode("ascii").lower()
    except (UnicodeError, UnicodeDecodeError) as exc:
        raise UrlGuardError(
            REASON_HOSTNAME,
            f"hostname {hostname!r} is not IDNA-encodable: {exc}",
        ) from exc


def validate_public_url(url: str) -> GuardedUrl:
    """Raise :class:`UrlGuardError`, or return the guarded URL.

    Checks run in a fixed order (scheme, userinfo, port, hostname, DNS) so the
    reason code is deterministic for inputs that fail more than one rule —
    ``http://localhost:8000/`` reports ``scheme_not_https``, not
    ``invalid_hostname``. Performs DNS and no other IO.
    """
    if not isinstance(url, str) or not url.strip():
        raise UrlGuardError(REASON_HOSTNAME, "URL is empty")

    parts = urlsplit(url.strip())

    # 1. scheme
    if parts.scheme != "https":
        raise UrlGuardError(
            REASON_SCHEME,
            f"only https is accepted; got scheme {parts.scheme!r} in {url!r}",
        )

    # 2. userinfo — `https://boards.greenhouse.io@evil.tld/` is an evil.tld fetch
    if "@" in parts.netloc:
        raise UrlGuardError(
            REASON_USERINFO,
            f"credentials in the URL are not accepted: {url!r}",
        )

    # 3. port
    try:
        port = parts.port
    except ValueError as exc:
        raise UrlGuardError(REASON_PORT, f"invalid port in {url!r}: {exc}") from exc
    if port is not None and port != 443:
        raise UrlGuardError(
            REASON_PORT,
            f"only the default https port is accepted; got {port} in {url!r}",
        )

    # 4. hostname
    hostname = parts.hostname
    if not hostname:
        raise UrlGuardError(REASON_HOSTNAME, f"{url!r} has no hostname")
    if len(hostname) > MAX_HOSTNAME_LENGTH:
        raise UrlGuardError(
            REASON_HOSTNAME,
            f"hostname exceeds {MAX_HOSTNAME_LENGTH} characters",
        )
    # An IP literal skips DNS entirely, so reject it outright rather than
    # trying to decide which literals are safe.
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise UrlGuardError(
            REASON_HOSTNAME,
            f"IP literals are not accepted; got {hostname!r}",
        )

    host = _normalize_hostname(hostname)
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UrlGuardError(
            REASON_HOSTNAME,
            f"hostname {host!r} names a non-public host",
        )

    # 5. DNS — every answer must be public, not just the first.
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlGuardError(
            REASON_DNS,
            f"could not resolve {host!r}: {exc}",
        ) from exc
    except OSError as exc:  # pragma: no cover - platform-specific resolver errors
        raise UrlGuardError(
            REASON_DNS,
            f"could not resolve {host!r}: {exc}",
        ) from exc

    addresses = tuple(str(info[4][0]) for info in infos)
    if not addresses:
        raise UrlGuardError(REASON_DNS, f"{host!r} resolved to no addresses")

    # ALL answers must pass. A host with one public and one private A record is
    # rejected: whichever the kernel picks at connect time is out of our hands.
    bad = [a for a in addresses if not _is_public_address(a)]
    if bad:
        raise UrlGuardError(
            REASON_PRIVATE_ADDRESS,
            f"{host!r} resolves to non-public address(es) {bad!r}",
        )

    normalized = urlunsplit(("https", host, parts.path, parts.query, ""))
    return GuardedUrl(url=normalized, host=host, resolved_ips=addresses)


# -----------------------------------------------------------------------------
# guarded_get
# -----------------------------------------------------------------------------


def _strip_body_headers(headers: httpx.Headers) -> httpx.Headers:
    """Drop framing headers that would contradict a truncated body."""
    out = httpx.Headers(headers)
    for key in ("content-length", "content-encoding", "transfer-encoding"):
        if key in out:
            del out[key]
    return out


async def guarded_get(
    url: str,
    http: httpx.AsyncClient,
    *,
    max_hops: int = 5,
    max_bytes: int = 1_048_576,
    allow_cross_host: bool = True,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[httpx.Response, tuple[str, ...]]:
    """Fetch ``url``, following redirects manually with a guard on every hop.

    Returns ``(final response, tuple of hop URLs)``. The hop tuple contains
    every URL actually requested, in order, starting with the (normalized)
    input — callers feed each one back through the pure resolver.

    ``allow_cross_host`` distinguishes the two phases (PLAN §1.2):
    ``True`` at *discovery* time, where a vanity careers domain redirecting to
    a different ATS host is the single most common real-world shape
    (``jobs.intel.com`` → ``corpredirect.intel.com`` → ``intel.wd1.…``);
    ``False`` at *scrape* time, where a host change is drift we must see rather
    than absorb.

    ``method``, ``headers`` and ``timeout`` are additions to the PLAN's
    signature: ``follow_to_ats`` needs ``HEAD`` (with a ``GET`` retry on 405),
    and pinning a timeout here keeps a hostile host from holding a request
    open for the client's default.

    The body is bounded **while streaming**, not after buffering, so a
    multi-gigabyte response cannot be pulled into memory before the cap is
    noticed.
    """
    if max_hops < 0:
        raise ValueError("max_hops must be >= 0")

    hops: list[str] = []
    current = url
    origin_host: str | None = None

    for hop_index in range(max_hops + 1):
        try:
            guarded = validate_public_url(current)
        except UrlGuardError as exc:
            # Re-raise carrying the chain so far: "we stopped at hop 2" is the
            # diagnostic, and a bare reason code loses it.
            raise UrlGuardError(exc.reason, str(exc), hops=tuple(hops)) from exc

        if origin_host is None:
            origin_host = guarded.host
        elif not allow_cross_host and guarded.host != origin_host:
            raise UrlGuardError(
                REASON_CROSS_HOST,
                f"redirect to a different host is not allowed here: "
                f"{origin_host!r} -> {guarded.host!r}",
                hops=tuple(hops),
            )

        hops.append(guarded.url)

        try:
            async with http.stream(
                method,
                guarded.url,
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
            ) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        # A redirect status with no Location is a dead end, not
                        # a hop. Hand the (bodyless) response back as final.
                        return (
                            httpx.Response(
                                status_code=response.status_code,
                                headers=_strip_body_headers(response.headers),
                                content=b"",
                                request=response.request,
                            ),
                            tuple(hops),
                        )
                    if hop_index == max_hops:
                        raise UrlGuardError(
                            REASON_TOO_MANY_HOPS,
                            f"exceeded {max_hops} redirect hops starting at {url!r}",
                            hops=tuple(hops),
                        )
                    current = str(httpx.URL(guarded.url).join(location))
                    continue

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    remaining = max_bytes - len(body)
                    if remaining <= 0:
                        break
                    body.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        break

                return (
                    httpx.Response(
                        status_code=response.status_code,
                        headers=_strip_body_headers(response.headers),
                        content=bytes(body),
                        request=response.request,
                    ),
                    tuple(hops),
                )
        except httpx.HTTPError as exc:
            raise UrlGuardError(
                REASON_FETCH_FAILED,
                f"request to {guarded.url!r} failed: {exc}",
                hops=tuple(hops),
            ) from exc

    # Unreachable: the loop either returns or raises TOO_MANY_HOPS on the last
    # iteration. Kept so the function has no implicit ``None`` return path.
    raise UrlGuardError(  # pragma: no cover
        REASON_TOO_MANY_HOPS,
        f"exceeded {max_hops} redirect hops starting at {url!r}",
        hops=tuple(hops),
    )
