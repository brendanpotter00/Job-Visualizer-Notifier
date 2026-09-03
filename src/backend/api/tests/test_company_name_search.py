"""Unit tests for rung A of the name ladder — one search call, scored locally.

Everything runs through ``httpx.MockTransport``; no live network in CI. The
payloads replay real Browserbase Search responses captured 2026-09-01, including
the two that matter most: the Cisco result (the owner's headline example) and the
Databricks/Guidehouse collision that the name gate exists to stop.
"""

from __future__ import annotations

import httpx
import pytest

from api.config import settings
from api.services import company_name_search as cns
from api.services.ats_link_resolver import AtsCandidate
from api.services.company_name_search import (
    NameSearchUnavailable,
    build_query,
    is_aggregator,
    normalize_name,
    search_ats_candidates,
)


def _results(*urls: str) -> dict:
    return {
        "requestId": "test",
        "query": "test",
        "results": [
            {"id": u, "url": u, "title": f"title for {u}"} for u in urls
        ],
    }


def _client(payload: dict, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == cns._SEARCH_API
        assert request.headers["X-BB-API-Key"] == "test-key"
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "browserbase_api_key", "test-key", raising=False)


# ---------------------------------------------------------------------------
# The query
# ---------------------------------------------------------------------------


def test_query_names_all_six_ats_hosts() -> None:
    """The hosts ARE the strategy — 76% with them, 41% with a prose instruction."""
    query = build_query("Cisco")
    for host in (
        "myworkdayjobs.com", "greenhouse.io", "ashbyhq.com",
        "lever.co", "jobs.gem.com", "eightfold.ai",
    ):
        assert host in query
    assert query.startswith("Cisco ")


def test_query_fits_browserbase_200_char_cap_at_the_name_limit() -> None:
    """The cap is the API's, and silently blowing it would truncate the hosts off."""
    longest = "x" * cns._MAX_NAME_CHARS
    assert len(build_query(longest)) <= cns._QUERY_MAX_CHARS


@pytest.mark.asyncio
async def test_an_overlong_name_is_refused_rather_than_truncated() -> None:
    async with _client(_results()) as http:
        with pytest.raises(NameSearchUnavailable):
            await search_ats_candidates("y" * (cns._MAX_NAME_CHARS + 1), http)


# ---------------------------------------------------------------------------
# The name gate — the one that stops us scraping the wrong company
# ---------------------------------------------------------------------------


def test_normalize_name_folds_case_and_punctuation() -> None:
    assert normalize_name("Jane Street") == "janestreet"
    assert normalize_name("  Y-Combinator!  ") == "ycombinator"


@pytest.mark.parametrize(
    "typed, token, expected",
    [
        ("Cisco", "cisco", True),
        ("Jane Street", "janestreet", True),
        ("Anthropic", "anthropic", True),
        # A longer token that still LEADS with the name.
        ("Ramp", "ramp-payments", True),
        # A longer typed name that leads with the token — someone typing the legal
        # name at a board registered under the short one.
        ("Cisco Systems", "cisco", True),
        # The measured near-misses, and why the rule is a prefix rather than
        # anything looser. Edit distance accepts `poki` (a Dutch games site);
        # plain substring accepts `river` (a bitcoin company) because it really
        # is inside "hudsonrivertrading".
        ("Poke", "poki", False),
        ("Hudson River Trading", "river", False),
        ("Databricks", "guidehouse", False),
        ("Retool", "generalmotors", False),
        ("Snap", "gc-ai", False),
    ],
)
def test_name_gate_is_containment_never_fuzzy(
    typed: str, token: str, expected: bool
) -> None:
    candidate = AtsCandidate(
        ats="greenhouse", board_token=token, provider_config={}, source_url="https://x"
    )
    assert cns._names_match(typed, candidate) is expected


@pytest.mark.parametrize(
    "typed, token, expected",
    [
        # A one- or two-character prefix matches almost anything, and the request
        # model allows a one-character name — so "A" would prefix-match `acme`,
        # probe non-empty, and be AUTO-ADDED. Below the floor, exact only.
        ("A", "acme", False),
        ("Ac", "acme", False),
        ("IBM", "ibmcareers", False),
        # Exact still wins at any length, so short real names keep working.
        ("GM", "gm", True),
        ("IBM", "ibm", True),
        # At or above the floor the prefix rule applies as normal.
        ("Acme", "acmecorp", True),
    ],
)
def test_short_names_require_an_exact_match(
    typed: str, token: str, expected: bool
) -> None:
    candidate = AtsCandidate(
        ats="greenhouse", board_token=token, provider_config={}, source_url="https://x"
    )
    assert cns._names_match(typed, candidate) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [[], "nope", 42, {"results": "not-a-list"}])
