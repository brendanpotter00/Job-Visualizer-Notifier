"""Which trusted careers URL we offer — the job list, not the brochure.

Every fixture in the T section is a VERBATIM slice of a real
``"{company} careers"`` search: the URLs and the titles are what Browserbase
returned on 2026-09-03, trimmed to the rows that decide the answer. The first row
of each is what the old code offered (first trusted result, in search rank order)
and is wrong every time — that is the bug.

THE CRITERION CHANGED, and that is why several expectations below are ``None``.
The study this module was built from scored an answer correct when its HOST named
the company, so ``www.oracle.com/careers/`` — a marketing page — was recorded as
Oracle's right answer and the module was measured "16 of 28" against labels like
that one. The bar is now "the URL demonstrably leads to postings", checked by
loading each answer in a real browser and counting job links. Re-measured that way
over the same 28-company corpus: **21 land on a real job list, 1 on a page with no
jobs, 6 offer nothing at all** — against 18 / 10 / 0 for the code this replaces.
Offering nothing is the honest answer, not a regression: every one of those six
used to be handed a brochure the user would have spent a discovery run on.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from api.services.careers_page_pick import (
    CareersResult,
    derive_list_url,
    harvest_job_list_links,
    is_job_list_url,
    is_single_posting_url,
    pick_careers_url,
    rank_careers_results,
    title_score,
    unscoped_variant,
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
async def test_a_403_is_not_a_rejection_of_the_candidate() -> None:
    """Tesla, Citadel, Epic Games and Dell all 403 us. A verification that read
    that as "reject" would discard every candidate on a Cloudflare-fronted site.

    It falls through to the ranker exactly as before — but the ranker now has
    nothing OFFERABLE here, because ``careers.airbnb.com/`` is a landing page and
    the rest of the rows are single postings. "Paste the URL of their careers
    page" beats a brochure the user would spend a discovery run on.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="denied")

    async with _client(handler) as http:
        chosen = await pick_careers_url(AIRBNB, http, is_trusted=_trust_everything)

    assert chosen is None


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
    # `/us/en` is the landing page, not the list, and `/us/en/home` is what the
    # site itself redirected to — so there is nothing here to offer.
    assert chosen is None


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

    assert chosen is None


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

    # The DERIVED url is never contacted. The landing page still is — with nothing
    # offerable in the results, reading it is the only way left to find a list —
    # but nothing it links to can pass a trust test that refuses everything.
    assert "https://careers.airbnb.com/positions" not in seen
    assert chosen is None


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
async def test_a_transport_failure_is_not_an_error() -> None:
    """It costs the mechanism, never the request."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    async with _client(handler) as http:
        chosen = await pick_careers_url(AIRBNB, http, is_trusted=_trust_everything)

    assert chosen is None


@pytest.mark.asyncio
async def test_no_rows_at_all_offers_nothing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200)

    async with _client(handler) as http:
        assert await pick_careers_url([], http, is_trusted=_trust_everything) is None


# ---------------------------------------------------------------------------
# The offer bar — is it a job LIST, or a page about working here?
#
# `oracle.com/careers/` used to be recorded as the correct answer for Oracle,
# because the criterion was "a URL on the company's own domain" and a brochure
# satisfies that perfectly. These are the rows that criterion could not separate.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        # Real job lists, all measured to render postings.
        ("https://careers.oracle.com/en/sites/jobsearch/jobs?location=US", True),
        ("https://www.atlassian.com/company/careers/all-jobs", True),
        ("https://www.github.careers/careers-home/jobs", True),
        ("https://careers.amd.com/careers-home/jobs", True),
        ("https://www.metacareers.com/jobsearch/", True),
        ("https://www.ibm.com/careers/search", True),
        ("https://careers.cisco.com/global/en/search-results", True),
        ("https://careers.airbnb.com/positions/", True),
        ("https://www.disneycareers.com/en/search_jobs?k=", True),
        ("https://jobs.sap.com/?locale=en_US", True),
        # Brochures. Every one of these is on the company's own domain, which is
        # exactly why the old criterion called them right.
        ("https://www.oracle.com/careers/", False),
        ("https://www.amd.com/en/corporate/careers.html", False),
        ("https://careers.airbnb.com/", False),
        ("https://www.atlassian.com/company/careers", False),
        ("https://facebook.it/careers/", False),
        ("https://www.pokemoto.com/careers", False),
        ("https://www.metacareers.com/careerprograms/research?tab=Full-Time", False),
        # THE LAST SEGMENT, not any segment. A list word in the middle of a path
        # is a directory name, and what follows it is what the page is about.
        ("https://oracle.com/careers/opportunities/engineering-development/", False),
        ("https://jobs.ebayinc.com/us/en/emerging-talent", False),
        ("https://jobs.uber.com/en/", False),
    ],
)
def test_the_offer_bar_separates_a_list_from_a_brochure(
    url: str, expected: bool
) -> None:
    assert is_job_list_url(url) is expected


def test_links_are_harvested_only_when_they_are_lists() -> None:
    """Oracle's page, verbatim. Every other link on it is a real link the page
    publishes, and none of them is a list of open roles."""
    body = (
        '<a href="/en/sites/jobsearch/jobs?location=US">Search jobs</a>'
        '<a href="/en/sites/jobsearch/join-talent-community">Join our network</a>'
        '<a href="/en/sites/jobsearch/job/334096/">Senior Software Engineer</a>'
        '<a href="/life-at-oracle/">Life at Oracle</a>'
        '<a href="mailto:jobs@oracle.com">Email us</a>'
        '<a href="#main">Skip to content</a>'
    )
    harvested = harvest_job_list_links(body, "https://careers.oracle.com/en/")

    assert harvested == [
        (
            "https://careers.oracle.com/en/sites/jobsearch/jobs?location=US",
            "Search jobs",
        )
    ], "the talent community, one posting, a brochure, mailto: and #anchors are not"


def test_the_link_text_separates_two_links_the_path_cannot() -> None:
    """A link's words are the same kind of evidence as a search result's title,
    and sometimes the only kind: these two paths are identical."""
    body = (
        '<a href="/jobsearch/?teams[0]=Research">View full-time research jobs</a>'
        '<a href="/jobsearch/">Jobs</a>'
    )
    harvested = harvest_job_list_links(body, "https://www.metacareers.com/")

    assert [text for _, text in harvested] == [
        "View full-time research jobs",
        "Jobs",
    ]
    # "re|search jobs" is not "search jobs" — a substring test scored the filtered
    # slice 9 against the whole list's 5 and picked the wrong one.
    assert title_score("View full-time research jobs") == title_score("Jobs")


@pytest.mark.asyncio
async def test_the_page_is_asked_where_its_board_is_when_search_has_nothing() -> None:
    """THE ORACLE CLASS. The real board is on a subdomain that search never
    returned — not the list, not a posting under it — so it can be neither ranked
    nor derived. The company's own careers page is the only place it exists."""
    rows = _rows(
        ("https://www.oracle.com/careers/", "Oracle Careers | Job Search | Oracle"),
        ("https://www.oracle.com/careers/students-grads/", "Students and Graduates"),
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            text=(
                '<a href="https://careers.oracle.com/en/sites/jobsearch/jobs">'
                "Search jobs</a>"
                '<a href="https://careers.oracle.com/en/sites/jobsearch/'
                'join-talent-community">Join our network</a>'
            ),
        )

    async with _client(handler) as http:
        chosen = await pick_careers_url(rows, http, is_trusted=_trust_everything)

    assert chosen == "https://careers.oracle.com/en/sites/jobsearch/jobs"
    assert seen == ["https://www.oracle.com/careers/"], "one page read"


