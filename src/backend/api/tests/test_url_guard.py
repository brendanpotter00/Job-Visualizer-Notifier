"""Unit tests for the SSRF boundary.

Two guarantees are load-bearing and each has a dedicated test:

1. A rejected URL is rejected **before any socket is opened**. Every case in
   the rejection table is replayed through ``guarded_get`` with an
   ``httpx.MockTransport`` whose handler raises — if the guard ever ran after
   the request, the handler would fire and the test would fail.
2. A redirect chain cannot launder a private host. The hop is validated before
   *its* request goes out, so a 302 to ``169.254.169.254`` costs exactly one
   transport call and never reaches the metadata service.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import socket
import threading
import time
import tracemalloc
import zlib
from typing import AsyncIterator

import httpx
import pytest

from api.services import url_guard
from api.services.url_guard import (
    REASON_ATS_HOST,
    REASON_CONTENT_ENCODING,
    REASON_CROSS_HOST,
    REASON_DEADLINE,
    REASON_DNS,
    REASON_FETCH_FAILED,
    REASON_HOSTNAME,
    REASON_PORT,
    REASON_PRIVATE_ADDRESS,
    REASON_SCHEME,
    REASON_TOO_MANY_HOPS,
    REASON_USERINFO,
    UrlGuardError,
    assert_ats_api_host,
    guarded_get,
    normalize_public_url,
    validate_public_url,
)


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _addrinfo(*ips: str) -> list[tuple]:
    """Build a getaddrinfo-shaped result for the given addresses."""
    out = []
    for ip in ips:
        if ":" in ip:
            out.append(
                (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443, 0, 0))
            )
        else:
            out.append(
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))
            )
    return out


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch):
    """Resolve every hostname to a public address, deterministically."""

    def fake(host, port, *args, **kwargs):
        return _addrinfo("93.184.216.34")

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return fake


@pytest.fixture
def exploding_dns(monkeypatch: pytest.MonkeyPatch):
    """Any DNS lookup at all is a test failure."""

    def fake(*args, **kwargs):
        raise AssertionError("getaddrinfo must not be reached for this input")

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    return fake


class _CountingTransport:
    """A MockTransport wrapper that records how many requests were issued."""

    def __init__(self, handler):
        self.calls: list[httpx.Request] = []
        self._handler = handler

    def transport(self) -> httpx.MockTransport:
        def wrapped(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            return self._handler(request)

        return httpx.MockTransport(wrapped)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport())


def _exploding_client() -> tuple[_CountingTransport, httpx.AsyncClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request must be issued; got {request.url}")

    counter = _CountingTransport(handler)
    return counter, counter.client()


# ----------------------------------------------------------------------------
# The nine-case rejection table
# ----------------------------------------------------------------------------

# PLAN §1.6. Case 2 is listed there as "scheme_not_https (and invalid_hostname)":
# the checks run in a fixed order, so scheme wins and the reason is deterministic.
REJECTION_TABLE: list[tuple[str, str]] = [
    ("http://169.254.169.254/latest/meta-data/", REASON_SCHEME),
    ("http://localhost:8000/api/admin/users", REASON_SCHEME),
    ("https://127.0.0.1/", REASON_HOSTNAME),
    ("https://[::1]/", REASON_HOSTNAME),
    ("http://10.0.0.5/", REASON_SCHEME),
    ("https://user:pass@evil.tld/", REASON_USERINFO),
    ("https://boards.greenhouse.io:8080/acme", REASON_PORT),
    ("file:///etc/passwd", REASON_SCHEME),
]


@pytest.mark.parametrize("url,expected_reason", REJECTION_TABLE)
def test_rejected_before_dns(url: str, expected_reason: str, exploding_dns) -> None:
    """Cases 1-8 are decided from the URL text alone — DNS is never consulted."""
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url(url)
    assert exc.value.reason == expected_reason


def test_private_dns_answer_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 9: a public-looking hostname that resolves into RFC1918 space."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: _addrinfo("10.0.0.5")
    )
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://evil.example/")
    assert exc.value.reason == REASON_PRIVATE_ADDRESS


@pytest.mark.asyncio
@pytest.mark.parametrize("url,expected_reason", REJECTION_TABLE)
async def test_table_issues_zero_outbound_requests(
    url: str, expected_reason: str, exploding_dns
) -> None:
    """Every rejected URL costs zero requests when routed through guarded_get."""
    counter, client = _exploding_client()
    async with client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get(url, client)
    assert exc.value.reason == expected_reason
    assert counter.calls == []


@pytest.mark.asyncio
async def test_private_dns_answer_issues_zero_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo("10.0.0.5"))
    counter, client = _exploding_client()
    async with client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get("https://evil.example/", client)
    assert exc.value.reason == REASON_PRIVATE_ADDRESS
    assert counter.calls == []


# ----------------------------------------------------------------------------
# DNS answer handling
# ----------------------------------------------------------------------------


def test_mixed_dns_answers_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """One public and one private A record still fails: the kernel picks, not us."""
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: _addrinfo("93.184.216.34", "10.0.0.5")
    )
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://split-horizon.example/")
    assert exc.value.reason == REASON_PRIVATE_ADDRESS
    assert "10.0.0.5" in str(exc.value)


def test_ipv4_mapped_ipv6_answer_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: _addrinfo("::ffff:10.0.0.5")
    )
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://mapped.example/")
    assert exc.value.reason == REASON_PRIVATE_ADDRESS


@pytest.mark.parametrize(
    "address",
    ["169.254.169.254", "127.0.0.1", "0.0.0.0", "192.168.1.1", "172.16.0.1", "::1", "fd00::1"],
)
def test_every_private_range_rejected(
    address: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(address))
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://sneaky.example/")
    assert exc.value.reason == REASON_PRIVATE_ADDRESS


def test_dns_failure_has_its_own_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://nx.example/")
    assert exc.value.reason == REASON_DNS


def test_empty_dns_answer_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://void.example/")
    assert exc.value.reason == REASON_DNS


# ----------------------------------------------------------------------------
# Hostname normalization
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host", ["localhost", "db.localhost", "printer.local", "metadata.internal"]
)
def test_reserved_suffixes_rejected(host: str, exploding_dns) -> None:
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url(f"https://{host}/")
    assert exc.value.reason == REASON_HOSTNAME


def test_unicode_homoglyph_is_idna_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Cyrillic-'a' lookalike is punycoded before anything compares it."""
    seen: list[str] = []

    def fake(host, port, *args, **kwargs):
        seen.append(host)
        return _addrinfo("93.184.216.34")

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    guarded = validate_public_url("https://exаmple.com/careers")
    assert guarded.host.startswith("xn--")
    assert seen == [guarded.host]


