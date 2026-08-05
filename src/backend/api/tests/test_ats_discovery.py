"""Unit tests for L1 (redirect following) and L2 (embedded-board sniffing).

Everything runs through ``httpx.MockTransport`` — no live network in CI. The
two headline cases replay the *real* chains captured live on 2026-08-05:

* **Intel** — ``jobs.intel.com`` →301→ ``corpredirect.intel.com`` →301→
  ``intel.wd1.myworkdayjobs.com/External/page/6042…``. A cross-host redirect
  chain, which is exactly why discovery-phase redirects are allowed.
* **Cisco** — ``jobs.cisco.com`` →302→ ``careers.cisco.com`` →303→
  ``/global/en``, whose body names no board; the board only appears on
  ``/global/en/search-results``. That is why the sniffer tries sub-paths
  rather than only the landing page.
"""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from api.services import ats_discovery
from api.services.ats_discovery import (
    DiscoveryResult,
    discover_ats,
    follow_to_ats,
    probe_candidate,
    sniff_embedded_ats,
)
from api.services.ats_link_resolver import AtsCandidate

INTEL_REDIRECTOR = (
    "https://corpredirect.intel.com/Redirector/404Redirector.aspx"
    "?404;https://jobs.intel.com/"
)
INTEL_WORKDAY = (
    "https://intel.wd1.myworkdayjobs.com/External/page/"
    "6042070b79e01001f04fa9b468070000"
)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch):
    """Every hostname resolves to one public address. Keeps DNS out of the way."""

    def fake(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


class _Recorder:
    """MockTransport wrapper that records every request it serves."""

    def __init__(self, handler):
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def client(self) -> httpx.AsyncClient:
        def wrapped(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self._handler(request)

        return httpx.AsyncClient(transport=httpx.MockTransport(wrapped))

    @property
    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


# ----------------------------------------------------------------------------
# L1 — follow_to_ats
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_hit_makes_no_request() -> None:
    """A URL that already IS a board costs zero IO."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request expected; got {request.url}")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await follow_to_ats("https://boards.greenhouse.io/acme", http)

    assert result.via == "direct"
    assert result.candidate is not None
    assert result.candidate.ats == "greenhouse"
    assert result.candidate.board_token == "acme"
    assert recorder.requests == []


def _intel_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url in ("https://jobs.intel.com", "https://jobs.intel.com/"):
        return httpx.Response(301, headers={"location": INTEL_REDIRECTOR})
    if url == INTEL_REDIRECTOR:
        return httpx.Response(301, headers={"location": INTEL_WORKDAY})
    if url == INTEL_WORKDAY:
        return httpx.Response(200, text="<html>Workday</html>")
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_intel_regression_resolves_via_redirect() -> None:
    """🔴 The D11 acceptance target. Cross-host chain → Workday/External."""
    recorder = _Recorder(_intel_handler)
    async with recorder.client() as http:
        result = await follow_to_ats("https://jobs.intel.com", http)

    assert result.via == "redirect"
    assert result.candidate is not None
    assert result.candidate.ats == "workday"
    assert result.candidate.provider_config == {
        "base_url": "https://intel.wd1.myworkdayjobs.com",
        "tenant_slug": "intel",
        "career_site_slug": "External",
    }
    assert result.final_url == INTEL_WORKDAY
    assert result.hops == (
        "https://jobs.intel.com",
        INTEL_REDIRECTOR,
        INTEL_WORKDAY,
    )
    # HEAD is enough to walk a Location chain.
    assert {r.method for r in recorder.requests} == {"HEAD"}


@pytest.mark.asyncio
async def test_head_405_falls_back_to_get() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405)
        if str(request.url) == "https://picky.example/":
            return httpx.Response(302, headers={"location": "https://jobs.lever.co/acme"})
        return httpx.Response(200, text="ok")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await follow_to_ats("https://picky.example/", http)

    assert "HEAD" in calls and "GET" in calls
    assert result.via == "redirect"
    assert result.candidate is not None
    assert result.candidate.ats == "lever"


@pytest.mark.asyncio
async def test_guard_rejection_mid_chain_is_reported_with_its_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await follow_to_ats("https://ok.example/", http)

    assert result.candidate is None
    assert result.via == "unsupported"
    assert result.reason == "scheme_not_https"
    assert len(recorder.requests) == 1


@pytest.mark.asyncio
async def test_no_ats_anywhere_in_the_chain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>nothing here</html>")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await follow_to_ats("https://www.tesla.com/careers", http)

    assert result.candidate is None
    assert result.reason == "no_ats_detected"
    assert result.via == "unsupported"


# ----------------------------------------------------------------------------
# L2 — sniff_embedded_ats
# ----------------------------------------------------------------------------

CISCO_LANDING = "https://careers.cisco.com/global/en"
CISCO_SEARCH = "https://careers.cisco.com/global/en/search-results"
CISCO_BOARD = "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers"


def _cisco_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url in ("https://jobs.cisco.com", "https://jobs.cisco.com/"):
        return httpx.Response(302, headers={"location": "https://careers.cisco.com"})
    if url in ("https://careers.cisco.com", "https://careers.cisco.com/"):
        return httpx.Response(303, headers={"location": "/global/en"})
    if url == CISCO_LANDING:
        # The real landing page contains ZERO ATS URLs.
        return httpx.Response(200, text="<html><body>Cisco Careers</body></html>")
    if url == CISCO_SEARCH:
        # The real search-results page embeds the board 10 times in applyUrl values.
        body = "".join(
            f'{{"jobId":"{i}","applyUrl":"{CISCO_BOARD}/job/{i}"}}' for i in range(10)
        )
        return httpx.Response(200, text=f'<script>phApp.ddo = {{"jobs":[{body}]}}</script>')
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_cisco_regression_resolves_via_embedded_sniff() -> None:
    """🔴 The Phenom-fronted case. Cisco renders on Phenom; its ATS is Workday."""
    recorder = _Recorder(_cisco_handler)
    async with recorder.client() as http:
        result = await discover_ats("https://jobs.cisco.com", http)

    assert result.via == "embedded"
    assert result.candidate is not None
    assert result.candidate.ats == "workday"
    assert result.candidate.provider_config == {
        "base_url": "https://cisco.wd5.myworkdayjobs.com",
        "tenant_slug": "cisco",
        "career_site_slug": "Cisco_Careers",
    }
    assert result.final_url == CISCO_SEARCH


@pytest.mark.asyncio
async def test_sniffer_stops_at_the_first_page_that_names_a_board() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f"see https://jobs.lever.co/acme at {request.url}")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://start.example/careers", http)

    assert result.candidate is not None
    assert len(recorder.requests) == 1


@pytest.mark.asyncio
async def test_sniffer_tries_at_most_four_urls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>nothing</html>")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://start.example/careers", http)

    assert result.candidate is None
    assert len(recorder.requests) == 4
    assert recorder.urls == [
        "https://start.example/careers",
        "https://start.example/careers/search-results",
        "https://start.example/careers/careers",
        "https://start.example/careers/jobs",
    ]


@pytest.mark.asyncio
async def test_sniffed_body_is_truncated() -> None:
    """A board named past the 512 KB cap is not found — the cap is real."""
    padding = "x" * (ats_discovery._SNIFF_MAX_BYTES + 100)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=padding + "https://jobs.lever.co/acme")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://big.example/careers", http)

    assert result.candidate is None


@pytest.mark.asyncio
async def test_most_frequent_candidate_wins_and_runners_up_are_recorded() -> None:
    body = (
        "https://jobs.lever.co/decoy "
        + "https://boards.greenhouse.io/realboard " * 5
        + "https://jobs.ashbyhq.com/other "
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://multi.example/careers", http)

    assert result.candidate is not None
    assert result.candidate.ats == "greenhouse"
    assert result.candidate.board_token == "realboard"
    runners = {(c.ats, c.board_token) for c in result.runners_up}
    assert runners == {("lever", "decoy"), ("ashby", "other")}


@pytest.mark.asyncio
async def test_a_failing_subpath_does_not_sink_the_whole_sniff() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search-results"):
            return httpx.Response(404)
        if request.url.path.endswith("/careers/careers"):
            return httpx.Response(200, text="https://jobs.gem.com/nominal")
        return httpx.Response(200, text="<html>nothing</html>")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://x.example/careers", http)

    assert result.candidate is not None
    assert result.candidate.ats == "gem"


# ----------------------------------------------------------------------------
# discover_ats — the composition
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_prefers_l1_and_never_sniffs_on_a_hit() -> None:
    recorder = _Recorder(_intel_handler)
    async with recorder.client() as http:
        result = await discover_ats("https://jobs.intel.com", http)

    assert result.via == "redirect"
    # Three hops and nothing else: no sniff sub-paths were fetched.
    assert len(recorder.requests) == 3


@pytest.mark.asyncio
async def test_discover_does_not_sniff_after_a_guard_rejection() -> None:
    """A host we just refused to talk to does not get four more chances."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://10.0.0.5/"})

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await discover_ats("https://ok.example/", http)

    assert result.candidate is None
    assert result.reason == "scheme_not_https"
    assert len(recorder.requests) == 1


