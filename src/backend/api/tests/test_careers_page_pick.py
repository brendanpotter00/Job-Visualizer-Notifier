"""Which trusted careers URL we offer — the job list, not the brochure.

Every fixture in the T section is a VERBATIM slice of a real
``"{company} careers"`` search: the URLs and the titles are what Browserbase
returned on 2026-09-03, trimmed to the rows that decide the answer. The first row
of each is what the old code offered (first trusted result, in search rank order)
and is wrong every time — that is the bug.

Measured over the whole 28-company corpus with this module in place: the offered
URL is the company's real job list **16 times**, against 3 for search rank alone
and 11 for a URL word list alone.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from api.services.careers_page_pick import (
    CareersResult,
    derive_list_url,
    is_single_posting_url,
    pick_careers_url,
    rank_careers_results,
    verify_list_url,
)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every host in these tests resolves to a public address.

    ``verify_list_url`` goes through ``guarded_get``, which does a real
    ``getaddrinfo`` before it opens anything. Without this the SSRF guard would
    refuse the fixtures for not existing, and every Y test would pass for the
    wrong reason.
    """

    def fake(host, port, *args, **kwargs):
        return [
            (
                socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                ("93.184.216.34", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


def _rows(*pairs: tuple[str, str]) -> list[CareersResult]:
    """Search results in the order they came back, 1-based rank."""
    return [
        CareersResult(url=url, title=title, rank=rank)
        for rank, (url, title) in enumerate(pairs, start=1)
    ]


def _client(handler) -> httpx.AsyncClient:
    # ``follow_redirects=False`` matches the real client: every hop is followed
    # manually by ``guarded_get`` so it can be revalidated first.
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    )


def _trust_everything(_url: str) -> bool:
    return True


# ---------------------------------------------------------------------------
# T — the ranker. No network, real corpus rows.
# ---------------------------------------------------------------------------

ATLASSIAN = _rows(
    ("https://www.atlassian.com/company/careers",
     "Atlassian Careers: Join the Team | Atlassian"),
    ("https://www.atlassian.com/company/careers/all-jobs",
     "Atlassian Jobs: View Listings for Open Positions | Atlassian"),
    ("https://www.atlassian.com/company/careers/engineering",
     "Engineering careers | Atlassian"),
    ("https://www.atlassian.com/company/careers/earlycareers",
     "Atlassian Internships: Students and New Grads | Atlassian"),
)

# The case that proves the TITLE is doing independent work: spacex.com serves
# `<title>SpaceX</title>` on every one of these pages, so the served HTML cannot
# tell them apart. The search engine's title can.
SPACEX = _rows(
    ("https://www.spacex.com/careers/", "SpaceX - Careers"),
    ("https://www.spacex.com/careers/jobs", "SpaceX - Jobs"),
    ("https://www.spacex.com/careers/jobs/?type=international", "SpaceX - Jobs"),
    ("https://www.spacex.com/careers/jobs/?type=intern", "SpaceX - Jobs"),
)

IBM = _rows(
    ("https://www.ibm.com/careers", "Define your career with IBM"),
    ("https://www.ibm.com/careers/search", "Search jobs | IBM Careers"),
    ("https://www.ibm.com/careers/career-opportunities", "Entry Level Jobs | IBM Careers"),
    ("https://www.ibm.com/careers/culture", "Culture | IBM Careers"),
)

CISCO = _rows(
    ("https://careers.cisco.com/global/en", "Careers at Cisco"),
    ("https://careers.cisco.com/global/en/search-results", "Job Openings - Cisco Careers"),
    ("https://careers.cisco.com/global/en/home", "Careers at Cisco"),
    ("https://careers.cisco.com/global/en/india", "Jobs in India – Cisco Careers"),
)

STRIPE = _rows(
    ("https://stripe.com/jobs",
     "Stripe Careers | Shape the Future of the Global Economy"),
    ("https://stripe.com/careers/search", "Stripe Careers | Open Roles"),
    ("https://stripe.com/careers/emerging-talent",
     "Stripe Careers | Stripe Internship and Early Career Opportunities"),
)


@pytest.mark.parametrize(
    "rows, expected",
    [
        (ATLASSIAN, "https://www.atlassian.com/company/careers/all-jobs"),
        (SPACEX, "https://www.spacex.com/careers/jobs"),
        (IBM, "https://www.ibm.com/careers/search"),
        (CISCO, "https://careers.cisco.com/global/en/search-results"),
        (STRIPE, "https://stripe.com/careers/search"),
    ],
    ids=["atlassian", "spacex", "ibm", "cisco", "stripe"],
)
def test_the_job_list_beats_the_landing_page(
    rows: list[CareersResult], expected: str
) -> None:
    """Each of these was answered with ``rows[0]`` — the marketing page — until now."""
    assert rows[0].url != expected, "fixture no longer demonstrates the bug"
    assert rank_careers_results(rows)[0].url == expected


def test_a_single_posting_is_never_offered() -> None:
    """A discovery run pointed at one job posting finds one job.

    These are Epic Games' real results: four of the six are individual postings,
    and the two collection pages are what may be offered.
    """
    rows = _rows(
        ("https://epicgames.com/careers/jobs/6144540004?gh_jid=6144540004",
         "Senior Engine Programmer, Unreal Cloud Services at Epicgames"),
        ("https://www.epicgames.com/site/careers/jobs",
         "Epic Games Careers, Jobs and Employment Opportunity - Epic Games"),
        ("https://epicgames.com/careers/jobs/6145723004?gh_jid=6145723004",
         "Senior Game Designer at Epicgames"),
        ("https://www.epicgames.com/site/en-US/careers",
         "Epic Games Careers, Jobs and Employment Opportunity - Epic Games"),
    )
    ranked = rank_careers_results(rows)

    assert [row.url for row in ranked] == [
        "https://www.epicgames.com/site/careers/jobs",
        "https://www.epicgames.com/site/en-US/careers",
    ]
    assert all(not is_single_posting_url(row.url) for row in ranked)


def test_nothing_but_postings_offers_nothing() -> None:
    """Saying we found nothing beats offering a page with one job on it.

    The UI already knows how to say the first one; the second spends a paid
    discovery run.
    """
    rows = _rows(
        ("https://careers.example.com/positions/8078019/", "Staff Backend Engineer"),
        ("https://careers.example.com/positions/8077995/", "Staff Software Engineer"),
    )
    assert rank_careers_results(rows) == []


def test_results_that_score_the_same_keep_search_order() -> None:
    """The fallback is the old behaviour, not an arbitrary one."""
    rows = _rows(
        ("https://careers.example.com/a", ""),
        ("https://careers.example.com/b", ""),
        ("https://careers.example.com/c", ""),
    )
    assert [row.url for row in rank_careers_results(rows)] == [
        "https://careers.example.com/a",
        "https://careers.example.com/b",
        "https://careers.example.com/c",
    ]


def test_a_dead_page_demotes_itself_without_a_fetch() -> None:
    """90 of the corpus's 364 own-domain results were not 200, and the search
    engine titles them "Page not found" — so T needs no liveness probe."""
    rows = _rows(
        ("https://careers.example.com/job-search", "Page not found - Careers at Example"),
        ("https://careers.example.com/openings", "Open positions at Example"),
    )
    assert rank_careers_results(rows)[0].url == "https://careers.example.com/openings"


# ---------------------------------------------------------------------------
# Y — derive the list from the job URLs. Pure half.
# ---------------------------------------------------------------------------

# Airbnb's real results: the list URL is NOT among them at any rank, so no
# ranker can reach it. Only the postings betray where it lives.
AIRBNB = _rows(
    ("https://careers.airbnb.com/", "Home - Careers at Airbnb"),
    ("https://careers.airbnb.com/positions/8078019/",
     "Staff Backend Engineer, Host Pricing & Availability - Careers at Airbnb"),
    ("https://careers.airbnb.com/positions/8077995/",
     "Staff Software Engineer, Guest & Host - Careers at Airbnb"),
    ("https://careers.airbnb.com/positions/7948314/",
     "Lead, Advanced Analytics, Acquisition - Careers at Airbnb"),
)


def test_the_list_url_is_derived_from_the_job_urls() -> None:
    assert derive_list_url(AIRBNB) == "https://careers.airbnb.com/positions"


def test_one_posting_is_not_a_cluster() -> None:
    """One detail page says nothing about whether its parent is a real page."""
    rows = _rows(
        ("https://careers.example.com/", "Careers at Example"),
        ("https://careers.example.com/positions/8078019/", "Staff Backend Engineer"),
    )
    assert derive_list_url(rows) is None


def test_an_id_at_the_root_has_no_parent_to_derive() -> None:
    """The parent would be the bare host, which is not a job list."""
    rows = _rows(
        ("https://careers.example.com/8078019", "Staff Backend Engineer"),
        ("https://careers.example.com/8077995", "Staff Software Engineer"),
    )
    assert derive_list_url(rows) is None


def test_the_biggest_cluster_wins() -> None:
    rows = _rows(
        ("https://careers.example.com/archive/9000001", "Old job"),
        ("https://careers.example.com/positions/8078019", "Staff Backend Engineer"),
        ("https://careers.example.com/positions/8077995", "Staff Software Engineer"),
        ("https://careers.example.com/archive/9000002", "Another old job"),
        ("https://careers.example.com/positions/7948314", "Lead, Advanced Analytics"),
    )
    assert derive_list_url(rows) == "https://careers.example.com/positions"


# ---------------------------------------------------------------------------
# Y — the verification fetch. One request, and it fails open.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_derived_list_that_answers_200_is_offered() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="<html><title>Positions</title></html>")

    async with _client(handler) as http:
        chosen = await pick_careers_url(
            AIRBNB, http, is_trusted=_trust_everything
        )

    assert chosen == "https://careers.airbnb.com/positions"
    assert seen == ["https://careers.airbnb.com/positions"], "exactly one fetch"


@pytest.mark.asyncio
async def test_a_403_falls_back_to_the_ranker() -> None:
    """Tesla, Citadel, Epic Games and Dell all 403 us. A verification that read
    that as "reject" would discard every candidate on a Cloudflare-fronted site."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    async with _client(handler) as http:
        chosen = await pick_careers_url(AIRBNB, http, is_trusted=_trust_everything)

    # Nothing is lost: the ranker still answers, with the only non-posting row.
    assert chosen == "https://careers.airbnb.com/"


@pytest.mark.asyncio
async def test_a_redirect_to_another_page_falls_back_to_the_ranker() -> None:
    """Walmart's shape: ``/us/en/jobs`` derives, and bounces to ``/us/en/home``.

    A 200 at the end of that chain is a 200 for a different page.
    """
    rows = _rows(
        ("https://careers.walmart.com/us/en", "Walmart Careers"),
        ("https://careers.walmart.com/us/en/jobs/1234567", "Software Engineer III"),
        ("https://careers.walmart.com/us/en/jobs/1234568", "Data Scientist"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/us/en/jobs":
            return httpx.Response(
                302, headers={"location": "https://careers.walmart.com/us/en/home"}
            )
        return httpx.Response(200, text="home")

    async with _client(handler) as http:
        chosen = await pick_careers_url(rows, http, is_trusted=_trust_everything)

    assert derive_list_url(rows) == "https://careers.walmart.com/us/en/jobs"
    assert chosen == "https://careers.walmart.com/us/en"


@pytest.mark.asyncio
async def test_a_redirect_to_another_host_falls_back_to_the_ranker() -> None:
    """Microsoft's shape: the derived host answers by sending you somewhere else."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "careers.airbnb.com":
            return httpx.Response(
                302, headers={"location": "https://someoneelse.example/careers"}
            )
        return httpx.Response(200, text="not airbnb")

    async with _client(handler) as http:
        chosen = await pick_careers_url(AIRBNB, http, is_trusted=_trust_everything)

    assert chosen == "https://careers.airbnb.com/"


@pytest.mark.asyncio
async def test_a_same_site_redirect_onto_the_real_list_is_kept() -> None:
    """Riot Games' shape, and why the prefix is not segment-bounded: their detail
    URLs sit under ``/en/work-with-us/job``, which the site redirects to
    ``/en/work-with-us/jobs`` — their real job list."""
    rows = _rows(
        ("https://www.riotgames.com/en/work-with-us", "Careers | Riot Games"),
        ("https://www.riotgames.com/en/work-with-us/job/8078019", "Software Engineer"),
        ("https://www.riotgames.com/en/work-with-us/job/8077995", "Data Scientist"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/work-with-us/job":
            return httpx.Response(
                301,
                headers={"location": "https://www.riotgames.com/en/work-with-us/jobs"},
            )
        return httpx.Response(200, text="jobs")

    async with _client(handler) as http:
        chosen = await pick_careers_url(rows, http, is_trusted=_trust_everything)

    assert chosen == "https://www.riotgames.com/en/work-with-us/jobs"


@pytest.mark.asyncio
async def test_a_derived_url_on_an_untrusted_host_is_not_even_fetched() -> None:
    """The trust filter still decides what may be offered. A derived URL is a NEW
    URL, so it faces the same host test the rows already passed — before the
    fetch, so a host we would never offer is never contacted either."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text="ok")

    async with _client(handler) as http:
        chosen = await pick_careers_url(
            AIRBNB, http, is_trusted=lambda url: False
        )

    assert seen == []
    assert chosen == "https://careers.airbnb.com/"


@pytest.mark.asyncio
async def test_the_verification_fetch_goes_through_the_ssrf_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A URL derived from third-party search results is a third-party URL."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        seen.append(str(request.url))
        return httpx.Response(200, text="secret")

    def loopback(host, port, *args, **kwargs):
        return [
            (
                socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                ("127.0.0.1", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", loopback)
    async with _client(handler) as http:
        verified = await verify_list_url(
            "https://careers.airbnb.com/positions", http
        )

    assert verified is None
    assert seen == []


@pytest.mark.asyncio
async def test_a_transport_failure_falls_back_to_the_ranker() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    async with _client(handler) as http:
        chosen = await pick_careers_url(AIRBNB, http, is_trusted=_trust_everything)

    assert chosen == "https://careers.airbnb.com/"


@pytest.mark.asyncio
async def test_no_rows_at_all_offers_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200)

    async with _client(handler) as http:
        assert await pick_careers_url([], http, is_trusted=_trust_everything) is None
