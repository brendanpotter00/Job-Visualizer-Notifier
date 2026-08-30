"""THE CORPUS REGRESSION — every real board we have captured, replayed offline.

Three defects found on higher.gs.com, each of which had already shipped and none of
which anything in the pipeline could see:

* **A — the cursor went to the wrong place.** ``_request`` merged the page parameter
  into the TOP LEVEL of a POST body. Goldman's lives at
  ``body.variables.searchQueryInput.page.pageNumber``, so all 56 pages were page 0 and
  dedupe collapsed 1,120 rows to 20. Its second half: discovery never emitted
  ``start_page``, so the runner's default of 1 skipped a 0-based board's whole first
  page — and THAT sweep still ends short and clean, so a ``self_consistent`` board
  would VERIFY the short read and start closing what it never fetched.
* **B — the url template pointed at the wrong id.** ``{roleId}`` is not the route key;
  ``{externalSource.sourceId}`` is. The board is a Next.js SPA that answers 200 for
  any ``/roles/<x>``, so every dead link looked alive.
* **C — a bracket path resolved to nothing.** ``locations[0].city`` — ``dig`` split on
  ``.`` only, ``render_field`` swallowed the raise, and every Goldman row stored
  ``location = NULL`` at 100%.

Everything here is offline (``httpx.MockTransport`` + recorded fixtures) and $0. The
corpus is the point: a future edit to the cursor merge or the url repair must fail a
TEST, not a board, and the boards that were already RIGHT are what prove the fixes did
not buy Goldman at their expense.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from api.services.custom_baseline import Baseline
from api.services.capture.request_selector import (
    is_published_url_spec,
    published_url_fields,
    repair_url_template,
)
from api.services.harvest_verification import VERIFIED, run_gate, verify_harvest
from api.services.recipe_rows import recipe_rows_to_job_listings
from api.services.recipe_runner import (
    _request,
    find_body_param_path,
    iter_composite_query_params,
    merge_body_params,
    merge_query_params,
    render_field,
    run_recipe,
)
from api.services.recipe_schema import RecipeError, dig

# The capture package's ``__init__`` re-exports the FUNCTION ``discover``, which shadows
# the submodule of the same name — so ``from api.services.capture.discover import x``
# resolves against the function and fails. Every other test in the tree hits this; here
# the module is reached through ``sys.modules`` because two private helpers are the
# units under test.
import api.services.capture  # noqa: E402  (import order is the point)

_discover = sys.modules["api.services.capture.discover"]
_prove_job_link = _discover._prove_job_link
_board_page_link = _discover._board_page_link
_pages_differ = _discover._pages_differ
_page_text = _discover._page_text

_FIXTURES = Path(__file__).parent / "fixtures"
_RECIPES = _FIXTURES / "recipes"
_URL_REPAIR = _FIXTURES / "url_repair"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _step(script: dict, prefix: str) -> dict | None:
    return next((s for s in script["steps"] if s["op"].startswith(prefix)), None)


# ==========================================================================
# DEFECT A, part 1 — where the cursor lands, across the WHOLE corpus
# ==========================================================================

# Every paginated recipe we have, and the FULL path at which its cursor must appear in
# the outgoing POST body. ``None`` means this recipe is a GET and must keep using the
# untouched query-merge branch.
_CURSOR_PLACEMENT: dict[str, tuple[str, ...] | None] = {
    # POST + paginate_page, cursor FOUR levels down a GraphQL envelope. The defect.
    "goldman_sachs.json": ("variables", "searchQueryInput", "page", "pageNumber"),
    # POST + paginate_offset with the cursor ALREADY at the top level. This one must
    # stay byte-identical — it is the only browser_fetch board in production.
    "tiktok_browser_fetch.json": ("offset",),
    # Every GET board: the query-merge branch, untouched by this change.
    "amazon_search.json": None,
    "amazon_global.json": None,
    "microsoft.json": None,
}

# The recipes with no pagination step at all: the body/URL must go out verbatim.
_NO_PAGINATION = ("meta.json", "spotify.json", "atlassian.json", "janestreet.json")


class _Recorder:
    """A MockTransport that records outgoing requests and answers with an empty 200."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return httpx.Response(200, json={})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


def _issue(script: dict, params: dict[str, Any] | None) -> httpx.Request:
    fetch = _step(script, "fetch")
    assert fetch is not None
    recorder = _Recorder()
    with recorder.client() as http:
        _request(http, fetch, params)
    return recorder.requests[0]


@pytest.mark.parametrize("name", sorted(_CURSOR_PLACEMENT))
def test_every_paginated_recipe_sends_its_cursor_where_the_board_carries_it(
    name: str,
) -> None:
    """THE REGRESSION FOR DEFECT A. One assertion per board about the actual bytes."""
    script = _load(_RECIPES / name)
    fetch = _step(script, "fetch")
    pagination = _step(script, "paginate_")
    assert fetch is not None and pagination is not None
    param = pagination.get("param") or pagination["facet_param"]
    expected = _CURSOR_PLACEMENT[name]

    sent = _issue(script, {param: 7})

    if expected is None:                       # the GET branch, untouched
        assert fetch["method"] == "GET"
        assert sent.url.params[param] == "7"
        # Every captured filter survives the merge — replacing the whole query string
        # is how a scoped 76-job search silently becomes the global 10,000-job one.
        for key, value in httpx.URL(fetch["url"]).params.multi_items():
            if key != param:
                assert (key, value) in sent.url.params.multi_items()
        return

    assert fetch["method"] == "POST"
    assert expected[-1] == param
    body = json.loads(sent.content)
    # The cursor is where the board carries it...
    assert _at(body, expected) == 7
    # ...and NOTHING else about the captured body moved. Restore the captured value at
    # that one path and the body must be the object we captured, key for key. This is
    # the byte-identity claim that keeps TikTok safe.
    restored = copy.deepcopy(body)
    node: Any = restored
    for segment in expected[:-1]:
        node = node[segment]
    node[expected[-1]] = _at(fetch["body"], expected)
    assert restored == fetch["body"]


def _at(body: dict, path: tuple[str, ...]) -> Any:
    node: Any = body
    for segment in path:
        node = node[segment]
    return node