def test_normalized_url_drops_fragment_and_default_port(public_dns) -> None:
    guarded = validate_public_url("https://Jobs.Example.com:443/careers?a=1#frag")
    assert guarded.url == "https://jobs.example.com/careers?a=1"
    assert guarded.host == "jobs.example.com"
    assert guarded.resolved_ips == ("93.184.216.34",)


def test_overlong_hostname_rejected(exploding_dns) -> None:
    host = ".".join(["a" * 50] * 6)  # 305 chars
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url(f"https://{host}/")
    assert exc.value.reason == REASON_HOSTNAME


def test_host_shaped_userinfo_rejected(exploding_dns) -> None:
    """``https://boards.greenhouse.io@evil.tld/`` fetches evil.tld, not greenhouse."""
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://boards.greenhouse.io@evil.tld/")
    assert exc.value.reason == REASON_USERINFO


# ----------------------------------------------------------------------------
# Malformed input must be a rejection, never an exception
# ----------------------------------------------------------------------------

# Every one of these produced an uncaught exception → HTTP 500 with no reason
# code and (in PR 3) no audit row. All are reachable straight from the request
# body of ``POST /api/companies/resolve``.
MALFORMED_URLS = [
    # ``urlsplit`` itself raises ValueError("Invalid IPv6 URL") on an unbalanced
    # bracket — the parse, not just the .hostname access, has to be guarded.
    "https://a]b.com/",
    "https://[oops/",
    # A bogus Punycode A-label. The stdlib ``"idna"`` codec passes any ASCII label
    # through untouched (``"xn--a.com".encode("idna")`` == b"xn--a.com"), so the
    # guard used to APPROVE these — and then httpx, which builds its request host
    # with the ``idna`` *package*, raised ``idna.IDNAError``. That subclasses
    # UnicodeError/ValueError but NOT httpx.HTTPError, so it slipped every except
    # clause on the path.
    "https://xn--a.com/careers",
    "https://xn--0.com/",
    "https://xn--.com/",
]


@pytest.mark.parametrize("url", MALFORMED_URLS)
def test_malformed_url_is_a_rejection_not_an_exception(
    url: str, exploding_dns
) -> None:
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url(url)
    assert exc.value.reason == REASON_HOSTNAME


@pytest.mark.asyncio
@pytest.mark.parametrize("url", MALFORMED_URLS)
async def test_malformed_url_issues_zero_requests(url: str, exploding_dns) -> None:
    counter, client = _exploding_client()
    async with client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get(url, client)
    assert exc.value.reason == REASON_HOSTNAME
    assert counter.calls == []