@pytest.mark.asyncio
async def test_discover_returns_unsupported_when_nothing_matches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>just a marketing page</html>")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await discover_ats("https://www.tesla.com/careers", http)

    assert result == DiscoveryResult(
        candidate=None,
        via="unsupported",
        hops=result.hops,
        final_url=result.final_url,
        reason="no_ats_detected",
    )


# ----------------------------------------------------------------------------
# probe_candidate
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_greenhouse_counts_jobs() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "boards-api.greenhouse.io"
        return httpx.Response(200, json={"jobs": [{"id": i} for i in range(7)]})

    recorder = _Recorder(handler)
    candidate = AtsCandidate("greenhouse", "acme", {}, "https://boards.greenhouse.io/acme")
    async with recorder.client() as http:
        result = await probe_candidate(candidate, http)

    assert result == ats_discovery.ProbeResult(ok=True, job_count=7, error=None)


@pytest.mark.asyncio
async def test_probe_workday_reads_the_published_total() -> None:
    """One request, ``limit=1``, and the count comes from the source's own total.

    Walking the board would be 35 sequential pages / 24 s for Intel — see the
    ``_COUNT_ONLY_ATS`` comment in ats_discovery.
    """
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"total": 681, "jobPostings": [{"title": "x"}]})

    recorder = _Recorder(handler)
    candidate = AtsCandidate(
        "workday",
        "intel",
        {
            "base_url": "https://intel.wd1.myworkdayjobs.com",
            "tenant_slug": "intel",
            "career_site_slug": "External",
        },
        INTEL_WORKDAY,
    )
    async with recorder.client() as http:
        result = await probe_candidate(candidate, http)

    assert result.ok is True
    assert result.job_count == 681
    assert len(recorder.requests) == 1
    assert recorder.urls == [
        "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs"
    ]
    assert bodies == [{"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}]


@pytest.mark.asyncio
async def test_probe_eightfold_reads_the_published_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["domain"] == "netflix.com"
        return httpx.Response(200, json={"count": 484, "positions": [{"id": 1}]})

    recorder = _Recorder(handler)
    candidate = AtsCandidate(
        "eightfold",
        "netflix",
        {"tenant_host": "explore.jobs.netflix.net", "domain": "netflix.com"},
        "https://explore.jobs.netflix.net/careers?domain=netflix.com",
    )
    async with recorder.client() as http:
        result = await probe_candidate(candidate, http)

    assert result.ok is True
    assert result.job_count == 484


@pytest.mark.asyncio
async def test_probe_refuses_a_candidate_pointed_off_its_api_host() -> None:
    """The guard runs BEFORE the client, so a poisoned base_url issues no request."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request must be issued; got {request.url}")

    recorder = _Recorder(handler)
    candidate = AtsCandidate(
        "workday",
        "evil",
        {
            "base_url": "https://evil.tld",
            "tenant_slug": "evil",
            "career_site_slug": "External",
        },
        "https://evil.tld/External",
    )
    async with recorder.client() as http:
        result = await probe_candidate(candidate, http)

    assert result.ok is False
    assert result.error is not None
    assert "evil.tld" in result.error
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_probe_propagates_the_upstream_error_text() -> None:
    """A failure is data: the underlying message survives, not just a bool."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="board not found")

    recorder = _Recorder(handler)
    candidate = AtsCandidate("greenhouse", "nope", {}, "https://boards.greenhouse.io/nope")
    async with recorder.client() as http:
        result = await probe_candidate(candidate, http)

    assert result.ok is False
    assert result.job_count == 0
    assert result.error is not None
    assert "404" in result.error


@pytest.mark.asyncio
async def test_probe_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ats_discovery, "_PROBE_TIMEOUT_S", 0.05)

    async def never(*args, **kwargs):
        await asyncio.sleep(5)
        return []

    monkeypatch.setattr(ats_discovery, "_count_jobs", never)

    recorder = _Recorder(lambda r: httpx.Response(200, json={"jobs": []}))
    candidate = AtsCandidate("greenhouse", "slow", {}, "https://boards.greenhouse.io/slow")
    async with recorder.client() as http:
        result = await probe_candidate(candidate, http)

    assert result.ok is False
    assert result.error is not None
    assert "timed out" in result.error


@pytest.mark.asyncio
async def test_probe_rejects_a_workday_payload_without_a_total() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobPostings": []})

    recorder = _Recorder(handler)
    candidate = AtsCandidate(
        "workday",
        "intel",
        {
            "base_url": "https://intel.wd1.myworkdayjobs.com",
            "tenant_slug": "intel",
            "career_site_slug": "External",
        },
        INTEL_WORKDAY,
    )
    async with recorder.client() as http:
        result = await probe_candidate(candidate, http)

    assert result.ok is False
    assert result.error is not None
    assert "total" in result.error