def test_tiktok_post_offset_is_byte_identical_to_the_old_flat_merge() -> None:
    """TikTok is POST + ``paginate_offset`` with ``offset`` ALREADY at the top level.

    Pinned separately and explicitly because it is the one production board on the
    ``browser_fetch`` tier: the new merge must produce the SAME bytes the old
    ``body.update(params)`` produced, for every cursor value.
    """
    script = _load(_RECIPES / "tiktok_browser_fetch.json")
    captured = _step(script, "fetch")["body"]
    assert "offset" in captured                # top level, as the board sent it
    for cursor in (0, 10, 250):
        old = {**copy.deepcopy(captured), "offset": cursor}
        assert merge_body_params(captured, {"offset": cursor}) == old


@pytest.mark.parametrize("name", _NO_PAGINATION)
def test_unpaginated_recipes_send_the_captured_request_verbatim(name: str) -> None:
    script = _load(_RECIPES / name)
    fetch = _step(script, "fetch")
    assert _step(script, "paginate_") is None
    sent = _issue(script, None)
    if fetch["method"] == "POST":
        assert json.loads(sent.content or b"{}") == (fetch.get("body") or {})
    assert str(sent.url) == fetch["url"]


# --------------------------------------------------------------------------
# DEFECT A, THE GET HALF: the cursor inside a COMPOSITE query value
# --------------------------------------------------------------------------
#
# Oracle Fusion Recruiting carries its whole search — filters, sort, page size AND page
# offset — inside ONE query parameter:
#
#   finder=findReqs;siteNumber=CX_1001,facetsList=...,limit=25,sortBy=...,offset=75
#
# ``copy_merge_params`` appends ``&offset=25``, which that board does not read, so every
# page of the sweep is page one. Same failure class as the higher.gs.com nested body,
# other transport.

_ORACLE_URL = (
    "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/"
    "recruitingCEJobRequisitions?onlyData=true"
    "&expand=requisitionList.secondaryLocations"
    "&finder=findReqs;siteNumber=CX_1001,facetsList=LOCATIONS%3BWORK_LOCATIONS,"
    "limit=25,sortBy=POSTING_DATES_DESC,offset=75"
)


def test_a_composite_query_cursor_is_set_where_the_board_carries_it() -> None:
    """Measured 2026-08-30 against the live board: with the cursor written inside the
    ``finder`` value the sweep read 7,124 distinct rows over 285 pages against a declared
    7,181; appended as a top-level parameter it reads page one, 285 times."""
    merged = merge_query_params(_ORACLE_URL, {"offset": 0})
    finder = merged.params["finder"]
    assert "offset=0" in finder and "offset=75" not in finder
    # ...and NOTHING else in that value moved.
    assert finder == (
        "findReqs;siteNumber=CX_1001,facetsList=LOCATIONS;WORK_LOCATIONS,"
        "limit=25,sortBy=POSTING_DATES_DESC,offset=0"
    )
    # ...and no stray top-level cursor was appended beside it.
    assert "offset" not in merged.params
    # ...and every other captured parameter survives.
    assert merged.params["onlyData"] == "true"
    assert merged.params["expand"] == "requisitionList.secondaryLocations"


def test_only_an_integer_token_is_ever_rewritten() -> None:
    """The safety of the whole mechanism. ``sortBy=POSTING_DATES_DESC`` and
    ``facetsList=LOCATIONS;WORK_LOCATIONS`` live in the same value as the cursor, and a
    substring rewrite over either of them is a request the board answers with something
    other than page two."""
    tokens = {name for _c, name, _v in iter_composite_query_params(_ORACLE_URL)}
    assert tokens == {"limit", "offset"}, (
        f"only the integer-valued tokens may be addressable; got {tokens}"
    )
    untouched = merge_query_params(_ORACLE_URL, {"sortBy": "x"})
    assert "sortBy=POSTING_DATES_DESC" in untouched.params["finder"]
    assert untouched.params["sortBy"] == "x"     # a name it does not carry: top level


def test_a_flat_get_cursor_merges_exactly_as_before() -> None:
    """The compatibility guarantee, and the reason this is safe to land on every board:
    a name that is already a real query parameter, or that appears nowhere, takes the
    ``copy_merge_params`` path untouched."""
    url = "https://b.example/api?team=eng&limit=100&offset=0"
    assert str(merge_query_params(url, {"offset": 200})) == str(
        httpx.URL(url).copy_merge_params({"offset": 200})
    )
    plain = "https://b.example/api?team=eng"
    assert str(merge_query_params(plain, {"offset": 200})) == str(
        httpx.URL(plain).copy_merge_params({"offset": 200})
    )
    assert str(merge_query_params(plain, None)) == plain


@pytest.mark.parametrize("name", sorted(_CURSOR_PLACEMENT) + list(_NO_PAGINATION))
def test_no_stored_recipe_has_a_composite_cursor_to_rewrite(name: str) -> None:
    """The corpus control. Not one board in the tracked set carries a paging token
    inside a query value, so the new branch is unreachable for all of them and their
    bytes cannot have changed."""
    script = _load(_RECIPES / name)
    url = _step(script, "fetch")["url"]
    for _container, token, _value in iter_composite_query_params(url):
        assert token.lower() not in {
            "offset", "from", "start", "startindex", "startrow", "skip", "firstresult",
        }, f"{name} carries a composite cursor {token!r} — this test is now load-bearing"


# --------------------------------------------------------------------------
# RUNG 1 — a published link we can stand behind
# --------------------------------------------------------------------------
#
# Rung 1 takes the board's own ``field_map["url"]`` VERBATIM and fetches nothing, on the
# theory that a path the board published must be right. 13 of the 19 corpus boards take
# it (JOB-LINK-RULE.md), so it is the highest-exposure rung there is.
#
# Greenhouse EMBEDS disprove the theory. Nintendo's feed publishes
# ``absolute_url = "https://careers.nintendo.com/?gh_jid=4295098009"`` — distinct per
# job, link-shaped, and measured live 2026-08-30 it answers 200 with 64,408 bytes of the
# LISTING page (``<title>Careers at Nintendo - Join Our Team</title>``) with the job's
# own title nowhere in it. ``/jobs/4295098009/`` is the working link: 82,962 bytes,
# ``<title>Brand Ambassador [Part-Time] - Peoria, IL - …</title>``.