async def test_a_malformed_response_is_unavailable_not_a_500(body: object) -> None:
    """A bare `[]` body would make `.get` raise AttributeError, escaping
    NameSearchUnavailable and turning an honest 503 into a 500 — "search
    misbehaved" would reach the user as "your employer cannot be tracked"."""
    async with _client(body) as http:  # type: ignore[arg-type]
        with pytest.raises(NameSearchUnavailable):
            await search_ats_candidates("Cisco", http)


@pytest.mark.asyncio
async def test_a_non_object_result_row_is_skipped_not_fatal() -> None:
    payload = {
        "requestId": "t",
        "query": "t",
        "results": [
            "a bare string",
            None,
            {"id": "x", "url": "https://boards.greenhouse.io/figma", "title": "Figma"},
        ],
    }
    async with _client(payload) as http:
        candidates, _, _ = await search_ats_candidates("Figma", http)

    assert [c.candidate.board_token for c in candidates] == ["figma"]


@pytest.mark.parametrize(
    "typed, token, expected",
    [
        # THE REVERSE DIRECTION MUST LAND ON A WORD BOUNDARY. A bare prefix
        # auto-adds Meta's board for a Metabase search and Apple's for Applebee's
        # — the exact wrong-company failure this gate exists to stop.
        ("Metabase", "meta", False),
        ("Applebee's", "apple", False),
        ("Snapdragon", "snap", False),
        # ...while the case the reverse direction exists for still works.
        ("Cisco Systems", "cisco", True),
        ("Ramp Network", "ramp", True),
    ],
)
def test_the_typed_name_may_only_extend_a_token_at_a_word_boundary(
    typed: str, token: str, expected: bool
) -> None:
    candidate = AtsCandidate(
        ats="greenhouse", board_token=token, provider_config={}, source_url="https://x"
    )
    assert cns._names_match(typed, candidate) is expected


@pytest.mark.parametrize("slug", ["Global", "External", "Careers", "Campus"])
def test_a_generic_career_site_slug_never_establishes_identity(slug: str) -> None:
    """`career_site_slug` is routinely an ordinary English word on real tenants.
    Letting one match means typing "Global Payments" auto-adds ANY unrelated
    company whose Workday site happens to be called `…/Global`."""
    candidate = AtsCandidate(
        ats="workday",
        board_token="someoneelse",
        provider_config={
            "base_url": "https://someoneelse.wd1.myworkdayjobs.com",
            "tenant_slug": "someoneelse",
            "career_site_slug": slug,
        },
        source_url="https://someoneelse.wd1.myworkdayjobs.com/" + slug,
    )
    assert cns._names_match(f"{slug} Payments", candidate) is False


def test_a_board_token_may_still_be_an_ordinary_word() -> None:
    """The generic-slug rule is scoped to provider_config. A company really can
    be called `global`, and its own board token is its identity."""
    candidate = AtsCandidate(
        ats="greenhouse", board_token="global", provider_config={}, source_url="https://x"
    )
    assert cns._names_match("Global", candidate) is True


def test_name_gate_reads_the_workday_career_site_slug_too() -> None:
    """Slack's board is `salesforce.wd12…/Slack` — the brand is only in the slug."""
    candidate = AtsCandidate(
        ats="workday",
        board_token="salesforce",
        provider_config={
            "base_url": "https://salesforce.wd12.myworkdayjobs.com",
            "tenant_slug": "salesforce",
            "career_site_slug": "Slack",
        },
        source_url="https://salesforce.wd12.myworkdayjobs.com/Slack",
    )
    assert cns._names_match("Slack", candidate) is True


# ---------------------------------------------------------------------------
# Scoring the results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_correct_board_is_found_and_auto_addable() -> None:
    payload = _results(
        "https://careers.cisco.com/global/en/home",
        "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers",
    )
    async with _client(payload) as http:
        candidates, careers, _ = await search_ats_candidates("Cisco", http)

    assert len(candidates) == 1
    assert candidates[0].candidate.ats == "workday"
    assert candidates[0].auto_addable is True
    assert candidates[0].rank == 2
    assert careers == ["https://careers.cisco.com/global/en/home"]


