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
   read through ``read_bounded_body``, which bounds **both** the raw bytes taken
   off the wire and the decoded bytes retained — see that function for why
   asking for ``Accept-Encoding: identity`` was never a bound at all.

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

import asyncio
import ipaddress
import socket
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Union
from urllib.parse import SplitResult, urlsplit, urlunsplit

import httpx

# The ``idna`` *package* (a hard httpx dependency — httpx uses it to build every
# request's host), NOT the stdlib ``"idna"`` codec. The two disagree, and the
# disagreement is a bug source: see ``_normalize_hostname``.
import idna

from .ashby_client import ASHBY_BASE_URL
from .ats_link_resolver import WORKDAY_HOST_PATTERN
from .eightfold_client import _is_allowed_eightfold_host
from .gem_client import GEM_BASE_URL
from .greenhouse_client import GREENHOUSE_BASE_URL
from .lever_client import LEVER_BASE_URL

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
REASON_DEADLINE = "deadline_exceeded"       # the caller's overall budget ran out
# We send ``Accept-Encoding: identity``; a response that is compressed anyway is
# non-compliant and, more to the point, unbounded. See ``read_bounded_body``.
REASON_CONTENT_ENCODING = "unexpected_content_encoding"

MAX_HOSTNAME_LENGTH = 253

# 308/307 preserve the method; 301/302/303 may rewrite it. We re-issue the same
# method on every hop regardless — discovery only ever uses HEAD/GET, for which
# the distinction is moot.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Hostname suffixes that never name a public host. ``.local`` is mDNS,
# ``.internal`` is the GCP/AWS metadata convention, ``.localhost`` is reserved.
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal")
_BLOCKED_HOSTS = frozenset({"localhost"})