_NINTENDO_EMBED = [
    {"id": 4295098009, "internal_job_id": 4173984009,
     "title": "Brand Ambassador [Part-Time] - Peoria, IL",
     "absolute_url": "https://careers.nintendo.com/?gh_jid=4295098009"},
    {"id": 4204762009, "internal_job_id": 4119610009,
     "title": "CONTRACT - Ambassador - Nintendo SF",
     "absolute_url": "https://careers.nintendo.com/?gh_jid=4204762009"},
    {"id": 4363567009, "internal_job_id": 4239003009,
     "title": "Software Engineer",
     "absolute_url": "https://careers.nintendo.com/?gh_jid=4363567009"},
]


def test_a_published_link_with_no_path_is_not_a_link_to_one_job() -> None:
    """All the identity in the query string, and the query is exactly what a board
    serving one SPA shell ignores. Rung 1 must decline it — and rung 2 as well, or the
    same string comes back through ``published_url_fields``."""
    assert is_published_url_spec(_NINTENDO_EMBED, "absolute_url") is False
    assert "absolute_url" not in published_url_fields(_NINTENDO_EMBED)


@pytest.mark.parametrize(
    "label, spec, url",
    [
        ("greenhouse", "absolute_url",
         "https://boards.greenhouse.io/spacex/jobs/866393800{i}?gh_jid=866393800{i}"),
        ("greenhouse-hosted", "absolute_url",
         "https://job-boards.greenhouse.io/anthropic/jobs/446123{i}"),
        ("greenhouse-on-brand", "absolute_url",
         "https://careers.roblox.com/jobs/735008{i}?gh_jid=735008{i}"),
        ("stripe-search-page", "absolute_url",
         "https://stripe.com/jobs/search?gh_jid=753273{i}"),
        ("lever", "hostedUrl",
         "https://jobs.lever.co/palantir/ac978161-6f46-4f6b-adcd-00000000000{i}"),
        ("icims", "portalUrl",
         "https://globalcareers-atlassian.icims.com/jobs/2558{i}/account-executive/job"),
        ("amazon-relative", "job_path", "/en/jobs/1052120{i}/senior-networking-sa"),
        ("microsoft-relative", "positionUrl", "/careers/job/197039355698322{i}"),
    ],
)
def test_every_path_bearing_published_link_still_takes_rung_one(
    label: str, spec: str, url: str
) -> None:
    """THE NON-REGRESSION, and it is the whole risk of this guard.

    Measured against the live boards 2026-08-30: **10 of the 10 corpus boards whose
    payload is publicly fetchable still take rung 1** (SpaceX, Figma, Roblox, Anthropic,
    Stripe, Palantir, Binance, Amazon, Atlassian, Microsoft), and only Nintendo's embed
    changes. Note Stripe deliberately survives — ``/jobs/search?gh_jid=…`` names a page,
    even though the id is in the query, and the guard is about the PATH being empty
    rather than about where the id lives.
    """
    records = [
        {"id": i, "title": f"Engineer {i}", spec: url.format(i=i)} for i in range(3)
    ]
    assert is_published_url_spec(records, spec) is True, label


def test_a_single_record_board_still_has_to_name_a_page() -> None:
    """The distinctness test is waived for a one-record board (it cannot be answered
    there). The path test is not — it is answerable on one row."""
    one = [{"id": 1, "title": "Engineer",
            "absolute_url": "https://careers.nintendo.com/?gh_jid=1"}]
    assert is_published_url_spec(one, "absolute_url") is False
    good = [{"id": 1, "title": "Engineer",
             "absolute_url": "https://boards.greenhouse.io/x/jobs/1"}]
    assert is_published_url_spec(good, "absolute_url") is True


def test_a_cursor_name_the_body_does_not_carry_still_lands_at_the_top_level() -> None:
    """The unchanged fallback: a board that takes a cursor key it never sent us."""
    assert merge_body_params({"q": "x"}, {"page": 3}) == {"q": "x", "page": 3}
    assert find_body_param_path({"q": "x"}, "page") is None


def test_a_top_level_name_wins_over_a_deeper_one() -> None:
    """Shallowest-first is the compatibility guarantee — a flat cursor is never
    re-routed into some nested homonym."""
    body = {"offset": 0, "filters": {"offset": 99}}
    assert find_body_param_path(body, "offset") == ("offset",)
    assert merge_body_params(body, {"offset": 5}) == {
        "offset": 5, "filters": {"offset": 99},
    }


def test_the_merge_never_mutates_the_stored_recipe() -> None:
    """Every page re-merges into the SAME stored body; a shallow copy would let page
    two edit the recipe under the sweep."""
    script = _load(_RECIPES / "goldman_sachs.json")
    body = _step(script, "fetch")["body"]
    before = copy.deepcopy(body)
    merge_body_params(body, {"pageNumber": 41})
    assert body == before


# ==========================================================================
# DEFECT A, part 2 — the 0-based board, end to end, BOTH halves
# ==========================================================================

_GS_TOTAL = 105
_GS_PAGE = 20


def _gs_record(i: int) -> dict:
    return {
        "roleId": f"{130000 + i}_GS_MID_CAREER",
        "jobTitle": f"Engineer {i}",
        "division": "Engineering",
        "locations": [{"city": "New York", "state": "NY", "primary": True}],
        "externalSource": {"sourceId": str(130000 + i)},
    }


