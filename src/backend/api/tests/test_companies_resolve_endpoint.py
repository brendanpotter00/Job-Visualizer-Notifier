"""Integration tests for POST /api/companies/resolve.

The endpoint's whole job is to answer a question without changing anything, so
**every** test here asserts ``companies`` is untouched afterwards. If a future
change starts persisting from this route, every case in this file fails.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.config import settings

INTEL_REDIRECTOR = (
    "https://corpredirect.intel.com/Redirector/404Redirector.aspx"
    "?404;https://jobs.intel.com/"
)
INTEL_WORKDAY = (
    "https://intel.wd1.myworkdayjobs.com/External/page/"
    "6042070b79e01001f04fa9b468070000"
)
RESOLVE = "/api/companies/resolve"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch):
    def fake(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture(autouse=True)
def feature_enabled(monkeypatch: pytest.MonkeyPatch):
    """Default the flag ON so each test states its own intent; 503 test flips it off."""
    monkeypatch.setattr(settings, "custom_company_sources_enabled", True)


def _company_count(db_conn) -> int:
    cur = db_conn.cursor()
    cur.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier("companies")))
    row = cur.fetchone()
    cur.close()
    return int(row["n"])


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    """Point the router's client factory at a MockTransport; return the request log."""
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(wrapped), follow_redirects=False
        )

    monkeypatch.setattr("api.routers.companies._http_client", factory)
    return seen


def _intel_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url in ("https://jobs.intel.com", "https://jobs.intel.com/"):
        return httpx.Response(301, headers={"location": INTEL_REDIRECTOR})
    if url == INTEL_REDIRECTOR:
        return httpx.Response(301, headers={"location": INTEL_WORKDAY})
    if url == INTEL_WORKDAY:
        return httpx.Response(200, text="<html>Workday</html>")
    if url == "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs":
        return httpx.Response(200, json={"total": 681, "jobPostings": [{"title": "SWE"}]})
    return httpx.Response(404)


# ----------------------------------------------------------------------------
# 200
# ----------------------------------------------------------------------------


def test_intel_resolves_to_workday_with_a_real_job_count(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 The D11 acceptance criterion, end to end through the route."""
    before = _company_count(db_conn)
    _install_transport(monkeypatch, _intel_handler)

    resp = client.post(RESOLVE, json={"url": "https://jobs.intel.com"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate"]["ats"] == "workday"
    assert body["candidate"]["providerConfig"] == {
        "base_url": "https://intel.wd1.myworkdayjobs.com",
        "tenant_slug": "intel",
        "career_site_slug": "External",
    }
    assert body["via"] == "redirect"
    assert body["finalUrl"] == INTEL_WORKDAY
    assert body["hops"] == ["https://jobs.intel.com", INTEL_REDIRECTOR, INTEL_WORKDAY]
    assert body["probe"] == {"ok": True, "jobCount": 681, "error": None}
    assert body["probe"]["jobCount"] > 500
    assert _company_count(db_conn) == before


def test_response_uses_camel_case_keys(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_transport(monkeypatch, _intel_handler)
    body = client.post(RESOLVE, json={"url": "https://jobs.intel.com"}).json()

    assert set(body) == {"candidate", "probe", "via", "hops", "finalUrl"}
    assert set(body["candidate"]) == {"ats", "boardToken", "providerConfig", "sourceUrl"}
    assert set(body["probe"]) == {"ok", "jobCount", "error"}


def test_direct_board_url_resolves_without_redirects(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _company_count(db_conn)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "boards-api.greenhouse.io"
        return httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]})

    _install_transport(monkeypatch, handler)
    resp = client.post(RESOLVE, json={"url": "https://boards.greenhouse.io/acme"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["via"] == "direct"
    assert body["candidate"]["boardToken"] == "acme"
    assert body["probe"]["jobCount"] == 2
    assert _company_count(db_conn) == before


def test_a_failing_probe_still_returns_200_with_the_error(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """We found a board; it just did not answer. That is a 200 with ok=false."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no such board")

    _install_transport(monkeypatch, handler)
    resp = client.post(RESOLVE, json={"url": "https://boards.greenhouse.io/ghost"})

    assert resp.status_code == 200
    probe = resp.json()["probe"]
    assert probe["ok"] is False
    assert probe["jobCount"] == 0
    assert probe["error"]