@pytest.mark.asyncio
async def test_a_remote_location_header_cannot_500_us(public_dns) -> None:
    """A remote site answering ``Location: https://xn--a.com/`` was a free 500.

    httpx builds a redirect request from any 3xx even with
    ``follow_redirects=False``, and doing so touches ``URL.host`` →
    ``idna.decode`` → ``IDNAError``. That fired from inside our own
    ``http.stream(...)`` call, past ``except httpx.HTTPError``, so any third-party
    host in a chain could crash this endpoint on demand.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://xn--a.com/"})

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get("https://ok.example/", client)

    assert exc.value.reason == REASON_FETCH_FAILED
    assert exc.value.hops == ("https://ok.example/",)
    assert len(counter.calls) == 1


def test_trailing_dot_fqdn_hits_the_reserved_name_check(exploding_dns) -> None:
    """``localhost.`` is a legal FQDN spelling of ``localhost``.

    Without the dot strip it sails past the reserved-name check and the verdict
    comes from whatever DNS answers — in practice 127.0.0.1, i.e. the misleading
    ``resolves_to_private_address`` instead of ``invalid_hostname``, and only if
    the resolver happens to cooperate. ``exploding_dns`` here is the assertion
    that we never get that far.
    """
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://localhost./")
    assert exc.value.reason == REASON_HOSTNAME
    assert "localhost" in str(exc.value)


@pytest.mark.parametrize(
    "address,label",
    [
        ("100.64.1.1", "RFC 6598 CGNAT"),
        ("100.127.255.254", "RFC 6598 CGNAT, top of range"),
        ("192.88.99.1", "RFC 3068 6to4 relay anycast"),
    ],
)
def test_cgnat_and_6to4_are_not_public(
    address: str, label: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither is caught by the is_private/is_reserved/… flag union.

    Measured on Python 3.13.3: ``100.64.1.1`` has every one of those flags False
    (``is_global`` is False — which is why ``is_global`` is now the primary
    predicate), and ``192.88.99.1`` has ``is_global`` **True**, which is why
    ``_DENY_NETWORKS`` still has to name it explicitly.
    """
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(address))
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://carrier-nat.example/")
    assert exc.value.reason == REASON_PRIVATE_ADDRESS, label


# ----------------------------------------------------------------------------
# assert_ats_api_host
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ats,url",
    [
        ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/acme/jobs"),
        ("ashby", "https://api.ashbyhq.com/posting-api/job-board/acme"),
        ("lever", "https://api.lever.co/v0/postings/acme"),
        ("gem", "https://api.gem.com/job_board/v0/acme/job_posts/"),
        ("workday", "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs"),
        ("eightfold", "https://explore.jobs.netflix.net/api/apply/v2/jobs"),
        ("eightfold", "https://acme.eightfold.ai/api/apply/v2/jobs"),
    ],
)
def test_allowed_ats_api_hosts(ats: str, url: str) -> None:
    assert_ats_api_host(ats, url) is None


@pytest.mark.parametrize(
    "ats,url",
    [
        ("greenhouse", "https://evil.tld/v1/boards/acme"),
        ("greenhouse", "https://boards.greenhouse.io/acme"),  # public board, not the API
        ("ashby", "https://jobs.ashbyhq.com/acme"),
        ("lever", "https://api.lever.co.evil.tld/v0/postings/acme"),
        ("gem", "https://api.gem.com.evil.tld/"),
        ("workday", "https://evil.tld/wday/cxs/intel/External/jobs"),
        ("workday", "https://intel.wd1.myworkdayjobs.com.evil.tld/wday/cxs/x/y/jobs"),
        ("eightfold", "https://evil.tld/api/apply/v2/jobs"),
        ("eightfold", "https://eightfold.ai.evil.tld/api/apply/v2/jobs"),
    ],
)
def test_rejected_ats_api_hosts(ats: str, url: str) -> None:
    with pytest.raises(UrlGuardError) as exc:
        assert_ats_api_host(ats, url)
    assert exc.value.reason == REASON_ATS_HOST


def test_unknown_ats_rejected() -> None:
    with pytest.raises(UrlGuardError) as exc:
        assert_ats_api_host("phenom", "https://careers.cisco.com/widgets")
    assert exc.value.reason == REASON_ATS_HOST


def test_ats_api_host_requires_https() -> None:
    with pytest.raises(UrlGuardError) as exc:
        assert_ats_api_host("greenhouse", "http://boards-api.greenhouse.io/v1/boards/a")
    assert exc.value.reason == REASON_SCHEME