def _goldman_board(counter: list[int] | None = None) -> "httpx.MockTransport":
    """higher.gs.com, faithfully: 0-BASED pages, and the page number is read from the
    GraphQL envelope. A cursor written anywhere else leaves ``pageNumber`` at its
    captured 0 and the board serves page 0 forever — which is exactly what the flat
    merge did in production."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        page = body["variables"]["searchQueryInput"]["page"]
        number, size = int(page["pageNumber"]), int(page["pageSize"])
        if counter is not None:
            counter.append(number)
        start = number * size
        items = [_gs_record(i) for i in range(start, min(start + size, _GS_TOTAL))]
        return httpx.Response(200, json={
            "data": {"roleSearch": {"totalCount": _GS_TOTAL, "items": items}}
        })

    return httpx.MockTransport(handler)


def _run(script: dict) -> tuple[list[dict], Any, list[int]]:
    seen: list[int] = []
    with httpx.Client(transport=_goldman_board(seen)) as http:
        rows, evidence = run_recipe(script, http)
    return rows, evidence, seen


def test_goldman_harvests_the_whole_board() -> None:
    """The fixed recipe reads every job the board declares — the end-to-end pin.

    It fails if EITHER half of defect A regresses: a flat merge leaves ``pageNumber``
    at 0 and every page is page one (20 rows after dedupe), and a missing
    ``start_page`` skips page 0 (85 rows). Measured against the live board on the
    fixed tree: 20 → 1,013 → 1,033 = the declared total exactly.
    """
    script = _load(_RECIPES / "goldman_sachs.json")
    rows, evidence, pages = _run(script)

    assert len(rows) == _GS_TOTAL == evidence.declared_total
    assert pages == [0, 1, 2, 3, 4, 5]          # 0-BASED, and every page distinct
    assert evidence.page_advance_ok and evidence.terminated_cleanly
    # Defect B: the link is built from the board's own route key.
    assert rows[0]["url"] == "https://higher.gs.com/roles/130000"
    # Defect C: the bracket path resolves.
    assert rows[0]["location"] == "New York"


def test_the_flat_merge_would_collapse_goldman_to_one_page() -> None:
    """The defect itself, reproduced against the same board: injecting the cursor at
    the top level of a GraphQL envelope leaves the real one at its captured 0."""
    script = _load(_RECIPES / "goldman_sachs.json")
    fetch = _step(script, "fetch")
    flat = {**copy.deepcopy(fetch["body"]), "pageNumber": 3}
    with httpx.Client(transport=_goldman_board()) as http:
        payload = http.post(fetch["url"], json=flat).json()
    assert [r["roleId"] for r in payload["data"]["roleSearch"]["items"]] == [
        _gs_record(i)["roleId"] for i in range(_GS_PAGE)
    ]


def test_dropping_start_page_silently_verifies_a_short_read() -> None:
    """WHY THE TWO HALVES OF DEFECT A MUST SHIP TOGETHER — and the reason this test
    asserts a bad outcome rather than a good one.

    With the merge fixed but ``start_page`` still defaulting to 1, the sweep skips the
    board's first page and then ends on a genuinely short one. Nothing about that run
    looks wrong: it terminated cleanly, pages advanced, no cap was hit. Goldman itself
    survives only because ``declared_probed`` compares at tolerance 0, so 85 ≠ 105 drops
    it to UNVERIFIED — but swap in the ``self_consistent`` oracle that every board
    without a trusted total gets, and the SAME short read VERIFIES.

    Only a VERIFIED run may close a job (``fetch_custom_company``), so that is a
    self-inflicted mass close of a fifth of the board. This test is the record of it:
    it fails the moment discovery stops emitting ``start_page``, because then
    :func:`test_goldman_harvests_the_whole_board` and this one describe the same run.
    """
    script = _load(_RECIPES / "goldman_sachs.json")
    pagination = _step(script, "paginate_")
    del pagination["start_page"]
    script["oracle"] = {"kind": "self_consistent"}

    rows, evidence, pages = _run(script)

    assert pages == [1, 2, 3, 4, 5]                       # page 0 never requested
    assert len(rows) == _GS_TOTAL - _GS_PAGE == 85        # a fifth of the board, gone
    assert evidence.terminated_cleanly and evidence.page_advance_ok and not evidence.cap_hit

    jobs = recipe_rows_to_job_listings("gs", rows)
    gate = run_gate(jobs, evidence, oracle_kind="self_consistent")
    verdict = verify_harvest(
        "self_consistent", gate, evidence,
        Baseline(median_records=None, run_count=0, min_ratio=0.5),
    )
    assert verdict.verdict == VERIFIED, (
        "a short read that looks clean is exactly what closes jobs — see the docstring"
    )


def test_a_flat_post_offset_board_still_sweeps_every_page() -> None:
    """The TikTok shape, harvested: a top-level cursor in a POST body is unaffected."""
    dataset = [{"id": str(i), "title": f"J{i}", "url": f"https://t/{i}"} for i in range(25)]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert set(body) == {"limit", "offset"}          # nothing new was injected
        offset = int(body["offset"])
        page = dataset[offset:offset + int(body["limit"])]
        return httpx.Response(200, json={"data": {"count": len(dataset), "list": page}})

    script = {
        "script_version": 1, "transport": "http_json", "expected_min_jobs": 1,
        "steps": [
            {"op": "fetch", "method": "POST", "url": "https://t.example/api",
             "body": {"limit": 10, "offset": 0}, "headers": {}},
            {"op": "paginate_offset", "param": "offset", "page_size": 10, "max_pages": 10},
            {"op": "extract_json_path", "records_path": "data.list",
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "declared_probed", "total_path": "data.count"},
    }
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) == 25 and evidence.pages_fetched == 3


# ==========================================================================
# DEFECT B — the url repair, over every board in the corpus
# ==========================================================================

@pytest.mark.parametrize("name", sorted(p.stem for p in _URL_REPAIR.glob("*.json")))
def test_url_repair_over_the_corpus(name: str) -> None:
    """Each fixture holds one board's REAL records and the URL log of the SAME capture.

    Only Goldman may change. Every other board is a live production link that was
    already correct, and the fixture's ``why`` says which clause protects it.
    """
    case = _load(_URL_REPAIR / f"{name}.json")
    repaired = repair_url_template(
        case["records"], case["url_spec"], case["captured_urls"], case["board_host"]
    )
    assert repaired == case["expected"], case["why"]


def test_microsoft_is_not_rewritten_and_still_renders_a_real_link() -> None:
    """MICROSOFT IS THE NAMED REGRESSION. The first version of this rule scored the
    template's placeholder against URL segments, and ``{positionUrl}`` renders a whole
    PATH — which can never equal one segment, so it scored 0 while ``id`` scored 8.
    That version rewrote every Microsoft link to
    ``https://apply.careers.microsoft.com1970393556982379``: a missing slash, a
    well-formed URL, and a dead link on 2,000 jobs.
    """
    case = _load(_URL_REPAIR / "microsoft.json")
    spec = case["url_spec"]
    assert repair_url_template(
        case["records"], spec, case["captured_urls"], case["board_host"]
    ) == spec
    rendered = render_field(case["records"][0], spec)
    assert rendered.startswith("https://apply.careers.microsoft.com/")


def test_goldman_url_is_repointed_at_the_boards_own_route_key() -> None:
    """The stored link renders a compound id the board's router does not know; the
    repaired one renders the bare number its own ``_next/data`` calls use."""
    case = _load(_URL_REPAIR / "goldman_sachs.json")
    record = case["records"][0]
    assert not render_field(record, case["url_spec"]).rsplit("/", 1)[-1].isdigit()

    repaired = repair_url_template(
        case["records"], case["url_spec"], case["captured_urls"], case["board_host"]
    )
    assert repaired == "https://higher.gs.com/roles/{externalSource.sourceId}"
    assert render_field(record, repaired).rsplit("/", 1)[-1].isdigit()


def test_url_repair_refuses_without_evidence() -> None:
    """The three ways the rule declines. Each returns the model's answer unchanged."""
    case = _load(_URL_REPAIR / "goldman_sachs.json")
    records, urls, spec = case["records"], case["captured_urls"], case["url_spec"]
    # No captured links on the board's own host — nothing to score against.
    assert repair_url_template(records, spec, [], "higher.gs.com") == spec
    assert repair_url_template(records, spec, urls, "example.com") == spec
    # A template with two distinct placeholders: one winner cannot replace both.
    two = "https://higher.gs.com/{division}/{roleId}"
    assert repair_url_template(records, two, urls, "higher.gs.com") == two
    # Already right — the asymmetry that makes every correct board untouchable.
    right = "https://higher.gs.com/roles/{externalSource.sourceId}"
    assert repair_url_template(records, right, urls, "higher.gs.com") == right


