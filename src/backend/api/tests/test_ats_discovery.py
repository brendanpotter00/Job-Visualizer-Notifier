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
import gzip
import socket
import time
from typing import AsyncIterator, Callable

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
from api.services.url_guard import REASON_CONTENT_ENCODING

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
async def test_sniff_finds_a_locale_prefixed_workday_board() -> None:
    """🔴 I4. ``/en-US/Cisco_Careers`` is as common on a careers page as the bare form.

    With the L2 pattern limited to one path segment the match stopped at
    ``.../en-US``, which the resolver then correctly strips as a locale prefix —
    leaving no career-site slug and resolving to ``None``. So L2 could not see the
    very shape it exists to find, even though ``test_ats_link_resolver`` already
    pins ``/en-US/BlueOrigin`` as real.
    """
    board = "https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=f'<a href="{board}">Search jobs</a>')

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://prefixed.example/careers", http)

    assert result.candidate is not None
    assert result.candidate.ats == "workday"
    assert result.candidate.provider_config == {
        "base_url": "https://cisco.wd5.myworkdayjobs.com",
        "tenant_slug": "cisco",
        "career_site_slug": "Cisco_Careers",
    }


@pytest.mark.asyncio
async def test_sniff_finds_an_embedded_greenhouse_board() -> None:
    """🔴 I3. The Greenhouse iframe form, which is what a careers page embeds.

    Before the fix this "succeeded" with ``board_token='embed'`` and stopped
    looking: ``sniff_embedded_ats`` returns at the first page yielding any
    candidate, and ``_rank`` could not help because ``embed`` was the only one. A
    row written from that would point at nothing.
    """
    body = (
        '<iframe src="https://boards.greenhouse.io/embed/job_board?for=acme">'
        "</iframe>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://embedder.example/careers", http)

    assert result.candidate is not None
    assert result.candidate.ats == "greenhouse"
    assert result.candidate.board_token == "acme"
    assert [c.board_token for c in result.runners_up] == []


@pytest.mark.asyncio
async def test_sniff_finds_a_greenhouse_api_host_reference() -> None:
    """Duolingo regression: the only ATS string on the page is the API host.

    careers.duolingo.com is a Greenhouse board that resolved to
    ``no_ats_detected``. Its served HTML is 3 KB and contains exactly one ATS
    reference — ``boards-api.greenhouse.io/v1/boards/duolingo/departments`` —
    with no ``boards.greenhouse.io`` link anywhere. A careers SPA on its own
    domain calls the API host directly, so this is the common shape, not an
    exotic one, and no browser or JS execution is needed to see it.
    """
    body = (
        '<script>window.__CONFIG__={"api":'
        '"https://boards-api.greenhouse.io/v1/boards/duolingo/departments"};'
        "</script>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://careers.duolingo.com", http)

    assert result.candidate is not None
    assert result.candidate.ats == "greenhouse"
    assert result.candidate.board_token == "duolingo"


@pytest.mark.asyncio
async def test_sniff_ignores_non_board_endpoints_on_the_greenhouse_api_host() -> None:
    """The ``/v1/boards/`` prefix is load-bearing, not decoration.

    Matching the API host alone would turn any other endpoint it serves into a
    board token — ``/v1/jobs`` would yield ``board_token='jobs'``, the same
    class of bug as the literal ``embed`` token above.
    """
    body = '<a href="https://boards-api.greenhouse.io/v1/jobs">all jobs</a>'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://nothing.example/careers", http)

    assert result.candidate is None