# ----------------------------------------------------------------------------
# guarded_get — the redirect loop
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redirect_hop_to_metadata_service_rejected_at_the_hop(
    public_dns,
) -> None:
    """The single most important test in this file.

    ``https://ok.example`` 302s to the EC2 metadata service. The guard must
    reject at the hop, and the transport must have been called exactly once —
    proving we never issued the request to 169.254.169.254.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get("https://ok.example/", client)

    assert exc.value.reason == REASON_SCHEME
    assert len(counter.calls) == 1
    assert str(counter.calls[0].url) == "https://ok.example/"
    assert exc.value.hops == ("https://ok.example/",)


@pytest.mark.asyncio
async def test_redirect_chain_is_returned_in_order(public_dns) -> None:
    chain = {
        "https://a.example/": "https://b.example/two",
        "https://b.example/two": "https://c.example/three",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        target = chain.get(str(request.url))
        if target:
            return httpx.Response(301, headers={"location": target})
        return httpx.Response(200, text="done")

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        response, hops = await guarded_get("https://a.example/", client)

    assert response.status_code == 200
    assert hops == (
        "https://a.example/",
        "https://b.example/two",
        "https://c.example/three",
    )


def _redirect_loop_handler(request: httpx.Request) -> httpx.Response:
    n = int(request.url.path.strip("/") or 0)
    return httpx.Response(302, headers={"location": f"https://loop.example/{n + 1}"})


@pytest.mark.asyncio
async def test_too_many_hops(public_dns) -> None:
    """``max_hops`` counts REQUESTS, which is also len(the returned hop tuple).

    It previously meant "redirects followed", so ``max_hops=5`` issued 6 requests
    and returned 6 hops — one more than the PLAN's "max 5 hops" cap, and a bound
    that could not be checked against the value the function hands back. One
    meaning, and this is the test that pins it.
    """
    counter = _CountingTransport(_redirect_loop_handler)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get("https://loop.example/0", client, max_hops=3)

    assert exc.value.reason == REASON_TOO_MANY_HOPS
    assert len(counter.calls) == 3
    assert len(exc.value.hops) == 3


@pytest.mark.asyncio
async def test_max_hops_one_fetches_once_and_follows_nothing(public_dns) -> None:
    counter = _CountingTransport(_redirect_loop_handler)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get("https://loop.example/0", client, max_hops=1)

    assert exc.value.reason == REASON_TOO_MANY_HOPS
    assert len(counter.calls) == 1


@pytest.mark.asyncio
async def test_max_hops_below_one_is_a_programming_error(public_dns) -> None:
    counter, client = _exploding_client()
    async with client:
        with pytest.raises(ValueError, match="max_hops"):
            await guarded_get("https://ok.example/", client, max_hops=0)
    assert counter.calls == []


# ----------------------------------------------------------------------------
# The event loop, and the aggregate budget
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dns_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``getaddrinfo`` is sync and must not run on the loop thread.

    Per src/backend/CLAUDE.md the Procrastinate worker shares this process, so a
    slow-resolving user-supplied host would otherwise freeze every in-flight ATS
    fetch task for the duration of the lookup. Before ``asyncio.to_thread`` the
    ticker below counted 0 ticks across a 1.0 s lookup.
    """

    def slow(host, port, *args, **kwargs):
        time.sleep(0.30)
        return _addrinfo("93.184.216.34")

    monkeypatch.setattr(socket, "getaddrinfo", slow)

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    counter = _CountingTransport(lambda r: httpx.Response(200, text="ok"))
    async with counter.client() as client:
        task = asyncio.create_task(ticker())
        await asyncio.sleep(0.02)
        await guarded_get("https://slow-dns.example/", client)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert ticks >= 5, f"the loop was blocked during the DNS lookup (ticks={ticks})"


@pytest.mark.asyncio
async def test_an_expired_deadline_issues_zero_requests(public_dns) -> None:
    counter, client = _exploding_client()
    async with client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get(
                "https://ok.example/", client, deadline=time.monotonic() - 1.0
            )
    assert exc.value.reason == REASON_DEADLINE
    assert counter.calls == []