def test_a_sibling_host_is_not_the_board() -> None:
    """``higher.gs.com`` is a SUBSTRING of ``api-higher.gs.com``, and the fixture
    contains both. A substring host test would score the API host's paths as if they
    were the board's job links — so a detail endpoint keyed by the id the template
    ALREADY uses would read as "this template is right" and suppress a real repair.
    """
    case = _load(_URL_REPAIR / "goldman_sachs.json")
    assert any("api-higher.gs.com" in u for u in case["captured_urls"])

    # The sibling host, serving a per-role detail call keyed by roleId.
    decoys = [
        f"https://api-higher.gs.com/gateway/api/v1/role/{r['roleId']}"
        for r in case["records"]
    ]
    assert repair_url_template(
        case["records"], case["url_spec"], case["captured_urls"] + decoys, "higher.gs.com"
    ) == "https://higher.gs.com/roles/{externalSource.sourceId}"


# --- the repair's remaining guards, on the shapes that make each load-bearing ---
#
# Each of these is a board shape the corpus does not happen to contain, written out
# because the clause it exercises is the difference between a rule that only ever
# fixes a wrong link and one that can also break a right one.

def _two_id_board() -> tuple[list[dict], list[str]]:
    """A board whose records carry TWO ids, both of which appear in its own links —
    ``/jobs/<slug>/<ref>``. Neither id is obviously the route key from the outside."""
    records = [
        {"slug": f"engineer-{i}", "ref": f"R{1000 + i}", "title": f"Engineer {i}"}
        for i in range(8)
    ]
    urls = [f"https://b.example/jobs/{r['slug']}/{r['ref']}" for r in records]
    return records, urls


def test_a_template_that_is_already_right_is_never_rewritten_to_the_other_id() -> None:
    """The ALREADY-RIGHT clause. Both ids appear in the board's links, so without the
    zero-hits precondition the rule would find one "winner" and swap a working
    ``{slug}`` link for a ``{ref}`` one that the board may not route on at all."""
    records, urls = _two_id_board()
    spec = "https://b.example/jobs/{slug}"
    assert repair_url_template(records, spec, urls, "b.example") == spec


def test_two_plausible_replacements_are_a_refusal_not_a_coin_flip() -> None:
    """The EXACTLY-ONE clause. The current field appears nowhere, but two others do —
    and picking either would be a guess. Refusing leaves the model's answer, which the
    user can see is wrong; guessing produces a link that merely looks right."""
    records, urls = _two_id_board()
    for record in records:
        record["internalId"] = f"X{record['ref']}"       # matches nothing in the links
    spec = "https://b.example/jobs/{internalId}"
    assert repair_url_template(records, spec, urls, "b.example") == spec


def test_a_replacement_proven_on_two_records_is_a_coincidence_not_evidence() -> None:
    """The MINIMUM-HITS clause. One or two matches is what an unrelated field hits by
    accident against a page's worth of URL segments, so the bar is three. The ONLY
    thing that changes between the two halves below is how many of the board's links
    the capture happened to record."""
    records, _ = _two_id_board()
    for record in records:
        record["internalId"] = f"X{record['ref']}"      # matches nothing in the links
    spec = "https://b.example/jobs/{internalId}"

    links = [f"https://b.example/jobs/{r['ref']}" for r in records]
    assert repair_url_template(records, spec, links[:2], "b.example") == spec
    assert repair_url_template(records, spec, links[:3], "b.example") == (
        "https://b.example/jobs/{ref}"
    )


# ==========================================================================
# DEFECT C — the bracket path
# ==========================================================================

def test_bracket_index_paths_resolve() -> None:
    record = {"locations": [{"city": "New York"}, {"city": "London"}]}
    assert dig(record, "locations[0].city") == "New York"
    assert dig(record, "locations[1].city") == "London"
    assert render_field(record, "locations[0].city") == "New York"


def test_bracket_support_is_a_superset_and_changes_no_working_path() -> None:
    """The dotted spelling still wins outright, and a key that literally contains
    brackets still resolves by its real name."""
    assert dig({"locations": [{"city": "NY"}]}, "locations.0.city") == "NY"
    assert dig({"items[0]": {"x": 1}}, "items[0].x") == 1


def test_an_unresolvable_bracket_path_reports_the_path_the_recipe_carries() -> None:
    with pytest.raises(RecipeError, match=r"nope\[0\]"):
        dig({"locations": [{"city": "NY"}]}, "nope[0].city")


def test_goldman_locations_would_otherwise_be_null_on_every_row() -> None:
    """The measured shape of defect C: 0 of 1,074 rows had a location, and nothing
    raised, logged or looked wrong. Now 1,010 of them do — the remainder are rows on
    which the board itself publishes no city, which is a NULL that means something."""
    case = _load(_URL_REPAIR / "goldman_sachs.json")
    spec = "locations[0].city"
    resolved = [render_field(r, spec) for r in case["records"]]
    assert sum(1 for v in resolved if isinstance(v, str) and v) == 7
    assert resolved.count(None) == 1            # the board's own missing city

    # ...while the dot-only resolver the runner used to have found nothing at all, on
    # any row, including the seven that have a perfectly good city.
    from api.services.recipe_schema import _dig_dotted

    for record in case["records"]:
        with pytest.raises(RecipeError):
            _dig_dotted(record, spec)


