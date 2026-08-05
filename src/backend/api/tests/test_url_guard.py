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

import socket

import httpx
import pytest

from api.services.url_guard import (
    REASON_ATS_HOST,
    REASON_CROSS_HOST,
    REASON_DNS,
    REASON_HOSTNAME,
    REASON_PORT,
    REASON_PRIVATE_ADDRESS,
    REASON_SCHEME,
    REASON_TOO_MANY_HOPS,
    REASON_USERINFO,
    UrlGuardError,
    assert_ats_api_host,
    guarded_get,
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


@pytest.mark.asyncio
async def test_too_many_hops(public_dns) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.path.strip("/") or 0)
        return httpx.Response(302, headers={"location": f"https://loop.example/{n + 1}"})

    counter = _CountingTransport(handler)
    async with counter.client() as client:
        with pytest.raises(UrlGuardError) as exc:
            await guarded_get("https://loop.example/0", client, max_hops=3)

    assert exc.value.reason == REASON_TOO_MANY_HOPS
    # max_hops=3 permits the original request plus three more.
    assert len(counter.calls) == 4


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
