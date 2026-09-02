"""Integration tests for POST /api/companies/search-by-name.

Like the resolve endpoint, this route answers a question without changing
anything, so every test asserts ``companies`` is untouched afterwards.

The one behaviour worth stating up front: **"we could not search" and "we searched
and there is no board" must never reach a user as the same sentence.** The first
is a 503, the second is a 200 with an empty list, and several tests below exist
only to keep those apart.
"""

from __future__ import annotations

import socket

import httpx
import pytest
from psycopg2 import sql

from api.config import settings
from api.services.rate_limit import resolve_rate_limiter

SEARCH = "/api/companies/search-by-name"
SEARCH_API = "https://api.browserbase.com/v1/search"
CISCO_BOARD = "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers"
CISCO_JOBS = "https://cisco.wd5.myworkdayjobs.com/wday/cxs/cisco/Cisco_Careers/jobs"
GUIDEHOUSE_BOARD = "https://guidehouse.wd1.myworkdayjobs.com/External"
GUIDEHOUSE_JOBS = (
    "https://guidehouse.wd1.myworkdayjobs.com/wday/cxs/guidehouse/External/jobs"
)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch):
    def fake(host, port, *args, **kwargs):
        return [
            (
                socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                ("93.184.216.34", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


@pytest.fixture(autouse=True)
def feature_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "custom_company_sources_enabled", True)
    monkeypatch.setattr(settings, "company_name_search_enabled", True)
    monkeypatch.setattr(settings, "browserbase_api_key", "test-key", raising=False)


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    resolve_rate_limiter.reset()
    yield
    resolve_rate_limiter.reset()


def _company_count(db_conn) -> int:
    cur = db_conn.cursor()
    cur.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier("companies")))
    row = cur.fetchone()
    cur.close()
    return int(row["n"])


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
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


def _search_payload(*urls: str) -> dict:
    return {
        "requestId": "t",
        "query": "t",
        "results": [{"id": u, "url": u, "title": f"Careers — {u}"} for u in urls],
    }


def _handler(search_urls: list[str], job_counts: dict[str, int]):
    """Serve the search response, then the Workday job-count probes."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == SEARCH_API:
            return httpx.Response(200, json=_search_payload(*search_urls))
        if url in job_counts:
            return httpx.Response(
                200, json={"total": job_counts[url], "jobPostings": [{"title": "SWE"}]}
            )
        return httpx.Response(404)

    return handler


# ----------------------------------------------------------------------------
# The happy path
# ----------------------------------------------------------------------------


def test_a_typed_name_returns_the_board_with_a_live_job_count(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _company_count(db_conn)
    _install_transport(
        monkeypatch,
        _handler(
            ["https://careers.cisco.com/global/en/home", CISCO_BOARD],
            {CISCO_JOBS: 1248},
        ),
    )

    resp = client.post(SEARCH, json={"name": "Cisco"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "Cisco"
    assert len(body["candidates"]) == 1
    found = body["candidates"][0]
    assert found["candidate"]["ats"] == "workday"
    # `provider_config` is a dict VALUE, so `to_camel` does not touch its keys —
    # they stay exactly as the resolver emitted them, which is what the ATS
    # clients read.
    assert found["candidate"]["providerConfig"]["career_site_slug"] == "Cisco_Careers"
    assert found["probe"]["jobCount"] == 1248
    assert found["autoAddable"] is True
    # The careers page we did NOT pick is still offered as the fallback.
    assert body["careersUrl"] == "https://careers.cisco.com/global/en/home"
    assert _company_count(db_conn) == before


def test_the_search_query_names_the_ats_hosts(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host-shaped query is the strategy — 76% with it, 41% with prose."""
    seen = _install_transport(monkeypatch, _handler([CISCO_BOARD], {CISCO_JOBS: 10}))

    client.post(SEARCH, json={"name": "Cisco"})

    search_request = next(r for r in seen if str(r.url) == SEARCH_API)
    import json as _json

    sent = _json.loads(search_request.content)
    assert sent["numResults"] == 25
    assert len(sent["query"]) <= 200
    for host in ("myworkdayjobs.com", "greenhouse.io", "ashbyhq.com", "lever.co"):
        assert host in sent["query"]
    assert search_request.headers["X-BB-API-Key"] == "test-key"


# ----------------------------------------------------------------------------
# The wrong-company failure — the one that matters
# ----------------------------------------------------------------------------