# ==========================================================================
# DEFECT D — the link we INVENTED, over every board we have measured
# ==========================================================================
#
# The generalization of defect B, and the reason B's fix was not enough. B re-pointed a
# template using URLs the CAPTURE recorded on the board's host — which only exists when
# the board's own page happens to request a job page. Jane Street's does not, so the
# rule refused, and a link that 404s shipped anyway. Walmart's does not either, and its
# link has been dead the whole time without anyone noticing.
#
# ``fixtures/job_links/*.json`` is the corpus behind
# ``docs/implementations/custom-company-sources/JOB-LINK-RULE.md``: real records from
# each board's real feed, plus what its job pages ACTUALLY returned when fetched on
# 2026-08-29 (status, normalized length, whether the page carried that job's own
# title). ``kind`` is who authored the path; ``proves`` is what a fetch says about it.

_JOB_LINKS = _FIXTURES / "job_links"


def _rendered_url(case: dict, record: dict) -> str:
    origin = "https://" + case["origin_url"].split("/")[2]
    rendered = str(render_field(record, case["field_map"]["url"]))
    return origin + rendered if rendered.startswith("/") else rendered


def _measured_probe(case: dict) -> Callable[[str], tuple[int, str]]:
    """A probe that replays what each of this board's job pages really returned.

    The body is RECONSTRUCTED from the measurement rather than stored: a job page is
    tens of kilobytes, and only four things about it decide anything — the status, the
    length after script/style stripping, whether the job's own title is on it, and
    whether the OTHER jobs' titles are (a related-jobs block, or a listing page served
    for every URL). Every one of those four came from a real GET on 2026-08-29.

    The fixtures were generated by running this exact reconstruction beside the LIVE
    bodies and requiring the verdicts to match on all 13 boards, so ``proves`` is what
    the real pages say, not what the replay happens to produce.
    """
    def titles_of(url: str) -> tuple[str, list[str]]:
        own, others = "", []
        for record in case["records"]:
            title = str(render_field(record, case["field_map"]["title"]) or "")
            if _rendered_url(case, record) == url:
                own = title
            elif title:
                others.append(title)
        return own, others

    def probe(url: str) -> tuple[int, str]:
        page = case["pages"].get(url)
        if page is None:                       # a url the measurement never took
            return 0, ""
        own, others = titles_of(url)
        parts = ([own] if page["carries_own_title"] and own else [])
        parts += others if page["carries_other_titles"] else []
        body = " ".join(parts)
        body = f"{body} " if body else ""
        return page["status"], body + "x" * max(0, page["chars"] - len(body))

    return probe


@pytest.mark.parametrize("name", sorted(p.stem for p in _JOB_LINKS.glob("*.json")))
def test_job_link_corpus(name: str) -> None:
    """Two claims per board: WHO authored the path, and what fetching it proves.

    The classification is the branch: a path the board published is kept verbatim and
    never fetched; one we invented has to be proved. The proof result is measured, not
    asserted into existence — every number in ``pages`` came from a real GET.
    """
    case = _load(_JOB_LINKS / f"{name}.json")
    records, field_map = case["records"], case["field_map"]
    base_url = "https://" + case["origin_url"].split("/")[2]

    published = is_published_url_spec(records, field_map["url"])
    assert published is (case["kind"] == "published"), case["why"]

    why = _prove_job_link(records, field_map, base_url, _measured_probe(case))
    assert (why is None) is case["proves"], f"{case['why']} (probe said: {why})"


def test_the_three_dead_boards_are_all_refused() -> None:
    """THE POINT OF THE WHOLE CHANGE. Three boards shipped a link that does not open
    the job, and each failed differently — which is why a status check alone is not the
    fix, and neither is a length check alone.

    * **Jane Street** — a flat 404 nobody looked at.
    * **Goldman** *(pre-repair)* — HTTP **200**, and the same 23-char shell for every
      job. A status check calls this healthy.
    * **Walmart** — HTTP 200, the same 1,606-char shell for every job, on a host that
      answers 200 for literally every path. A third dead board, found by the rule.
    """
    two_hundreds = set()
    for name in ("janestreet", "goldman_pre_repair", "walmart"):
        case = _load(_JOB_LINKS / f"{name}.json")
        assert is_published_url_spec(case["records"], case["field_map"]["url"]) is False
        assert _prove_job_link(
            case["records"], case["field_map"],
            "https://" + case["origin_url"].split("/")[2], _measured_probe(case),
        ) is not None, name
        if name != "janestreet":
            two_hundreds |= {page["status"] for page in case["pages"].values()}
    assert two_hundreds == {200}        # two of the three answered 200 the whole time


def test_probing_a_published_link_would_reject_two_working_boards() -> None:
    """WHY BRANCH 1 NEVER FETCHES. Two of the thirteen published links in the corpus
    are live production links the proof cannot confirm, and each fails differently:

    * **Atlassian** — its iCIMS page renders the job in an **iframe**, so three
      different jobs serve 18,086 chars each and none carries its own title.
      Indistinguishable, over plain HTTP, from Goldman's empty shell.
    * **Roblox** — its Greenhouse-backed page carries the job's title *and* a related-
      jobs block carrying the others', and the pages differ by 0.8%. Both halves of the
      proof say no.

    The proof is not asked to settle these: the board authored the path, so there is
    nothing of OURS to prove. If this test starts failing because the probe passes, the
    branch is still right — it just stopped being free.
    """
    atlassian = _load(_JOB_LINKS / "atlassian.json")
    assert len({page["chars"] for page in atlassian["pages"].values()}) == 1
    assert not any(p["carries_own_title"] for p in atlassian["pages"].values())

    roblox = _load(_JOB_LINKS / "roblox.json")
    assert all(p["carries_own_title"] and p["carries_other_titles"]
               for p in roblox["pages"].values())

    for case in (atlassian, roblox):
        assert is_published_url_spec(case["records"], case["field_map"]["url"]) is True
        assert case["proves"] is False
        assert _prove_job_link(
            case["records"], case["field_map"],
            "https://" + case["origin_url"].split("/")[2], _measured_probe(case),
        ) is not None