@pytest.mark.asyncio
async def test_sniff_never_returns_the_literal_embed_token() -> None:
    """A ``/embed/`` link with no ``?for=`` must be a miss, not a garbage token."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='<iframe src="https://boards.greenhouse.io/embed/job_board"></iframe>',
        )

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://embedder.example/careers", http)

    assert result.candidate is None
    assert result.reason == "no_ats_detected"


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


@pytest.mark.asyncio
async def test_a_stale_subpath_rejection_is_not_the_sniff_verdict() -> None:
    """🔴 M5. A page we read and found no board on is ``no_ats_detected``.

    The sub-paths are guesses we invented; a DNS/guard rejection on one of them is
    not a verdict about the site. Here sub-path 1 is refused by the guard (it
    redirects to a private host) and the other three are read fine and simply have
    no board — the answer must be ``no_ats_detected``, not the leftover
    ``scheme_not_https`` from the guess.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search-results"):
            return httpx.Response(302, headers={"location": "http://10.0.0.5/"})
        return httpx.Response(200, text="<html>a page, but no board</html>")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://x.example/careers", http)

    assert result.candidate is None
    assert result.reason == "no_ats_detected"


@pytest.mark.asyncio
async def test_a_sniff_that_never_read_anything_reports_the_real_reason() -> None:
    """The flip side of M5: with nothing read, the transport reason is the answer."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://10.0.0.5/"})

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://x.example/careers", http)

    assert result.candidate is None
    assert result.reason == "scheme_not_https"


# ----------------------------------------------------------------------------
# Compression, and the aggregate budget
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_requests_ask_for_an_identity_encoding() -> None:
    """🔴 C2. ``max_bytes`` counts DECODED bytes, so gzip walks straight past it.

    ``Response.aiter_bytes()`` decompresses each raw chunk before the guard's loop
    sees it. Measured with httpx's default ``Accept-Encoding: gzip, deflate``: a
    500 MiB gzip of zeros is 509,616 bytes on the wire, the 512 KiB cap is
    "honoured" — and the largest single decoded chunk allocated was 67,415,144
    bytes, ~128× the cap, up to 4 times per ``/resolve``.
    """
    recorder = _Recorder(lambda r: httpx.Response(200, text="<html>nothing</html>"))
    async with recorder.client() as http:
        await discover_ats("https://plain.example/careers", http)

    assert recorder.requests, "no request was issued"
    encodings = {r.headers.get("accept-encoding") for r in recorder.requests}
    assert encodings == {"identity"}, encodings


INTEL_CANDIDATE = AtsCandidate(
    "workday",
    "intel",
    {
        "base_url": "https://intel.wd1.myworkdayjobs.com",
        "tenant_slug": "intel",
        "career_site_slug": "External",
    },
    INTEL_WORKDAY,
)


@pytest.mark.asyncio
async def test_probe_requests_ask_for_an_identity_encoding() -> None:
    """Same reasoning for the two probes whose bodies this PR byte-caps (M7).

    Greenhouse/Ashby/Lever/Gem probes go through the existing ATS clients, which
    own their own headers and are out of scope here.
    """
    recorder = _Recorder(
        lambda r: httpx.Response(200, json={"total": 1, "jobPostings": [{"t": "x"}]})
    )
    async with recorder.client() as http:
        result = await probe_candidate(INTEL_CANDIDATE, http)

    assert result.ok is True
    assert recorder.requests[0].headers.get("accept-encoding") == "identity"


@pytest.mark.asyncio
async def test_an_oversized_probe_body_is_an_error_not_an_oom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 M7. The probe used to buffer whatever the ATS host sent, unbounded.

    Over the cap has to be an error rather than a truncation: truncated JSON is
    not JSON, and 'parse what fits' would report a fabricated job count.
    """
    monkeypatch.setattr(ats_discovery, "_PROBE_MAX_BYTES", 4096)
    pulled = 0

    async def firehose():
        nonlocal pulled
        for _ in range(100_000):
            pulled += 1
            yield b"x" * 1000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=firehose())

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await probe_candidate(INTEL_CANDIDATE, http)

    assert result.ok is False
    assert result.error is not None
    assert "exceeded" in result.error
    # And it stopped reading rather than draining the whole 100 MB on offer.
    assert pulled <= 10, pulled


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 500])
async def test_a_bounded_probe_still_reports_the_http_status(status: int) -> None:
    """``raise_for_status`` has to keep working now that the probe streams.

    Behaviour-preservation guard on the ``_bounded_json`` refactor: an HTTP error
    must still arrive as ``ok=False`` with the status in the message, not as a
    ``ResponseNotRead`` from calling ``raise_for_status`` on an unread stream.
    """
    recorder = _Recorder(lambda r: httpx.Response(status, text="nope"))
    async with recorder.client() as http:
        result = await probe_candidate(INTEL_CANDIDATE, http)

    assert result.ok is False
    assert result.error is not None
    assert str(status) in result.error