@pytest.mark.asyncio
async def test_deadline_stops_a_slow_chain_well_before_max_hops(public_dns) -> None:
    """Per-request timeouts do not compose; only the deadline bounds the total.

    50 hops × a 5 s per-request timeout is over four minutes of outbound requests
    from one call. With a 0.3 s deadline the chain stops after a handful.
    """

    async def slow_redirect(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return _redirect_loop_handler(request)

    counter = _CountingTransport(slow_redirect)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get(
                "https://loop.example/0",
                client,
                max_hops=50,
                timeout=5.0,
                deadline=time.monotonic() + 0.30,
            )

    assert exc.value.reason == REASON_DEADLINE
    assert 1 <= len(counter.calls) <= 20, len(counter.calls)


@pytest.mark.asyncio
async def test_deadline_clamps_the_per_request_timeout(
    public_dns, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hop's own timeout is narrowed to whatever budget is left.

    Otherwise the last hop of an almost-exhausted call could still hold the
    connection open for the full per-request ``timeout``, which is how a 30 s
    ``timeout`` sails past a 25 s overall budget. Asserted on the value handed to
    ``http.stream`` because ``MockTransport`` does not enforce timeouts at all.
    """
    seen: list[float] = []
    counter = _CountingTransport(lambda r: httpx.Response(200, text="ok"))

    async with counter.client() as client:
        original = client.stream

        def spy(method, url, **kwargs):
            seen.append(kwargs["timeout"])
            return original(method, url, **kwargs)

        monkeypatch.setattr(client, "stream", spy)
        await guarded_get(
            "https://ok.example/",
            client,
            timeout=30.0,
            deadline=time.monotonic() + 0.5,
        )

    assert seen, "http.stream was never called"
    assert seen[0] <= 0.5, f"per-request timeout was not clamped: {seen[0]}"


@pytest.mark.asyncio
async def test_without_a_deadline_the_timeout_is_passed_through(public_dns, monkeypatch) -> None:
    """No deadline means no clamp — PR 2/PR 3 callers keep the old behaviour."""
    seen: list[float] = []
    counter = _CountingTransport(lambda r: httpx.Response(200, text="ok"))

    async with counter.client() as client:
        original = client.stream

        def spy(method, url, **kwargs):
            seen.append(kwargs["timeout"])
            return original(method, url, **kwargs)

        monkeypatch.setattr(client, "stream", spy)
        await guarded_get("https://ok.example/", client, timeout=7.5)

    assert seen == [7.5]


@pytest.mark.asyncio
async def test_cross_host_redirect_blocked_when_disallowed(public_dns) -> None:
    """Scrape-phase policy: a host change is drift we must see, not absorb."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "start.example":
            return httpx.Response(302, headers={"location": "https://other.example/"})
        return httpx.Response(200, text="ok")

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get(
                "https://start.example/", client, allow_cross_host=False
            )

    assert exc.value.reason == REASON_CROSS_HOST
    assert len(counter.calls) == 1


@pytest.mark.asyncio
async def test_same_host_redirect_allowed_when_cross_host_disallowed(
    public_dns,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(302, headers={"location": "/landing"})
        return httpx.Response(200, text="ok")

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        response, hops = await guarded_get(
            "https://start.example/", client, allow_cross_host=False
        )

    assert response.status_code == 200
    assert hops == ("https://start.example/", "https://start.example/landing")


@pytest.mark.asyncio
async def test_body_is_truncated_at_max_bytes(public_dns) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 5000)

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        response, _ = await guarded_get("https://big.example/", client, max_bytes=1000)

    assert len(response.content) == 1000
    # The truncated body must not carry a Content-Length claiming the original size.
    assert response.headers.get("content-length") in (None, "1000")


@pytest.mark.asyncio
async def test_the_stream_is_abandoned_at_the_cap_not_drained(public_dns) -> None:
    """The cap has to stop the *reading*, not trim an already-buffered body.

    A ``content=b"..."`` response proves truncation but says nothing about
    streaming, because the bytes were already materialised before the loop ran.
    Here the body is a generator that counts how many chunks were actually pulled:
    100 MB is on offer and the loop must walk away after ~1 KB.
    """
    pulled = 0

    async def body() -> AsyncIterator[bytes]:
        nonlocal pulled
        for _ in range(100_000):
            pulled += 1
            yield b"x" * 1000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body())

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        response, _ = await guarded_get("https://firehose.example/", client, max_bytes=1000)

    assert len(response.content) == 1000
    assert pulled <= 2, f"kept reading past the cap ({pulled} chunks pulled)"


@pytest.mark.asyncio
async def test_head_method_is_honoured(public_dns) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="")

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        await guarded_get("https://head.example/", client, method="HEAD")

    assert counter.calls[0].method == "HEAD"


@pytest.mark.asyncio
async def test_transport_failure_becomes_a_guard_error(public_dns) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get("https://down.example/", client)

    assert exc.value.reason == "fetch_failed"
    assert exc.value.hops == ("https://down.example/",)


@pytest.mark.asyncio
async def test_redirect_without_location_is_terminal(public_dns) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        response, hops = await guarded_get("https://dead.example/", client)

    assert response.status_code == 302
    assert hops == ("https://dead.example/",)
    assert len(counter.calls) == 1


# ----------------------------------------------------------------------------
# The address predicate — the six-flag union is NOT redundant with is_global
# ----------------------------------------------------------------------------

# Every address that a `not ip.is_global`-only predicate approves and the
# PLAN §1.2 six-flag union rejects. Enumerated by sweeping one representative
# address per IPv4 /8 plus a wide IPv6 sample: 52 hits, 49 distinct, and **zero**
# addresses in the other direction. `_is_public_address` therefore runs both, and
# `_DENY_NETWORKS` behind them; this table is the guard against a third attempt
# at "``is_global`` subsumes the flags".
_IPV4_MULTICAST = [f"{octet}.0.0.1" for octet in range(224, 240)] + [
    f"{octet}.255.255.254" for octet in range(224, 240)
]
IS_GLOBAL_ONLY_HOLES: list[str] = sorted(
    {
        *_IPV4_MULTICAST,
        "224.0.0.251",          # mDNS
        "239.255.255.250",      # SSDP
        "233.1.2.3",
        "::127.0.0.1",          # RFC 4291 IPv4-compatible loopback
        "::169.254.169.254",    # ...and the metadata service
        "::10.0.0.1",
        "::ffff:0:127.0.0.1",           # RFC 2765 IPv4-translated
        "::ffff:0:169.254.169.254",
        "64:ff9b::127.0.0.1",           # RFC 6052 NAT64
        "64:ff9b::a9fe:a9fe",
        "5f00::1",
        "0200::1",
        "ff01::1",
        "ff02::1",
        "ff02::fb",
        "ff05::1",
        "ff0e::1",
    }
)