def test_microsofts_link_is_published_because_its_placeholder_is_a_path() -> None:
    """MICROSOFT, AGAIN, AND FOR THE SAME REASON. ``{positionUrl}`` renders
    ``/careers/job/1970393556983225`` — a path the BOARD wrote. That single fact keeps
    it out of the repair (``_renders_id_token``) and out of the probe
    (``is_published_url_spec``), which is deliberate: one definition of "we made this
    path up", used by both, so the two can never disagree about this board.
    """
    case = _load(_JOB_LINKS / "microsoft.json")
    spec = case["field_map"]["url"]
    assert is_published_url_spec(case["records"], spec) is True
    assert render_field(case["records"][0], spec).startswith(
        "https://apply.careers.microsoft.com/careers/job/"
    )


def test_a_board_that_publishes_a_link_beats_a_template_we_invented() -> None:
    """Direction #1 of the rule: never synthesise a path a board already publishes.

    Ranked so the POSTING beats the apply form — Lever ships ``hostedUrl`` and
    ``applyUrl`` (the same URL plus ``/app``), Recruitee ``careers_url`` and
    ``careers_apply_url``, Amazon ``job_path`` and ``url_next_step``. Both are real
    pages for the same job, so this only decides which one wins.
    """
    records = [
        {"id": i, "text": f"Engineer {i}",
         "hostedUrl": f"https://jobs.lever.co/acme/{i}",
         "applyUrl": f"https://jobs.lever.co/acme/{i}/apply",
         "meta": {"canonical": f"https://acme.example/jobs/{i}"}}
        for i in range(4)
    ]
    assert published_url_fields(records) == ["hostedUrl", "meta.canonical", "applyUrl"]
    assert published_url_fields([{"id": 1, "title": "x"}]) == []


def test_a_template_with_two_placeholders_is_never_called_published() -> None:
    """THE SINGLE-PLACEHOLDER BOUND, and why dropping it is not a small relaxation.

    "The board authored this path" is only decidable about ONE substitution. With two,
    the question has two answers and the code would have to pick one — so a template
    where either half renders a path (``{prefix}{suffix}`` → ``/jobs`` + ``/1``) would
    be waved through as board-authored while WE chose how the two were joined. The
    board published two fragments; the URL is still ours.

    Both records below have path-valued parts precisely so the assertion does not
    depend on which placeholder a set iterates first.
    """
    records = [
        {"prefix": "/jobs", "suffix": f"/{i}", "team": f"team{i}", "n": str(i)}
        for i in range(4)
    ]
    assert is_published_url_spec(records, "https://b.example{prefix}{suffix}") is False
    assert is_published_url_spec(records, "https://b.example/{team}/{n}") is False
    # ...while the one-placeholder forms are still decided on their own merits.
    assert is_published_url_spec(records, "https://b.example{suffix}") is True
    assert is_published_url_spec(records, "https://b.example/jobs/{n}") is False


def test_the_board_page_fallback_is_a_link_that_renders() -> None:
    """The last resort has to actually work, and stay distinct per job.

    ``url`` is one of ``CANONICAL_REQUIRED_FIELDS``, so "store nothing" is not a shape
    the recipe can hold; a literal with no placeholder would be read as a dotted PATH by
    ``render_field`` and render ``None`` on every row. The id rides in the fragment,
    which is never sent to the server — so it cannot turn a working listing URL into a
    404 — and keeps one row per job.
    """
    spec = _board_page_link("https://www.janestreet.com/join-jane-street/open-roles/", "id")
    assert spec == "https://www.janestreet.com/join-jane-street/open-roles/#{id}"
    assert render_field({"id": 8631912002}, spec) == (
        "https://www.janestreet.com/join-jane-street/open-roles/#8631912002"
    )
    # An origin that already carries a fragment does not grow a second one.
    assert _board_page_link("https://b.example/jobs#top", "id") == "https://b.example/jobs#{id}"


def test_two_jobs_that_render_the_same_url_are_not_a_comparison() -> None:
    """A spec that ignores the record renders one URL for the whole board, so there is
    nothing to compare and nothing is proved. It fails BEFORE any fetch — the probe
    below would happily answer 200 twice."""
    records = [{"id": i, "title": f"Engineer {i}"} for i in range(4)]
    fetched: list[str] = []

    def probe(url: str) -> tuple[int, str]:
        fetched.append(url)
        return 200, "x" * 5000

    why = _prove_job_link(
        records, {"id": "id", "title": "title", "url": "https://b.example/jobs/{nope}"},
        "https://b.example", probe,
    )
    assert why is not None and "distinct link" in why
    assert fetched == []


def test_the_two_page_comparison_needs_BOTH_bounds() -> None:
    """``_pages_differ`` is an absolute floor AND a fraction, and each one alone is
    wrong in a direction the corpus contains.

    * **Fraction alone** would call a 10-char difference in a 400-char shell decisive
      (2.5%) — and a 400-char shell with a per-request nonce in it is exactly the
      Goldman/Kakao shape.
    * **Absolute alone** would call a 300-char difference in a 700 KB single-page app
      decisive — and 700 KB SPAs are what Lever and Microsoft serve, where 300 chars is
      one analytics token.
    """
    assert _pages_differ("x" * 400, "x" * 390) is False        # 2.5%, only 10 chars
    assert _pages_differ("x" * 700_000, "x" * 700_300) is False  # 300 chars, 0.04%
    assert _pages_differ("x" * 400, "x" * 4000) is True        # both bounds cleared


def test_a_title_hiding_in_a_script_bundle_is_not_the_page() -> None:
    """WHY ``_page_text`` STRIPS SCRIPTS FIRST, and it is not about noise.

    An SPA ships its whole dataset inside a ``<script>`` tag, so a shell that renders
    NOTHING still contains every job's title in its bundle. Left in, "the page carries
    this job's title" would be true for every board that is client-rendered — which is
    most of them — and the strongest signal in the proof would fire on the exact shape
    it exists to reject.
    """
    bundle = (
        '<html><head><script>window.__DATA__={"jobs":'
        '[{"t":"Staff Machine Learning Engineer"},{"t":"Principal Site Reliability Eng"}]}'
        "</script></head><body></body></html>"
    )
    records = [
        {"id": 1, "title": "Staff Machine Learning Engineer"},
        {"id": 2, "title": "Principal Site Reliability Eng"},
    ]
    why = _prove_job_link(
        records, {"id": "id", "title": "title", "url": "https://b.example/jobs/{id}"},
        "https://b.example", lambda url: (200, bundle),
    )
    assert why is not None and "same page" in why
    # ...and the stripped text really is empty, which is what the shell IS.
    assert _page_text(bundle) == ""