@pytest.mark.asyncio
async def test_a_harvested_link_on_an_untrusted_host_is_not_offered() -> None:
    """``trusted_careers_urls`` is still the filter. A careers page may link
    anywhere, and a job list on a host that does not name the company is
    ``resumeadapter.com`` arriving through a new door."""
    rows = _rows(("https://www.oracle.com/careers/", "Oracle Careers"))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text='<a href="https://resumeadapter.com/jobs">Search jobs</a>'
        )

    async with _client(handler) as http:
        chosen = await pick_careers_url(
            rows, http, is_trusted=lambda url: "oracle.com" in url
        )

    assert chosen is None


@pytest.mark.asyncio
async def test_a_list_search_already_returned_beats_a_link_on_a_page() -> None:
    """ATLASSIAN, and why Z is last. Its cluster derives
    ``join.atlassian.com/atlassian-talent-community/jobs``, which redirects to a
    signup form whose one job link is ``join.atlassian.com/jobs`` — while
    ``/company/careers/all-jobs``, the right answer, was in the results all along.
    A page's own links are weaker evidence than a result search ranked."""
    rows = ATLASSIAN + _rows(
        ("https://join.atlassian.com/atlassian-talent-community/jobs/12345", "SWE"),
        ("https://join.atlassian.com/atlassian-talent-community/jobs/12346", "PM"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "join.atlassian.com" and "12345" not in str(request.url):
            return httpx.Response(
                302,
                headers={"location": "https://join.atlassian.com/talentcommunity/form"},
            )
        return httpx.Response(
            200, text='<a href="https://join.atlassian.com/jobs">here</a>'
        )

    async with _client(handler) as http:
        chosen = await pick_careers_url(rows, http, is_trusted=_trust_everything)

    assert chosen == "https://www.atlassian.com/company/careers/all-jobs"


@pytest.mark.asyncio
async def test_one_page_read_serves_both_the_check_and_the_links() -> None:
    """EBAY. The cluster derives ``jobs.ebayinc.com/us/en/job``, which answers 410
    — and the body of that 410 links to ``/us/en/search-results``, eBay's real
    list. Fetching for the check and then declining to look at what came back
    would spend the budget and throw the answer away."""
    rows = _rows(
        ("https://jobs.ebayinc.com/us/en/emerging-talent", "Emerging Talent"),
        ("https://jobs.ebayinc.com/us/en/job/R0068048/Sr-DBA", "Sr NoSQL DBA"),
        ("https://jobs.ebayinc.com/us/en/job/R0068049/Staff-SWE", "Staff SWE"),
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            410, text='<a href="/us/en/search-results">Search Jobs</a>'
        )

    async with _client(handler) as http:
        chosen = await pick_careers_url(rows, http, is_trusted=_trust_everything)

    assert chosen == "https://jobs.ebayinc.com/us/en/search-results"
    assert seen == ["https://jobs.ebayinc.com/us/en/job"], "one page read"


@pytest.mark.asyncio
async def test_the_recruiting_host_wins_over_the_corporate_one() -> None:
    """APPLE. Its design brochure offers "Search apple.com" →
    ``apple.com/us/search``, a product search that has never had a job on it, and
    "Search Roles" → ``jobs.apple.com/en-us/search``. Same words, same path shape,
    same empty query — the only difference is that one leaves for the recruiting
    site."""
    rows = _rows(
        ("https://www.apple.com/careers/us/work-at-apple/teams/design.html",
         "Design - Careers at Apple"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                '<a href="https://www.apple.com/us/search">Search apple.com</a>'
                '<a href="https://jobs.apple.com/en-us/search">Search Roles</a>'
            ),
        )

    async with _client(handler) as http:
        chosen = await pick_careers_url(rows, http, is_trusted=_trust_everything)

    assert chosen == "https://jobs.apple.com/en-us/search"


# ---------------------------------------------------------------------------
# The query — a filter on the list, or the name of the list?
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        # ORACLE. Every "Search jobs" link on oracle.com/careers/ is scoped to one
        # country, and a recipe inherits its capture's scope — follow the link as
        # published and we build a US-only scraper for a company hiring worldwide.
        (
            "https://careers.oracle.com/en/sites/jobsearch/jobs"
            "?location=United%20States&locationId=300000000149325",
            "https://careers.oracle.com/en/sites/jobsearch/jobs",
        ),
        # GREENHOUSE'S EMBED ASSET, and the reason this is a whitelist. `?for=` is
        # not a filter, it IS the board — `_greenhouse_candidate` reads the token
        # out of it, and the bare path belongs to nobody.
        ("https://boards.greenhouse.io/embed/job_board/js?for=acme", None),
        # EIGHTFOLD, the same shape through a different parameter.
        ("https://app.eightfold.ai/careers?domain=netflix.com", None),
        # ONE UNRECOGNISED NAME KEEPS THE WHOLE QUERY. We cannot tell what
        # `locale` does to this page, so we do not touch it.
        ("https://jobs.sap.com/?locale=en_US", None),
        ("https://careers.example.com/jobs?location=NY&team=Eng", 
         "https://careers.example.com/jobs"),
        # Nothing to drop.
        ("https://careers.example.com/jobs", None),
    ],
    ids=["oracle", "greenhouse-for", "eightfold-domain", "unknown-param",
         "two-filters", "no-query"],
)
def test_a_filter_is_dropped_and_an_identifier_is_not(
    url: str, expected: str | None
) -> None:
    assert unscoped_variant(url) == expected