# Explicit deny list, applied *in addition to* the flag union in
# ``_is_public_address``. Neither layer subsumes the other — that was measured,
# not assumed:
#
# * ``100.64.0.0/10`` (CGNAT) and ``192.88.99.0/24`` (6to4 relay anycast) have
#   every ``is_*`` flag False on Python 3.13.3, so only this table rejects them.
# * ``224.0.0.0/4``, ``ff00::/8``, ``::/96``, ``::ffff:0:0:0/96``, ``64:ff9b::/96``
#   and ``fec0::/10`` all have ``is_global`` **False** *and* a flag set, so both
#   layers cover them — deliberately, because each layer has been the only one
#   standing at some point in this file's history.
_DENY_NETWORKS: tuple[
    Union[ipaddress.IPv4Network, ipaddress.IPv6Network], ...
] = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),    # RFC 6598 CGNAT
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    # RFC 3068 6to4 relay anycast. Measured on Python 3.13.3,
    # ``ip_address("192.88.99.1").is_global`` is **True** and every other
    # predicate is False, so this line is the only thing rejecting it. Do not
    # delete it assuming another check subsumes it.
    ipaddress.ip_network("192.88.99.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),      # IPv4 multicast
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    # RFC 4291 IPv4-compatible IPv6 (``::127.0.0.1``, ``::169.254.169.254``).
    ipaddress.ip_network("::/96"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fec0::/10"),        # deprecated site-local
    ipaddress.ip_network("ff00::/8"),         # IPv6 multicast
    # RFC 6052 NAT64 — ``64:ff9b::a9fe:a9fe`` is the metadata service behind a
    # translator, and ``::ffff:0:169.254.169.254`` is the SIIT spelling of the
    # same thing. Neither is caught by ``_unwrap_mapped`` (which only collapses
    # the ``::ffff:0:0/96`` mapped form).
    ipaddress.ip_network("64:ff9b::/96"),
    ipaddress.ip_network("::ffff:0:0/96"),    # IPv4-mapped
    ipaddress.ip_network("::ffff:0:0:0/96"),  # RFC 2765 IPv4-translated
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

    Checks run in the same order as ``validate_public_url`` (scheme, userinfo,
    port, hostname) and for the same reason: ``parts.hostname`` of
    ``https://evil.tld@boards-api.greenhouse.io/x`` is the *allowlisted* host,
    so a host-only check would pass a URL that fetches ``evil.tld``. Neither
    shape is reachable through today's ``_probe_url``, which builds its URLs
    from client constants — but this function is billed as the reusable
    boundary PR 2's recipe runtime and PR 3's add path call with URLs they did
    not build, so it may not assume its input is well-formed.
    """
    if ats not in SUPPORTED_ATS:
        raise UrlGuardError(
            REASON_ATS_HOST,
            f"unknown ATS {ats!r}; expected one of {sorted(SUPPORTED_ATS)}",
        )

    parts = _split_or_reject(url)
    if parts.scheme != "https":
        raise UrlGuardError(
            REASON_SCHEME,
            f"{ats} API URL must be https, got {parts.scheme!r} in {url!r}",
        )
    if "@" in parts.netloc:
        raise UrlGuardError(
            REASON_USERINFO,
            f"credentials in the URL are not accepted: {url!r}",
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise UrlGuardError(REASON_PORT, f"invalid port in {url!r}: {exc}") from exc
    if port is not None and port != 443:
        raise UrlGuardError(
            REASON_PORT,
            f"only the default https port is accepted; got {port} in {url!r}",
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


def _split_or_reject(url: str) -> SplitResult:
    """``urlsplit`` that fails closed instead of raising.

    ``urlsplit`` raises ``ValueError: Invalid IPv6 URL`` on unbalanced square
    brackets — ``https://a]b.com/`` is enough. Every entry point here takes a
    user-supplied string, so an unguarded ``urlsplit`` is an uncaught exception
    (HTTP 500, no reason code, no audit row) rather than a rejection.
    """
    try:
        return urlsplit(url)
    except ValueError as exc:
        raise UrlGuardError(
            REASON_HOSTNAME,
            f"{url!r} is not a parseable URL: {exc}",
        ) from exc


def _unwrap_mapped(ip: _IpAddress) -> _IpAddress:
    """Collapse an IPv4-mapped IPv6 address (``::ffff:10.0.0.5``) to its IPv4 form."""
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return mapped
    return ip


def _is_public_address(raw: str) -> bool:
    """True iff ``raw`` parses as an address we are willing to connect to.

    Three layers, all of them load-bearing, none of them a superset of another:

    1. ``not is_global``. Measured on Python 3.13.3, ``100.64.1.1`` (RFC 6598
       CGNAT — a carrier's internal space, and on some hosts the container
       network) has every individual flag False, so the flag union alone
       approved it.
    2. The six-flag union PLAN §1.2 specifies verbatim. It is **not** redundant
       with ``is_global``: replacing the union with ``is_global`` alone was
       measured to newly approve 52 addresses and newly reject none — all of
       IPv4 multicast ``224.0.0.0/4``, IPv6 multicast ``ff00::/8``,
       ``::127.0.0.1``, ``::169.254.169.254``, ``::ffff:0:169.254.169.254``,
       NAT64 ``64:ff9b::a9fe:a9fe``, ``5f00::1`` and ``0200::1``, every one of
       which has ``is_global`` **True**.
    3. ``_DENY_NETWORKS``, the explicit table, so a future Python release
       quietly widening any predicate cannot open a hole on its own.
    """
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    ip = _unwrap_mapped(ip)
    if (
        not ip.is_global
        or ip.is_private
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

    Two subtleties, both of which produced live ``500``s before they were fixed:

    * **The trailing dot.** ``localhost.`` is a legal FQDN spelling of
      ``localhost``, and it is not caught by an equality/suffix check written
      without the dot. Stripped here, *before* normalization, so the reserved-
      name check downstream sees the bare label and the reason code is
      ``invalid_hostname`` rather than whatever the resolver happens to answer.
    * **Two different IDNA implementations.** ``str.encode("idna")`` (stdlib
      codec) passes any all-ASCII label through untouched, so ``xn--a.com``
      survives it unchanged. httpx builds its request host with the ``idna``
      *package*, which rejects that same string as a malformed A-label. The
      guard would therefore approve a hostname the fetch could not express and
      the resulting ``idna.IDNAError`` escaped as a 500 with no reason code. The
      round-trip through ``idna.encode`` below makes the guard agree with the
      transport. ``idna.IDNAError`` subclasses ``UnicodeError``, so the existing
      ``except`` already names it.
    * **The stdlib codec is IDNA2003**, so it NFKC-maps confusables: ``⑧`` comes
      out as ``8``. That is *why* ``normalize_public_url`` re-runs the IP-literal
      check on the value this function returns and not only on the raw hostname.
    """
    hostname = hostname.rstrip(".")
    if not hostname:
        raise UrlGuardError(REASON_HOSTNAME, "hostname is empty after normalization")
    try:
        host = hostname.encode("idna").decode("ascii").lower()
        idna.encode(host)
    except (UnicodeError, UnicodeDecodeError, idna.IDNAError) as exc:
        raise UrlGuardError(
            REASON_HOSTNAME,
            f"hostname {hostname!r} is not IDNA-encodable: {exc}",
        ) from exc
    return host


def normalize_public_url(url: str) -> tuple[str, str]:
    """Every check ``validate_public_url`` makes *except* DNS. Pure — no IO.

    Returns ``(normalized url, IDNA-encoded host)``. Split out of
    ``validate_public_url`` (which calls it, so there is exactly one
    implementation and one check order) because two callers need the normalized
    spelling of a URL without paying for — or being able to reach — a
    resolution: the resolve endpoint's timeout branch, which must report the
    same ``finalUrl`` shape as every other 422 rather than echoing the raw user
    string back, and any future caller that wants to canonicalise before
    deciding whether to fetch at all.
    """
    if not isinstance(url, str) or not url.strip():
        raise UrlGuardError(REASON_HOSTNAME, "URL is empty")

    parts = _split_or_reject(url.strip())

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
    # trying to decide which literals are safe. Checked twice, on the raw
    # hostname and again on the normalized one: ``_normalize_hostname`` runs
    # IDNA, which NFKC-maps confusables, so ``⑧.⑧.⑧.⑧`` is *not* an IP literal
    # on the way in and *is* ``8.8.8.8`` on the way out. Only the raw check
    # existed, so the circled-digit spelling of any address — including
    # ``①⑥⑨.254.169.254`` — walked straight through.
    _reject_ip_literal(hostname)

    host = _normalize_hostname(hostname)
    _reject_ip_literal(host)
    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UrlGuardError(
            REASON_HOSTNAME,
            f"hostname {host!r} names a non-public host",
        )

    return urlunsplit(("https", host, parts.path, parts.query, "")), host


def _reject_ip_literal(hostname: str) -> None:
    """Raise if ``hostname`` parses as an IP address."""
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return
    raise UrlGuardError(
        REASON_HOSTNAME,
        f"IP literals are not accepted; got {hostname!r}",
    )


def validate_public_url(url: str) -> GuardedUrl:
    """Raise :class:`UrlGuardError`, or return the guarded URL.

    Checks run in a fixed order (scheme, userinfo, port, hostname, DNS) so the
    reason code is deterministic for inputs that fail more than one rule —
    ``http://localhost:8000/`` reports ``scheme_not_https``, not
    ``invalid_hostname``. Performs DNS and no other IO.
    """
    normalized, host = normalize_public_url(url)

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

    return GuardedUrl(url=normalized, host=host, resolved_ips=addresses)


# -----------------------------------------------------------------------------
# guarded_get
# -----------------------------------------------------------------------------


def _remaining(deadline: float | None) -> float | None:
    """Seconds left on an overall budget, or ``None`` when there is no budget.

    ``deadline`` is a ``time.monotonic()`` value, never a wall-clock one — an
    NTP step must not shorten or extend a request budget.
    """
    if deadline is None:
        return None
    return deadline - time.monotonic()


def _strip_body_headers(headers: httpx.Headers) -> httpx.Headers:
    """Drop framing headers that would contradict a truncated body."""
    out = httpx.Headers(headers)
    for key in ("content-length", "content-encoding", "transfer-encoding"):
        if key in out:
            del out[key]
    return out


# -----------------------------------------------------------------------------
# Bounded body reads
# -----------------------------------------------------------------------------

# ``Content-Encoding`` values that mean "the bytes on the wire are the bytes".
# An absent header and the explicit ``identity`` token are the same thing.
_UNCOMPRESSED_ENCODINGS = frozenset({"", "identity"})

# Minimum slice of an overall budget worth starting a request with. Below this
# the request cannot plausibly complete, and letting it go produces a transport
# timeout reported as ``fetch_failed`` — which is both the wrong diagnosis and
# fatal to the ``REASON_DEADLINE`` short-circuit in
# ``ats_discovery.sniff_embedded_ats``, which stops the remaining sub-path
# guesses only when it sees ``deadline_exceeded``.
_MIN_HOP_BUDGET_S = 0.25


def _decompressor_for(encoding: str) -> "zlib._Decompress | None":
    """A streaming decompressor for ``encoding``, or ``None`` if we cannot bound it."""
    if encoding in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        return zlib.decompressobj()
    return None


async def read_bounded_body(
    response: httpx.Response,
    max_bytes: int,
    *,
    allow_compressed: bool = False,
) -> tuple[bytes, bool]:
    """Read a streamed response under a real memory bound.

    Returns ``(body, truncated)``. ``body`` is at most ``max_bytes`` decoded
    bytes; ``truncated`` says whether there was more we chose not to take.

    **Why this is not just a loop over ``aiter_bytes()``.** ``max_bytes`` used to
    count decoded bytes coming out of ``Response.aiter_bytes()``, which
    decompresses each raw chunk *before* the caller sees it, and the requests
    "defended" that by sending ``Accept-Encoding: identity``. That header is a
    *request*; a hostile origin answers ``Content-Encoding: gzip`` anyway and
    httpx decodes on the response header. Measured end-to-end through
    ``ats_discovery.discover_ats``: a 500 MiB gzip of zeros is 509,616 bytes on
    the wire, the 512 KiB cap was "honoured" — and one ``/resolve`` worth of
    discovery (4 sniff GETs) took RSS from 47 MB to 181 MB, with a single
    decoded chunk of 67 MB. There is an OOM incident on file for this container
    (``docs/incidents/2026-04-09-oom-memory-fragmentation.md``).

    Two independent layers, so neither has to be perfect:

    1. **Reject** a response whose ``Content-Encoding`` is present and not
       ``identity``. We asked for identity; a compressed reply is non-compliant,
       and refusing it is free. Verified 2026-08-07 that neither acceptance
       target (``jobs.intel.com``, ``jobs.cisco.com``, their Workday CXS hosts)
       compresses a response to an ``identity`` request, so this costs no real
       traffic.
    2. **Bound it anyway.** Bytes come off ``aiter_raw()`` — undecoded — and are
       counted raw; if a caller ever passes ``allow_compressed=True`` (PR 2's
       recipe runtime is the plausible one, where bandwidth matters), we run the
       decompressor ourselves with ``max_length=`` so the *output* is bounded
       too. Raw ≤ ``max_bytes`` and decoded ≤ ``max_bytes``, both enforced.
    """
    encoding = response.headers.get("content-encoding", "").strip().lower()
    compressed = encoding not in _UNCOMPRESSED_ENCODINGS
    if compressed and not allow_compressed:
        raise UrlGuardError(
            REASON_CONTENT_ENCODING,
            f"response declared Content-Encoding {encoding!r} after we asked "
            f"for identity; refusing to decode it",
        )

    # httpx materialises — and decodes — a response constructed from a bytes body
    # rather than a stream: ``httpx.Response(200, text=...)``, which is every
    # ``MockTransport`` reply, and anything a caller already read. ``aiter_raw``
    # raises ``StreamConsumed`` on those, and there is nothing left to bound
    # because the allocation already happened outside this function. Apply the
    # same ceiling to what is there and say so.
    if response.is_stream_consumed:
        content = response.content
        return content[:max_bytes], len(content) > max_bytes

    decompressor: "zlib._Decompress | None" = None
    if compressed:
        decompressor = _decompressor_for(encoding)
        if decompressor is None:
            raise UrlGuardError(
                REASON_CONTENT_ENCODING,
                f"Content-Encoding {encoding!r} cannot be decoded under a bound",
            )

    # One byte of deliberate overshoot: reaching it is how we learn there was
    # more on the wire without having to ask the transport.
    limit = max_bytes + 1
    body = bytearray()
    raw_seen = 0
    async for chunk in response.aiter_raw():
        raw_seen += len(chunk)
        room = limit - len(body)
        if decompressor is None:
            body.extend(chunk[:room])
        else:
            body.extend(decompressor.decompress(chunk, max_length=room))
        if len(body) >= limit or raw_seen > max_bytes:
            break
    return bytes(body[:max_bytes]), len(body) > max_bytes or raw_seen > max_bytes


# A dedicated pool, deliberately NOT the event loop's default executor.
# ``asyncio.to_thread`` (and ``run_in_executor(None, ...)``) hand work to the
# loop's shared default pool — the same pool ``loop.getaddrinfo`` uses for every
# outbound connection in this process, including the in-process Procrastinate
# worker's ATS fetches. Cancelling a thread-pool task does **not** interrupt the
# running thread, so the resolve endpoint's ``asyncio.wait_for`` backstop
# reclaims nothing: measured, 18 concurrent resolves against a never-answering
# resolver exhausted the 16-worker default pool and a co-tenant lookup was still
# unserved 8 s later. Four workers bound the blast radius of a hostile host to
# this module; the per-user rate limit on ``POST /api/companies/resolve`` bounds
# how fast one caller can fill even those.
_DNS_EXECUTOR_MAX_WORKERS = 4
_DNS_EXECUTOR = ThreadPoolExecutor(
    max_workers=_DNS_EXECUTOR_MAX_WORKERS, thread_name_prefix="url-guard-dns"
)


async def guarded_get(
    url: str,
    http: httpx.AsyncClient,
    *,
    max_hops: int = 5,
    max_bytes: int = 1_048_576,
    allow_cross_host: bool = True,
    allow_compressed: bool = False,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    deadline: float | None = None,
) -> tuple[httpx.Response, tuple[str, ...]]:
    """Fetch ``url``, following redirects manually with a guard on every hop.

    Returns ``(final response, tuple of hop URLs)``. The hop tuple contains
    every URL actually requested, in order, starting with the (normalized)
    input — callers feed each one back through the pure resolver.

    ``max_hops`` is the maximum number of **requests issued**, which is also the
    maximum length of the returned hop tuple: ``max_hops=5`` fetches at most 5
    URLs and therefore follows at most 4 redirects. (It previously meant
    "redirects followed", so ``max_hops=5`` issued 6 requests and returned 6
    "hops" — one more than the PLAN's "max 5 hops" cap. One meaning, and it is
    this one, because it is the one the returned tuple can be checked against.)

    ``allow_cross_host`` distinguishes the two phases (PLAN §1.2):
    ``True`` at *discovery* time, where a vanity careers domain redirecting to
    a different ATS host is the single most common real-world shape
    (``jobs.intel.com`` → ``corpredirect.intel.com`` → ``intel.wd1.…``);
    ``False`` at *scrape* time, where a host change is drift we must see rather
    than absorb.

    ``method``, ``headers``, ``timeout`` and ``deadline`` are additions to the
    PLAN's signature. ``follow_to_ats`` needs ``HEAD`` (with a ``GET`` retry on
    405). ``timeout`` is *per request* and is passed explicitly on every hop, so
    it overrides the client's own default rather than being bounded by it.
    ``deadline`` is the aggregate bound that ``timeout`` alone cannot provide: a
    ``time.monotonic()`` value past which no further request is issued and every
    remaining per-request timeout is clamped to what is left. Without it,
    ``max_hops`` × ``timeout`` × (number of calls a caller makes) is the real
    worst case — 36 × 8 s ≈ 288 s for one ``/resolve``.

    ``max_bytes`` — what is actually enforced
    -----------------------------------------
    Both directions, by ``read_bounded_body``: at most ``max_bytes`` **raw**
    bytes are taken off the wire and at most ``max_bytes`` **decoded** bytes are
    retained, so the returned ``Response.content`` and the peak allocation are
    both bounded. With ``allow_compressed=False`` (the default) a response that
    declares a non-``identity`` ``Content-Encoding`` is refused outright with
    ``REASON_CONTENT_ENCODING`` before a single body byte is read. The previous
    contract — "``max_bytes`` decoded bytes, and the requests ask for
    ``Accept-Encoding: identity``" — bounded nothing: ``Accept-Encoding`` is a
    request header, and a hostile origin that ignores it turned a 512 KiB cap
    into a 67 MB allocation. See ``read_bounded_body`` for the measurements.

    ``HEAD`` responses carry no body (RFC 9110), so nothing is read and the
    ``Content-Encoding`` check does not run for them — origins routinely echo
    the encoding they *would* have used on a ``GET``, and rejecting that would
    break ``follow_to_ats``'s cheap ``HEAD`` chain for no memory benefit.
    """
    if max_hops < 1:
        raise ValueError("max_hops must be >= 1 (it counts requests, not redirects)")
    reads_body = method.upper() != "HEAD"

    hops: list[str] = []
    current = url
    origin_host: str | None = None

    loop = asyncio.get_running_loop()

    for hop_index in range(max_hops):
        left = _remaining(deadline)
        # A sliver of budget is not a budget. Handing 0.05 s to the transport
        # produces a ``ReadTimeout`` reported as ``fetch_failed``, which both
        # misdiagnoses the failure and hides ``deadline_exceeded`` from the
        # short-circuit that stops the remaining sniff sub-paths.
        if left is not None and left < _MIN_HOP_BUDGET_S:
            raise UrlGuardError(
                REASON_DEADLINE,
                f"the overall budget ran out before hop {hop_index + 1} of {url!r} "
                f"({left:.3f}s left, {_MIN_HOP_BUDGET_S}s needed)",
                hops=tuple(hops),
            )
        hop_timeout = timeout if left is None else min(timeout, left)

        try:
            # ``validate_public_url`` is deliberately sync (PR 2 / PR 3 have
            # non-async callers), but its ``getaddrinfo`` blocks the event loop —
            # measured: the loop ticked 0 times during a 1.0 s lookup. The
            # Procrastinate worker shares this process, so a slow-resolving
            # user-supplied host would stall every in-flight ATS fetch task.
            # ``_DNS_EXECUTOR``, not ``asyncio.to_thread``: see that constant for
            # why the loop's shared default pool is the wrong place for this.
            guarded = await loop.run_in_executor(
                _DNS_EXECUTOR, validate_public_url, current
            )
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
                timeout=hop_timeout,
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
                    if hop_index == max_hops - 1:
                        raise UrlGuardError(
                            REASON_TOO_MANY_HOPS,
                            f"exceeded the {max_hops}-hop limit starting at {url!r}",
                            hops=tuple(hops),
                        )
                    current = str(httpx.URL(guarded.url).join(location))
                    continue

                body = b""
                if reads_body:
                    body, _ = await read_bounded_body(
                        response, max_bytes, allow_compressed=allow_compressed
                    )

                return (
                    httpx.Response(
                        status_code=response.status_code,
                        headers=_strip_body_headers(response.headers),
                        content=body,
                        request=response.request,
                    ),
                    tuple(hops),
                )
        except UrlGuardError as exc:
            # ``read_bounded_body``'s ``REASON_CONTENT_ENCODING`` (and the
            # TOO_MANY_HOPS raise above) reach here. Re-raised so the hop chain
            # travels with them exactly as it does for a pre-request rejection.
            raise UrlGuardError(exc.reason, str(exc), hops=tuple(hops)) from exc
        except (httpx.HTTPError, httpx.InvalidURL, UnicodeError) as exc:
            # ``UnicodeError`` is not paranoia and not dead code. httpx builds
            # every request host through the ``idna`` package, and
            # ``idna.IDNAError`` subclasses ``UnicodeError``/``ValueError`` but
            # NOT ``httpx.HTTPError``. It fires from two places inside this
            # block: the request build for a host the guard approved, and — the
            # nastier one — httpx's own ``_build_redirect_request``, which
            # touches ``URL.host`` (→ ``idna.decode``) on any 3xx even with
            # ``follow_redirects=False``. That second path means a remote site
            # could 500 this endpoint at will by answering
            # ``Location: https://xn--a.com/``. Now it is ``fetch_failed``.
            raise UrlGuardError(
                REASON_FETCH_FAILED,
                f"request to {guarded.url!r} failed: {exc}",
                hops=tuple(hops),
            ) from exc

    # Unreachable: the loop either returns or raises TOO_MANY_HOPS on the last
    # iteration. Kept so the function has no implicit ``None`` return path.
    raise UrlGuardError(  # pragma: no cover
        REASON_TOO_MANY_HOPS,
        f"exceeded the {max_hops}-hop limit starting at {url!r}",
        hops=tuple(hops),
    )