# ----------------------------------------------------------------------------
# 422 — machine-readable reasons
# ----------------------------------------------------------------------------


def test_unrecognized_url_returns_422_with_a_reason(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _company_count(db_conn)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>marketing</html>")

    _install_transport(monkeypatch, handler)
    resp = client.post(RESOLVE, json={"url": "https://www.tesla.com/careers"})

    assert resp.status_code == 422
    body = resp.json()
    assert body["reason"] == "no_ats_detected"
    assert body["finalUrl"]
    assert isinstance(body["hops"], list)
    assert _company_count(db_conn) == before


def test_ssrf_rejection_surfaces_its_guard_reason(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _company_count(db_conn)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request must be issued; got {request.url}")

    seen = _install_transport(monkeypatch, handler)
    resp = client.post(RESOLVE, json={"url": "http://169.254.169.254/latest/meta-data/"})

    assert resp.status_code == 422
    assert resp.json()["reason"] == "scheme_not_https"
    assert seen == []
    assert _company_count(db_conn) == before


@pytest.mark.parametrize(
    "url",
    [
        # ``urlsplit`` raises ValueError("Invalid IPv6 URL") on an unbalanced bracket
        "https://a]b.com/",
        # bogus Punycode A-labels: the stdlib "idna" codec waves any ASCII label
        # through, then httpx's ``idna`` package refuses to build the host and
        # raises an IDNAError that is not an httpx.HTTPError
        "https://xn--a.com/careers",
        "https://xn--0.com/",
        "https://xn--.com/",
    ],
)
def test_malformed_url_is_422_with_a_reason_not_500(
    client, db_conn, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """🔴 C1. Each of these was an uncaught exception → 500, no reason, no audit row."""
    before = _company_count(db_conn)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request must be issued; got {request.url}")

    seen = _install_transport(monkeypatch, handler)
    resp = client.post(RESOLVE, json={"url": url})

    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "invalid_hostname"
    assert seen == []
    assert _company_count(db_conn) == before


def test_a_remote_location_header_cannot_500_the_endpoint(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 C1. Any third-party host in a chain could crash this route on demand.

    ``Location: https://xn--a.com/`` is all it took: httpx builds a redirect
    request from any 3xx even with ``follow_redirects=False``, which touches
    ``URL.host`` → ``idna.decode`` → ``IDNAError``, from inside our own
    ``http.stream`` call and past ``except httpx.HTTPError``.
    """
    before = _company_count(db_conn)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://xn--a.com/"})

    _install_transport(monkeypatch, handler)
    resp = client.post(RESOLVE, json={"url": "https://hostile.example/careers"})

    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "fetch_failed"
    assert _company_count(db_conn) == before


def test_url_over_the_length_cap_is_422(client, db_conn) -> None:
    before = _company_count(db_conn)
    resp = client.post(RESOLVE, json={"url": "https://x.example/" + "a" * 2100})
    assert resp.status_code == 422
    assert _company_count(db_conn) == before


def test_unknown_body_field_is_rejected(client, db_conn) -> None:
    resp = client.post(
        RESOLVE, json={"url": "https://boards.greenhouse.io/acme", "sneaky": True}
    )
    assert resp.status_code == 422


def test_missing_body_is_rejected(client, db_conn) -> None:
    assert client.post(RESOLVE, json={}).status_code == 422


# ----------------------------------------------------------------------------
# The aggregate budget, and what gets logged
# ----------------------------------------------------------------------------


def test_a_slow_host_cannot_hold_the_request_open_indefinitely(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 I2. There was no aggregate bound — only per-request timeouts.

    ``_RESOLVE_CLIENT_TIMEOUT_S`` was described as "the backstop" but is not one:
    every ``guarded_get`` passes an explicit ``timeout=``, which overrides the
    client default instead of being capped by it. Worst case was ~36 outbound
    requests × 8 s ≈ 288 s at a third-party host.
    """
    before = _company_count(db_conn)
    monkeypatch.setattr("api.routers.companies._RESOLVE_BUDGET_S", 0.20)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return httpx.Response(200, text="<html>slow and boardless</html>")

    _install_transport(monkeypatch, handler)
    started = time.monotonic()
    resp = client.post(RESOLVE, json={"url": "https://slow.example/careers"})
    elapsed = time.monotonic() - started

    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "deadline_exceeded"
    assert elapsed < 5.0, elapsed
    assert _company_count(db_conn) == before


def test_the_outer_wait_for_backstops_anything_the_deadline_misses(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The threaded deadline is the primary bound; this is the hard stop behind it.

    Simulated with a ``discover_ats`` that ignores its deadline entirely — which is
    what any future non-``guarded_get`` work inside the handler (DNS in a worker
    thread, a big JSON parse) would look like.
    """
    monkeypatch.setattr("api.routers.companies._RESOLVE_BUDGET_S", 0.05)
    monkeypatch.setattr("api.routers.companies._RESOLVE_GRACE_S", 0.05)

    async def ignores_the_deadline(url, http, *, deadline=None):
        await asyncio.sleep(30)
        raise AssertionError("should have been cancelled")

    monkeypatch.setattr("api.routers.companies.discover_ats", ignores_the_deadline)
    _install_transport(monkeypatch, lambda r: httpx.Response(200, text="x"))

    started = time.monotonic()
    resp = client.post(RESOLVE, json={"url": "https://slow.example/careers"})

    assert resp.status_code == 422
    assert resp.json()["reason"] == "deadline_exceeded"
    assert time.monotonic() - started < 5.0


def test_embedded_runners_up_are_logged(
    client, db_conn, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """🔴 M4. ``runners_up`` was populated by the L2 ranker and then dropped.

    "We picked Greenhouse/realboard but the page also named Lever/decoy" is the
    whole diagnosis for a wrong embedded resolution, and this log line is the only
    place PR 1 records it.
    """
    page = (
        "https://jobs.lever.co/decoy "
        + "https://boards.greenhouse.io/realboard " * 5
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boards-api.greenhouse.io":
            return httpx.Response(200, json={"jobs": [{"id": 1}, {"id": 2}]})
        return httpx.Response(200, text=page)

    _install_transport(monkeypatch, handler)
    with caplog.at_level(logging.INFO, logger="api.routers.companies"):
        resp = client.post(RESOLVE, json={"url": "https://multi.example/careers"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["via"] == "embedded"
    assert body["candidate"]["boardToken"] == "realboard"
    assert "runners_up=['lever/decoy']" in caplog.text


# ----------------------------------------------------------------------------
# 401 / 503
# ----------------------------------------------------------------------------


def test_without_a_token_returns_401(test_app, db_conn) -> None:
    from api.auth.dependencies import get_current_user

    before = _company_count(db_conn)
    saved = test_app.dependency_overrides.pop(get_current_user, None)
    try:
        resp = TestClient(test_app).post(
            RESOLVE, json={"url": "https://boards.greenhouse.io/acme"}
        )
        assert resp.status_code == 401
    finally:
        if saved is not None:
            test_app.dependency_overrides[get_current_user] = saved
    assert _company_count(db_conn) == before


def test_flag_off_returns_503(client, db_conn, monkeypatch: pytest.MonkeyPatch) -> None:
    before = _company_count(db_conn)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the flag gate must run before any IO")

    seen = _install_transport(monkeypatch, handler)
    monkeypatch.setattr(settings, "custom_company_sources_enabled", False)

    resp = client.post(RESOLVE, json={"url": "https://boards.greenhouse.io/acme"})

    assert resp.status_code == 503
    assert seen == []
    assert _company_count(db_conn) == before


def test_the_flag_name_is_pinned() -> None:
    """``Settings.model_config`` uses ``extra="ignore"``.

    A typo'd env var would therefore leave the feature silently off forever with
    no error anywhere. Pin the field name so a rename is a test failure, not a
    production mystery.
    """
    assert "custom_company_sources_enabled" in type(settings).model_fields
    assert type(settings).model_fields["custom_company_sources_enabled"].default is False


# ----------------------------------------------------------------------------
# The existing GET route is untouched
# ----------------------------------------------------------------------------


def test_get_companies_still_works(client, db_conn) -> None:
    resp = client.get("/api/companies")
    assert resp.status_code == 200
    assert resp.json() == {"companies": []}