def test_a_title_too_short_to_be_distinctive_is_not_used_as_proof() -> None:
    """"QA" and "ML" occur on half the web by accident, so below
    :data:`_DISTINCTIVE_TITLE_CHARS` the title is not consulted at all and the PAGES
    have to differ on their own.

    The board here is the trap that makes the bar load-bearing: it serves the same
    boilerplate careers shell for every job, and that shell happens to contain the two-
    letter string. Each page therefore "carries its own title and not the other's" —
    the strongest signal the proof has — on a coincidence. Only the length bar stops it
    being believed, and the two shells are the same length.
    """
    shells = {
        "https://b.example/jobs/1": "<html><body>qa hiring " + "x" * 3000 + "</body></html>",
        "https://b.example/jobs/2": "<html><body>ml hiring " + "x" * 3000 + "</body></html>",
    }
    records = [{"id": 1, "title": "QA"}, {"id": 2, "title": "ML"}]
    why = _prove_job_link(
        records, {"id": "id", "title": "title", "url": "https://b.example/jobs/{id}"},
        "https://b.example", lambda url: (200, shells[url]),
    )
    assert why is not None and "same page" in why

    # The same board, the same pages, real titles: now the signal means something.
    real = [{"id": 1, "title": "Quality Assurance Engineer"},
            {"id": 2, "title": "Machine Learning Engineer"}]
    named = {
        url: body.replace("qa hiring", "quality assurance engineer")
                 .replace("ml hiring", "machine learning engineer")
        for url, body in shells.items()
    }
    assert _prove_job_link(
        real, {"id": "id", "title": "title", "url": "https://b.example/jobs/{id}"},
        "https://b.example", lambda url: (200, named[url]),
    ) is None


def test_a_listing_page_returned_for_every_job_url_is_refused() -> None:
    """The board that answers every job URL with its full LIST. Each page does carry
    the job's own title — so the "own title" half passes — and it carries every OTHER
    job's title too, which is what the cross-title half is for. Without it this board
    would prove on the strongest signal available."""
    titles = ["Staff Machine Learning Engineer", "Principal Site Reliability Eng"]
    listing = "<html><body>" + " ".join(titles) + "x" * 2000 + "</body></html>"
    records = [{"id": i, "title": t} for i, t in enumerate(titles)]
    why = _prove_job_link(
        records, {"id": "id", "title": "title", "url": "https://b.example/jobs/{id}"},
        "https://b.example", lambda url: (200, listing),
    )
    assert why is not None and "same page" in why


def test_a_probe_that_cannot_reach_the_board_proves_nothing() -> None:
    """A guard refusal, a DNS failure or a timeout comes back as status 0. "We could
    not check" and "the check failed" lead to the same place — unproven — because the
    alternative is storing a link on the strength of our own network having a bad
    minute."""
    records = [{"id": i, "title": f"Engineer number {i}"} for i in range(3)]
    why = _prove_job_link(
        records, {"id": "id", "title": "title", "url": "https://b.example/jobs/{id}"},
        "https://b.example", lambda url: (0, ""),
    )
    assert why is not None and "HTTP 0" in why


def test_a_link_that_is_the_same_on_every_row_is_not_a_job_link() -> None:
    """THE FIELD THAT LOOKS LIKE A LINK AND IS NOT ONE. A board's ``companyLogoUrl``,
    careers banner or department page renders a perfectly well-formed absolute URL on
    every record — so "is it link-shaped?" alone would store a PNG as the link to every
    job on the board, and the recipe would look completely fine.

    A per-job link is different per job by definition. Requiring that costs nothing and
    closes the class.
    """
    records = [
        {"id": i, "title": f"Engineer {i}",
         "logoUrl": "https://cdn.b.example/logo.png",     # identical on every row
         "detailUrl": f"https://b.example/jobs/{i}"}
        for i in range(5)
    ]
    assert published_url_fields(records) == ["detailUrl"]
    assert is_published_url_spec(records, "logoUrl") is False
    assert is_published_url_spec(records, "detailUrl") is True

    # ...and a board with exactly ONE posting cannot answer the question, so the only
    # evidence available — that it is link-shaped — is accepted.
    assert is_published_url_spec(records[:1], "logoUrl") is True


def test_truncation_can_only_push_the_proof_towards_refusing() -> None:
    """WHY THE BYTE CAP NEEDS NO GUARD, which is not obvious and was nearly guarded
    wrongly.

    The probe stops reading at :data:`_LINK_PROBE_MAX_BYTES`, so a clipped body's
    length is partly ours. The concern is that clipping could manufacture a PASS —
    it cannot. Reading stops on the first chunk past the cap, so two clipped bodies
    land within about one chunk of each other, far inside the 2% bar (80 KB at a 4 MB
    cap). And a clipped pair that still differs differs because their first 4 MB really
    do, which is exactly the routing evidence being looked for.

    The error clipping CAN cause is the safe one: two pages that only diverge after the
    cap read as identical, and an identical pair is refused.
    """
    cap = _discover._LINK_PROBE_MAX_BYTES
    chunk = 65_536                       # httpx's default read size, the worst overshoot
    assert chunk < _discover._MIN_PAGE_DELTA_FRACTION * cap

    field_map = {"id": "id", "title": "title", "url": "https://b.example/jobs/{id}"}
    records = [{"id": 1, "title": "Distributed Systems Engineer"},
               {"id": 2, "title": "Compiler Engineer, Runtime"}]
    clipped = {
        "https://b.example/jobs/1": "x" * cap,
        "https://b.example/jobs/2": "x" * (cap + chunk),
    }
    assert _prove_job_link(
        records, field_map, "https://b.example", lambda url: (200, clipped[url])
    ) is not None


def test_the_fallback_survives_an_id_path_that_contains_a_brace() -> None:
    """A JSON key with a brace in it would nest inside the fragment placeholder and
    render a mangled string on every row. It gets a placeholder that resolves to
    nothing instead — which still has to BE a placeholder, because ``render_field``
    reads a spec with no ``{`` as a dotted PATH and a bare literal URL renders ``None``.
    """
    spec = _board_page_link("https://b.example/jobs", "weird{key}")
    assert render_field({"weird{key}": 7}, spec) == "https://b.example/jobs#"
    # ...and the ordinary case still carries the id.
    ordinary = _board_page_link("https://b.example/jobs", "id")
    assert render_field({"id": 7}, ordinary) == "https://b.example/jobs#7"
