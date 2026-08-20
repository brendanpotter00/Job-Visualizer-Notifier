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
from typing import Any

import pytest

# NOTE: `from ...discover import` (not `import ... as disc`) — the capture package
# `__init__` re-exports the FUNCTION `discover`, which shadows the submodule attribute.
from api.services.capture.discover import (
    _MAX_SELECTION_ROUNDS,
    discover,
    synthesize_recipe,
)
from api.services.capture.network_capture import (
    CaptureError,
    CaptureResult,
    _responses_from_report,
)
from api.services.capture.request_selector import (
    PaginationHint,
    RequestSelection,
    RequestSelectionError,
    SelectorKeyMissingError,
    prefilter_candidates,
)
from api.services.harvest_meta import HarvestEvidence
from api.services.recipe_runner import RecipeExecutionError, map_records
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
    assert replays == ["http_json", "browser_fetch"]
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


async def test_refuses_when_both_transports_fail_and_candidates_are_exhausted() -> None:
    """Candidates exhausted → REFUSE, and the ladder is BOUNDED: each round costs a
    Haiku call and up to two replays inside a 240s task, so an unbounded loop would be a
    money bug as well as a hang."""
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
    # Two candidates in the TikTok capture → at most _MAX_SELECTION_ROUNDS rounds.
    assert len(select_calls) == _MAX_SELECTION_ROUNDS
    assert select_calls == [2, 1]           # the failed candidate is dropped, then re-asked
    _assert_stores_nothing(outcome)


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
    with no recovery but Remove + re-add, so an unexpected crash must still refuse."""
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
    _assert_stores_nothing(outcome)


def _assert_stores_nothing(outcome: Any) -> None:
    """A REFUSE carries no script, no transport and no oracle_kind — the discovery task
    asserts all three are present before it writes a ``company_scripts`` row, so this is
    what makes "refuse stores nothing" a property of the value object, not of the SQL."""
    assert outcome.script is None
    assert outcome.transport is None
    assert outcome.oracle_kind is None


# --- synthesis details worth pinning on their own ----------------------------

def test_no_pagination_step_when_the_capture_already_saw_the_whole_board() -> None:
    """Spotify's shape: the declared total equals the page we captured. A pagination
    step there would spend a round-trip a night fetching an empty second page."""
    responses = _responses_from_report(
        json.loads((_FIXTURES / "amazon_capture.json").read_text())
    )
    body = json.loads(responses[2].body)
    body["hits"] = 10                                   # == the captured record count
    whole = responses[2].__class__(**{**responses[2].__dict__, "body": json.dumps(body)})
    candidate = prefilter_candidates([whole])[0]

    script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    assert [s["op"] for s in script["steps"] if s["op"].startswith("paginate_")] == []


def test_a_board_with_no_declared_total_gets_the_self_consistent_oracle() -> None:
    """No trusted total → ``self_consistent``, which can only ever VERIFY after the
    3-run streak. Inventing an oracle path instead would make every night a FAILED run;
    that is why the total is searched deterministically and never asked of the LLM."""
    responses = _responses_from_report(
        json.loads((_FIXTURES / "amazon_capture.json").read_text())
    )
    body = json.loads(responses[2].body)
    del body["hits"]
    del body["facets"]
    untotalled = responses[2].__class__(
        **{**responses[2].__dict__, "body": json.dumps(body)}
    )
    candidate = prefilter_candidates([untotalled])[0]

    script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    assert script["oracle"] == {"kind": "self_consistent"}


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
