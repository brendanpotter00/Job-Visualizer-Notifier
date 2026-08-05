"""Layers L1 and L2 of the ATS resolution ladder — the only IO in PR 1.

``ats_link_resolver.resolve_ats_url`` (L0) answers "is this URL itself a board
we know?". Most real pastes are not: a user types the vanity careers domain
their employer advertises, and the actual ATS is one or two hops away, or
embedded in a page that a JavaScript front end renders.

```
L0  resolve_ats_url(url)        pure, IO-free.                Intel? no.   Cisco? no.
L1  follow_to_ats(url)          follows redirects, guarding
                                every hop, feeding each back
                                into L0.                      Intel? YES.  Cisco? no.
L2  sniff_embedded_ats(url)     fetches the landing page and
                                a few fixed sub-paths, regex-
                                scans for known ATS URLs,
                                feeds hits into L0.           Cisco? YES.
```

``discover_ats`` runs L0 → L1 → L2 and stops at the first hit. It is the single
entry point the resolve endpoint (and PR 3's add path) calls.

Redirect policy here is **discovery** policy: cross-host redirects are allowed,
capped at 5 hops, and every hop is revalidated by ``url_guard`` *before* its
request goes out. That is not the scrape-phase policy — the recipe runtime and
the six ATS clients follow no redirects at all. ``jobs.intel.com`` →
``corpredirect.intel.com`` → ``intel.wd1.myworkdayjobs.com`` is exactly why
discovery has to allow it.

No HTML parser is used: bodies are scanned as text with ``re``. BeautifulSoup
is a PR 2 dependency and is deliberately not pulled forward.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import httpx

from . import (
    ashby_client,
    eightfold_client,
    gem_client,
    greenhouse_client,
    lever_client,
    workday_client,
)
from .ats_link_resolver import AtsCandidate, resolve_ats_url
from .url_guard import (
    REASON_ATS_HOST,
    UrlGuardError,
    assert_ats_api_host,
    guarded_get,
)

logger = logging.getLogger(__name__)

# Well below the clients' DEFAULT_TIMEOUT_SECONDS = 30.0: the probe runs inside
# the user's request, behind a Vercel proxy, with a spinner on screen.
_PROBE_TIMEOUT_S: float = 12.0

# Per-request timeout for a discovery hop. Five hops at 8s each still leaves
# room for the probe inside a comfortable overall budget.
_DISCOVERY_TIMEOUT_S: float = 8.0

_MAX_REDIRECT_HOPS = 5
_MAX_SNIFF_URLS = 4
_SNIFF_MAX_BYTES = 512 * 1024

# Sub-paths appended to the landing page when the landing page itself carries no
# ATS link. Cisco's ``/global/en`` has zero occurrences; its
# ``/global/en/search-results`` has ten. Same host, path-only variations, each
# individually guard-validated before it is fetched.
_SNIFF_SUBPATHS: tuple[str, ...] = ("search-results", "careers", "jobs")

_REASON_NO_ATS = "no_ats_detected"

# Known ATS URL forms, scanned against the raw page text. Kept deliberately
# narrow — a false positive here becomes a company row pointed at someone
# else's board.
_EMBEDDED_ATS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https://[a-z0-9-]+\.wd[0-9]+\.myworkdayjobs\.com/[A-Za-z0-9_-]+"),
    re.compile(r"https://(?:job-)?boards\.greenhouse\.io/[A-Za-z0-9_-]+"),
    re.compile(r"https://jobs\.ashbyhq\.com/[A-Za-z0-9_-]+"),
    re.compile(r"https://jobs\.lever\.co/[A-Za-z0-9_-]+"),
    re.compile(r"https://jobs\.gem\.com/[A-Za-z0-9_-]+"),
)

# The contact URL in the User-Agent is load-bearing, not decoration. Intel's
# redirector (``corpredirect.intel.com``, hop 2 of the Intel chain) runs a WAF
# that 403s a bare product token — verified 2026-08-05:
#     "Job-Visualizer-Notifier/1.0"                          -> 403
#     "Job-Visualizer-Notifier/1.0 (+careers-page discovery)" -> 403
#     "Job-Visualizer-Notifier/1.0 (+https://onesecondswe.dev)" -> 301
# A self-identifying UA with a contact URL is the standard crawler convention
# anyway; it just happens to also be the difference between Intel resolving and
# Intel appearing unsupported. Do not shorten it. Never impersonate a browser:
# a browser UA ("Mozilla/5.0 …") is also 403'd there, and impersonation is not
# a thing we do.
_DISCOVERY_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "Job-Visualizer-Notifier/1.0 (+https://onesecondswe.dev)",
}


@dataclass(frozen=True)
class ProbeResult:
    """What the real ATS client said when we actually called it."""

    ok: bool
    job_count: int
    error: str | None      # the underlying message, NOT collapsed to a bool


@dataclass(frozen=True)
class DiscoveryResult:
    candidate: AtsCandidate | None
    via: str                        # 'direct' | 'redirect' | 'embedded' | 'unsupported'
    hops: tuple[str, ...]
    final_url: str
    reason: str | None              # a url_guard REASON_* or 'no_ats_detected'
    # When a page names more than one board, the losers are kept for the admin
    # log rather than dropped — "we picked Workday but also saw Greenhouse" is
    # exactly what makes a wrong resolution diagnosable.
    runners_up: tuple[AtsCandidate, ...] = field(default=())


# -----------------------------------------------------------------------------
# L1 — follow redirects
# -----------------------------------------------------------------------------


async def follow_to_ats(url: str, http: httpx.AsyncClient) -> DiscoveryResult:
    """L0 on the input, then follow redirects and run L0 on every hop.

    Issues ``HEAD`` (cheap — we only want the ``Location`` chain), falling back
    to ``GET`` if the origin rejects the method. This is what makes Intel work.
    """
    direct = resolve_ats_url(url)
    if direct is not None:
        return DiscoveryResult(
            candidate=direct,
            via="direct",
            hops=(url,),
            final_url=url,
            reason=None,
        )

    try:
        response, hops = await _fetch_chain(url, http, method="HEAD")
        if response.status_code in (405, 501):
            response, hops = await _fetch_chain(url, http, method="GET")
    except UrlGuardError as exc:
        return DiscoveryResult(
            candidate=None,
            via="unsupported",
            hops=exc.hops,
            final_url=exc.hops[-1] if exc.hops else url,
            reason=exc.reason,
        )

    for hop in hops:
        candidate = resolve_ats_url(hop)
        if candidate is not None:
            return DiscoveryResult(
                candidate=candidate,
                via="redirect",
                hops=hops,
                final_url=hops[-1],
                reason=None,
            )

    return DiscoveryResult(
        candidate=None,
        via="unsupported",
        hops=hops,
        final_url=hops[-1] if hops else url,
        reason=_REASON_NO_ATS,
    )


async def _fetch_chain(
    url: str,
    http: httpx.AsyncClient,
    *,
    method: str,
) -> tuple[httpx.Response, tuple[str, ...]]:
    return await guarded_get(
        url,
        http,
        max_hops=_MAX_REDIRECT_HOPS,
        allow_cross_host=True,
        method=method,
        headers=_DISCOVERY_HEADERS,
        timeout=_DISCOVERY_TIMEOUT_S,
    )


# -----------------------------------------------------------------------------
# L2 — sniff for an embedded board
# -----------------------------------------------------------------------------


def _sniff_urls(url: str) -> list[str]:
    """The landing URL plus a small fixed candidate sub-path list, capped at 4."""
    parts = urlsplit(url)
    base_path = parts.path.rstrip("/")
    urls = [url]
    for suffix in _SNIFF_SUBPATHS:
        variant = urlunsplit((parts.scheme, parts.netloc, f"{base_path}/{suffix}", "", ""))
        if variant not in urls:
            urls.append(variant)
    return urls[:_MAX_SNIFF_URLS]


def _scan_body(body: str, page_url: str) -> list[AtsCandidate]:
    """Every known-ATS URL in ``body``, resolved through L0, in document order."""
    found: list[AtsCandidate] = []
    for pattern in _EMBEDDED_ATS_PATTERNS:
        for match in pattern.finditer(body):
            candidate = resolve_ats_url(match.group(0))
            if candidate is not None:
                found.append(candidate)
    if found:
        logger.info(
            "Embedded ATS scan of %s found %d reference(s)", page_url, len(found)
        )
    return found


def _rank(found: list[AtsCandidate]) -> tuple[AtsCandidate, tuple[AtsCandidate, ...]]:
    """Most-frequently-referenced candidate wins; the rest are runners-up.

    Picking the first match would let a single stray link in a footer outvote
    the 10 ``applyUrl`` values that name the real board.
    """
    keyed: dict[tuple[str, str, tuple[tuple[str, str], ...]], AtsCandidate] = {}
    counts: Counter[tuple[str, str, tuple[tuple[str, str], ...]]] = Counter()
    for candidate in found:
        key = (
            candidate.ats,
            candidate.board_token,
            tuple(sorted(candidate.provider_config.items())),
        )
        counts[key] += 1
        keyed.setdefault(key, candidate)
    ordered = [keyed[key] for key, _ in counts.most_common()]
    return ordered[0], tuple(ordered[1:])


async def sniff_embedded_ats(url: str, http: httpx.AsyncClient) -> DiscoveryResult:
    """L2: fetch up to 4 same-host URLs and regex-scan each body for a board.

    Stops at the first page that yields a resolvable candidate, so a site whose
    landing page already names its board costs exactly one request.
    """
    fetched: list[str] = []
    last_reason: str | None = None

    for target in _sniff_urls(url):
        try:
            response, hops = await guarded_get(
                target,
                http,
                max_hops=_MAX_REDIRECT_HOPS,
                max_bytes=_SNIFF_MAX_BYTES,
                allow_cross_host=True,
                method="GET",
                headers=_DISCOVERY_HEADERS,
                timeout=_DISCOVERY_TIMEOUT_S,
            )
        except UrlGuardError as exc:
            # One bad sub-path must not sink the whole sniff — the sub-paths are
            # guesses, and a 4xx/DNS failure on a guess is the expected case.
            last_reason = exc.reason
            logger.debug("Sniff of %s rejected (%s)", target, exc.reason)
            continue

        fetched.extend(hop for hop in hops if hop not in fetched)
        if response.status_code >= 400:
            logger.debug("Sniff of %s returned HTTP %d", target, response.status_code)
            continue

        found = _scan_body(response.text, target)
        if found:
            winner, runners_up = _rank(found)
            return DiscoveryResult(
                candidate=winner,
                via="embedded",
                hops=tuple(fetched),
                final_url=fetched[-1] if fetched else target,
                reason=None,
                runners_up=runners_up,
            )

    return DiscoveryResult(
        candidate=None,
        via="unsupported",
        hops=tuple(fetched),
        final_url=fetched[-1] if fetched else url,
        reason=last_reason or _REASON_NO_ATS,
    )


# -----------------------------------------------------------------------------
# The entry point
# -----------------------------------------------------------------------------


async def discover_ats(url: str, http: httpx.AsyncClient) -> DiscoveryResult:
    """L0 → L1 → L2, first hit wins. The single entry point callers use."""
    followed = await follow_to_ats(url, http)
    if followed.candidate is not None:
        return followed
    if followed.reason is not None and followed.reason != _REASON_NO_ATS:
        # A guard rejection or a transport failure is a definitive answer about
        # this URL. Sniffing sub-paths of a host we just refused to talk to
        # would be both pointless and a second helping of the same risk.
        return followed

    sniffed = await sniff_embedded_ats(followed.final_url, http)
    merged = followed.hops + tuple(h for h in sniffed.hops if h not in followed.hops)
    if sniffed.candidate is not None:
        return DiscoveryResult(
            candidate=sniffed.candidate,
            via="embedded",
            hops=merged,
            final_url=sniffed.final_url,
            reason=None,
            runners_up=sniffed.runners_up,
        )
    return DiscoveryResult(
        candidate=None,
        via="unsupported",
        hops=merged,
        final_url=sniffed.final_url or followed.final_url,
        reason=_REASON_NO_ATS,
    )


# -----------------------------------------------------------------------------
# Probe
# -----------------------------------------------------------------------------


def _probe_url(candidate: AtsCandidate) -> str:
    """The URL the ATS client will actually hit, for the host assertion.

    Built from the same client constants the fetch uses, so a client that
    re-points cannot leave the assertion checking a stale host.
    """
    if candidate.ats == "greenhouse":
        return f"{greenhouse_client.GREENHOUSE_BASE_URL}/{candidate.board_token}/jobs"
    if candidate.ats == "ashby":
        return f"{ashby_client.ASHBY_BASE_URL}/{candidate.board_token}"
    if candidate.ats == "lever":
        return f"{lever_client.LEVER_BASE_URL}/{candidate.board_token}"
    if candidate.ats == "gem":
        return f"{gem_client.GEM_BASE_URL}/{candidate.board_token}/job_posts/"
    if candidate.ats == "workday":
        base = str(candidate.provider_config.get("base_url", "")).rstrip("/")
        tenant = candidate.provider_config.get("tenant_slug", "")
        site = candidate.provider_config.get("career_site_slug", "")
        return f"{base}/wday/cxs/{tenant}/{site}/jobs"
    if candidate.ats == "eightfold":
        host = candidate.provider_config.get("tenant_host", "")
        return f"https://{host}/api/apply/v2/jobs"
    raise UrlGuardError(
        REASON_ATS_HOST, f"no probe URL is defined for ATS {candidate.ats!r}"
    )


# Greenhouse / Ashby / Lever / Gem each return a whole board in ONE request, so
# probing them is literally ``len(await fetch_jobs(...))``. Workday and
# Eightfold paginate (20 and 10 rows per page respectively), and both publish a
# server-side total on page one — so for those we ask for a single row and read
# the total instead of walking the board.
#
# DELIBERATE DEVIATION from PLAN §1.4, which says probe_candidate delegates to
# ``fetch_jobs`` for all six. Measured 2026-08-05: a full
# ``workday_client.fetch_jobs`` for Intel is **680 jobs in 24.2 s** (35 sequential
# pages). That cannot fit the 12 s probe budget, and the PLAN's own acceptance
# criterion — Intel returning a job count > 500 synchronously inside the request
# — is unreachable through the paginating path. Netflix on Eightfold is worse
# (10 rows/page, ~68 pages). Reading the published total is also the *more*
# correct number: it is the source's own completeness oracle, the same value
# D10 makes load-bearing at scrape time, and it does not drift with how far a
# walk happened to get.
_COUNT_ONLY_ATS = frozenset({"workday", "eightfold"})

_PROBE_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    # Mirrors workday_client's UA — some tenants 403 a missing one.
    "User-Agent": "Job-Visualizer-Notifier/1.0",
}


async def _count_workday(candidate: AtsCandidate, http: httpx.AsyncClient) -> int:
    """One CXS POST with ``limit=1``; the answer is the payload's own ``total``.

    Body keys mirror ``workday_client.fetch_jobs`` exactly so a probe that
    succeeds is evidence the real scrape will too. ``_validate_provider_config``
    is reused (not reimplemented) so the required-key contract has one home.
    """
    provider_config = dict(candidate.provider_config)
    workday_client._validate_provider_config(provider_config)
    response = await http.post(
        _probe_url(candidate),
        json={
            "appliedFacets": provider_config.get("default_facets") or {},
            "limit": 1,
            "offset": 0,
            "searchText": "",
        },
        headers=_PROBE_HEADERS,
        timeout=_PROBE_TIMEOUT_S,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(
            f"Workday probe response is not a dict: got {type(payload).__name__}"
        )
    if not isinstance(payload.get("jobPostings"), list):
        raise ValueError("Workday probe response missing a 'jobPostings' list")
    total = payload.get("total")
    if not isinstance(total, int) or total < 0:
        raise ValueError(f"Workday probe returned an invalid 'total': {total!r}")
    return total


async def _count_eightfold(candidate: AtsCandidate, http: httpx.AsyncClient) -> int:
    """One page of 1 row; the answer is the payload's ``count``."""
    domain = candidate.provider_config.get("domain", "")
    if not domain:
        raise ValueError("Eightfold probe requires a non-empty domain")
    response = await http.get(
        _probe_url(candidate),
        params={"domain": domain, "num": 1, "start": 0},
        headers={"Accept": "application/json"},
        timeout=_PROBE_TIMEOUT_S,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(
            f"Eightfold probe response is not a dict: got {type(payload).__name__}"
        )
    if not isinstance(payload.get("positions"), list):
        raise ValueError("Eightfold probe response missing a 'positions' list")
    count = payload.get("count")
    if not isinstance(count, int) or count < 0:
        raise ValueError(f"Eightfold probe returned an invalid 'count': {count!r}")
    return count


async def _count_jobs(candidate: AtsCandidate, http: httpx.AsyncClient) -> int:
    if candidate.ats == "greenhouse":
        return len(await greenhouse_client.fetch_jobs(candidate.board_token, http))
    if candidate.ats == "ashby":
        return len(await ashby_client.fetch_jobs(candidate.board_token, http))
    if candidate.ats == "lever":
        return len(await lever_client.fetch_jobs(candidate.board_token, http))
    if candidate.ats == "gem":
        return len(await gem_client.fetch_jobs(candidate.board_token, http))
    if candidate.ats == "workday":
        return await _count_workday(candidate, http)
    if candidate.ats == "eightfold":
        return await _count_eightfold(candidate, http)
    raise UrlGuardError(
        REASON_ATS_HOST, f"no client is wired for ATS {candidate.ats!r}"
    )


async def probe_candidate(
    candidate: AtsCandidate,
    http: httpx.AsyncClient,
) -> ProbeResult:
    """Call the real ATS API and report how many jobs are actually there.

    The probe runs synchronously inside the user's request on purpose: the user
    needs a real "we found 681 open jobs" confirmation *before* anything is
    written. There is no human review behind this (owner decision D1), so an
    unprobed candidate would mean persisting a row we never confirmed.

    ``assert_ats_api_host`` runs first, so even a candidate derived from an
    attacker-chosen page can only ever cause a request to that ATS's own API
    host. See ``_COUNT_ONLY_ATS`` for why Workday and Eightfold read a published
    total instead of walking the board.

    Never raises. A failure is data — ``ok=False`` with the underlying message
    preserved, not collapsed to a boolean — because "the board 404s" and "the
    board timed out" need different answers from the user.
    """
    try:
        assert_ats_api_host(candidate.ats, _probe_url(candidate))
        job_count = await asyncio.wait_for(
            _count_jobs(candidate, http), timeout=_PROBE_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        return ProbeResult(
            ok=False,
            job_count=0,
            error=f"probe timed out after {_PROBE_TIMEOUT_S:.0f}s",
        )
    except (UrlGuardError, ValueError, httpx.HTTPError) as exc:
        return ProbeResult(ok=False, job_count=0, error=str(exc) or type(exc).__name__)

    return ProbeResult(ok=True, job_count=job_count, error=None)