@pytest.mark.asyncio
async def test_the_whole_list_is_offered_when_it_is_really_there() -> None:
    """ORACLE, end to end through the picker: the page publishes only the US view,
    and what we offer is the list itself."""
    scoped = (
        "https://careers.oracle.com/en/sites/jobsearch/jobs"
        "?location=United%20States&locationId=300000000149325"
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.query:
            return httpx.Response(404)
        if "careers.oracle.com" in str(request.url):
            return httpx.Response(200, text="<html>every job</html>")
        return httpx.Response(200, text=f'<a href="{scoped}">Search jobs</a>')

    async with _client(handler) as http:
        chosen = await pick_careers_url(
            _rows(("https://www.oracle.com/careers/", "Careers at Oracle")),
            http,
            is_trusted=_trust_everything,
        )

    assert chosen == "https://careers.oracle.com/en/sites/jobsearch/jobs"
    # The page read that found the board, then one request to prove the filter is
    # droppable. The scoped URL is never fetched and never offered.
    assert seen == [
        "https://www.oracle.com/careers/",
        "https://careers.oracle.com/en/sites/jobsearch/jobs",
    ]


@pytest.mark.asyncio
async def test_a_bare_path_that_is_not_a_page_keeps_its_filter() -> None:
    """FAILING OPEN. Some sites really do 404 the unfiltered path — the filter is
    then part of what makes the page exist, whatever its name suggests — and the
    scoped list we already had is a great deal better than nothing."""
    scoped = "https://careers.example.com/en/jobs?location=Berlin"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.query:
            return httpx.Response(200, text="<html>berlin jobs</html>")
        if str(request.url).endswith("/en/jobs"):
            return httpx.Response(404)
        return httpx.Response(200, text=f'<a href="{scoped}">Search jobs</a>')

    async with _client(handler) as http:
        chosen = await pick_careers_url(
            _rows(("https://www.example.com/careers/", "Careers")),
            http,
            is_trusted=_trust_everything,
        )

    assert chosen == scoped


@pytest.mark.asyncio
async def test_the_unscoped_url_faces_the_host_filter_before_it_is_fetched() -> None:
    """Dropping a query cannot change a host, and the rewritten URL is asked anyway
    — the module's invariant is that everything it constructs is re-checked, and an
    invariant with an exception is not one."""
    asked: list[str] = []
    fetched: list[str] = []

    def is_trusted(url: str) -> bool:
        asked.append(url)
        return "?" in url or "careers/" in url

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        return httpx.Response(200, text="<html>ok</html>")

    async with _client(handler) as http:
        chosen = await pick_careers_url(
            _rows(("https://careers.example.com/jobs?location=NY", "Search jobs")),
            http,
            is_trusted=is_trusted,
        )

    assert chosen == "https://careers.example.com/jobs?location=NY"
    assert "https://careers.example.com/jobs" in asked
    assert fetched == [], "a host we would not offer is never contacted"