def test_the_is_global_hole_table_is_the_measured_one() -> None:
    """Pin the table's size so a silent edit cannot shrink the coverage."""
    assert len(IS_GLOBAL_ONLY_HOLES) == 49


@pytest.mark.parametrize("address", IS_GLOBAL_ONLY_HOLES)
def test_is_global_only_holes_are_rejected(
    address: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Each of these has ``is_global=True`` and is still not somewhere we go."""
    import ipaddress

    assert ipaddress.ip_address(address).is_global, (
        f"{address} no longer belongs in this table"
    )
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(address))
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://looks-fine.example/")
    assert exc.value.reason == REASON_PRIVATE_ADDRESS


@pytest.mark.parametrize(
    "address",
    [
        "100.64.1.1",      # RFC 6598 CGNAT — every flag False, is_global False
        "192.88.99.1",     # RFC 3068 6to4 relay — every flag False, is_global TRUE
    ],
)
def test_the_deny_table_still_catches_what_the_flags_miss(
    address: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction: restoring the flag union must not drop these two."""
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(address))
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url("https://looks-fine.example/")
    assert exc.value.reason == REASON_PRIVATE_ADDRESS


# ----------------------------------------------------------------------------
# IP literals hidden behind IDNA normalization
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostname,normalizes_to",
    [
        ("⑧.⑧.⑧.⑧", "8.8.8.8"),
        ("①②⑦.0.0.1", "127.0.0.1"),
        ("①⑥⑨.254.169.254", "169.254.169.254"),
    ],
)
def test_a_unicode_spelled_ip_literal_is_still_an_ip_literal(
    hostname: str, normalizes_to: str, public_dns
) -> None:
    """🔴 The literal ban ran on the RAW hostname; IDNA's NFKC mapping ran after.

    ``https://⑧.⑧.⑧.⑧/`` was therefore approved and fetched as ``8.8.8.8`` — and
    with the multicast hole above, ``https://②②④.0.0.1/`` reached multicast.
    """
    # Sanity: the normalization really does produce an address.
    assert hostname.encode("idna").decode("ascii") == normalizes_to
    with pytest.raises(UrlGuardError) as exc:
        validate_public_url(f"https://{hostname}/")
    assert exc.value.reason == REASON_HOSTNAME
    assert "IP literals" in str(exc.value)


# ----------------------------------------------------------------------------
# assert_ats_api_host — port and userinfo
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected_reason",
    [
        # The hostname of this URL IS the allowlisted host; the fetch is not.
        ("https://evil.tld@boards-api.greenhouse.io/v1/boards/acme/jobs", REASON_USERINFO),
        ("https://u:p@boards-api.greenhouse.io/v1/boards/acme/jobs", REASON_USERINFO),
        ("https://boards-api.greenhouse.io:22/v1/boards/acme/jobs", REASON_PORT),
        ("https://boards-api.greenhouse.io:8080/v1/boards/acme/jobs", REASON_PORT),
    ],
)
def test_ats_host_assertion_checks_port_and_userinfo(
    url: str, expected_reason: str
) -> None:
    """🔴 Host-only was not enough for the boundary PR 2/PR 3 are told to reuse."""
    with pytest.raises(UrlGuardError) as exc:
        assert_ats_api_host("greenhouse", url)
    assert exc.value.reason == expected_reason


def test_ats_host_assertion_still_accepts_the_real_probe_url() -> None:
    assert_ats_api_host(
        "greenhouse", "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    )
    assert_ats_api_host("greenhouse", "https://boards-api.greenhouse.io:443/x")


# ----------------------------------------------------------------------------
# Response-side compression — Accept-Encoding never enforced anything
# ----------------------------------------------------------------------------

# 16 MiB of zeros: ~16 KB on the wire, four orders of magnitude over any cap
# used here. The point is the ratio, not the absolute size.
_BOMB_DECODED_BYTES = 16 * 1024 * 1024


def _gzip_bomb_stream(chunk_size: int = 16 * 1024) -> tuple[AsyncIterator[bytes], list[int]]:
    """A streamed gzip bomb plus a mutable counter of how many chunks were pulled."""
    payload = gzip.compress(b"\0" * _BOMB_DECODED_BYTES, 9)
    pulls: list[int] = []

    async def body() -> AsyncIterator[bytes]:
        for offset in range(0, len(payload), chunk_size):
            pulls.append(offset)
            yield payload[offset : offset + chunk_size]

    return body(), pulls


@pytest.mark.asyncio
async def test_a_server_that_ignores_identity_and_gzips_anyway_is_refused(
    public_dns,
) -> None:
    """🔴 C1. ``Accept-Encoding: identity`` is a *request* header and enforces nothing.

    A hostile origin answers ``Content-Encoding: gzip`` regardless and httpx
    decodes on the response header, so the "decoded bytes" cap was measured
    handing the loop a single 67 MB chunk from a 509 KB wire body — RSS 47 MB →
    181 MB for one ``/resolve`` worth of discovery. The response is now refused
    on its headers, before a single body byte is pulled.
    """
    stream, pulls = _gzip_bomb_stream()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("accept-encoding") == "identity"
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=stream
        )

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get(
                "https://hostile.example/",
                client,
                max_bytes=1024,
                headers={"Accept-Encoding": "identity"},
            )

    assert exc.value.reason == REASON_CONTENT_ENCODING
    assert exc.value.hops == ("https://hostile.example/",)
    assert pulls == [], f"body bytes were read before the refusal: {len(pulls)} chunks"