def test_another_companys_live_board_is_returned_but_never_auto_addable(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Searching `Databricks` really did return Guidehouse's board at rank 1 with
    794 live jobs. It passes every automated check we own — it IS a real board and
    it DOES return jobs — so the only defence is showing it to a human. It must
    come back (with its name and count) and must never be auto-addable."""
    _install_transport(
        monkeypatch, _handler([GUIDEHOUSE_BOARD], {GUIDEHOUSE_JOBS: 794})
    )

    body = client.post(SEARCH, json={"name": "Databricks"}).json()

    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["probe"]["jobCount"] == 794
    assert body["candidates"][0]["autoAddable"] is False


def test_a_matching_token_with_an_empty_board_is_not_auto_addable(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A board with zero jobs is the cheapest signal that we picked wrong, so the
    name gate alone is not enough to add it silently."""
    _install_transport(monkeypatch, _handler([CISCO_BOARD], {CISCO_JOBS: 0}))

    body = client.post(SEARCH, json={"name": "Cisco"}).json()

    assert body["candidates"][0]["autoAddable"] is False


# ----------------------------------------------------------------------------
# "Could not search" is never "no board exists"
# ----------------------------------------------------------------------------


def test_no_board_found_is_an_empty_200_not_an_error(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_transport(
        monkeypatch, _handler(["https://www.example.com/careers"], {})
    )

    resp = client.post(SEARCH, json={"name": "Nobody"})

    assert resp.status_code == 200
    assert resp.json()["candidates"] == []
    assert resp.json()["careersUrl"] == "https://www.example.com/careers"


def test_a_search_rate_limit_is_503_not_an_empty_result(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """429 from Browserbase must never read as 'your employer cannot be tracked'."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    _install_transport(monkeypatch, handler)

    assert client.post(SEARCH, json={"name": "Cisco"}).status_code == 503


def test_search_is_503_when_credentials_are_missing(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "browserbase_api_key", None, raising=False)
    seen = _install_transport(monkeypatch, _handler([], {}))

    assert client.post(SEARCH, json={"name": "Cisco"}).status_code == 503
    assert seen == []


# ----------------------------------------------------------------------------
# Flags and input validation
# ----------------------------------------------------------------------------


def test_route_is_503_when_the_name_search_flag_is_off(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "company_name_search_enabled", False)
    seen = _install_transport(monkeypatch, _handler([], {}))

    assert client.post(SEARCH, json={"name": "Cisco"}).status_code == 503
    assert seen == []


def test_route_is_503_when_the_custom_sources_flag_is_off(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "custom_company_sources_enabled", False)

    assert client.post(SEARCH, json={"name": "Cisco"}).status_code == 503


def test_an_overlong_name_is_422_before_any_spend(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 60-char cap protects the 200-char query budget the ATS hosts live in."""
    seen = _install_transport(monkeypatch, _handler([], {}))

    resp = client.post(SEARCH, json={"name": "z" * 61})

    assert resp.status_code == 422
    assert seen == []


def test_the_burst_limiter_is_actually_applied(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE SPEND CONTROL. Every call is a paid third-party search plus up to five
    outbound ATS probes, and the limiter is the only thing bounding how fast one
    account can spend. Without this test the `enforce_resolve_rate_limit` line
    could be deleted and all the other cases here would still pass."""
    # Patch the LIMITER, not `settings`: the instance is constructed at import
    # time from the settings values, so a later settings change never reaches it.
    monkeypatch.setattr(resolve_rate_limiter, "_max", 2)
    resolve_rate_limiter.reset()
    _install_transport(monkeypatch, _handler([CISCO_BOARD], {CISCO_JOBS: 5}))

    codes = [
        client.post(SEARCH, json={"name": "Cisco"}).status_code for _ in range(4)
    ]

    assert codes[:2] == [200, 200]
    assert 429 in codes[2:]


def test_probes_are_capped_regardless_of_how_many_boards_come_back(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probing all 25 results would turn one user action into 25 outbound ATS
    calls. Only the handful we intend to SHOW may be probed."""
    boards = [f"https://boards.greenhouse.io/acme{n}" for n in range(20)]
    seen = _install_transport(monkeypatch, _handler(boards, {}))

    body = client.post(SEARCH, json={"name": "Acme"}).json()

    assert len(body["candidates"]) == 5
    probe_calls = [r for r in seen if "boards-api.greenhouse.io" in str(r.url)]
    assert len(probe_calls) == 5


def test_requires_a_bearer_token(db_conn) -> None:
    """The route spends money, so it must never be reachable unauthenticated."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routers import companies as companies_router

    app = FastAPI()
    app.include_router(companies_router.router, prefix="/api/companies")
    with TestClient(app) as bare:
        assert bare.post(SEARCH, json={"name": "Cisco"}).status_code == 401


def test_unknown_body_field_is_rejected(client, db_conn) -> None:
    resp = client.post(SEARCH, json={"name": "Cisco", "nmae": "typo"})
    assert resp.status_code == 422


def test_empty_name_is_rejected(client, db_conn) -> None:
    assert client.post(SEARCH, json={"name": ""}).status_code == 422