@pytest.mark.asyncio
async def test_a_live_board_owned_by_someone_else_is_gated_not_dropped() -> None:
    """THE failure mode. Guidehouse's board came back at rank 1 for `Databricks`
    with 794 real jobs — it passes every automated check we own. It must survive
    as a candidate the user can see and reject, but must never be auto-added."""
    payload = _results("https://guidehouse.wd1.myworkdayjobs.com/External")
    async with _client(payload) as http:
        candidates, _, _ = await search_ats_candidates("Databricks", http)

    assert len(candidates) == 1
    assert candidates[0].auto_addable is False


@pytest.mark.asyncio
async def test_scoring_looks_past_the_first_result() -> None:
    """Measured: the right board is first only half the time it is present at all."""
    payload = _results(
        *[f"https://example.com/page-{n}" for n in range(20)],
        "https://jobs.ashbyhq.com/raindrop",
    )
    async with _client(payload) as http:
        candidates, _, _ = await search_ats_candidates("Raindrop", http)

    assert [c.candidate.board_token for c in candidates] == ["raindrop"]
    assert candidates[0].rank == 21


@pytest.mark.asyncio
async def test_aggregators_are_dropped_from_both_lists() -> None:
    payload = _results(
        "https://www.linkedin.com/jobs/cisco",
        "https://www.indeed.com/cmp/Cisco/jobs",
        "https://careers.cisco.com/",
    )
    async with _client(payload) as http:
        candidates, careers, _ = await search_ats_candidates("Cisco", http)

    assert candidates == []
    assert careers == ["https://careers.cisco.com/"]


@pytest.mark.asyncio
async def test_the_trace_counts_what_actually_happened() -> None:
    """The add page narrates a search as steps, and every step names a number
    from here. So the arithmetic has to hold: `results - filtered` is what got
    scored, and `boards` is how many of those resolved."""
    payload = _results(
        "https://www.linkedin.com/jobs/cisco",
        "https://careers.cisco.com/",
        "https://cisco.wd5.myworkdayjobs.com/Cisco_Careers",
        "https://boards.greenhouse.io/cisco-meraki",
    )
    async with _client(payload) as http:
        candidates, _, trace = await search_ats_candidates("Cisco", http)

    assert trace.query == build_query("Cisco")
    assert trace.results == 4
    assert trace.filtered == 1  # LinkedIn, and nothing else
    assert trace.results - trace.filtered == 3  # what scoring actually saw
    assert trace.boards == len(candidates) == 2