@pytest.mark.asyncio
async def test_an_expired_deadline_stops_discovery_before_any_request() -> None:
    """🔴 I2. One resolve is worth up to ~36 outbound requests without a deadline.

    L1's HEAD chain (5) + its GET retry (5) + 4 sniff targets × 5 hops, each with
    its own ``_DISCOVERY_TIMEOUT_S`` — the per-request timeout composes into
    minutes, and Vercel 504s the user long before the backend gives up.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request must be issued; got {request.url}")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await discover_ats(
            "https://slow.example/careers", http, deadline=time.monotonic() - 1.0
        )

    assert result.candidate is None
    assert result.reason == "deadline_exceeded"
    assert recorder.requests == []


@pytest.mark.asyncio
async def test_a_deadline_that_expires_mid_sniff_is_reported_as_such() -> None:
    """The sniff must not relabel an exhausted budget as 'this site has no board'."""
    started = time.monotonic()

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return httpx.Response(200, text="<html>nothing</html>")

    recorder = _Recorder(slow)
    async with recorder.client() as http:
        result = await sniff_embedded_ats(
            "https://slow.example/careers", http, deadline=started + 0.15
        )

    assert result.candidate is None
    assert result.reason == "deadline_exceeded"
    # Not all four sub-paths: the budget stopped the loop.
    assert len(recorder.requests) < 4


@pytest.mark.asyncio
async def test_probe_budget_is_clamped_to_the_remaining_deadline() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2.0)
        return httpx.Response(200, json={"jobs": []})

    recorder = _Recorder(slow)
    candidate = AtsCandidate("greenhouse", "acme", {}, "https://boards.greenhouse.io/acme")
    started = time.monotonic()
    async with recorder.client() as http:
        result = await probe_candidate(candidate, http, deadline=started + 0.1)

    assert result.ok is False
    assert result.error is not None
    assert "timed out" in result.error
    # The 12 s _PROBE_TIMEOUT_S must not have been used.
    assert time.monotonic() - started < 2.0


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


# ----------------------------------------------------------------------------
# A hostile origin that ignores Accept-Encoding
# ----------------------------------------------------------------------------

# 16 MiB of zeros, ~16 KB on the wire. Four orders of magnitude over the caps
# used below — the ratio is the point, not the size.
_BOMB_DECODED_BYTES = 16 * 1024 * 1024


def _gzip_bomb_body() -> tuple[Callable[[], AsyncIterator[bytes]], list[int]]:
    """A fresh streamed gzip bomb per request, plus a shared pull counter."""
    payload = gzip.compress(b"\0" * _BOMB_DECODED_BYTES, 9)
    pulls: list[int] = []

    def factory() -> AsyncIterator[bytes]:
        async def body() -> AsyncIterator[bytes]:
            for offset in range(0, len(payload), 16 * 1024):
                pulls.append(offset)
                yield payload[offset : offset + 16 * 1024]

        return body()

    return factory, pulls


@pytest.mark.asyncio
async def test_a_sniff_of_a_host_that_gzips_despite_identity_reads_nothing() -> None:
    """🔴 C1, end to end through the layer that actually runs 4 GETs.

    ``Accept-Encoding: identity`` is a request header. Measured against the real
    ``discover_ats`` before this fix: a 500 MiB gzip of zeros (509,616 bytes on
    the wire) took RSS from 46.9 MB to 181.8 MB for ONE ``/resolve`` worth of
    discovery, with a single decoded chunk of 67 MB. Nothing in the suite covered
    a server that ignores the header — which was the entire gap.
    """
    factory, pulls = _gzip_bomb_body()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("accept-encoding") == "identity"
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-type": "text/html"})
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=factory()
        )

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://hostile.example/careers", http)

    assert result.candidate is None
    assert result.reason == REASON_CONTENT_ENCODING
    assert pulls == [], f"decoded {len(pulls)} chunks of the bomb before refusing"


@pytest.mark.asyncio
async def test_discover_ats_refuses_a_gzip_bomb_rather_than_decoding_it() -> None:
    """The same thing through the full ladder — the shape the RSS was measured on.

    ``discover_ats`` deliberately collapses a sniff's per-sub-path reason to
    ``no_ats_detected`` (only ``deadline_exceeded`` survives), so the assertion
    here is the one that matters end to end: not one byte of the bomb was read
    across all four sniff targets.
    """
    factory, pulls = _gzip_bomb_body()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-type": "text/html"})
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=factory()
        )

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await discover_ats("https://hostile.example/careers", http)

    assert result.candidate is None
    assert pulls == []


@pytest.mark.asyncio
async def test_a_gzip_bomb_on_the_L1_get_fallback_keeps_its_reason() -> None:
    """When L1 is what hits it, the reason is not collapsed and L2 never runs."""
    factory, pulls = _gzip_bomb_body()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(405)
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=factory()
        )

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await discover_ats("https://hostile.example/careers", http)

    assert result.candidate is None
    assert result.reason == REASON_CONTENT_ENCODING
    assert pulls == []


@pytest.mark.asyncio
async def test_a_probe_host_that_gzips_despite_identity_reads_nothing() -> None:
    """🔴 C1 + I3 on the probe path.

    ``_bounded_json`` did ``body.extend(chunk)`` and *then* compared against the
    4 MiB cap, so the bytearray was 67,200,488 bytes long at the moment the cap
    fired. Now the encoding is refused on the response header and the body is
    never pulled.
    """
    factory, pulls = _gzip_bomb_body()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=factory()
        )

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await probe_candidate(INTEL_CANDIDATE, http)

    assert result.ok is False
    assert result.error is not None
    assert "Content-Encoding" in result.error
    assert pulls == []


# ----------------------------------------------------------------------------
# probe_candidate must never raise
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        # 🔴 C2. ``httpx.InvalidURL`` subclasses ``Exception``, not
        # ``httpx.HTTPError``, so it escaped the except tuple as an HTTP 500 with
        # no reason code and no audit row. ``ats_link_resolver`` now rejects these
        # shapes too, but ``probe_candidate`` is also called by PR 3 on values read
        # back out of the database, by code that never saw the URL they came from.
        AtsCandidate("greenhouse", "\x00x", {}, "https://boards.greenhouse.io/x"),
        AtsCandidate("lever", "\x00x", {}, "https://jobs.lever.co/x"),
        AtsCandidate("ashby", "a\x7fb", {}, "https://jobs.ashbyhq.com/x"),
        AtsCandidate(
            "workday",
            "acme",
            {
                "base_url": "https://acme.wd1.myworkdayjobs.com",
                "tenant_slug": "acme",
                "career_site_slug": "\x00x",
            },
            "https://acme.wd1.myworkdayjobs.com/x",
        ),
    ],
)
@pytest.mark.asyncio
async def test_probe_never_raises_on_a_token_httpx_refuses(
    candidate: AtsCandidate,
) -> None:
    """🔴 C2. "Never raises" is the contract; it was not true."""
    recorder = _Recorder(lambda r: httpx.Response(200, json={"jobs": []}))
    async with recorder.client() as http:
        result = await probe_candidate(candidate, http)

    assert result.ok is False
    assert result.error


# ----------------------------------------------------------------------------
# The last unguarded urlsplit
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unparseable_landing_url_is_a_reason_not_a_500() -> None:
    """``_sniff_urls`` used a bare ``urlsplit``, which raises on ``https://a]b/``."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request must be issued; got {request.url}")

    recorder = _Recorder(handler)
    async with recorder.client() as http:
        result = await sniff_embedded_ats("https://a]b.com/careers", http)

    assert result.candidate is None
    assert result.reason == "invalid_hostname"
    assert recorder.requests == []