@pytest.mark.asyncio
async def test_the_cap_still_holds_when_compression_is_deliberately_allowed(
    public_dns,
) -> None:
    """🔴 C1, layer two. The bound must not depend on the header check being there.

    ``allow_compressed=True`` is the relaxation PR 2's recipe runtime would want.
    With it, we decompress ourselves through ``decompressobj(max_length=…)``, so
    16 MiB of decoded zeros still costs at most ``max_bytes`` — and we stop
    pulling raw chunks too.
    """
    stream, pulls = _gzip_bomb_stream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=stream
        )

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        response, _ = await guarded_get(
            "https://hostile.example/",
            client,
            max_bytes=1024,
            allow_compressed=True,
        )

    assert len(response.content) == 1024
    assert response.content == b"\0" * 1024
    assert len(pulls) <= 2, f"kept pulling raw chunks past the cap: {len(pulls)}"


@pytest.mark.asyncio
async def test_a_bounded_decompression_never_materialises_the_whole_body(
    public_dns,
) -> None:
    """🔴 C1, layer two, measured rather than asserted.

    The distinction the reviewer's finding turns on is invisible to a
    length check: ``aiter_bytes()`` reaches the same 1 KiB answer *after*
    allocating the entire decoded body, because httpx's decoder hands the loop
    an already-materialised chunk. ``decompressobj(max_length=…)`` over
    ``aiter_raw()`` never allocates it in the first place. Peak traced
    allocation is the only thing that tells the two apart — which is exactly the
    RSS measurement (47 MB → 181 MB) that opened the finding.
    """
    stream, _ = _gzip_bomb_stream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-encoding": "gzip"}, content=stream
        )

    counter = _CountingTransport(handler)
    tracemalloc.start()
    try:
        async with counter.client() as client:
            response, _ = await guarded_get(
                "https://hostile.example/",
                client,
                max_bytes=1024,
                allow_compressed=True,
            )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert len(response.content) == 1024
    # A quarter of the decoded size is a 4× margin over the "it decoded the lot"
    # outcome and ~40× over what the bounded path actually costs.
    assert peak < _BOMB_DECODED_BYTES // 4, (
        f"peaked at {peak:,} bytes to keep 1 KiB of a "
        f"{_BOMB_DECODED_BYTES:,}-byte body"
    )


@pytest.mark.asyncio
async def test_an_encoding_we_cannot_bound_is_refused_even_when_allowed(
    public_dns,
) -> None:
    """``br``/``zstd`` have no bounded decoder here, so they are a refusal, not a guess."""

    async def body() -> AsyncIterator[bytes]:
        yield b"\x00"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-encoding": "br"}, content=body())

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get("https://brotli.example/", client, allow_compressed=True)

    assert exc.value.reason == REASON_CONTENT_ENCODING


@pytest.mark.asyncio
async def test_an_identity_response_is_read_normally(public_dns) -> None:
    """The common case: no Content-Encoding header at all is not a rejection."""
    counter = _CountingTransport(
        lambda r: httpx.Response(200, headers={"content-encoding": "identity"}, text="ok")
    )
    async with counter.client() as client:
        response, _ = await guarded_get("https://plain.example/", client)

    assert response.status_code == 200
    assert response.text == "ok"


@pytest.mark.asyncio
async def test_a_head_response_may_echo_an_encoding_without_being_refused(
    public_dns,
) -> None:
    """HEAD carries no body, so its ``Content-Encoding`` is a claim about a GET.

    Real origins echo it. Refusing there would break ``follow_to_ats``'s cheap
    HEAD chain — the thing that makes Intel resolve — for no memory benefit.
    """
    counter = _CountingTransport(
        lambda r: httpx.Response(200, headers={"content-encoding": "gzip"})
    )
    async with counter.client() as client:
        response, hops = await guarded_get(
            "https://head.example/", client, method="HEAD"
        )

    assert response.status_code == 200
    assert response.content == b""
    assert hops == ("https://head.example/",)


@pytest.mark.asyncio
async def test_read_bounded_body_checks_before_it_appends(public_dns) -> None:
    """🔴 I3. The retained buffer never exceeds the cap, even for one huge chunk.

    ``_bounded_json``'s loop did ``body.extend(chunk)`` and then compared, so the
    bytearray was 67,200,488 bytes long at the moment the 4 MiB cap "fired".
    """

    async def body() -> AsyncIterator[bytes]:
        yield b"x" * 100_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body())

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        async with client.stream("GET", "https://big.example/") as response:
            content, truncated = await url_guard.read_bounded_body(response, 1000)

    assert len(content) == 1000
    assert truncated is True