@pytest.mark.asyncio
async def test_the_traced_query_is_the_one_that_was_sent() -> None:
    """Reported verbatim rather than rebuilt: a trace that disagreed with the
    wire would be the page confidently showing a query nobody ran."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.append(json.loads(request.content)["query"])
        return httpx.Response(200, json=_results())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        _, _, trace = await search_ats_candidates("Jane Street", http)

    assert sent == [trace.query]


@pytest.mark.asyncio
async def test_the_fallback_prefers_the_companys_own_domain() -> None:
    """The fallback URL is what a user accepts to start a PAID discovery, so
    handing back an aggregator spends money and one of their monthly adds.
    Measured: `Databricks` really returned `scoutify.com/companies/databricks/`
    ahead of anything on databricks.com, and scoutify is not on any denylist."""
    payload = _results(
        "https://scoutify.com/companies/databricks/",
        "https://tryjeremy.com/companies/databricks",
        "https://www.databricks.com/company/careers/open-positions",
    )
    async with _client(payload) as http:
        _, careers, _ = await search_ats_candidates("Databricks", http)

    assert careers[0] == "https://www.databricks.com/company/careers/open-positions"


@pytest.mark.parametrize(
    "company, url, expected",
    [
        ("Databricks", "https://www.databricks.com/careers", True),
        # A multiword name still owns its own domain. `normalize_name` strips the
        # space, so "ciscosystems" matches no label of `cisco.com` — and the real
        # careers page would lose to whatever ranked above it, which is the URL
        # then offered for a PAID discovery run.
        ("Cisco Systems", "https://cisco.com/careers", True),
        ("Jane Street Capital", "https://www.janestreet.com/join", True),
        # ...but the first word only counts above the length floor, so a
        # two-character one cannot claim an unrelated host.
        ("GM Financial", "https://www.figma.com/careers", False),
        # A SHORT identity matches a whole label only. As a prefix "GM" claims
        # `gmc.com` and "HP" claims `hpe.com` — different companies, and the URL
        # that wins here is the one offered for a paid discovery run.
        ("GM", "https://gmc.com/careers", False),
        ("HP", "https://hpe.com/jobs", False),
        # The exact label still matches at any length, so the real ones work.
        ("GM", "https://gm.com/careers", True),
        ("HP", "https://hp.com/jobs", True),
        # Same substring flaw the name gate refuses: `gm` is inside `figma`.
        ("GM", "https://www.figma.com/careers", False),
        ("Apple", "https://pineapple.io/jobs", False),
        ("Cisco", "https://careers.cisco.com/", True),
    ],
)
def test_fallback_ownership_is_per_host_label(
    company: str, url: str, expected: bool
) -> None:
    # The candidate goes SECOND so it can only reach the front by actually
    # winning the ownership test — the sort is stable, so a first-placed URL
    # would stay first either way and the assertion would prove nothing.
    other = "https://unrelated.example/x"
    ranked = cns._rank_careers_urls(company, [other, url])
    assert (ranked[0] == url) is expected


@pytest.mark.asyncio
async def test_the_fallback_keeps_search_rank_between_equal_hosts() -> None:
    payload = _results(
        "https://careers.example.com/a",
        "https://careers.example.com/b",
    )
    async with _client(payload) as http:
        _, careers, _ = await search_ats_candidates("Nobody", http)

    assert careers == ["https://careers.example.com/a", "https://careers.example.com/b"]


def test_is_aggregator_does_not_match_a_lookalike_domain() -> None:
    assert is_aggregator("https://www.linkedin.com/jobs") is True
    # A company whose own domain merely CONTAINS an aggregator name is not one.
    assert is_aggregator("https://notlinkedin.example/careers") is False


@pytest.mark.parametrize(
    "url",
    [
        # `x.com` is on the list, and a substring test deleted EVERY company whose
        # domain ends with it. Measured live: this dropped all eight real Nutanix
        # careers results, so the fallback offered was an aggregator instead — and
        # the fallback is what a user hands to a PAID discovery run.
        "https://careers.nutanix.com/jobs",
        "https://jobs.wix.com/",
        "https://careers.citrix.com/",
        "https://jobs.equinix.com/",
        "https://app.eightfold.ai/careers?domain=netflix.com",
        # A lookalike that merely ENDS with an aggregator name as a bare string.
        "https://linkedin.com.attacker.example/jobs",
    ],
)
def test_a_real_careers_host_is_never_mistaken_for_an_aggregator(url: str) -> None:
    assert is_aggregator(url) is False


@pytest.mark.parametrize(
    "url", ["https://www.linkedin.com/jobs", "https://uk.indeed.com/cmp/x"]
)
def test_aggregator_subdomains_still_match(url: str) -> None:
    assert is_aggregator(url) is True


@pytest.mark.asyncio
async def test_duplicate_board_identities_collapse() -> None:
    payload = _results(
        "https://boards.greenhouse.io/figma",
        "https://job-boards.greenhouse.io/figma",
    )
    async with _client(payload) as http:
        candidates, _, _ = await search_ats_candidates("Figma", http)

    assert len(candidates) == 1


# ---------------------------------------------------------------------------
# Unavailable is not the same answer as "no board exists"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_rate_limit_is_unavailable_not_an_empty_result() -> None:
    """429 must never read as 'your employer cannot be tracked'."""
    async with _client({}, status=429) as http:
        with pytest.raises(NameSearchUnavailable):
            await search_ats_candidates("Cisco", http)


@pytest.mark.asyncio
async def test_missing_credentials_raise_before_any_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    settings_key = settings.browserbase_api_key
    try:
        settings.browserbase_api_key = None
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(NameSearchUnavailable):
                await search_ats_candidates("Cisco", http)
    finally:
        settings.browserbase_api_key = settings_key
    assert called is False


@pytest.mark.asyncio
async def test_an_empty_name_is_a_no_op_not_a_search() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        candidates, careers, trace = await search_ats_candidates("   ", http)
    assert (candidates, careers) == ([], [])
    # An empty trace, not a missing one: the response model always carries the
    # block, and a name that never reached the API genuinely searched for nothing.
    assert (trace.query, trace.results, trace.filtered, trace.boards) == ("", 0, 0, 0)
    assert called is False
