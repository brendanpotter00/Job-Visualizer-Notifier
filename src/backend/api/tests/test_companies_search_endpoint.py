"""Integration tests for POST /api/companies/search-by-name.

Like the resolve endpoint, this route answers a question without changing
anything, so every test asserts ``companies`` is untouched afterwards.

The one behaviour worth stating up front: **"we could not search" and "we searched
and there is no board" must never reach a user as the same sentence.** The first
is a 503, the second is a 200 with an empty list, and several tests below exist
only to keep those apart.
"""

from __future__ import annotations

import json
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


def _sent_queries(seen: list[httpx.Request]) -> list[str]:
    """Every search query this request actually paid for, in order."""
    return [
        json.loads(r.content)["query"] for r in seen if str(r.url) == SEARCH_API
    ]


def _two_query_handler(
    host_shaped: list[str], plain: list[str], job_counts: dict[str, int]
):
    """Answer the two searches DIFFERENTLY, which is the whole point of them.

    The host-shaped query finds boards and SEO content about applicant tracking
    systems; the plain ``"{name} careers"`` query finds careers pages. A fixture
    that served one payload to both could not tell the escalation apart from the
    first search simply being repeated.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == SEARCH_API:
            query = json.loads(request.content)["query"]
            second = query.endswith(" careers")
            return httpx.Response(
                200, json=_search_payload(*(plain if second else host_shaped))
            )
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
    # NO FALLBACK when the answer is already good. `careers.cisco.com` was offered
    # here until 2026-09-02, beside a board we were about to add automatically —
    # a second, weaker action next to the right one.
    assert body["careersUrl"] is None
    assert body["careersSearch"] is None
    # ...and the trace the add page narrates the run from. `boards` is counted
    # BEFORE the five-candidate display cap, which is the whole reason it is on
    # the wire rather than derived from `candidates`.
    assert body["trace"]["results"] == 2
    assert body["trace"]["filtered"] == 0
    assert body["trace"]["boards"] == 1
    assert "myworkdayjobs.com" in body["trace"]["query"]
    # The rows the add page's morphing list folds away, on the wire because it may
    # only draw results that really came back. The BOARD is not among them — it is
    # already a candidate above, with a token and a live count.
    assert [row["url"] for row in body["trace"]["nonBoards"]] == [
        "https://careers.cisco.com/global/en/home"
    ]
    assert body["trace"]["nonBoards"][0]["aggregator"] is False
    assert body["trace"]["nonBoardsOmitted"] == 0
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
        monkeypatch,
        _two_query_handler(
            ["https://www.example.com/careers"],
            ["https://www.nobody.com/careers"],
            {},
        ),
    )

    resp = client.post(SEARCH, json={"name": "Nobody"})

    assert resp.status_code == 200
    assert resp.json()["candidates"] == []
    assert resp.json()["careersUrl"] == "https://www.nobody.com/careers"


# ----------------------------------------------------------------------------
# The careers-page fallback — a second query, and only on a miss
#
# Measured live 2026-09-02 over 22 companies
# (docs/implementations/custom-company-sources/CAREERS-FALLBACK-POC.md). Each case
# below is one of the real failures from that sweep, with the real URLs.
# ----------------------------------------------------------------------------


def test_a_junk_fallback_becomes_the_companys_own_careers_page(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE ORACLE CASE. Not one of the 23 host-shaped results was on oracle.com —
    with the ATS hostnames in the query, a company with no board on any of the six
    returns SEO content *about* applicant tracking systems. So we offered
    `resumeadapter.com/ats/workday/companies` as Oracle's careers page, and
    accepting it would have spent a paid discovery run and a monthly add on a
    stranger. `Oracle careers` returns `oracle.com/careers/` at rank 1."""
    seen = _install_transport(
        monkeypatch,
        _two_query_handler(
            ["https://resumeadapter.com/ats/workday/companies"],
            ["https://www.oracle.com/careers/"],
            {},
        ),
    )

    body = client.post(SEARCH, json={"name": "Oracle"}).json()

    assert body["candidates"] == []
    assert body["careersUrl"] == "https://www.oracle.com/careers/"
    # The panel narrates the run, so the second call has to be reported as one.
    assert body["careersSearch"]["query"] == "Oracle careers"
    assert body["careersSearch"]["trusted"] == 1
    assert _sent_queries(seen)[1] == "Oracle careers"


