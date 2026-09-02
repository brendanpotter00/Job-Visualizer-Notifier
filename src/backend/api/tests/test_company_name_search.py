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
        candidates, careers = await search_ats_candidates("Cisco", http)

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
        candidates, _ = await search_ats_candidates("Databricks", http)

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
        candidates, _ = await search_ats_candidates("Raindrop", http)

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
        candidates, careers = await search_ats_candidates("Cisco", http)

    assert candidates == []
    assert careers == ["https://careers.cisco.com/"]


def test_is_aggregator_does_not_match_a_lookalike_domain() -> None:
    assert is_aggregator("https://www.linkedin.com/jobs") is True
    # A company whose own domain merely CONTAINS an aggregator name is not one.
    assert is_aggregator("https://notlinkedin.example/careers") is False


@pytest.mark.asyncio
async def test_duplicate_board_identities_collapse() -> None:
    payload = _results(
        "https://boards.greenhouse.io/figma",
        "https://job-boards.greenhouse.io/figma",
    )
    async with _client(payload) as http:
        candidates, _ = await search_ats_candidates("Figma", http)

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
        assert await search_ats_candidates("   ", http) == ([], [])
    assert called is False
