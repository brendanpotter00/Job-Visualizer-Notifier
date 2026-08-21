"""E7 capture pivot — the discovery orchestrator + THE ACCEPTANCE GATE. $0.

Every collaborator is injected: the capture returns a fixture report (no browser), the
selector returns a canned answer (no LLM), the two replays are fakes (no network), and
the SSRF guard is a table the test controls (no DNS). What is REAL is everything that
decides: the pre-filter, the endpoint SSRF pass, recipe synthesis, ``validate_recipe``,
``run_gate`` and the match-the-capture assertion.

The properties under test are the load-bearing ones:

* the acceptance ladder tries ``http_json`` FIRST (a board that replays for $0 must
  never be stored as a nightly Chromium launch) and falls back to ``browser_fetch``;
* a replay that does not overlap the ids the browser saw is REFUSED — this is the only
  check that catches a structurally-perfect recipe pointed at the wrong array;
* SSRF is enforced on BOTH ends, and the endpoint half runs BEFORE the LLM sees a
  candidate, so an internal address can never reach a prompt or a stored recipe;
* a REFUSE stores NOTHING (no script, no transport, no oracle_kind); and
* ``discover`` NEVER raises — the caller is a retry=1 task whose provisional
  ``discovering`` row is only cleared by a returned outcome.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

# NOTE: `from ...discover import` (not `import ... as disc`) — the capture package
# `__init__` re-exports the FUNCTION `discover`, which shadows the submodule attribute.
from api.services.capture.discover import (
    _MAX_SELECTION_ROUNDS,
    _inband_error_keys,
    discover,
    synthesize_recipe,
)
from api.services.capture.network_capture import (
    CaptureError,
    CaptureResult,
    _responses_from_report,
)
from api.services.capture.request_selector import (
    NoJobsFeedError,
    PaginationHint,
    RequestSelection,
    RequestSelectionError,
    SelectorKeyMissingError,
    prefilter_candidates,
)
from api.services.harvest_meta import HarvestEvidence
from api.services.harvest_verification import UNVERIFIED, GateResult, verify_harvest
from api.services.recipe_runner import RecipeExecutionError, map_records
from api.services.recipe_schema import BROWSER_FETCH_MAX_PAGES
from api.services.url_guard import UrlGuardError

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).parent / "fixtures" / "discovery"

_AMAZON_URL = "https://www.amazon.jobs/en/search"
_TIKTOK_URL = "https://lifeattiktok.com/search"
_META_URL = "https://www.metacareers.com/jobs"

_AMAZON_MAP = {
    "id": "id_icims",
    "title": "title",
    "url": "https://www.amazon.jobs{job_path}",
    "location": "normalized_location",
    "posted_at": "posted_date",
    "department": "job_category",
}
_TIKTOK_MAP = {
    "id": "id",
    "title": "title",
    "url": "https://lifeattiktok.com/search/{id}",
    "location": "city_info.en_name",
    "department": "job_category.en_name",
}


# --- fixtures / fakes --------------------------------------------------------

def _capture_result(name: str) -> CaptureResult:
    report = json.loads((_FIXTURES / f"{name}_capture.json").read_text())
    return CaptureResult(
        final_url=report["final_url"],
        page_title=report["page_title"],
        responses=_responses_from_report(report),
    )


def _capturing(name: str, *, calls: list[str] | None = None):
    async def _capture(url: str) -> CaptureResult:
        if calls is not None:
            calls.append(url)
        return _capture_result(name)
    return _capture


def _selecting(selection: RequestSelection, *, calls: list[int] | None = None):
    async def _select(candidates: list[Any]) -> RequestSelection:
        if calls is not None:
            calls.append(len(candidates))
        return selection
    return _select


def _amazon_selection(index: int = 0) -> RequestSelection:
    return RequestSelection(
        chosen_request_index=index, records_path="jobs", field_map=dict(_AMAZON_MAP),
        pagination=PaginationHint(style="offset", param="offset", page_size=10),
    )


def _tiktok_selection() -> RequestSelection:
    return RequestSelection(
        chosen_request_index=0, records_path="data.job_post_list",
        field_map=dict(_TIKTOK_MAP),
        pagination=PaginationHint(style="offset", param="offset", page_size=10),
    )


def _faithful_replay(name: str, records_path: str, field_map: dict[str, str],
                     *, calls: list[str] | None = None, declared_total: int | None = None):
    """A replay that returns exactly what the capture browser saw — the happy path.

    Deriving the rows from the SAME captured records through the SAME ``map_records``
    the recipe uses is the point: a fake that invented its own ids would test the
    fixture, not the match-the-capture check.
    """
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        if calls is not None:
            calls.append(script["transport"])
        candidate = prefilter_candidates(_capture_result(name).responses)[0]
        rows = map_records(candidate.records, field_map, script.get("base_url", ""))
        return rows, HarvestEvidence(
            declared_total=declared_total, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )
    return _replay


def _failing_replay(exc: Exception, *, calls: list[str] | None = None):
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        if calls is not None:
            calls.append(script["transport"])
        raise exc
    return _replay


def _never_called_replay(label: str):
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        raise AssertionError(f"{label} must not run")
    return _replay


def _allow_all(url: str) -> None:
    return None


def _blocking(*blocked_substrings: str):
    def _validate(url: str) -> None:
        if any(sub in url for sub in blocked_substrings):
            raise UrlGuardError("private_address", f"{url} resolves to a private address")
    return _validate


# --- the accept paths --------------------------------------------------------

async def test_accepts_http_json_and_stores_a_replayable_recipe() -> None:
    """Tier 1a: a clean public GET. The stored recipe must be ``http_json`` (a $0
    nightly replay), carry the board's OWN total as a declared_probed oracle, and
    paginate — Amazon says 76 jobs exist and the capture saw 10."""
    replays: list[str] = []
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay(
            "amazon", "jobs", _AMAZON_MAP, calls=replays, declared_total=76
        ),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.transport == "http_json"
    assert outcome.oracle_kind == "declared_probed"
    assert replays == ["http_json"]                 # 1a first, 1b never reached
    assert outcome.script is not None
    script = outcome.script
    assert script["oracle"] == {"kind": "declared_probed", "total_path": "hits"}
    assert script["base_url"] == "https://www.amazon.jobs"
    assert "origin_url" not in script               # http_json must NOT carry one
    ops = [step["op"] for step in script["steps"]]
    assert ops[0] == "fetch"
    assert "paginate_offset" in ops
    assert "extract_json_path" in ops
    assert script["discovered_by"] == "capture/http_json"


async def test_falls_back_to_browser_fetch_when_the_http_replay_fails() -> None:
    """The TikTok case: a deterministic POST that 400s from our server and 200s from
    its own origin. 1a must be TRIED (that is how we learn it fails) and 1b stored."""
    replays: list[str] = []
    outcome = await discover(
        _TIKTOK_URL,
        capture=_capturing("tiktok"),
        select=_selecting(_tiktok_selection()),
        replay_http=_failing_replay(
            RecipeExecutionError("HTTP 400 from api.lifeattiktok.com"), calls=replays
        ),
        replay_browser=_faithful_replay(
            "tiktok", "data.job_post_list", _TIKTOK_MAP,
            calls=replays, declared_total=4026,
        ),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.transport == "browser_fetch"
    # Each tier is tried TWICE because TikTok's captured POST carries ``limit: 10``
    # against a declared 4,026, so acceptance offers the synthesized 100-record page
    # first and the captured 10 second. This fake always replies with the capture's one
    # page, so the page-size proof never passes and the fallback attempt is what lands
    # — which is exactly the ordering under test: 1a before 1b, upgrade before capture.
    assert replays == ["http_json", "http_json", "browser_fetch", "browser_fetch"]
    script = outcome.script
    assert script is not None
    # The origin the capture LANDED on — a browser_fetch replay navigates there before
    # issuing the captured request, which is the whole reason the tier exists.
    assert script["origin_url"] == _TIKTOK_URL
    assert script["oracle"] == {"kind": "declared_probed", "total_path": "data.count"}


async def test_pins_the_boards_own_success_sentinel_as_an_inband_error_key() -> None:
    """TikTok answers ``code: 0`` on success and non-zero on failure, and
    ``_check_inband_error`` fires on TRUTHINESS — so pinning ``code`` turns its error
    channel into a FAILED run. ``message: "ok"`` is captured TRUTHY and must NOT be
    pinned, or every single run would fail."""
    outcome = await discover(
        _TIKTOK_URL,
        capture=_capturing("tiktok"),
        select=_selecting(_tiktok_selection()),
        replay_http=_faithful_replay(
            "tiktok", "data.job_post_list", _TIKTOK_MAP, declared_total=4026
        ),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.script is not None
    (assertion,) = [
        s for s in outcome.script["steps"] if s["op"] == "assert_no_inband_error"
    ]
    assert assertion["error_keys"] == ["code"]


def test_a_truthy_candidate_key_is_not_pinned_as_an_inband_error_key() -> None:
    """The falsiness half, on a key that IS a candidate — the case no fixture carries,
    so nothing exercised the filter and dropping it kept the suite green. A board
    answering ``status: "ok"`` alongside ``code: 0`` must pin only ``code``:
    ``recipe_runner._check_inband_error`` fires on TRUTHINESS, so pinning ``status``
    would raise on every single run and refuse a perfectly readable board."""
    assert _inband_error_keys(
        {"status": "ok", "code": 0, "success": True, "jobs": [{"id": 1}]}
    ) == ["code"]


async def test_captured_credentials_never_reach_the_stored_recipe() -> None:
    """The Amazon fixture's captured headers carry a cookie, a bearer token and a CSRF
    token. Storing any of them would produce a board that passes acceptance TODAY and
    silently fails the night the token expires — so they are dropped, and a board that
    truly needs them belongs on browser_fetch (same-origin, re-earned nightly)."""
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.script is not None
    headers = outcome.script["steps"][0]["headers"]
    assert "cookie" not in headers
    assert "authorization" not in headers
    assert "x-csrf-token" not in headers
    assert headers["x-requested-with"] == "XMLHttpRequest"     # static, kept


# --- the refuse paths --------------------------------------------------------

async def test_refuses_when_the_replay_does_not_match_the_capture() -> None:
    """THE acceptance check (D5). These rows are perfectly job-shaped and pass every
    structural check in ``run_recipe`` and ``run_gate`` — they are simply a DIFFERENT
    list. Only the id overlap catches that, and getting it wrong means silently tracking
    the wrong board forever."""
    async def _wrong_feed(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        rows = [{"id": f"other-{i}", "title": f"Unrelated {i}", "url": "/x"} for i in range(20)]
        return rows, HarvestEvidence(
            declared_total=76, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )

    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_wrong_feed,
        replay_browser=_wrong_feed,
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "verifying we can read it" in (outcome.refuse_reason or "")
    assert "not reading the same list" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_refuses_when_the_replay_returns_far_fewer_jobs_than_the_capture() -> None:
    """A replay that comes back with a fraction of the page the browser saw is reading a
    different (or gated) slice. Believing it would store a board whose nightly harvest
    looks like a permanent 90% shrink."""
    async def _thin(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        candidate = prefilter_candidates(_capture_result("amazon").responses)[0]
        rows = map_records(candidate.records[:2], _AMAZON_MAP, script["base_url"])
        return rows, HarvestEvidence(
            declared_total=76, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )

    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_thin, replay_browser=_thin, validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "too few to believe it is the same feed" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_a_less_job_shaped_leftover_is_never_offered_a_second_round() -> None:
    """THE forced-answer bug. The TikTok capture is two candidates: the jobs POST
    (job_score 5) and the filter catalogue behind it (score 2, records "Engineering"
    and "Design"). When the jobs feed cannot be replayed either way, the old ladder
    dropped it and re-asked over the catalogue — and the selector schema REQUIRES an
    index, so the model had to name it. That forced pick then passed everything: the
    acceptance gate proves the replay reads the SAME array the browser saw, so a
    catalogue replayed against itself overlaps 100%. Measured: discovery ACCEPTED
    ``…/job/filters`` and tracked two categories as the company's jobs, forever, with a
    nightly harvest that would never fail.

    So a candidate LESS job-shaped than the one that just failed is not offered at all.
    The floor is the failed candidate's own score, not the pre-filter's top rank — the
    pre-filter is deliberately dumb and the model correcting it is a designed path."""
    select_calls: list[int] = []
    outcome = await discover(
        _TIKTOK_URL,
        capture=_capturing("tiktok"),
        select=_selecting(_tiktok_selection(), calls=select_calls),
        replay_http=_failing_replay(RecipeExecutionError("HTTP 400")),
        replay_browser=_failing_replay(RecipeExecutionError("Chromium crashed")),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "verifying we can read it" in (outcome.refuse_reason or "")
    assert select_calls == [2]              # asked once, over both; never re-asked
    _assert_stores_nothing(outcome)


async def test_an_equally_job_shaped_candidate_is_tried_and_the_ladder_is_bounded() -> None:
    """The fallback the round above exists for is still real: a second array that looks
    just as job-shaped IS re-offered. And the ladder is BOUNDED — each round costs a
    Haiku call and up to two replays inside a 240s task, so an unbounded loop would be
    a money bug as well as a hang."""
    twin = _amazon_response({**_amazon_body(), "hits": 76})
    other = twin.__class__(**{**twin.__dict__, "url": twin.url + "&page=2"})

    async def _capture(url: str) -> CaptureResult:
        return CaptureResult(final_url=_AMAZON_URL, page_title="", responses=[twin, other])

    select_calls: list[int] = []
    outcome = await discover(
        _AMAZON_URL,
        capture=_capture,
        select=_selecting(_amazon_selection(), calls=select_calls),
        replay_http=_failing_replay(RecipeExecutionError("HTTP 400")),
        replay_browser=_failing_replay(RecipeExecutionError("Chromium crashed")),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert select_calls == [2, 1]           # the failed candidate is dropped, then re-asked
    assert len(select_calls) == _MAX_SELECTION_ROUNDS
    _assert_stores_nothing(outcome)


async def test_the_selector_may_answer_that_none_of_them_is_a_jobs_feed() -> None:
    """The other half of the same defect: the model's own refusal branch. Re-asking
    after "none of these is jobs" can only manufacture an answer, so it must STOP — and
    name the filter step, because that is the user's actual problem (we recorded
    requests; none of them is a jobs feed)."""
    select_calls: list[int] = []

    async def _no_feed(candidates: list[Any]) -> RequestSelection:
        select_calls.append(len(candidates))
        raise NoJobsFeedError("none of the 2 captured request(s) is a list of job postings")

    outcome = await discover(
        _TIKTOK_URL, capture=_capturing("tiktok"), select=_no_feed,
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "finding the jobs feed" in (outcome.refuse_reason or "")
    assert "is a list of job postings" in (outcome.refuse_reason or "")
    assert select_calls == [2]              # asked once; a second ask cannot help
    _assert_stores_nothing(outcome)


async def test_a_transport_level_network_error_falls_through_to_browser_fetch() -> None:
    """The ladder's whole point, for the boards it exists for. An anti-bot origin that
    RSTs or blackholes a non-browser client raises ``httpx.ConnectTimeout`` /
    ``ConnectError`` / ``RemoteProtocolError`` — none of them a ``RecipeExecutionError``,
    so they escaped BOTH the transport loop and the round loop into the last-resort
    handler, and the board was permanently refused with an opaque internal-error
    message while ``browser_fetch`` was never even tried."""
    replays: list[str] = []
    outcome = await discover(
        _TIKTOK_URL,
        capture=_capturing("tiktok"),
        select=_selecting(_tiktok_selection()),
        replay_http=_failing_replay(httpx.ConnectTimeout("timed out"), calls=replays),
        replay_browser=_faithful_replay(
            "tiktok", "data.job_post_list", _TIKTOK_MAP,
            calls=replays, declared_total=4026,
        ),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.transport == "browser_fetch"
    # Two attempts per tier — the synthesized page size then the captured one; see
    # ``test_falls_back_to_browser_fetch_when_the_http_replay_fails``.
    assert replays == ["http_json", "http_json", "browser_fetch", "browser_fetch"]


async def test_the_model_may_correct_the_prefilters_records_path() -> None:
    """The pre-filter ranks arrays by ``(job_score, record_count)`` — deliberately dumb
    — and the prompt invites the model to correct it. When it does, everything
    downstream must follow: ``_capture_ids`` compares the replay against the
    candidate's records and ``paginate.page_size`` is the candidate's record count.
    Reading the pre-filter's array while the recipe extracts the model's refused a
    perfectly readable board ("the replay returned 12 job(s) but the browser saw 30" —
    a sentence that is also false) and wrote 30 as the page size of a 12-record page."""
    jobs = [{"id": f"J{i}", "title": f"Engineer {i}", "job_path": f"/jobs/{i}"}
            for i in range(12)]
    decoys = [{"id": f"S{i}", "title": f"Saved search {i}", "job_path": f"/s/{i}"}
              for i in range(30)]
    body = {"total": 120, "job_list": jobs, "saved_searches": decoys}
    response = _amazon_response(body)

    async def _capture(url: str) -> CaptureResult:
        return CaptureResult(final_url=_AMAZON_URL, page_title="", responses=[response])

    field_map = {"id": "id", "title": "title", "url": "https://www.amazon.jobs{job_path}"}
    corrected = RequestSelection(
        chosen_request_index=0, records_path="job_list", field_map=dict(field_map),
        pagination=PaginationHint(style="offset", param="offset", page_size=12),
    )

    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        # Replays what the STORED recipe says, which is the model's path.
        (extract,) = [s for s in script["steps"] if s["op"] == "extract_json_path"]
        rows = map_records(
            body[extract["records_path"]], extract["fields"], script["base_url"]
        )
        return rows, HarvestEvidence(
            declared_total=120, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )

    # The pre-filter really does prefer the longer decoy — otherwise this proves nothing.
    assert prefilter_candidates([response])[0].records_path == "saved_searches"

    outcome = await discover(
        _AMAZON_URL, capture=_capture, select=_selecting(corrected),
        replay_http=_replay, replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.script is not None
    (paginate,) = [s for s in outcome.script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["page_size"] == 12          # the model's array, not the decoy's 30


async def test_refuses_when_no_response_is_job_shaped() -> None:
    """The Meta case — a board with no capturable API. It must REFUSE, not fall back to
    a DOM/agent tier: there is no such tier by design, because one could silently drift
    and burn resources daily. The LLM is never called, so the refusal is also free."""
    async def _boom(candidates: list[Any]) -> RequestSelection:
        raise AssertionError("the selector must not run with nothing job-shaped")

    outcome = await discover(
        _META_URL,
        capture=_capturing("noise"),
        select=_boom,
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "finding the jobs feed" in (outcome.refuse_reason or "")
    assert "returned a list of job postings" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_a_page_that_fetches_no_json_at_all_gets_its_own_refusal_copy() -> None:
    """Measured on metacareers.com: it captures ZERO JSON XHRs. That is a different board
    from one that fetched plenty of JSON, none of it jobs, and the user's next action
    differs — so the two must not share a sentence."""
    async def _empty(url: str) -> CaptureResult:
        return CaptureResult(final_url=_META_URL, page_title="Meta", responses=[])

    outcome = await discover(
        _META_URL, capture=_empty, select=_selecting(_amazon_selection()),
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "without any JSON request we could record" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_refuses_when_the_synthesized_recipe_fails_validate_recipe() -> None:
    """validate-on-WRITE (invariant #5). The captured endpoint here is plain http, which
    ``recipe_schema`` rejects — and the refusal must name the synthesis step rather than
    escaping as a bare RecipeError. Note the SSRF guard is stubbed open on purpose: the
    two checks are independent, and this proves the schema is a real second wall."""
    report = json.loads((_FIXTURES / "amazon_capture.json").read_text())
    report["responses"][2]["url"] = "http://www.amazon.jobs/en/search.json?offset=0"

    async def _capture(url: str) -> CaptureResult:
        return CaptureResult(
            final_url=report["final_url"], page_title="",
            responses=_responses_from_report(report),
        )

    outcome = await discover(
        _AMAZON_URL,
        capture=_capture,
        select=_selecting(_amazon_selection()),
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "writing the replay recipe" in (outcome.refuse_reason or "")
    assert "invalid" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_refuses_a_blocked_entry_url_before_opening_a_browser() -> None:
    """SSRF, entry half (invariant #4). A blocked URL must cost ZERO Chromium, which is
    provable only by counting captures — hence the calls list rather than a mock."""
    captures: list[str] = []
    outcome = await discover(
        "https://internal.corp.example/careers",
        capture=_capturing("amazon", calls=captures),
        select=_selecting(_amazon_selection()),
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_blocking("internal.corp.example"),
    )
    assert outcome.ok is False
    assert "checking the careers URL" in (outcome.refuse_reason or "")
    assert captures == []
    _assert_stores_nothing(outcome)


async def test_refuses_a_blocked_discovered_endpoint_before_the_llm_sees_it() -> None:
    """SSRF, discovered-endpoint half. The page loads fine and its jobs XHR points
    somewhere we refuse to fetch; that endpoint must never reach a prompt (it would leak
    an internal address into an outbound API call) let alone a stored recipe."""
    async def _boom(candidates: list[Any]) -> RequestSelection:
        raise AssertionError("a non-public endpoint must never reach the selector")

    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_boom,
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_blocking("search.json"),
    )
    assert outcome.ok is False
    assert "finding the jobs feed" in (outcome.refuse_reason or "")
    assert "refuse to fetch" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_refuses_when_the_capture_itself_fails() -> None:
    async def _capture(url: str) -> CaptureResult:
        raise CaptureError("capture subprocess timed out after 120.0s")

    outcome = await discover(
        _AMAZON_URL, capture=_capture, select=_selecting(_amazon_selection()),
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "opening the careers page" in (outcome.refuse_reason or "")
    assert "timed out" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_refuses_when_the_selector_answer_is_unbelievable() -> None:
    async def _select(candidates: list[Any]) -> RequestSelection:
        raise RequestSelectionError("records_path 'data.results' does not resolve")

    outcome = await discover(
        _AMAZON_URL, capture=_capturing("amazon"), select=_select,
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "reading the jobs feed" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_missing_llm_key_refuses_without_burning_an_attempt() -> None:
    """A deployment without an API key is OUR misconfiguration. Refusing with
    ``attempts=0`` keeps that distinguishable in the audit row from a board we genuinely
    could not read after two real rounds."""
    async def _select(candidates: list[Any]) -> RequestSelection:
        raise SelectorKeyMissingError("anthropic_api_key is not configured")

    outcome = await discover(
        _AMAZON_URL, capture=_capturing("amazon"), select=_select,
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert outcome.attempts == 0
    assert "not configured on this deployment" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_never_raises_even_when_a_collaborator_explodes() -> None:
    """The caller is a retry=1 task whose provisional ``discovering`` row is cleared
    only by a RETURNED outcome. An escaping exception wedges that row at "Setting up…"
    with no recovery but Remove + re-add, so an unexpected crash must still refuse.

    The reason must name the step we actually REACHED. A hardcoded "verifying we can
    read it" told a user whose capture blew up to go look at the wrong thing."""
    async def _explode(url: str) -> CaptureResult:
        raise ZeroDivisionError("something nobody predicted")

    outcome = await discover(
        _AMAZON_URL, capture=_explode, select=_selecting(_amazon_selection()),
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "ZeroDivisionError" in (outcome.refuse_reason or "")
    assert (outcome.refuse_reason or "").startswith("opening the careers page")
    _assert_stores_nothing(outcome)


async def test_an_unexpected_crash_in_the_selector_names_the_selection_step() -> None:
    """Same property, a different step — proving the step is tracked rather than
    coincidentally right. A selector that raises something nobody anticipated is a
    "reading the jobs feed" problem, not an acceptance one."""
    async def _explode(candidates: list[Any]) -> RequestSelection:
        raise MemoryError("something nobody predicted")

    outcome = await discover(
        _AMAZON_URL, capture=_capturing("amazon"), select=_explode,
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert (outcome.refuse_reason or "").startswith("reading the jobs feed")
    assert "MemoryError" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


async def test_a_body_too_big_to_record_says_so_instead_of_blaming_the_board() -> None:
    """A captured body over the child's cap comes back EMPTY with ``truncated=True``
    (half a JSON document parses as nothing at all, so truncating it was worse than
    useless). The pre-filter then drops it — and folding that into "none of them
    returned a list of job postings" tells the user the exact opposite of what
    happened about the one request that did, and leaves them no next action."""
    responses = _capture_result("amazon").responses
    oversize = [
        r.__class__(**{**r.__dict__, "body": "", "truncated": True}) for r in responses
    ]

    async def _capture(url: str) -> CaptureResult:
        return CaptureResult(final_url=_AMAZON_URL, page_title="", responses=oversize)

    outcome = await discover(
        _AMAZON_URL, capture=_capture, select=_selecting(_amazon_selection()),
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "finding the jobs feed" in (outcome.refuse_reason or "")
    assert "more data than we can record" in (outcome.refuse_reason or "")
    _assert_stores_nothing(outcome)


def _assert_stores_nothing(outcome: Any) -> None:
    """A REFUSE carries no script, no transport and no oracle_kind — the discovery task
    asserts all three are present before it writes a ``company_scripts`` row, so this is
    what makes "refuse stores nothing" a property of the value object, not of the SQL."""
    assert outcome.script is None
    assert outcome.transport is None
    assert outcome.oracle_kind is None


# --- synthesis details worth pinning on their own ----------------------------

def _amazon_body() -> dict[str, Any]:
    """The Amazon fixture's jobs response, parsed — the base for shape variations."""
    responses = _responses_from_report(
        json.loads((_FIXTURES / "amazon_capture.json").read_text())
    )
    return dict(json.loads(responses[2].body))


def _amazon_response(body: dict[str, Any]) -> Any:
    """That same captured response carrying ``body`` instead of its own."""
    responses = _responses_from_report(
        json.loads((_FIXTURES / "amazon_capture.json").read_text())
    )
    original = responses[2]
    return original.__class__(**{**original.__dict__, "body": json.dumps(body)})


def _untotalled_amazon() -> Any:
    """The Amazon jobs response with every total-ish key removed — a board that
    publishes no total at all."""
    body = _amazon_body()
    del body["hits"]
    del body["facets"]
    return _amazon_response(body)


def test_no_pagination_step_when_the_capture_already_saw_the_whole_board() -> None:
    """Spotify's shape: the declared total equals the page we captured. A pagination
    step there would spend a round-trip a night fetching an empty second page."""
    body = _amazon_body()
    body["hits"] = 10                                   # == the captured record count
    candidate = prefilter_candidates([_amazon_response(body)])[0]

    script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    assert [s["op"] for s in script["steps"] if s["op"].startswith("paginate_")] == []


def test_a_board_with_no_declared_total_still_pages_and_is_self_consistent() -> None:
    """No trusted total → ``self_consistent``, which can only ever VERIFY after the
    3-run streak. Inventing an oracle path instead would make every night a FAILED run;
    that is why the total is searched deterministically and never asked of the LLM.

    The paginate step is the other half and used to be dropped here: emitting it only
    when a total said "there is more" left a paging board stored as a page-1-only
    recipe, and a page-1-only sweep reports ``terminated_cleanly`` with no cap — so
    ``self_consistent`` VERIFIED it every night and began closing everything past page
    one, on a board it never finished reading (invariant #2)."""
    candidate = prefilter_candidates([_untotalled_amazon()])[0]

    script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    assert script["oracle"] == {"kind": "self_consistent"}
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["param"] == "offset"


def test_a_page_one_only_recipe_makes_no_completeness_claim_at_all() -> None:
    """The residual of the case above: no declared total AND no paging hint. One
    request that returns page one of an unknown-length board is indistinguishable from
    one that returns the whole board, so the recipe must not claim ``self_consistent``
    — a sweep it never ran. ``none`` maps to UNVERIFIED in ``verify_harvest``, which
    shows the board's jobs every night and closes none of them."""
    candidate = prefilter_candidates([_untotalled_amazon()])[0]
    no_paging = RequestSelection(
        chosen_request_index=0, records_path="jobs",
        field_map=dict(_AMAZON_MAP), pagination=None,
    )

    script = synthesize_recipe(
        candidate, no_paging, transport="http_json", origin_url=_AMAZON_URL
    )
    assert script["oracle"] == {"kind": "none"}
    assert [s["op"] for s in script["steps"] if s["op"].startswith("paginate_")] == []
    # ...and prove what that oracle BUYS, in the gate that actually decides closing:
    # a clean, uncapped, stable run still lands UNVERIFIED, so no miss and no close.
    clean = HarvestEvidence(
        declared_total=None, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=None, pages_fetched=1, transport_ok=True,
    )
    verdict = verify_harvest(
        "none",
        GateResult(jobs=[], records_harvested=10, id_dedup_dropped=0),
        clean,
        SimpleNamespace(median_records=10),
    )
    assert verdict.verdict == UNVERIFIED


def test_the_declared_total_is_the_largest_total_key_not_the_first_one_found() -> None:
    """A board that publishes both a per-page and a whole-board count lists them in its
    own order. Taking the first match pinned the PAGE SIZE as the trusted total: the
    nightly run harvests page one, matches its own "total" exactly, lands VERIFIED
    ``declared_exact`` — and ``declared_probed`` is exempt from the id-churn guard, so
    every job that rolled off page one is closed while still open (invariant #2)."""
    body = {"resultCount": 10, "hits": 76, "jobs": _amazon_body()["jobs"]}
    candidate = prefilter_candidates([_amazon_response(body)])[0]

    script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    assert script["oracle"] == {"kind": "declared_probed", "total_path": "hits"}
    assert [s["op"] for s in script["steps"] if s["op"].startswith("paginate_")] != []


def test_a_post_board_stores_its_captured_body_as_an_object() -> None:
    """``recipe_schema`` requires ``fetch.body`` to be an object because that is what the
    pagination merge writes into — a stored string body would page silently nowhere."""
    candidate = prefilter_candidates(_capture_result("tiktok").responses)[0]
    script = synthesize_recipe(
        candidate, _tiktok_selection(), transport="browser_fetch", origin_url=_TIKTOK_URL
    )
    fetch = script["steps"][0]
    assert fetch["method"] == "POST"
    assert fetch["body"]["limit"] == 10
    assert fetch["headers"]["website-path"] == "tiktok"      # the header it 400s without


# --- the discovery-progress checklist (E7 unit 3) -----------------------------


def _steps(progress: dict) -> dict:
    return {step["key"]: step for step in progress["steps"]}


async def test_an_accept_narrates_every_step_with_a_specific_result() -> None:
    """A generic tick is a spinner with extra steps. Each step must carry the thing it
    actually found ("found 1 candidate feed", "read 10 jobs") — that number is how a
    user tells whether the board we are about to track is theirs."""
    published: list[dict] = []

    async def _emit(snapshot: dict) -> None:
        published.append(snapshot)

    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        emit=_emit,
    )
    assert outcome.ok is True
    assert outcome.progress is not None
    steps = _steps(outcome.progress)
    assert outcome.progress["outcome"] == "tracking"
    assert all(step["status"] == "done" for step in outcome.progress["steps"])
    assert "www.amazon.jobs" in steps["open_page"]["result"]
    assert steps["find_feed"]["result"].startswith("found ")
    assert steps["verify_read"]["result"].startswith("read ")
    assert "no browser needed" in steps["ready"]["result"]

    # LIVE, not just terminal: the user watches steps land while the run is going.
    # Three publishes — entering step 1, finishing it, and finishing step 2 — and the
    # terminal one is deliberately NOT emitted (it rides the outcome so the persist
    # writes it in the same statement that flips the row).
    assert len(published) == 3
    assert _steps(published[0])["open_page"]["status"] == "active"
    assert _steps(published[1])["open_page"]["status"] == "done"
    assert _steps(published[2])["verify_read"]["status"] == "active"
    assert all(p["outcome"] == "running" for p in published)


async def test_the_accept_preview_is_the_jobs_the_REPLAY_returned() -> None:
    """Not the capture's rows — the replay's. Those are the bytes the nightly harvest
    will read, and showing jobs only the capture browser could see would preview a
    board we cannot actually track (DECISION D3)."""
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.progress is not None
    preview = outcome.progress["job_preview"]
    assert 1 <= len(preview) <= 5
    assert all(row["title"] for row in preview)
    # Only the renderable fields — the rest of the harvested record is not echoed back.
    assert all(set(row) <= {"title", "location", "url"} for row in preview)


async def test_a_refusal_marks_the_step_that_actually_failed() -> None:
    """The acceptance gate rejected the replay, so the ✕ belongs on "verifying we can
    read it" while the earlier steps keep their ticks — that is the difference between
    "we couldn't read this board" and a next action the user can take."""
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_failing_replay(RecipeExecutionError("HTTP 403 from amazon.jobs")),
        replay_browser=_failing_replay(RecipeExecutionError("blocked in Chromium too")),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert outcome.progress is not None
    assert outcome.progress["outcome"] == "refused"
    steps = _steps(outcome.progress)
    assert steps["open_page"]["status"] == "done"
    assert steps["find_feed"]["status"] == "done"
    assert steps["verify_read"]["status"] == "failed"
    assert steps["ready"]["status"] == "pending"


async def test_a_capture_failure_fails_the_first_step_not_a_later_one() -> None:
    """A page we could not even open must not report "couldn't confirm the results
    match" — the user's next action for a bot-walled page is nothing like the one for a
    feed we read and disbelieved."""
    async def _blocked(url: str) -> CaptureResult:
        raise CaptureError("navigation blocked")

    outcome = await discover(
        _META_URL, capture=_blocked, select=_selecting(_amazon_selection()),
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert outcome.progress is not None
    steps = _steps(outcome.progress)
    assert steps["open_page"]["status"] == "failed"
    assert "navigation blocked" in steps["open_page"]["result"]
    assert steps["find_feed"]["status"] == "pending"


async def test_a_failed_step_overrides_the_tick_it_had_already_earned() -> None:
    """The pre-filter finds job-shaped feeds ("found N candidate feeds" ✓) and the
    selector then says none of them is a jobs list. Leaving the ✓ on "finding the jobs
    feed" would hide the one thing the user needs to know."""
    async def _no_feed(candidates: list[Any]) -> RequestSelection:
        raise NoJobsFeedError("none of these is a jobs feed")

    outcome = await discover(
        _AMAZON_URL, capture=_capturing("amazon"), select=_no_feed,
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    steps = _steps(outcome.progress or {"steps": []})
    assert steps["find_feed"]["status"] == "failed"
    assert "list of job postings" in steps["find_feed"]["result"]


async def test_a_progress_write_that_blows_up_never_refuses_the_board() -> None:
    """The narration is cosmetic; the discovery is not. An exception out of ``emit``
    would otherwise land in the broad last-resort handler and refuse a board we can
    read perfectly well — the exact inversion of what this feature is for."""
    async def _explode(snapshot: dict) -> None:
        raise RuntimeError("the progress connection is down")

    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        emit=_explode,
    )
    assert outcome.ok is True
    assert outcome.transport == "http_json"


async def test_a_browserbase_live_view_url_rides_the_checklist_when_there_is_one() -> None:
    """Optional garnish, absent by default: only a Browserbase session has a hosted
    view and our default is our own Chromium, so the UI must treat it as an extra and
    never block on it (DECISION D4)."""
    async def _with_live_view(url: str) -> CaptureResult:
        base = _capture_result("amazon")
        return CaptureResult(
            final_url=base.final_url, page_title=base.page_title,
            responses=base.responses,
            live_view_url="https://www.browserbase.com/devtools-fullscreen/x?navbar=false",
        )

    outcome = await discover(
        _AMAZON_URL, capture=_with_live_view,
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.progress is not None
    assert outcome.progress["live_view_url"].startswith("https://www.browserbase.com/")


# --- THE TWO PAGE BUDGETS, and the page size that makes them affordable -------
#
# One constant used to be both the acceptance budget AND the nightly harvest budget
# (``_MAX_PAGES = 10``), and the page size was always whatever the careers page's own
# layout asked for. On amazon.jobs that is ten pages of ten: 97 jobs out of ~22,000,
# a company pinned at ``health_state='unverified'`` forever, and a user shown a sliver
# of the board. Acceptance and harvest are different questions — "can we read this?"
# and "read all of it" — and these lock them apart.


def _big_amazon(hits: int = 5000, *, facet_consensus: int | None = None) -> Any:
    """The Amazon fixture's response with a bigger declared total (and optionally a
    facet block pair that CONTRADICTS it — the window-cap shape)."""
    body = _amazon_body()
    body["hits"] = hits
    if facet_consensus is None:
        body["facets"] = {"normalized_state_name_facet": [{"Washington": hits}]}
    else:
        # TWO independently-computed partitions agreeing on a bigger number: the
        # signal that ``hits`` is a search WINDOW, not the size of the board.
        body["facets"] = {
            "category_facet": [{"Software Development": facet_consensus}],
            "business_category_facet": [
                {"aws": facet_consensus - 1}, {"retail": 1},
            ],
            # ...and one that merely COVERS without partitioning, which must not be
            # able to create a consensus on its own (GM's 1,042-vs-835).
            "location_facet": [{"Seattle": facet_consensus * 2}],
        }
    return _amazon_response(body)


def _capturing_big(hits: int = 5000, *, facet_consensus: int | None = None):
    """The Amazon capture with a board big enough for the page-size upgrade to be
    worth proving (the fixture's own ``hits: 76`` is one page and change)."""
    async def _capture(url: str) -> CaptureResult:
        original = _capture_result("amazon")
        responses = list(original.responses)
        responses[2] = _big_amazon(hits, facet_consensus=facet_consensus)
        return CaptureResult(
            final_url=original.final_url, page_title=original.page_title,
            responses=responses,
        )
    return _capture


def _paging_replay(
    *,
    declared_total: int,
    honours_page_size: bool = True,
    rejects_page_size: bool = False,
    calls: list[dict[str, Any]] | None = None,
):
    """A replay that answers the way a REAL board answers a page-size request.

    Records ``{page_size, max_pages}`` per call, so a test can assert what acceptance
    actually asked for. ``honours_page_size=False`` is the board that silently caps the
    page at its own size — it returns the capture's one short page, which is exactly
    what a sweep reads as "the board ended"; ``rejects_page_size=True`` is the board
    that says so out loud (amazon.jobs answers ``"Result limit cannot be greater than
    100"`` in-band, which the runner raises on).
    """
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
        page_size = paginate["page_size"]
        if calls is not None:
            calls.append({"page_size": page_size, "max_pages": paginate["max_pages"]})
        captured = prefilter_candidates(_capture_result("amazon").responses)[0]
        rows = map_records(captured.records, _AMAZON_MAP, script.get("base_url", ""))
        upgraded = page_size > len(rows)
        if upgraded and rejects_page_size:
            raise RecipeExecutionError(
                "in-band error key 'error' present in a 200 body: "
                "'Result limit cannot be greater than 100'"
            )
        if upgraded and not honours_page_size:
            # A SHORT first page. The sweep stops there and reports a clean terminus.
            return rows, HarvestEvidence(
                declared_total=declared_total, cap_hit=False, terminated_cleanly=True,
                page_advance_ok=None, pages_fetched=1, transport_ok=True,
            )
        # Both probe pages came back FULL: the real capture rows plus filler, so the
        # match-the-capture check still compares against ids the browser really saw.
        filler = [
            {**rows[0], "id": f"filler-{i}"}
            for i in range(page_size * 2 - len(rows))
        ]
        return rows + filler, HarvestEvidence(
            declared_total=declared_total, cap_hit=False, terminated_cleanly=False,
            page_advance_ok=True, pages_fetched=2, transport_ok=True,
        )
    return _replay


def test_the_harvest_budget_is_derived_from_the_boards_own_total() -> None:
    """The stored budget must be able to REACH the end of the board.

    A flat constant is wrong in both directions at once: ten pages of a board that
    declares 5,000 is a 5% sample that ``verify_harvest`` can never certify (so the
    company never leaves 'unverified' and the user never sees the other 95%), while the
    same ten pages on a 30-job board are eight wasted round-trips a night. Derived from
    the board's own two numbers, it is neither.
    """
    candidate = prefilter_candidates([_big_amazon(hits=5000)])[0]

    script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json",
        origin_url=_AMAZON_URL, page_size_override=100,
    )
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["page_size"] == 100
    # ceil(5000 / 100) + the growth headroom — enough to read the whole board and
    # still terminate on a short page after the board grows.
    assert paginate["max_pages"] == 52


def test_the_harvest_budget_never_exceeds_the_transports_own_ceiling() -> None:
    """A budget the transport cannot honour is not a budget. ``browser_fetch`` runs
    every page as a fresh in-browser fetch inside one 90s Chromium session, so its
    ceiling is far lower than the http tier's — and the parent's ``min()`` clamp is the
    WRONG place to discover that, because a clamped sweep still reports a terminus."""
    candidate = prefilter_candidates([_big_amazon(hits=50_000)])[0]

    http_script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    browser_script = synthesize_recipe(
        candidate, _amazon_selection(), transport="browser_fetch",
        origin_url=_AMAZON_URL,
    )
    (http_paginate,) = [s for s in http_script["steps"] if s["op"].startswith("paginate_")]
    (bf_paginate,) = [s for s in browser_script["steps"] if s["op"].startswith("paginate_")]
    assert http_paginate["max_pages"] == 100
    assert bf_paginate["max_pages"] == BROWSER_FETCH_MAX_PAGES


def test_a_board_with_no_declared_total_gets_the_ceiling_not_a_flat_ten() -> None:
    """With no total there is no derivation, and the only defensible budget left is the
    ceiling: the sweep stops on the first short page, so a small board pays nothing for
    it, while any smaller flat number truncates exactly the boards whose length we
    cannot otherwise measure — and a ``self_consistent`` board that never reaches its
    own end is UNVERIFIED forever."""
    candidate = prefilter_candidates([_untotalled_amazon()])[0]

    script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["max_pages"] == 100


async def test_acceptance_is_bounded_while_the_stored_budget_is_not() -> None:
    """THE SPLIT. Acceptance asks "can we read this board from our own environment?",
    which two pages answer as well as a hundred — and it runs inside a 240s task that
    has already spent a browser capture and an LLM call. The STORED recipe carries the
    whole-board budget. One constant doing both jobs is what capped amazon.jobs at 97.
    """
    calls: list[dict[str, Any]] = []
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing_big(),
        select=_selecting(_amazon_selection()),
        replay_http=_paging_replay(declared_total=5000, calls=calls),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.script is not None
    (stored,) = [s for s in outcome.script["steps"] if s["op"].startswith("paginate_")]
    # What ACCEPTANCE replayed vs what got STORED — same recipe, different budgets.
    assert [c["max_pages"] for c in calls] == [2]
    assert stored["max_pages"] == 52


async def test_the_page_size_is_synthesized_and_the_board_must_prove_it() -> None:
    """The page size is a RECIPE parameter, not a property of the board: amazon.jobs
    paints ten cards because that is what its layout wants, and replaying that verbatim
    turns a 22,000-job board into 1,000 sequential requests no nightly budget can hold.

    Raised to 100 it is ~100 requests — but only because the ACCEPTANCE REPLAY proved
    the board serves full 100-record pages. The recipe's URL and its ``page_size`` must
    move together, or the sweep either skips 90 jobs a page or re-reads the same ten.
    """
    calls: list[dict[str, Any]] = []
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing_big(),
        select=_selecting(_amazon_selection()),
        replay_http=_paging_replay(declared_total=5000, calls=calls),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.script is not None
    fetch, *_ = outcome.script["steps"]
    (paginate,) = [s for s in outcome.script["steps"] if s["op"].startswith("paginate_")]
    assert "result_limit=100" in fetch["url"]        # the request ASKS for 100...
    assert paginate["page_size"] == 100              # ...and the sweep pages by 100
    assert [c["page_size"] for c in calls] == [100]  # proven on the real replay path


async def test_a_board_that_ignores_the_bigger_page_falls_back_to_the_captured_one() -> None:
    """THE WRONG-CLOSE THIS PROOF PREVENTS. A board that silently caps the page answers
    a 100-record request with its own 10 — and ``_sweep_offset_page`` reads a page
    shorter than ``page_size`` as THE END OF THE BOARD. Stored unchallenged, that
    recipe reports 10 jobs as a complete board every night and, on a ``self_consistent``
    oracle, VERIFIES it and closes everything else. Detected at acceptance it costs one
    extra replay and the board is stored exactly as it was captured.
    """
    calls: list[dict[str, Any]] = []
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing_big(),
        select=_selecting(_amazon_selection()),
        replay_http=_paging_replay(
            declared_total=5000, honours_page_size=False, calls=calls
        ),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True                        # fall back, never refuse
    assert outcome.script is not None
    (paginate,) = [s for s in outcome.script["steps"] if s["op"].startswith("paginate_")]
    assert [c["page_size"] for c in calls] == [100, 10]   # tried, disproven, fell back
    assert paginate["page_size"] == 10
    assert "result_limit=10" in outcome.script["steps"][0]["url"]


async def test_a_board_that_rejects_the_bigger_page_falls_back_instead_of_refusing() -> None:
    """The louder half of the same case: amazon.jobs answers ``"Result limit cannot be
    greater than 100"`` in a 200 body, which the runner RAISES on. A parameter WE chose
    must never be able to refuse a board we can otherwise read."""
    calls: list[dict[str, Any]] = []
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing_big(),
        select=_selecting(_amazon_selection()),
        replay_http=_paging_replay(
            declared_total=5000, rejects_page_size=True, calls=calls
        ),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert [c["page_size"] for c in calls] == [100, 10]
    assert outcome.script is not None
    (paginate,) = [s for s in outcome.script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["page_size"] == 10


def test_a_window_capped_declared_total_is_never_a_completeness_oracle() -> None:
    """MEASURED ON amazon.jobs, and the reason a bigger budget is not enough on its own.

    ``hits: 10000`` is not the size of Amazon's board — it is its Elasticsearch WINDOW
    (``offset + result_limit > 10000`` is a hard in-band error), while six of its own
    facet blocks independently sum to 22,621. A budget derived from ``hits`` reads
    exactly 10,000 rows, matches that "total" EXACTLY, lands VERIFIED
    ``declared_exact`` — and closes the other 12,621 live jobs. The old flat 10-page
    budget only avoided that by never getting near the total, so raising the budget
    without this guard would have CREATED a confident wrong-close (invariant #2).

    The number is still kept, as the furthest offset the API will serve
    (``window_cap``); what it may not become is the thing that certifies the run.
    """
    candidate = prefilter_candidates(
        [_big_amazon(hits=10_000, facet_consensus=22_621)]
    )[0]

    script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json",
        origin_url=_AMAZON_URL, page_size_override=100,
    )
    assert script["oracle"] == {"kind": "self_consistent"}
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["window_cap"] == 10_000

    # ...and prove what that buys IN THE GATE THAT ACTUALLY CLOSES JOBS: a sweep that
    # read the whole 10,000-row window and ran out of budget cannot be VERIFIED, so it
    # increments no misses and closes nothing.
    exhausted = HarvestEvidence(
        declared_total=None, cap_hit=False, terminated_cleanly=False,
        page_advance_ok=True, pages_fetched=100, transport_ok=True,
    )
    verdict = verify_harvest(
        script["oracle"]["kind"],
        GateResult(jobs=[], records_harvested=10_000, id_dedup_dropped=0),
        exhausted,
        SimpleNamespace(median_records=10_000),
    )
    assert verdict.verdict == UNVERIFIED


def test_a_single_facet_block_cannot_discredit_a_declared_total_on_its_own() -> None:
    """The other side of the same guard. One facet that COVERS without PARTITIONING
    over-counts (GM's 1,042-vs-835; amazon's own ``location_facet`` sums to 35,048
    against a real 22,621), so a lone block bigger than the total is not evidence — and
    treating it as evidence would strip ``declared_probed`` off every honest board with
    a multi-valued facet, leaving it UNVERIFIED forever."""
    body = _amazon_body()
    body["hits"] = 76
    body["facets"] = {"location_facet": [{"Seattle": 60}, {"Austin": 60}]}
    candidate = prefilter_candidates([_amazon_response(body)])[0]

    script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    assert script["oracle"] == {"kind": "declared_probed", "total_path": "hits"}
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert "window_cap" not in paginate