@pytest.mark.asyncio
async def test_read_bounded_body_reports_a_body_that_fits_as_untruncated(
    public_dns,
) -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"x" * 1000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body())

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        async with client.stream("GET", "https://exact.example/") as response:
            content, truncated = await url_guard.read_bounded_body(response, 1000)

    assert content == b"x" * 1000
    assert truncated is False


def test_the_gzip_bomb_is_actually_a_bomb() -> None:
    """Guard the guard: if this ratio ever collapses the tests above prove nothing."""
    wire = len(gzip.compress(b"\0" * _BOMB_DECODED_BYTES, 9))
    assert _BOMB_DECODED_BYTES / wire > 100
    # And the decompressor really is bounded by ``max_length``.
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = decompressor.decompress(gzip.compress(b"\0" * _BOMB_DECODED_BYTES, 9), 64)
    assert len(out) == 64


# ----------------------------------------------------------------------------
# The DNS thread pool
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dns_runs_off_the_shared_default_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 I2. ``asyncio.to_thread`` puts the blocking lookup on the SHARED pool.

    That pool is also what ``loop.getaddrinfo`` — and therefore every outbound
    httpx connection in this process, including the in-process Procrastinate
    worker's — draws its threads from. Cancelling a ``to_thread`` does not
    interrupt the thread, so the resolve endpoint's ``wait_for`` backstop
    reclaims nothing: measured, 18 concurrent hostile-DNS resolves exhausted the
    16-worker default pool and a co-tenant lookup was still unserved after 8 s.
    """
    resolver_threads: list[str] = []

    def fake(host, port, *args, **kwargs):
        resolver_threads.append(threading.current_thread().name)
        return _addrinfo("93.184.216.34")

    monkeypatch.setattr(socket, "getaddrinfo", fake)

    default_pool_threads: list[str] = []

    def note_default_thread() -> None:
        default_pool_threads.append(threading.current_thread().name)

    # Force the loop's default executor into existence and learn its thread names.
    for _ in range(4):
        await asyncio.to_thread(note_default_thread)

    counter = _CountingTransport(lambda r: httpx.Response(200, text="ok"))
    async with counter.client() as client:
        await guarded_get("https://ok.example/", client)

    assert resolver_threads, "getaddrinfo was never called"
    assert all(
        name.startswith("url-guard-dns") for name in resolver_threads
    ), resolver_threads
    assert not set(resolver_threads) & set(default_pool_threads)


def test_the_dns_pool_is_small_enough_to_bound_the_blast_radius() -> None:
    """A dedicated pool only helps if it is dedicated *and* capped."""
    assert url_guard._DNS_EXECUTOR_MAX_WORKERS == 4
    assert url_guard._DNS_EXECUTOR._max_workers == url_guard._DNS_EXECUTOR_MAX_WORKERS


# ----------------------------------------------------------------------------
# The deadline floor
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_sliver_of_budget_is_deadline_exceeded_not_a_transport_timeout(
    public_dns,
) -> None:
    """🔴 M6. ``min(timeout, left)`` with 0.05 s left is a ``ReadTimeout``.

    That surfaces as ``fetch_failed``, which misnames the failure *and* defeats
    ``sniff_embedded_ats``'s ``REASON_DEADLINE`` short-circuit, so the remaining
    three sub-path guesses each burn another doomed request.
    """
    counter, client = _exploding_client()
    async with client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get(
                "https://ok.example/",
                client,
                timeout=30.0,
                deadline=time.monotonic() + 0.05,
            )

    assert exc.value.reason == REASON_DEADLINE
    assert counter.calls == [], "a request was issued on a budget that cannot fund it"


@pytest.mark.asyncio
async def test_a_budget_above_the_floor_still_issues_the_request(public_dns) -> None:
    """The floor must not swallow a small-but-workable budget."""
    counter = _CountingTransport(lambda r: httpx.Response(200, text="ok"))
    async with counter.client() as client:
        response, _ = await guarded_get(
            "https://ok.example/",
            client,
            timeout=30.0,
            deadline=time.monotonic() + url_guard._MIN_HOP_BUDGET_S + 1.0,
        )

    assert response.status_code == 200
    assert len(counter.calls) == 1


# ----------------------------------------------------------------------------
# normalize_public_url — the shared, IO-free half of validate_public_url
# ----------------------------------------------------------------------------


def test_normalize_public_url_performs_no_dns(exploding_dns) -> None:
    normalized, host = normalize_public_url("https://JOBS.INTEL.COM/careers#frag")
    assert normalized == "https://jobs.intel.com/careers"
    assert host == "jobs.intel.com"


def test_normalize_public_url_applies_the_same_rejections(exploding_dns) -> None:
    for url, reason in REJECTION_TABLE:
        with pytest.raises(UrlGuardError) as exc:
            normalize_public_url(url)
        assert exc.value.reason == reason, url