def test_a_strangers_board_no_longer_suppresses_the_careers_page(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE IBM CASE, and the reason the trigger is `auto_addable` rather than
    "no candidates at all". Searching IBM resolved `jobs.ashbyhq.com/Harvey` at
    rank 23 — a legal-AI company with 334 live jobs. It is a real board, so
    `candidates` was non-empty, so the fallback was suppressed and the user was
    left with a stranger's board and NO way forward. Both must appear now: the
    board is information, the careers page is the action."""
    # The resolver lower-cases the board token, so the probe is `/harvey`.
    harvey_jobs = "https://api.ashbyhq.com/posting-api/job-board/harvey"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == SEARCH_API:
            second = json.loads(request.content)["query"].endswith(" careers")
            return httpx.Response(
                200,
                json=_search_payload(
                    *(
                        ["https://www.ibm.com/careers"]
                        if second
                        else ["https://jobs.ashbyhq.com/Harvey"]
                    )
                ),
            )
        if url.startswith(harvey_jobs):
            return httpx.Response(200, json={"jobs": [{"title": "Counsel"}] * 334})
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)

    body = client.post(SEARCH, json={"name": "IBM"}).json()

    # The stranger's board is still shown — a user may recognise it — and it is
    # still never auto-addable.
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["candidate"]["boardToken"] == "harvey"
    assert body["candidates"][0]["probe"]["jobCount"] == 334
    assert body["candidates"][0]["autoAddable"] is False
    # ...and it no longer costs the user their careers page.
    assert body["careersUrl"] == "https://www.ibm.com/careers"


def test_nothing_that_names_the_company_means_nothing_is_offered(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`owns_host` is a FILTER, not just a sort key. When no result's host names
    the company we hand back NOTHING and the UI says "paste the URL of their
    careers page" — because the top-ranked stranger is not a weaker answer, it is
    a paid discovery run plus one of the user's twenty monthly adds spent on
    somebody else's website."""
    _install_transport(
        monkeypatch,
        _two_query_handler(
            ["https://findmejobs.co/companies/nomatch"],
            ["https://openjobradar.com/c/nomatch", "https://dreamworkhq.com/nomatch"],
            {},
        ),
    )

    body = client.post(SEARCH, json={"name": "Zzyzx Industries"}).json()

    assert body["candidates"] == []
    assert body["careersUrl"] is None
    # We DID look, and the trace says so — two results, none of them theirs.
    assert body["careersSearch"]["results"] == 2
    assert body["careersSearch"]["trusted"] == 0


def test_an_auto_addable_board_spends_exactly_one_search(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NO REGRESSION, and this is the test that keeps the second query honest. A
    name that resolves a live board naming the company must cost exactly what it
    cost before the escalation existed: one search, one answer."""
    seen = _install_transport(
        monkeypatch,
        _two_query_handler(
            ["https://careers.cisco.com/global/en/home", CISCO_BOARD],
            ["https://www.cisco.com/careers"],
            {CISCO_JOBS: 1248},
        ),
    )

    body = client.post(SEARCH, json={"name": "Cisco"}).json()

    assert body["candidates"][0]["autoAddable"] is True
    assert _sent_queries(seen) == [
        "Cisco jobs myworkdayjobs.com greenhouse.io ashbyhq.com lever.co "
        "jobs.gem.com eightfold.ai"
    ]
    assert body["careersUrl"] is None
    assert body["careersSearch"] is None


def test_a_second_search_that_fails_is_not_the_whole_request_failing(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The escalation is the footnote, not the answer. A 429 on the second call
    must not turn a working search into "we could not look" — we still have the
    first search's boards, and the first search's own trusted careers page."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == SEARCH_API:
            calls.append(1)
            if len(calls) > 1:
                return httpx.Response(429, json={"error": "slow down"})
            return httpx.Response(
                200, json=_search_payload("https://careers.tesla.com/")
            )
        return httpx.Response(404)

    _install_transport(monkeypatch, handler)

    resp = client.post(SEARCH, json={"name": "Tesla"})

    assert resp.status_code == 200
    body = resp.json()
    # Belt and braces: the first search's own trusted result, measured never to be
    # needed (the second query succeeded 15/15) and kept for exactly this case.
    assert body["careersUrl"] == "https://careers.tesla.com/"
    # Nothing narrated about a second search, because none of it happened.
    assert body["careersSearch"] is None


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
    # The trace still reports all 20, which is what lets the page say "found 20,
    # checked the top 5" instead of silently claiming it only ever found five.
    assert body["trace"]["boards"] == 20


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


# ----------------------------------------------------------------------------
# A company we ALREADY PUBLISH, answered HERE — not one press later
#
# The bug, in the owner's words: he typed `databricks`, was handed
# `https://www.databricks.com/company/careers` under a filled "Use this careers
# page" button, pressed it, and only THEN was told "this looks like Databricks,
# which we already track". "There should not be that flow. If we already track
# it, just say that."
#
# The three checks were only ever on the ADD path; this route had no database
# access at all and was structurally incapable of knowing what we publish. Every
# test below is about it having one now — and about the `matchKind` distinction,
# which decides whether the page may still offer a way past the answer.
# ----------------------------------------------------------------------------

DATABRICKS_CAREERS = "https://www.databricks.com/company/careers"
AMAZON_CAREERS = "https://www.amazon.jobs/en/search"


@pytest.fixture
def published(db_conn):
    """Seed ``visibility='public'`` rows for ONE test, then take them away again.

    ``db_conn`` is module-scoped, so a row left behind would silently change the
    answer for every later test in this file — several of which search for Cisco
    and expect no published match at all.
    """
    seeded: list[str] = []

    def seed(
        company_id: str,
        *,
        ats: str = "greenhouse",
        board_token: str,
        display_name: str | None = None,
        provider_config: str = "{}",
    ) -> None:
        cur = db_conn.cursor()
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (id, display_name, ats, board_token, "
                "provider_config, enabled, visibility) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, true, 'public')"
            ).format(sql.Identifier("companies")),
            (company_id, display_name or company_id, ats, board_token,
             provider_config),
        )
        db_conn.commit()
        seeded.append(company_id)

    yield seed

    cur = db_conn.cursor()
    for company_id in seeded:
        cur.execute(
            sql.SQL("DELETE FROM {} WHERE id = %s").format(
                sql.Identifier("companies")
            ),
            (company_id,),
        )
    db_conn.commit()


def test_the_careers_page_we_would_offer_is_a_company_we_publish(
    client, db_conn, published, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE DATABRICKS CASE, answered at search time.

    Nothing the first search found was auto-addable, so the careers fallback ran and
    came back with `databricks.com` — and `databricks` is a name we publish. That is
    the third rung, a GUESS from a string in a domain, so it answers
    `matchKind='name'` and the page keeps the "this isn't the same company" way out.
    """
    _install_transport(
        monkeypatch,
        _two_query_handler(
            [GUIDEHOUSE_BOARD], [DATABRICKS_CAREERS], {GUIDEHOUSE_JOBS: 794}
        ),
    )
    published("databricks", board_token="databricks", display_name="Databricks")
    before = _company_count(db_conn)

    body = client.post(SEARCH, json={"name": "Databricks"}).json()

    match = body["alreadyPublic"]
    assert match["status"] == "already_public"
    assert match["companyId"] == "databricks"
    assert match["displayName"] == "Databricks"
    # A GUESS, so the escape hatch survives. `finalUrl` is what it re-sends.
    assert match["matchKind"] == "name"
    assert match["finalUrl"] == DATABRICKS_CAREERS
    # The careers URL still rides along: it is what the correction re-sends, and the
    # narration draws its last row from it. The PAGE is what must not draw both.
    assert body["careersUrl"] == DATABRICKS_CAREERS
    # Guidehouse's board is still reported, unchanged — the boards are evidence.
    assert body["candidates"][0]["autoAddable"] is False
    assert _company_count(db_conn) == before


def test_a_published_careers_host_is_terminal(
    client, db_conn, published, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The five `ats='script'` boards have no ATS pair for rung 1 to compare, so the
    declared careers-host table is what catches `amazon.jobs`. That is an EXACT,
    declared host — `matchKind='board'` — and the page renders it with no way past."""
    _install_transport(
        monkeypatch, _two_query_handler([], [AMAZON_CAREERS], {})
    )
    published("amazon", ats="script", board_token="amazon", display_name="Amazon")

    body = client.post(SEARCH, json={"name": "Amazon"}).json()

    assert body["alreadyPublic"]["companyId"] == "amazon"
    assert body["alreadyPublic"]["matchKind"] == "board"


def test_a_published_board_answers_before_a_second_search_is_paid_for(
    client, db_conn, published, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE CHEAP WIN. The second search exists to find a careers page to OFFER, and
    a board we already publish means we are not going to offer one. So it never runs
    — a paid call saved on a question we could already answer.

    Cisco's board is empty here, so nothing is auto-addable and the fallback WOULD
    have fired. The pre-probe name gate is what still recognises it: a published
    board that is empty or unreachable today is still the board we publish."""
    seen = _install_transport(monkeypatch, _handler([CISCO_BOARD], {CISCO_JOBS: 0}))
    published(
        "cisco", ats="workday", board_token="cisco", display_name="Cisco",
        provider_config=json.dumps(
            {"tenant_slug": "cisco", "career_site_slug": "Cisco_Careers"}
        ),
    )

    body = client.post(SEARCH, json={"name": "Cisco"}).json()

    assert body["alreadyPublic"]["companyId"] == "cisco"
    assert body["alreadyPublic"]["matchKind"] == "board"
    assert body["alreadyPublic"]["finalUrl"] == CISCO_BOARD
    assert body["candidates"][0]["autoAddable"] is False
    # ONE search paid for, not two, and no careers page offered beside the answer.
    assert len(_sent_queries(seen)) == 1
    assert body["careersUrl"] is None
    assert body["careersSearch"] is None


def test_a_strangers_published_board_never_answers_for_the_name_typed(
    client, db_conn, published, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE GUARD ON THE WHOLE FEATURE, and the reason only name-gated candidates are
    asked about. Browserbase Search is semantic: searching `Databricks` really does
    return Guidehouse's live Workday board at rank 1. If a published board could
    answer without its token naming the query, this search would come back "we
    already track Guidehouse" — confident, wrong, and terminal, which is strictly
    worse than the dead end this whole change removes."""
    _install_transport(
        monkeypatch,
        _two_query_handler(
            [GUIDEHOUSE_BOARD], ["https://www.nobody.com/careers"],
            {GUIDEHOUSE_JOBS: 794},
        ),
    )
    published(
        "guidehouse", ats="workday", board_token="guidehouse",
        display_name="Guidehouse",
        provider_config=json.dumps(
            {"tenant_slug": "guidehouse", "career_site_slug": "External"}
        ),
    )

    body = client.post(SEARCH, json={"name": "Databricks"}).json()

    assert body["alreadyPublic"] is None
    assert body["candidates"][0]["probe"]["jobCount"] == 794


def test_a_company_we_do_not_publish_is_completely_unchanged(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE ORACLE CASE AGAIN, with the dedupe wired in. We publish no Oracle, so the
    body is byte-for-byte what it was before this existed and the careers page is
    still the answer."""
    _install_transport(
        monkeypatch,
        _two_query_handler(
            ["https://resumeadapter.com/ats/workday/companies"],
            ["https://www.oracle.com/careers/"],
            {},
        ),
    )

    body = client.post(SEARCH, json={"name": "Oracle"}).json()

    assert body["alreadyPublic"] is None
    assert body["careersUrl"] == "https://www.oracle.com/careers/"
    assert body["careersSearch"]["trusted"] == 1


def test_a_disabled_public_row_is_not_offered_as_the_answer(
    client, db_conn, published, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disabled public row is a board we have STOPPED reading. Pointing somebody at
    a chart that no longer updates is worse than letting them track their own copy,
    so `enabled` is part of the match on every rung — see
    `find_public_company_by_name`. Seeded enabled, then disabled, because the fixture
    only knows how to insert live rows."""
    _install_transport(
        monkeypatch,
        _two_query_handler([], [DATABRICKS_CAREERS], {}),
    )
    published("databricks", board_token="databricks", display_name="Databricks")
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("UPDATE {} SET enabled = false WHERE id = 'databricks'").format(
            sql.Identifier("companies")
        )
    )
    db_conn.commit()

    body = client.post(SEARCH, json={"name": "Databricks"}).json()

    assert body["alreadyPublic"] is None
    assert body["careersUrl"] == DATABRICKS_CAREERS


# ----------------------------------------------------------------------------
# WHICH careers page — the job list, not the landing page
#
# The trusted set was always right; the row we picked out of it was the first by
# search rank, and search rank prefers the page people link to. Measured over 28
# companies, that lands on the real job list 3 times; deriving it from the job
# URLs and ranking on the title lands on it 16 times.
# ----------------------------------------------------------------------------

# Airbnb's real 2026-09-03 results. `careers.airbnb.com/positions` — the job list —
# is not among them at ANY rank, so no amount of ranking can reach it. The
# postings are the only evidence it exists.
AIRBNB_RESULTS = [
    ("https://careers.airbnb.com/", "Home - Careers at Airbnb"),
    ("https://careers.airbnb.com/positions/8078019/", "Staff Backend Engineer"),
    ("https://careers.airbnb.com/positions/8077995/", "Staff Software Engineer"),
    ("https://careers.airbnb.com/positions/7948314/", "Lead, Advanced Analytics"),
]
AIRBNB_LIST = "https://careers.airbnb.com/positions"


def _airbnb_handler(verification: httpx.Response):
    """The two searches, then whatever the verification fetch is told to answer."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == SEARCH_API:
            second = json.loads(request.content)["query"].endswith(" careers")
            return httpx.Response(
                200,
                json={
                    "requestId": "t",
                    "query": "t",
                    "results": (
                        [{"id": u, "url": u, "title": t} for u, t in AIRBNB_RESULTS]
                        if second
                        else []
                    ),
                },
            )
        if url == AIRBNB_LIST:
            return verification
        return httpx.Response(404)

    return handler


def test_the_offered_careers_page_is_the_job_list(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Derived from the postings, then proved with ONE fetch."""
    seen = _install_transport(
        monkeypatch, _airbnb_handler(httpx.Response(200, text="<html>positions</html>"))
    )

    body = client.post(SEARCH, json={"name": "Airbnb"}).json()

    assert body["careersUrl"] == AIRBNB_LIST
    # Two searches and exactly one verification fetch — the postings themselves
    # are never fetched, and neither is the landing page.
    assert [str(r.url) for r in seen if str(r.url) != SEARCH_API] == [AIRBNB_LIST]


def test_a_derived_list_we_cannot_verify_falls_back_to_the_ranker(
    client, db_conn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FAILING OPEN, end to end. Tesla, Citadel, Epic Games and Dell all 403 us;
    treating that as "reject" would leave the user with nothing on every
    Cloudflare-fronted careers site."""
    _install_transport(monkeypatch, _airbnb_handler(httpx.Response(403, text="no")))

    body = client.post(SEARCH, json={"name": "Airbnb"}).json()

    # The landing page again — the old answer, which is the right one to fall
    # back to and never worse than what we offered before.
    assert body["careersUrl"] == "https://careers.airbnb.com/"
    assert body["careersSearch"]["trusted"] == 4
