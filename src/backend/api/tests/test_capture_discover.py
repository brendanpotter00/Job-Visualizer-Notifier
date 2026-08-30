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
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

# NOTE: `from ...discover import` (not `import ... as disc`) — the capture package
# `__init__` re-exports the FUNCTION `discover`, which shadows the submodule attribute.
from api.services.capture.discover import (
    _MAX_REQUEST_PUBLISHES,
    _MAX_SELECTION_ROUNDS,
    _PAGES_WITHIN_TIME_BUDGET,
    _coverage,
    _inband_error_keys,
    _labelled_facet_total,
    _totals_beside_records,
    discover,
    page_size_attempts,
    synthesize_recipe,
)
from api.services.capture.network_capture import (
    CaptureError,
    CaptureResult,
    _islands_from_report,
    _responses_from_report,
)
from api.services.capture.request_selector import (
    CandidateAnswer,
    NoJobsFeedError,
    PaginationHint,
    RequestSelection,
    RequestSelectionError,
    SelectorKeyMissingError,
    prefilter_candidates,
)
from api.services.capture.sources import (
    SitemapDocument,
    WellKnownEvidence,
)
from api.services.discovery.progress import (
    OUTCOME_RUNNING,
    STATUS_ACTIVE,
    STEP_OPEN_PAGE,
)
from api.services.harvest_meta import HarvestEvidence
from api.services.harvest_verification import UNVERIFIED, GateResult, verify_harvest
from api.services.recipe_runner import (
    MAX_HARVEST_RECORDS,
    RecipeExecutionError,
    map_records,
    run_recipe,
)
from api.services.recipe_schema import BROWSER_FETCH_MAX_PAGES, dig_records
from api.services.url_guard import UrlGuardError

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).parent / "fixtures" / "discovery"


def _one_page_per_job() -> "Any":
    """A probe double for a board that really does serve a different page per job.

    Discovery now PROVES a job link it INVENTED by fetching it (``_prove_job_link``),
    and the default probe is a real ``httpx`` GET. No unit test may make that request —
    it would be slow, flaky, and would silently pass or fail on whatever the live board
    is doing today — so :func:`_no_live_job_link_probe` installs this everywhere.

    It answers 200 with a page whose LENGTH is unique per URL, which is the shape of a
    board whose route key is right. The tests that exercise the other answers — a 404,
    an SPA shell that serves the same bytes for every job, a published link that must
    never be fetched at all — inject their own probe and are named for it.
    """
    lengths: dict[str, int] = {}

    def probe(url: str) -> tuple[int, str]:
        nth = lengths.setdefault(url, len(lengths))
        return 200, "<html><body>" + "job " * (500 + 200 * nth) + "</body></html>"

    return probe


@pytest.fixture(autouse=True)
def _no_live_job_link_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this module reaches the network to check a job link. See above.

    Reached through ``sys.modules`` for the reason the import NOTE at the top of this
    file gives: the capture package's ``__init__`` re-exports the FUNCTION ``discover``,
    so ``api.services.capture.discover`` is the function, not the module, and patching
    an attribute on it would silently patch nothing.
    """
    import sys

    monkeypatch.setattr(
        sys.modules["api.services.capture.discover"],
        "_default_probe",
        _one_page_per_job(),
    )


@pytest.fixture(autouse=True)
def _no_live_well_known(monkeypatch: pytest.MonkeyPatch) -> None:
    """...and no test in this module fetches a real robots.txt or sitemap either.

    Source 5 composes URLs from the entry origin and GETs them for real, concurrently
    with the capture. Every fixture in this file names a live board, so without this the
    suite would hammer amazon.jobs and careers.walmart.com on every run and pass or fail
    on whatever they served that second. Tests that exercise the collector inject their
    own evidence through the ``collect_sources`` seam and are named for it.
    """
    import sys

    async def _nothing(_url: str) -> WellKnownEvidence:
        return WellKnownEvidence()

    monkeypatch.setattr(
        sys.modules["api.services.capture.discover"], "collect_well_known", _nothing
    )

_AMAZON_URL = "https://www.amazon.jobs/en/search"
_TIKTOK_URL = "https://lifeattiktok.com/search"
_META_URL = "https://www.metacareers.com/jobs"

# Stand-ins for what ``select_candidates`` returns. Neither ``description`` nor
# ``department``: both fixtures' records were trimmed before either was a mappable field
# (the live amazon.jobs payload carries a description on 10/10 records). Both are
# OPTIONAL in the canonical set, so a map without them is a legitimate answer for a
# board that publishes neither — which is what these two fixtures now are.
_AMAZON_MAP = {
    "id": "id_icims",
    "title": "title",
    "url": "https://www.amazon.jobs{job_path}",
    "location": "normalized_location",
    "posted_at": "posted_date",
}
_TIKTOK_MAP = {
    "id": "id",
    "title": "title",
    "url": "https://lifeattiktok.com/search/{id}",
    "location": "city_info.en_name",
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
    async def _capture(url: str, **_: Any) -> CaptureResult:
        if calls is not None:
            calls.append(url)
        return _capture_result(name)
    return _capture


def _selecting(
    selection: RequestSelection,
    *,
    calls: list[int] | None = None,
    feedbacks: list[str | None] | None = None,
    confidence: str = "high",
):
    """A fan-out double answering YES about exactly one candidate.

    The seam returns a LIST of per-candidate answers now (one model call per array
    instead of one over the list), so this wraps a single ``RequestSelection`` into the
    one-yes answer the referee then ranks trivially. ``feedbacks`` records what each
    round was TOLD about the last one — the seam that lets a test prove a re-ask carried
    the probe's evidence.
    """
    async def _select(
        candidates: list[Any], *, feedback: str | None = None
    ) -> list[CandidateAnswer]:
        if calls is not None:
            calls.append(len(candidates))
        if feedbacks is not None:
            feedbacks.append(feedback)
        index = min(selection.chosen_request_index, len(candidates) - 1)
        return [CandidateAnswer(
            candidate_index=index,
            selection=replace(selection, chosen_request_index=index),
            confidence=confidence,
        )]
    return _select


def _answering(*answers: CandidateAnswer, calls: list[int] | None = None):
    """A fan-out double returning SEVERAL yeses, so the referee has something to rank."""
    async def _select(
        candidates: list[Any], *, feedback: str | None = None
    ) -> list[CandidateAnswer]:
        if calls is not None:
            calls.append(len(candidates))
        return list(answers)
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
    pre-filter is deliberately dumb and the model correcting it is a designed path.

    Round two now happens anyway, over the ONE feed that failed and with the failure's
    evidence attached — that is the retry-gap fix, and it is compatible with this rule
    rather than in tension with it: what must never be offered is the CATALOGUE, and it
    never is. The second ask is one candidate wide, not two."""
    select_calls: list[int] = []
    feedbacks: list[str | None] = []
    outcome = await discover(
        _TIKTOK_URL,
        capture=_capturing("tiktok"),
        select=_selecting(_tiktok_selection(), calls=select_calls, feedbacks=feedbacks),
        replay_http=_failing_replay(RecipeExecutionError("HTTP 400")),
        replay_browser=_failing_replay(RecipeExecutionError("Chromium crashed")),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "verifying we can read it" in (outcome.refuse_reason or "")
    # Round 1 saw both; round 2 saw ONLY the jobs feed — the catalogue is gone for good.
    assert select_calls == [2, 1]
    assert feedbacks[0] is None                          # nothing measured yet
    # The LAST thing measured, which on a board that failed both tiers is the browser
    # tier's answer. What matters is that the round was TOLD something.
    assert "Chromium crashed" in (feedbacks[1] or "")
    _assert_stores_nothing(outcome)


async def test_an_equally_job_shaped_candidate_is_tried_and_the_ladder_is_bounded() -> None:
    """The fallback the round above exists for is still real: a second array that looks
    just as job-shaped IS re-offered. And the ladder is BOUNDED — each round costs a
    Haiku call and up to two replays inside a 240s task, so an unbounded loop would be
    a money bug as well as a hang."""
    twin = _amazon_response({**_amazon_body(), "hits": 76})
    other = twin.__class__(**{**twin.__dict__, "url": twin.url + "&page=2"})

    async def _capture(url: str, **_: Any) -> CaptureResult:
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

    async def _no_feed(candidates: list[Any], **_: Any) -> RequestSelection:
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


async def test_a_second_round_no_reports_the_failure_that_provoked_it() -> None:
    """THE REFUSAL THAT LIED. Round two asks the model again with OUR OWN measured
    failure attached, so its "none of these is jobs" is frequently an echo of that
    failure rather than a verdict on the bytes — and the old code answered the user with
    the filter-step sentence regardless, blaming the board for something we did.

    Measured on ``jpmc.fa.oraclecloud.com`` (BOARD-FAILURE-TRIAGE.md §2): the fan-out
    answered **6 of 6 yes**, the coverage floor refused every one of them at 25 records
    against a published 7,181, round two said no with that attached, and the user was
    told the page publishes no jobs feed. Four unrelated boards wore that identical
    sentence for four different reasons.

    So: when something was actually measured, THAT is the refusal."""
    rounds: list[str | None] = []

    async def _select(candidates: list[Any], *, feedback: str | None = None):
        rounds.append(feedback)
        if len(rounds) == 1:
            return [CandidateAnswer(
                candidate_index=0, selection=_amazon_selection(), confidence="high",
            )]
        raise NoJobsFeedError("none of the 1 captured array(s) is a list of job postings")

    async def _wrong_feed(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        rows = [{"id": f"other-{i}", "title": f"Unrelated {i}", "url": "/x"} for i in range(20)]
        return rows, HarvestEvidence(
            declared_total=76, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )

    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_select,
        replay_http=_wrong_feed, replay_browser=_wrong_feed,
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert len(rounds) == 2 and rounds[1] is not None   # round two WAS told what we measured
    assert "verifying we can read it" in (outcome.refuse_reason or "")
    assert "not reading the same list" in (outcome.refuse_reason or "")
    assert "is a list of job postings" not in (outcome.refuse_reason or ""), (
        "the model's second-round no is downstream of the acceptance failure we fed it; "
        "reporting it as 'this page publishes no jobs feed' is the sentence that sent "
        "two investigations down the wrong path"
    )
    # The CHECKLIST has to move with it, or the UI keeps telling the old story.
    (failed_step,) = [
        s for s in (outcome.progress or {}).get("steps", []) if s["status"] == "failed"
    ]
    assert failed_step["key"] == "verify_read"
    _assert_stores_nothing(outcome)


async def test_a_first_round_no_still_says_the_page_publishes_no_jobs_feed() -> None:
    """The control for the test above, and the reason the old sentence is KEPT rather
    than deleted: when nothing we tried ever failed — the model simply read the captured
    requests and saw no jobs in them — the sentence is literally true and is the most
    useful thing we can say."""
    async def _no_feed(candidates: list[Any], **_: Any) -> RequestSelection:
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

    async def _capture(url: str, **_: Any) -> CaptureResult:
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
    async def _empty(url: str, **_: Any) -> CaptureResult:
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

    async def _capture(url: str, **_: Any) -> CaptureResult:
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
    async def _capture(url: str, **_: Any) -> CaptureResult:
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
    async def _select(candidates: list[Any], **_: Any) -> RequestSelection:
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
    async def _select(candidates: list[Any], **_: Any) -> RequestSelection:
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
    async def _explode(url: str, **_: Any) -> CaptureResult:
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
    async def _explode(candidates: list[Any], **_: Any) -> RequestSelection:
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

    async def _capture(url: str, **_: Any) -> CaptureResult:
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


def _pageless_response(body: dict[str, Any]) -> Any:
    """The captured Amazon response carrying ``body``, at a URL with NO paging parameter.

    ``synthesize_recipe`` now runs ``page_shape_refusal`` (the Walmart catch: a page
    index in the request and nothing advancing it), and the Amazon fixture's own URL
    carries ``offset``/``result_limit``. So a test about something ELSE that borrows that
    response and answers "no pagination" would be answering the WALMART question by
    accident and refusing. Same bytes, whole-catalogue URL.
    """
    original = _amazon_response(body)
    return original.__class__(
        **{**original.__dict__, "url": "https://www.amazon.jobs/en/all-jobs.json"}
    )


def _untotalled_amazon() -> Any:
    """The Amazon jobs response with every total-ish key removed — a board that
    publishes no total at all."""
    body = _amazon_body()
    del body["hits"]
    del body["facets"]
    return _amazon_response(body)


def _untotalled_pageless() -> Any:
    """...and the same board at a URL that asks for no particular page. See
    :func:`_pageless_response`."""
    body = _amazon_body()
    del body["hits"]
    del body["facets"]
    return _pageless_response(body)


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
    # A WHOLE-CATALOGUE URL, deliberately: a request that DOES carry a page index and
    # has nothing advancing it is the Walmart shape and is now refused at synthesis
    # (see ``test_a_page_index_with_nothing_advancing_it_is_refused``). This test is
    # about the residual — no total, no hint, and no page parameter either.
    candidate = prefilter_candidates([_untotalled_pageless()])[0]
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
    assert all(
        steps[key]["status"] == "done"
        for key in ("open_page", "find_feed", "verify_read", "ready")
    )
    # The FIFTH rung is left OPEN for the first harvest to settle. Ticking it here would
    # put a complete checklist over a company that still holds zero jobs — the exact
    # "we looked and found nothing" misread this rung exists to prevent.
    assert steps["first_scan"]["status"] == "active"
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
    async def _blocked(url: str, **_: Any) -> CaptureResult:
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
    async def _no_feed(candidates: list[Any], **_: Any) -> RequestSelection:
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


async def test_a_live_view_url_that_only_rides_the_result_is_never_published() -> None:
    """A URL that reaches us on the RETURN VALUE describes a session that has already
    been closed and released — the capture seam does both before it returns. Copying it
    onto the row there is how the retracted live view used to come back from the dead:
    the ``finally`` cleared it, and three statements later this put the corpse back."""
    async def _with_live_view(url: str, **_: Any) -> CaptureResult:
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
    assert outcome.progress["live_view_url"] is None


async def test_the_live_view_url_lands_on_the_row_while_step_one_is_still_running() -> None:
    """THE WHOLE POINT of the live view, and the thing an end-of-run write cannot do.

    A hosted Browserbase view is watchable only while the session is alive — a capture
    runs 30-120s and the session is released the moment it returns. So the URL has to
    reach the polled blob during ``open_page``, not with the terminal checklist. The
    assertion is on the FIRST snapshot that carries a URL: it must still show step 1
    ``active``, which is exactly what an end-of-run write could never produce.
    """
    snapshots: list[dict[str, Any]] = []

    async def _record(snapshot: dict[str, Any]) -> None:
        snapshots.append(snapshot)

    async def _capture_with_session(
        url: str, *, on_live_view: Any = None, **_: Any
    ) -> CaptureResult:
        # What ``capture_board`` does on the Browserbase path: publish the moment the
        # session exists, THEN spend the next half-minute driving the browser.
        assert on_live_view is not None
        await on_live_view("https://www.browserbase.com/devtools-fullscreen/s1")
        return _capture_result("amazon")

    outcome = await discover(
        _AMAZON_URL,
        capture=_capture_with_session,
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        emit=_record,
    )
    assert outcome.ok is True

    live = [s for s in snapshots if s["live_view_url"]]
    assert live, "the live-view URL never reached a mid-run progress write"
    first = live[0]
    assert first["live_view_url"] == "https://www.browserbase.com/devtools-fullscreen/s1"
    assert first["outcome"] == OUTCOME_RUNNING
    open_page = next(s for s in first["steps"] if s["key"] == STEP_OPEN_PAGE)
    assert open_page["status"] == STATUS_ACTIVE
    # What happens at the OTHER end of the session is the next test's job: this double
    # only ever opens a live view, so nothing here retracts one.


async def test_the_live_view_is_retracted_while_step_one_is_still_active() -> None:
    """THE BUG THIS CLOSES, stated as a sequence of polls.

    The browser dies when the capture's ``finally`` runs; ``open_page`` is not ticked
    over until after the pre-filter has scored the capture and rebuilt the network log.
    A frontend that treats "step 1 is active" as "there is a browser to watch" therefore
    renders a dead iframe for that whole gap — which is exactly what the user
    screenshotted: ``Opening the page`` spinning above ``Debugging connection was
    closed``. So the assertion is deliberately the awkward one: there must exist a
    snapshot carrying NO live view WHILE step 1 is still ``active``, i.e. the backend
    stated the browser was gone before its own checklist moved on.
    """
    snapshots: list[dict[str, Any]] = []

    async def _record(snapshot: dict[str, Any]) -> None:
        snapshots.append(snapshot)

    async def _capture_with_session(
        url: str, *, on_live_view: Any = None, on_live_view_closed: Any = None,
        **_: Any,
    ) -> CaptureResult:
        # ``capture_board``'s two halves, in its order: publish when the session exists,
        # drive the browser, retract from the ``finally`` that releases it — and still
        # hand back a result carrying the URL, the way the real one does.
        assert on_live_view is not None and on_live_view_closed is not None
        await on_live_view("https://www.browserbase.com/devtools-fullscreen/s1")
        base = _capture_result("amazon")
        await on_live_view_closed()
        return CaptureResult(
            final_url=base.final_url, page_title=base.page_title,
            responses=base.responses,
            live_view_url="https://www.browserbase.com/devtools-fullscreen/s1",
        )

    outcome = await discover(
        _AMAZON_URL,
        capture=_capture_with_session,
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        emit=_record,
    )
    assert outcome.ok is True

    def _status(snapshot: dict[str, Any], key: str) -> str:
        return next(s for s in snapshot["steps"] if s["key"] == key)["status"]

    live_at = [i for i, s in enumerate(snapshots) if s["live_view_url"]]
    assert live_at, "the live-view URL never reached a mid-run progress write"
    retracted = [
        s for s in snapshots[live_at[-1] + 1:] if s["live_view_url"] is None
    ]
    assert retracted, "the live view was never taken back off the row"
    # THE ORDERING CLAIM: the retraction reached a poll while the checklist still said
    # we were opening the page.
    assert _status(retracted[0], STEP_OPEN_PAGE) == STATUS_ACTIVE
    # ...and no later write resurrects it, including the terminal one the persist
    # writes in the same statement that flips the row to tracked.
    assert all(s["live_view_url"] is None for s in snapshots[live_at[-1] + 1:])
    assert outcome.progress is not None
    assert outcome.progress["live_view_url"] is None


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
    async def _capture(url: str, **_: Any) -> CaptureResult:
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


def test_the_ceiling_is_denominated_in_jobs_not_pages() -> None:
    """THE MICROSOFT BUG. A flat PAGE ceiling is a different JOB ceiling on every board,
    because the page size belongs to the board and not to us: 100 pages was 10,000 jobs
    of amazon.jobs (100/page) and 1,000 jobs of Microsoft's Eightfold board, which is
    hard-wired to 10 and ignores ``num``/``limit``/``size``/``pageSize`` alike. Microsoft
    declares 2,111, so we read 47% of its board and then told its owner we were
    "tracking part of this board" — truncated by our own constant and by nothing about
    Microsoft.

    Denominating the ceiling in JOBS and converting it through the page size we proved
    gives every board the same ceiling however it paginates.
    """
    ten_per_page = prefilter_candidates([_big_amazon(hits=2111)])[0]
    assert ten_per_page.record_count == 10       # the Microsoft shape, from the fixture

    script = synthesize_recipe(
        ten_per_page, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["page_size"] == 10
    # ceil(2111 / 10) + the growth headroom = 214 pages, i.e. the WHOLE board — where
    # the old flat ceiling stopped this exact shape at 100 pages / 1,000 jobs.
    assert paginate["max_pages"] == 214
    assert paginate["page_size"] * paginate["max_pages"] >= 2111


def test_the_harvest_budget_never_exceeds_the_transports_own_ceiling() -> None:
    """A budget the transport cannot honour is not a budget. ``browser_fetch`` runs
    every page as a fresh in-browser fetch inside one 90s Chromium session, so its
    ceiling is far lower than the http tier's — and the parent's ``min()`` clamp is the
    WRONG place to discover that, because a clamped sweep still reports a terminus.

    The two ceilings are also denominated differently on purpose, and this locks that:
    the http tier bounds ROWS (a page there is one cheap GET), the browser tier bounds
    PAGES (a page there holds a Chromium renderer). Dropping the http tier's flat page
    ceiling did not move the browser tier's.
    """
    candidate = prefilter_candidates([_big_amazon(hits=500_000)])[0]

    http_script = synthesize_recipe(
        candidate, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    browser_script = synthesize_recipe(
        candidate, _amazon_selection(), transport="browser_fetch",
        origin_url=_AMAZON_URL,
    )
    (http_paginate,) = [s for s in http_script["steps"] if s["op"].startswith("paginate_")]
    (bf_paginate,) = [s for s in browser_script["steps"] if s["op"].startswith("paginate_")]
    # 50,000 rows at the 10-per-page this board proved — a job ceiling, not a page one.
    assert http_paginate["max_pages"] == MAX_HARVEST_RECORDS // 10
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
    assert paginate["max_pages"] == MAX_HARVEST_RECORDS // 10


def test_the_coverage_claim_is_bounded_by_the_runtime_clock_too() -> None:
    """We may not PROMISE more of a board than the nightly clock can read.

    Walmart publishes 47,298 jobs ten at a time: the derived budget is 4,732 pages,
    which "reaches" the whole board on paper and about a fifth of it in the ~10 minutes
    ``recipe_runner.HARVEST_TIME_BUDGET_S`` allows. Every such run is safe — it stops on
    the clock with ``cap_hit`` and closes nothing — but the user would have been told at
    discovery that we track the whole board, and that promise is exactly what the
    partial banner exists to make honestly.
    """
    walmart = prefilter_candidates([_big_amazon(hits=47_298)])[0]
    script = synthesize_recipe(
        walmart, _amazon_selection(), transport="http_json", origin_url=_AMAZON_URL
    )
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]

    # The stored budget is NOT clamped by the clock — a latency guess baked into a
    # recipe is a flat cap in disguise, and the runtime clock measures instead.
    assert paginate["max_pages"] == 4732

    coverage = _coverage(script, walmart, _amazon_selection())
    assert coverage.visible == 47_298
    assert coverage.reachable == 10 * _PAGES_WITHIN_TIME_BUDGET
    assert coverage.is_partial is True


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


# =========================================================================
# READING A SLIVER OF A BOARD — the widening, and the honest label when we
# cannot widen. Three boards passed every gate above while tracking a slice.
# =========================================================================

_GROUPED_URL = "https://www.binance.com/en/careers/job-openings"
_GROUPED_MAP = {
    "id": "id", "title": "text", "url": "hostedUrl", "location": "country",
    "posted_at": "createdAt",
}


def _grouped_selection(records_path: str) -> RequestSelection:
    """What the model answered. ``2.postings`` is the pre-filter's old top pick — the
    biggest single department — and is the answer this whole section exists to correct."""
    return RequestSelection(
        chosen_request_index=0, records_path=records_path,
        field_map=dict(_GROUPED_MAP), pagination=None,
    )


def _replay_from_path(name: str, records_path: str, field_map: dict[str, str]):
    """A faithful replay that reads the path THE RECIPE ASKS FOR, not a fixed one.

    The widening is invisible to a fake that hardcodes its own path — it would return
    the same rows either way and the test would pass with the bug still in place.
    """
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        (extract,) = [s for s in script["steps"] if s["op"] == "extract_json_path"]
        candidate = prefilter_candidates(_capture_result(name).responses)[0]
        records = dig_records(candidate.payload, extract["records_path"])
        rows = map_records(records, field_map, script.get("base_url", ""))
        return rows, HarvestEvidence(
            declared_total=None, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )
    return _replay


async def test_a_grouped_board_is_widened_to_the_whole_board_before_it_is_stored() -> None:
    """binance.com, trimmed: 4 department groups of 2/1/4/3. The model answers with ONE
    group and the stored recipe must still read all ten.

    The measured bug, exactly: ``records_path: '4.postings'`` was stored, 81 of 279
    postings were tracked, and every downstream check agreed — because each of them
    compares the replay against that same 81-record array. Nothing in the pipeline could
    see the other 198 sitting in the response we had already downloaded.
    """
    outcome = await discover(
        _GROUPED_URL,
        capture=_capturing("grouped"),
        select=_selecting(_grouped_selection("2.postings")),
        replay_http=_replay_from_path("grouped", "2.postings", _GROUPED_MAP),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.script is not None
    (extract,) = [s for s in outcome.script["steps"] if s["op"] == "extract_json_path"]
    assert extract["records_path"] == "*.postings"
    assert outcome.progress is not None
    verify = next(s for s in outcome.progress["steps"] if s["key"] == "verify_read")
    assert verify["result"] == "read 10 job(s)"          # the union, not the group of 4
    # A widened board is not a partial one: there is nothing left in the response we
    # are not reading.
    assert outcome.progress["outcome"] == "tracking"


async def test_a_model_that_already_answers_the_union_is_left_alone() -> None:
    """The prompt names the ``*`` path, so the common case is that no widening is
    needed. It must be a no-op then, not a second rewrite."""
    outcome = await discover(
        _GROUPED_URL,
        capture=_capturing("grouped"),
        select=_selecting(_grouped_selection("*.postings")),
        replay_http=_replay_from_path("grouped", "*.postings", _GROUPED_MAP),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.script is not None
    (extract,) = [s for s in outcome.script["steps"] if s["op"] == "extract_json_path"]
    assert extract["records_path"] == "*.postings"


async def test_widening_is_declined_when_the_wider_path_maps_no_extra_jobs() -> None:
    """The union must map to strictly MORE usable rows through the SAME field map, or we
    keep the narrow path. That is what stops a wildcard from sweeping in a group whose
    array holds something other than job postings — the id/title render is the proof,
    and it is the only one available before the replay."""
    body = [
        {"title": "Eng", "postings": [
            {"id": "a", "text": "Engineer", "hostedUrl": "https://x/1"},
        ]},
        # A second group whose entries carry no id and no title: job-SHAPED enough for
        # the pre-filter's key-name score, worthless to ``map_records``.
        {"title": "Perks", "postings": [
            {"category": "office", "location": "NYC", "posted": "yes"},
            {"category": "remote", "location": "LON", "posted": "yes"},
        ]},
    ]
    response = _pageless_response(body)
    candidates = prefilter_candidates([response])
    assert candidates[0].records_path == "*.postings"    # the pre-filter offers it...

    selection = RequestSelection(
        chosen_request_index=0, records_path="0.postings",
        field_map={"id": "id", "title": "text", "url": "hostedUrl"}, pagination=None,
    )
    outcome = await discover(
        _GROUPED_URL,
        capture=_capture_of(response),
        select=_selecting(selection),
        replay_http=_replay_records(body, "0.postings", selection.field_map),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.script is not None
    (extract,) = [s for s in outcome.script["steps"] if s["op"] == "extract_json_path"]
    assert extract["records_path"] == "0.postings"       # ...and discovery declines it


# --- the partial verdict ----------------------------------------------------

def _jobs(n: int, prefix: str = "j") -> list[dict[str, Any]]:
    return [
        {"job_id": f"{prefix}{i}", "jobPostingTitle": f"Role {i}", "city": "Bentonville"}
        for i in range(n)
    ]


_PARTIAL_MAP = {
    "id": "job_id", "title": "jobPostingTitle",
    "url": "https://careers.walmart.com/job/{job_id}", "location": "city",
}


def _capture_of(*responses: Any) -> Any:
    async def _capture(url: str, **_: Any) -> CaptureResult:
        return CaptureResult(
            final_url="https://careers.walmart.com/us/en/results",
            page_title="Careers", responses=list(responses),
        )
    return _capture


def _replay_records(payload: Any, records_path: str, field_map: dict[str, str]):
    """Replay straight out of a literal payload, honouring the recipe's own path."""
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        (extract,) = [s for s in script["steps"] if s["op"] == "extract_json_path"]
        rows = map_records(
            dig_records(payload, extract["records_path"]), field_map,
            script.get("base_url", ""),
        )
        return rows, HarvestEvidence(
            declared_total=None, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )
    return _replay


def _walmart_sliver_body() -> tuple[dict[str, Any], str]:
    """careers.walmart.com's chat endpoint: ten jobs, and 47,298 in the same body."""
    body = {"data": {"assistant": {"tool_messages": [{"artifact": {
        "total_jobs": 47298,
        "total_future_roles": 276561,     # a bigger count of something that is NOT jobs
        "page_size": 10,
        "jobs": _jobs(10),
    }}]}}}
    return body, "data.assistant.tool_messages.0.artifact.jobs"


async def test_a_board_we_can_reach_a_fiftieth_of_is_REFUSED_not_stored() -> None:
    """THE COVERAGE FLOOR (S1). careers.walmart.com: a chat endpoint that answers ten
    jobs and, in the same body, says the board has 47,298.

    Every structural check is happy — the recipe replays, the ids match the capture, the
    gate passes, and the ``none`` oracle means the nightly run could never close a job.
    That is precisely why nothing below this line could catch it: the ONLY evidence that
    this is the wrong list is arithmetic the board itself published, and until this stage
    that number was measured, rendered to the user and then allowed to drive nothing.

    Reaching 10 of 47,298 is 0.02%. "We are tracking this company's job board" is not a
    true sentence about that recipe, so it is refused — with the board's own numbers in
    the reason, because the user's next action (paste a different URL) depends on knowing
    which board we could not read.
    """
    body, path = _walmart_sliver_body()
    # No page parameter in the REQUEST — that is a different defect with a different
    # answer (``test_a_page_index_with_nothing_advancing_it_is_refused``), and keeping it
    # out is what makes this test about the coverage floor and nothing else.
    response = _pageless_response(body)
    selection = RequestSelection(
        chosen_request_index=0, records_path=path,
        field_map=dict(_PARTIAL_MAP), pagination=None,
    )
    outcome = await discover(
        "https://careers.walmart.com/results",
        capture=_capture_of(response),
        select=_selecting(selection),
        replay_http=_replay_records(body, path, _PARTIAL_MAP),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    # A REFUSE stores NOTHING — that is the whole point of refusing rather than labelling.
    assert outcome.script is None
    assert outcome.transport is None
    assert outcome.oracle_kind is None
    assert "47,298" in (outcome.refuse_reason or "")
    assert "10 job(s)" in (outcome.refuse_reason or "")
    assert outcome.progress is not None
    assert outcome.progress["outcome"] == "refused"


def test_the_coverage_floor_fires_on_the_FEED_not_on_our_own_page_budget() -> None:
    """MUTATION GUARD, and the correction the plan needed.

    Two shortfalls look identical in ``reachable`` and mean opposite things:

    * a feed that hands back one page of ten and says the board is 47,298 — the array
      is not the board, and the floor must refuse it;
    * a feed that PAGES the whole board while our own browser-tier ceiling (25 pages of
      TikTok's 10-per-page API = 250 of 4,026) truncates what we read each night — the
      array IS the board, and refusing would throw away a board we track today.

    ``feed_reach`` is what separates them, and it is what ``is_refused`` reads.
    """
    body, path = _walmart_sliver_body()
    candidate = prefilter_candidates([_pageless_response(body)])[0]
    sliver = RequestSelection(
        chosen_request_index=0, records_path=path,
        field_map=dict(_PARTIAL_MAP), pagination=None,
    )
    script = synthesize_recipe(
        candidate, sliver, transport="http_json",
        origin_url="https://careers.walmart.com/results",
    )
    coverage = _coverage(script, candidate, sliver)
    assert coverage.feed_reach == 10
    assert coverage.visible == 47298
    assert coverage.is_refused is True

    # ...and the same board through a request that actually pages. The nightly budget
    # still only reaches a slice (that is the PARTIAL banner's job), but the FEED can
    # enumerate the board, so the floor must stay silent.
    paged = RequestSelection(
        chosen_request_index=0, records_path=path,
        field_map=dict(_PARTIAL_MAP),
        pagination=PaginationHint(style="offset", param="offset", page_size=10),
    )
    paged_script = synthesize_recipe(
        candidate, paged, transport="browser_fetch",
        origin_url="https://careers.walmart.com/results",
    )
    paged_coverage = _coverage(paged_script, candidate, paged)
    assert paged_coverage.feed_reach is None          # bounded by nothing the board said
    assert paged_coverage.reachable == 250            # 25 browser pages x 10 — OUR limit
    assert paged_coverage.is_refused is False
    assert paged_coverage.is_partial is True


# --- source 5: the claim nothing on the page could have produced ------------

def _walmart_ids(n: int) -> list[str]:
    """``R-1075582``-shaped, which is what Walmart's really are."""
    return [f"R-{1075582 + i}" for i in range(n)]


def _walmart_jobs(n: int) -> list[dict[str, Any]]:
    return [
        {"job_id": jid, "jobPostingTitle": f"Role {i}", "city": "Bentonville"}
        for i, jid in enumerate(_walmart_ids(n))
    ]


def _walmart_sitemap(job_pages: int) -> WellKnownEvidence:
    """Walmart's sitemap at fixture scale: job pages under one prefix, plus noise.

    The ids are ``R-1075582``-shaped because that is what Walmart's really are, and
    because an id has to be long enough to mean something inside a URL — a two-character
    id "matches" half the site and would manufacture a claim out of a coincidence.
    """
    locs = [
        f"https://careers.walmart.com/us/en/jobs/{jid}-software-engineer"
        for jid in _walmart_ids(job_pages)
    ]
    locs += [f"https://careers.walmart.com/us/en/stores/{i}" for i in range(7)]
    return WellKnownEvidence(
        sitemaps=(SitemapDocument(
            "https://careers.walmart.com/sitemap.xml", tuple(locs), False,
        ),),
    )


def _well_known(evidence: WellKnownEvidence, *, calls: list[str] | None = None):
    async def _collect(url: str) -> WellKnownEvidence:
        if calls is not None:
            calls.append(url)
        return evidence
    return _collect


async def test_the_sitemap_becomes_a_coverage_claim_the_page_never_published() -> None:
    """S2, and the whole reason source 5 exists.

    This board's payload publishes NO total at all — so before source 5, ``_coverage``
    had nothing to compare against, ``visible == reachable``, and a ten-row read of a
    fifteen-thousand-job board was a clean green success. The sitemap is a count of the
    same board, from a URL the careers page never requests and never will, and it lands
    in exactly the same claim list.
    """
    body = {"data": {"jobs": _walmart_jobs(10)}}
    response = _pageless_response(body)
    selection = RequestSelection(
        chosen_request_index=0, records_path="data.jobs",
        field_map=dict(_PARTIAL_MAP), pagination=None,
    )
    calls: list[str] = []
    outcome = await discover(
        "https://careers.walmart.com/results",
        capture=_capture_of(response),
        select=_selecting(selection),
        replay_http=_replay_records(body, "data.jobs", _PARTIAL_MAP),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        collect_sources=_well_known(_walmart_sitemap(15_660), calls=calls),
    )
    # The collector was asked about the ENTRY url, before anything was known about the
    # board — that is what lets it run concurrently with the capture.
    assert calls == ["https://careers.walmart.com/results"]
    assert outcome.ok is False
    assert outcome.script is None
    assert "sitemap lists 15,660 job page(s)" in (outcome.refuse_reason or "")


async def test_a_board_with_no_sitemap_is_completely_unaffected() -> None:
    """Jane Street 404s on ``/sitemap.xml``, as do amazon.jobs and higher.gs.com — three
    of the four boards measured. The silent-miss path is the COMMON path, so it has to
    leave a healthy board byte-for-byte where it was."""
    with_nothing = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        collect_sources=_well_known(WellKnownEvidence()),
    )
    assert with_nothing.ok is True
    assert with_nothing.progress is not None
    assert with_nothing.progress["outcome"] == "tracking"
    verify = next(
        s for s in with_nothing.progress["steps"] if s["key"] == "verify_read"
    )
    assert verify["result"] == "read 10 job(s)"


async def test_a_sitemap_that_agrees_with_the_feed_changes_nothing() -> None:
    """The control. A claim is a lower bound, and a lower bound we already meet has
    nothing to say — a source that fires on a healthy board is a source that gets turned
    off."""
    body = {"jobs": _walmart_jobs(40), "total_jobs": 40}
    response = _pageless_response(body)
    selection = RequestSelection(
        chosen_request_index=0, records_path="jobs",
        field_map=dict(_PARTIAL_MAP), pagination=None,
    )
    sitemap = WellKnownEvidence(sitemaps=(SitemapDocument(
        "https://careers.walmart.com/sitemap.xml",
        tuple(
            f"https://careers.walmart.com/us/en/jobs/{jid}" for jid in _walmart_ids(40)
        ),
        False,
    ),))
    outcome = await discover(
        "https://careers.walmart.com/results",
        capture=_capture_of(response),
        select=_selecting(selection),
        replay_http=_replay_records(body, "jobs", _PARTIAL_MAP),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        collect_sources=_well_known(sitemap),
    )
    assert outcome.ok is True
    assert outcome.progress is not None
    assert outcome.progress["outcome"] == "tracking"


# --- S3: the sitemap as a stored ORACLE -------------------------------------

def _sitemap_of(job_ids: list[str], *, noise: int = 0) -> WellKnownEvidence:
    locs = [f"https://careers.walmart.com/us/en/jobs/{jid}" for jid in job_ids]
    locs += [f"https://careers.walmart.com/us/en/stores/{i}" for i in range(noise)]
    return WellKnownEvidence(sitemaps=(SitemapDocument(
        "https://careers.walmart.com/sitemap.xml", tuple(locs), False,
    ),))


async def _discover_with_sitemap(
    body: dict[str, Any], records_path: str, evidence: WellKnownEvidence
):
    response = _pageless_response(body)
    selection = RequestSelection(
        chosen_request_index=0, records_path=records_path,
        field_map=dict(_PARTIAL_MAP), pagination=None,
    )
    return await discover(
        "https://careers.walmart.com/results",
        capture=_capture_of(response),
        select=_selecting(selection),
        replay_http=_replay_records(body, records_path, _PARTIAL_MAP),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        collect_sources=_well_known(evidence),
    )


async def test_a_sitemap_that_agrees_exactly_becomes_the_stored_oracle() -> None:
    """S3, and the thing the plan found orphaned. The ``sitemap`` oracle has been
    implemented end to end since Phase 3a — schema, replay on both transports,
    verification, tests — and discovery's oracle decision could only ever produce
    ``declared_probed``, ``self_consistent`` or ``none``.

    This board publishes no total and does not paginate, so its oracle was ``none``:
    UNVERIFIED forever, showing its jobs every night and closing nothing. Its own
    sitemap lists exactly the 40 pages the replay reads, which is a completeness proof
    the board published about itself.
    """
    ids = _walmart_ids(40)
    outcome = await _discover_with_sitemap(
        {"jobs": _walmart_jobs(40)}, "jobs", _sitemap_of(ids, noise=6),
    )
    assert outcome.ok is True
    assert outcome.oracle_kind == "sitemap"
    assert outcome.script is not None
    assert outcome.script["oracle"] == {
        "kind": "sitemap",
        "sitemap_url": "https://careers.walmart.com/sitemap.xml",
        "url_pattern": "https://careers.walmart.com/us/en/jobs/",
    }
    # The six store pages are NOT in the pattern, so they are not in the total.
    assert outcome.progress is not None
    assert outcome.progress["outcome"] == "tracking"


async def test_a_sitemap_that_does_not_agree_exactly_is_only_a_claim() -> None:
    """MUTATION TARGET — condition (b). ``_verify_oracle_total`` is tolerance 0, so a
    sitemap oracle VERIFIES only when tonight's count exactly equals the ``<loc>`` count.
    Attaching one to a board where those two numbers already disagree replaces an oracle
    that can verify with one that structurally cannot, forever."""
    outcome = await _discover_with_sitemap(
        {"jobs": _walmart_jobs(40)}, "jobs", _sitemap_of(_walmart_ids(43)),
    )
    assert outcome.ok is True
    assert outcome.oracle_kind == "none"          # unchanged
    # ...but the count is still recorded as a claim: 40 of 43 is a 93% read, above the
    # partial bar and far above the refusal floor, so nothing else changes either.
    assert outcome.progress is not None
    assert outcome.progress["outcome"] == "tracking"


async def test_a_sitemap_carrying_none_of_our_ids_never_becomes_the_oracle() -> None:
    """Overlap proves SAME BOARD. Without it we would attach the sitemap of whatever
    site the careers page happens to live on, and its count would be a number about
    something else entirely."""
    someone_elses = WellKnownEvidence(sitemaps=(SitemapDocument(
        "https://careers.walmart.com/sitemap.xml",
        tuple(f"https://careers.walmart.com/us/en/jobs/X-{i}" for i in range(40)),
        False,
    ),))
    outcome = await _discover_with_sitemap(
        {"jobs": _walmart_jobs(40)}, "jobs", someone_elses,
    )
    assert outcome.ok is True
    assert outcome.oracle_kind == "none"


async def test_a_sitemap_that_only_PARTLY_overlaps_never_becomes_the_oracle() -> None:
    """MUTATION TARGET — condition (a), on the case where it is the ONLY thing holding.

    A sitemap listing 40 job pages against a 40-row replay satisfies condition (b)
    perfectly — the counts agree exactly. But only five of those pages carry an id we
    captured, so the two 40s are a coincidence between two different lists, and a
    tolerance-0 oracle built on a coincidence VERIFIES a board we never read.
    """
    ours = _walmart_ids(40)
    locs = [f"https://careers.walmart.com/us/en/jobs/{jid}" for jid in ours[:5]]
    locs += [f"https://careers.walmart.com/us/en/jobs/X-{i}" for i in range(35)]
    half_matching = WellKnownEvidence(sitemaps=(SitemapDocument(
        "https://careers.walmart.com/sitemap.xml", tuple(locs), False,
    ),))
    outcome = await _discover_with_sitemap(
        {"jobs": _walmart_jobs(40)}, "jobs", half_matching,
    )
    assert outcome.ok is True
    assert outcome.oracle_kind == "none"


async def test_overlap_alone_does_not_attach_the_oracle_and_walmart_is_why() -> None:
    """The two conditions answer DIFFERENT questions, and this is the case that proves
    it. Walmart's chat endpoint returns REAL Walmart job ids, so ten of ten are found in
    the sitemap — overlap is perfect. The COUNT is what kills it: ten rows against
    15,660 published job pages.

    (Here the coverage floor gets there first, which is the correct order: the board is
    refused outright rather than stored with any oracle at all.)
    """
    outcome = await _discover_with_sitemap(
        {"jobs": _walmart_jobs(10)}, "jobs", _sitemap_of(_walmart_ids(15_660)),
    )
    assert outcome.ok is False
    assert outcome.oracle_kind is None
    assert "sitemap lists 15,660 job page(s)" in (outcome.refuse_reason or "")


async def test_a_board_that_already_has_a_trusted_total_keeps_it() -> None:
    """A ``declared_probed`` oracle is exact, free, and comes out of bytes we download
    anyway. Swapping it for a sitemap would buy nothing and cost a multi-megabyte GET
    every night forever, so the attach only ever upgrades the two HISTORICAL oracles."""
    outcome = await _discover_with_sitemap(
        {"jobs": _walmart_jobs(40), "total_jobs": 40}, "jobs",
        _sitemap_of(_walmart_ids(40)),
    )
    assert outcome.ok is True
    assert outcome.oracle_kind == "declared_probed"


# --- S4: the document as a candidate, end to end ----------------------------
#
# Two replay paths that have been implemented in ``recipe_runner`` since Phase 3a and
# that discovery has never emitted, plus the transport that carries them. What is proved
# here is that a whole discovery run — pre-filter, selection, synthesis,
# ``validate_recipe``, the acceptance ladder — produces a STORABLE ``http_html`` recipe.

_ISLAND_URL = "https://boards.example.com/careers"
_ISLAND_MAP = {"id": "id", "title": "title", "url": "https://boards.example.com/j/{id}"}


def _island_markup(n: int) -> str:
    blob = json.dumps({"props": {"pageProps": {"jobs": [
        {"id": f"J{i}", "title": f"Engineer {i}"} for i in range(n)
    ]}}})
    return (
        "<!doctype html><html><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{blob}</script>'
        "</body></html>"
    )


def _served_islands(markup: str) -> tuple[dict[str, Any], ...]:
    """The island rows a child would report for ``markup``, built HERE.

    Deliberately not by calling ``_capture_main._json_islands``: that module is the one
    place on the discovery side that imports ``playwright``, and importing it into the
    pytest process makes every later ``assert_no_agent_imports()`` raise. The child's own
    extractor is exercised in a subprocess by ``test_capture_sources``.
    """
    if "__NEXT_DATA__" not in markup:
        return ()
    blob = markup.split('type="application/json">', 1)[1].split("</script>", 1)[0]
    return _islands_from_report([
        {"scope": "served", "selector": "script#__NEXT_DATA__",
         "source": "text", "body": blob},
    ])


def _document_capture(markup: str):
    async def _capture(url: str, **_: Any) -> CaptureResult:
        return CaptureResult(
            final_url=_ISLAND_URL, page_title="Careers", responses=[],
            server_html=markup, server_html_url=_ISLAND_URL,
            islands=_served_islands(markup),
        )
    return _capture


def _html_replay(rows: list[dict[str, Any]]):
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        assert script["transport"] == "http_html", script["transport"]
        return rows, HarvestEvidence(
            declared_total=None, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )
    return _replay


async def test_a_served_island_becomes_a_stored_http_html_recipe() -> None:
    """SOURCE 2a, end to end. The page fires no XHR at all — every JSON candidate the
    old pipeline could ever have had is absent — and the board is still readable, because
    its jobs are sitting in the served document's ``__NEXT_DATA__``."""
    markup = _island_markup(12)
    selection = RequestSelection(
        chosen_request_index=0, records_path="props.pageProps.jobs",
        field_map=dict(_ISLAND_MAP), pagination=None,
    )
    rows = [
        {"id": f"J{i}", "title": f"Engineer {i}",
         "url": f"https://boards.example.com/j/J{i}"}
        for i in range(12)
    ]
    outcome = await discover(
        _ISLAND_URL,
        capture=_document_capture(markup),
        select=_selecting(selection),
        replay_http=_html_replay(rows),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.transport == "http_html"
    assert outcome.script is not None
    (extract,) = [
        s for s in outcome.script["steps"] if s["op"] == "extract_embedded_island"
    ]
    assert extract["selector"] == "script#__NEXT_DATA__"
    assert extract["source"] == "text"
    assert extract["records_path"] == "props.pageProps.jobs"
    (fetch,) = [s for s in outcome.script["steps"] if s["op"] == "fetch"]
    assert fetch == {"op": "fetch", "method": "GET", "url": _ISLAND_URL, "headers": {}}
    # ``http_html`` may never paginate — the executor issues one request and reports a
    # clean complete sweep, so a paging step would close every job past page one.
    assert not any(s["op"].startswith("paginate_") for s in outcome.script["steps"])
    assert outcome.script["discovered_by"] == "capture/http_html"


async def test_the_browser_tier_is_never_offered_a_document_candidate() -> None:
    """``browser_fetch`` hard-requires ``extract_json_path`` because its subprocess
    returns raw JSON bodies. Offering it a markup extraction would be an attempt that can
    only ever fail schema validation, so the tier list is a property of where the records
    came from."""
    markup = _island_markup(12)
    selection = RequestSelection(
        chosen_request_index=0, records_path="props.pageProps.jobs",
        field_map=dict(_ISLAND_MAP), pagination=None,
    )
    outcome = await discover(
        _ISLAND_URL,
        capture=_document_capture(markup),
        select=_selecting(selection),
        replay_http=_failing_replay(RecipeExecutionError("HTTP 403")),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    # ...and the reason is the board's 403, NOT a schema complaint about a browser
    # recipe we should never have tried to assemble. That is the difference between a
    # tier list derived from where the records came from and one that guesses.
    assert "403" in (outcome.refuse_reason or "")
    assert "browser_fetch" not in (outcome.refuse_reason or "")


async def test_the_served_documents_anchors_become_a_stored_extract_css_recipe() -> None:
    """SOURCE 6, end to end and with NO model involvement in the mapping: an ``<a href>``
    carries exactly a link and a label, so the field selectors are fixed."""
    markup = (
        "<!doctype html><html><body>"
        + "".join(
            f'<a href="/careers/{i}-staff-engineer">Staff Engineer {i}</a>'
            for i in range(12)
        )
        + "</body></html>"
    )
    selection = RequestSelection(
        chosen_request_index=0, records_path="records",
        field_map={"id": "id", "title": "title", "url": "url"}, pagination=None,
    )
    rows = [
        {"id": f"/careers/{i}-staff-engineer", "title": f"Staff Engineer {i}",
         "url": f"https://boards.example.com/careers/{i}-staff-engineer"}
        for i in range(12)
    ]
    outcome = await discover(
        _ISLAND_URL,
        capture=_document_capture(markup),
        select=_selecting(selection),
        replay_http=_html_replay(rows),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.transport == "http_html"
    assert outcome.script is not None
    (extract,) = [s for s in outcome.script["steps"] if s["op"] == "extract_css"]
    assert extract["record_selector"] == 'a[href*="/careers/"]'
    assert extract["field_selectors"] == {
        "id": ".@href", "title": ".@text", "url": ".@href",
    }


@pytest.mark.parametrize("markup_kind", ["island", "anchors"])
async def test_the_stored_html_recipe_really_replays_through_the_runner(
    markup_kind: str,
) -> None:
    """THE PROOF THAT MATTERS. Everything above uses a replay double; this one runs the
    recipe discovery actually stored through the REAL ``run_recipe`` against the REAL
    markup, so the selector, the records path and the field selectors are checked by the
    thing that will read them at 3am rather than by a fixture that agrees with itself.
    """
    if markup_kind == "island":
        markup = _island_markup(12)
        selection = RequestSelection(
            chosen_request_index=0, records_path="props.pageProps.jobs",
            field_map=dict(_ISLAND_MAP), pagination=None,
        )
    else:
        markup = (
            "<!doctype html><html><body>"
            + "".join(
                f'<a href="/careers/{i}-staff-engineer">Staff Engineer {i}</a>'
                for i in range(12)
            )
            + "</body></html>"
        )
        selection = RequestSelection(
            chosen_request_index=0, records_path="records",
            field_map={"id": "id", "title": "title", "url": "url"}, pagination=None,
        )

    def _serve(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=markup, headers={"content-type": "text/html"})

    async def _real_replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        with httpx.Client(transport=httpx.MockTransport(_serve)) as http:
            return run_recipe(script, http)

    outcome = await discover(
        _ISLAND_URL,
        capture=_document_capture(markup),
        select=_selecting(selection),
        replay_http=_real_replay,
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.transport == "http_html"
    assert outcome.progress is not None
    verify = next(s for s in outcome.progress["steps"] if s["key"] == "verify_read")
    assert verify["result"] == "read 12 job(s)"


async def test_a_document_candidate_never_displaces_a_real_jobs_xhr() -> None:
    """THE CROWDING-OUT GUARD. Amazon publishes a real jobs feed AND a document; the
    document candidates go on the END of the list the pre-filter ranked, so index 0 is
    still the XHR and the stored recipe is still a $0 ``http_json`` replay."""
    async def _capture(url: str, **_: Any) -> CaptureResult:
        base = _capture_result("amazon")
        markup = _island_markup(30)
        return CaptureResult(
            final_url=base.final_url, page_title=base.page_title,
            responses=base.responses, server_html=markup,
            server_html_url=_AMAZON_URL, islands=_served_islands(markup),
        )

    seen: list[int] = []
    outcome = await discover(
        _AMAZON_URL,
        capture=_capture,
        select=_selecting(_amazon_selection(), calls=seen),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.transport == "http_json"
    # The document candidate WAS offered — it is one of the candidates the model saw —
    # it simply did not come first.
    assert seen == [2]


# --- S5: the fan-out, at the whole-discovery level ---------------------------

async def test_the_referee_stores_the_board_not_the_chat_widget_beside_it() -> None:
    """THE CROWDING-OUT CASE, end to end and with both arrays saying yes.

    One page, two JSON responses, both of them genuinely lists of job objects: a chat
    endpoint that hands back ten of a self-declared 47,298, and the board's own feed that
    hands back all forty of its forty. The old pipeline showed both to one model and
    asked it to rank; the referee ranks on the board's own arithmetic instead, and the
    model's confidence is not consulted because nothing tied.
    """
    chat_body = {"jobs": _walmart_jobs(10), "total_jobs": 47298}
    feed_body = {"jobs": _walmart_jobs(40), "total_jobs": 40}
    chat = _pageless_response(chat_body)
    feed = _amazon_response(feed_body).__class__(
        **{**_amazon_response(feed_body).__dict__,
           "url": "https://careers.walmart.com/api/jobs.json"}
    )
    both = [
        CandidateAnswer(
            candidate_index=i,
            selection=RequestSelection(
                chosen_request_index=i, records_path="jobs",
                field_map=dict(_PARTIAL_MAP), pagination=None,
            ),
            confidence="high",
        )
        for i in (0, 1)
    ]

    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        body = feed_body if "jobs.json" in script["steps"][0]["url"] else chat_body
        return map_records(
            body["jobs"], _PARTIAL_MAP, script.get("base_url", "")
        ), HarvestEvidence(
            declared_total=None, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )

    outcome = await discover(
        "https://careers.walmart.com/results",
        capture=_capture_of(chat, feed),
        select=_answering(*both),
        replay_http=_replay,
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.script is not None
    assert outcome.script["steps"][0]["url"] == "https://careers.walmart.com/api/jobs.json"


async def test_a_second_yes_is_tried_when_the_first_fails_acceptance() -> None:
    """"The next candidate" is a REAL fallback for the first time. Before the fan-out it
    meant a second forced pick out of a list the model had already ranked; now a
    candidate is only ever tried because the model was asked about IT and said yes about
    IT — and every yes gets its turn inside ONE round."""
    # The failing one is the BIGGER array, so the pre-filter ranks it first and the
    # referee has nothing to separate them on — which is the case worth testing: the
    # fallback has to work when the ordering was not already lucky.
    first_body = {"jobs": _walmart_jobs(30)}
    second_body = {"jobs": _walmart_jobs(12)}
    first = _pageless_response(first_body)
    second = _amazon_response(second_body).__class__(
        **{**_amazon_response(second_body).__dict__,
           "url": "https://careers.walmart.com/api/real.json"}
    )
    both = [
        CandidateAnswer(
            candidate_index=i,
            selection=RequestSelection(
                chosen_request_index=i, records_path="jobs",
                field_map=dict(_PARTIAL_MAP), pagination=None,
            ),
            confidence="high",
        )
        for i in (0, 1)
    ]
    tried: list[str] = []

    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        url = script["steps"][0]["url"]
        tried.append(url)
        if "real.json" not in url:
            raise RecipeExecutionError("HTTP 500 from the chat endpoint")
        return map_records(
            second_body["jobs"], _PARTIAL_MAP, script.get("base_url", "")
        ), HarvestEvidence(
            declared_total=None, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )

    outcome = await discover(
        "https://careers.walmart.com/results",
        capture=_capture_of(first, second),
        select=_answering(*both),
        replay_http=_replay,
        replay_browser=_failing_replay(RecipeExecutionError("no browser either")),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.attempts == 1                   # ONE round, two candidates tried
    assert outcome.script is not None
    assert "real.json" in outcome.script["steps"][0]["url"]
    assert any("real.json" not in u for u in tried)  # the first one WAS tried


async def test_a_page_whose_every_array_is_declined_is_refused() -> None:
    """A no is now per-array, so "none of these is a jobs feed" is the fan-out returning
    nothing rather than one model answering null about a list. The refusal the user sees
    is unchanged, and it still stops the ladder rather than re-asking."""
    async def _all_no(candidates: list[Any], *, feedback: str | None = None):
        raise NoJobsFeedError("none of them")

    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_all_no,
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert "is a list of job postings" in (outcome.refuse_reason or "")


def test_the_total_that_counts_THESE_records_wins_over_the_bigger_one_beside_it() -> None:
    """walmart publishes ``total_jobs: 47298`` next to ``total_future_roles: 276561``.
    Taking the largest would report a board of 47,298 as a board of 276,561, in copy the
    user reads — so the count whose NAME matches the records array wins outright."""
    artifact = {
        "total_jobs": 47298, "total_future_roles": 276561, "total_content": 36,
        "page_size": 10, "jobs": _jobs(10),
    }
    body = {"data": {"assistant": {"tool_messages": [{"artifact": artifact}]}}}
    path = "data.assistant.tool_messages.0.artifact.jobs"
    assert _totals_beside_records(body, path, 10) == 47298

    # With no name match left, the largest in scope is the only defensible answer.
    del artifact["total_jobs"]
    assert _totals_beside_records(body, path, 10) == 276561


def test_a_per_record_count_two_levels_down_is_not_a_board_total() -> None:
    """kakao's ``jobTypeCountDtoList.2.jobCount`` is 14 and is a facet bucket, not a
    board size. Scoping the search to the records array's own containers is what keeps
    every payload's per-row counts out of a number we render."""
    body = {
        "jobList": _jobs(8),
        "jobTypeCountDtoList": [{"jobType": "TECH", "jobCount": 14}],
        "totalJobCount": 8,
    }
    assert _totals_beside_records(body, "jobList", 8) == 8


async def test_a_board_narrowed_to_a_tab_its_own_page_opened_is_stored_as_partial() -> None:
    """careers.kakao.com. The user pasted ``/jobs`` with no filter; the page redirected
    itself to ``part=TECHNOLOGY`` and the capture recorded THAT request.

    The board says both things in one response — ``totalJobCount: 8`` for the tab it
    happened to open, and its own category counts adding to 31 for the whole board — so
    this needs no guess about what the URL meant. The recipe stays at the scope it was
    captured at (widening a filter is a change we cannot validate); what changes is that
    we stop calling it the whole board.
    """
    body = {
        "jobList": _jobs(8, "P-"),
        "jobTypeCountDtoList": [
            {"jobType": "TECHNOLOGY", "jobCount": 8},
            {"jobType": "DESIGN", "jobCount": 3},
            {"jobType": "BUSINESS_SERVICES", "jobCount": 14},
            {"jobType": "STAFF", "jobCount": 6},
        ],
        "totalJobCount": 8,
        "totalPage": 1,
    }
    assert _labelled_facet_total(body, "jobList") == 31

    response = _amazon_response(body)
    selection = RequestSelection(
        chosen_request_index=0, records_path="jobList",
        field_map=dict(_PARTIAL_MAP), pagination=None,
    )
    outcome = await discover(
        "https://careers.kakao.com/jobs",
        capture=_capture_of(response),
        select=_selecting(selection),
        replay_http=_replay_records(body, "jobList", _PARTIAL_MAP),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.oracle_kind == "declared_probed"   # unchanged: 8 of 8 is still exact
    assert outcome.progress is not None
    assert outcome.progress["outcome"] == "partial"
    verify = next(s for s in outcome.progress["steps"] if s["key"] == "verify_read")
    assert "category counts add up to 31" in (verify["result"] or "")


def test_a_histogram_facet_is_not_read_as_a_tab_count() -> None:
    """amazon's ``{"US, WA, Seattle": 3409}`` buckets over-count multi-located jobs — its
    own location facet sums to 34,794 against a real 22,492 — so a single one of them may
    never become the number we quote. Requiring a STRING LABEL beside exactly one integer
    is what separates kakao's tab counts from amazon's histograms."""
    body = {
        "jobs": _jobs(10),
        "facets": {"location_facet": [{"US, WA, Seattle": 3409}, {"IN, KA": 1220}]},
    }
    assert _labelled_facet_total(body, "jobs") is None


async def test_a_board_read_completely_is_not_labelled_partial() -> None:
    """The control, and the one that keeps the label meaningful. Every board in the
    tracked set reaches at least as far as its own published total; the label must not
    fire on any of them."""
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.progress is not None
    assert outcome.progress["outcome"] == "tracking"
    verify = next(s for s in outcome.progress["steps"] if s["key"] == "verify_read")
    assert verify["result"] == "read 10 job(s)"


def test_the_partial_bar_is_a_shortfall_AND_a_ratio_not_either_alone() -> None:
    """Both guards, and each is load-bearing on a different size of board.

    The RATIO stops a big board being called partial for a rounding error (95 of 100 is
    not a sliver). The ABSOLUTE floor stops a small one being called partial for drift —
    two jobs closing between the capture and the replay seconds later is 20% of a
    ten-job board, and a label that fires on every board that breathes stops meaning
    anything. Neither alone covers the other's case.
    """
    def coverage_of(records: int, declared: int):
        body = {"jobs": _jobs(records), "total_jobs": declared}
        candidate = prefilter_candidates([_pageless_response(body)])[0]
        selection = RequestSelection(
            chosen_request_index=0, records_path="jobs",
            field_map=dict(_PARTIAL_MAP), pagination=None,
        )
        script = synthesize_recipe(
            candidate, selection, transport="http_json", origin_url=_AMAZON_URL
        )
        return _coverage(script, candidate, selection)

    assert coverage_of(95, 100).is_partial is False    # ratio 0.95 — a rounding error
    assert coverage_of(8, 10).is_partial is False      # 2 jobs — drift on a small board
    assert coverage_of(98, 400).is_partial is True     # a quarter of the board


# --------------------------------------------------------------------------
# THE NETWORK LOG — "show me what you actually did"
# --------------------------------------------------------------------------
# The checklist says what happened; this says what we SAW. It matters most on a
# refusal, where the panel's whole content used to be a conclusion with no evidence
# attached ("none of the 14 JSON requests this page made is a list of job postings").


def _log(progress: dict) -> list[dict]:
    return progress["network"]["requests"]


async def test_an_accepted_board_marks_which_request_won_and_what_it_returned() -> None:
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True
    assert outcome.progress is not None
    rows = _log(outcome.progress)
    # Every response the browser saw, in the order it saw them — not re-ranked.
    assert [row["url"] for row in rows] == [
        "https://metrics.example-cdn.com/collect",
        "https://www.amazon.jobs/config/locales.json",
        "https://www.amazon.jobs/en/search.json?sort=…&offset=…&result_limit=…",
    ]
    assert [row["state"] for row in rows] == ["recorded", "recorded", "chosen"]
    # ...and the two that were not jobs say so, which is the evidence for the pick.
    assert [row["records"] for row in rows] == [0, 0, 10]
    assert "came back when we replayed it" in rows[2]["note"]
    sample = outcome.progress["network"]["sample"]
    assert sample["path"] == "jobs"
    assert sample["records"] == 10
    # The board's OWN json, not our mapped rows — this is the "see the payload" bit.
    assert '"title"' in sample["text"]


async def test_a_refusal_publishes_every_request_it_looked_at() -> None:
    """THE point of the whole panel. metacareers-shaped: three JSON requests, none of
    them a jobs feed. The refusal sentence counts them; the log is the count."""
    outcome = await discover(
        _META_URL,
        capture=_capturing("noise"),
        select=_selecting(_amazon_selection()),
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is False
    assert outcome.progress is not None
    rows = _log(outcome.progress)
    assert len(rows) == 3
    # Scored, not un-examined: "we looked and there were no job postings in it".
    assert all(row["records"] == 0 for row in rows)
    assert all(row["state"] == "recorded" for row in rows)
    assert outcome.progress["network"]["sample"] is None
    assert outcome.progress["network"]["recorded"] == 3


async def test_a_request_we_refuse_to_fetch_is_named_as_that_and_not_as_empty() -> None:
    """A job-shaped feed on a private address is a different story from a response with
    no jobs in it, and the user's next action differs."""
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_never_called_replay("http_json"),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_blocking("search.json"),
    )
    assert outcome.ok is False
    assert outcome.progress is not None
    blocked = [row for row in _log(outcome.progress) if row["state"] == "blocked"]
    assert len(blocked) == 1
    assert blocked[0]["url"].startswith("https://www.amazon.jobs/en/search.json")
    assert blocked[0]["note"] == "we refuse to fetch this address"


async def test_the_log_streams_while_the_browser_is_open_but_not_per_response() -> None:
    """Narration must be visible AND cheap. The rows arrive as the browser sees them;
    the DATABASE sees at most :data:`_MAX_REQUEST_PUBLISHES` extra writes, because a
    write per response would turn one capture into dozens of UPDATEs on a row every
    open tab is already polling."""
    snapshots: list[dict] = []

    async def _emit(snapshot: dict) -> None:
        snapshots.append(snapshot)

    async def _chatty(url: str, *, on_request: Any = None, **_: Any) -> CaptureResult:
        for i in range(60):
            assert on_request is not None
            await on_request({
                "method": "GET", "url": f"https://www.amazon.jobs/x{i}",
                "status": 200, "bytes": 10, "truncated": False,
            })
        return _capture_result("amazon")

    outcome = await discover(
        _AMAZON_URL,
        capture=_chatty,
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        emit=_emit,
    )
    assert outcome.ok is True
    # The first response published immediately (nothing had been published yet), and
    # the interval throttle swallowed the other 59 — a real capture spreads them over
    # tens of seconds, so this asserts the CEILING, not the shape of one burst.
    mid_run = [s for s in snapshots if s["network"]["requests"]]
    assert 1 <= len(mid_run) <= _MAX_REQUEST_PUBLISHES
    assert mid_run[0]["network"]["requests"][0]["url"] == "https://www.amazon.jobs/x0"


async def test_the_finished_capture_replaces_whatever_was_streamed() -> None:
    """The streamed rows are provisional: the parent drops report entries it cannot
    read, so the list the user ends up reading has to be the capture's, or the record
    counts would land on the wrong rows."""
    async def _lying(url: str, *, on_request: Any = None, **_: Any) -> CaptureResult:
        assert on_request is not None
        await on_request({
            "method": "GET", "url": "https://www.amazon.jobs/never-happened",
            "status": 200, "bytes": 1, "truncated": False,
        })
        return _capture_result("amazon")

    outcome = await discover(
        _AMAZON_URL,
        capture=_lying,
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP, declared_total=76),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.progress is not None
    urls = [row["url"] for row in _log(outcome.progress)]
    assert "https://www.amazon.jobs/never-happened" not in urls
    assert len(urls) == 3


# --- higher.gs.com: the three defects, at the point discovery AUTHORS them ----
#
# The fixture is the real Aug-2026 capture: one GraphQL POST whose cursor and page
# size live four levels down ``variables.searchQueryInput.page``, and the twenty
# ``/_next/data/<build>/roles/<sourceId>.json`` calls the page's own job cards made.
# Those twenty URLs are the only evidence needed to tell which of the record's two
# ids the board actually routes on.

_GS_URL = "https://higher.gs.com/results"

_GS_MAP = {
    "id": "roleId",
    "url": "https://higher.gs.com/roles/{roleId}",      # the model's answer: WRONG
    "title": "jobTitle",
    "location": "locations[0].city",
    "department": "division",
}


def _gs_selection() -> RequestSelection:
    return RequestSelection(
        chosen_request_index=0, records_path="data.roleSearch.items",
        field_map=dict(_GS_MAP),
        pagination=PaginationHint(style="page", param="pageNumber", page_size=20),
    )


def _gs_candidate() -> Any:
    return prefilter_candidates(_capture_result("goldman").responses)[0]


def _gs_candidate_with_page(number: int) -> Any:
    """The same candidate with a different captured ``pageNumber``."""
    candidate = _gs_candidate()
    body = json.loads(candidate.post_data)
    body["variables"]["searchQueryInput"]["page"]["pageNumber"] = number
    return candidate.__class__(**{**candidate.__dict__, "post_data": json.dumps(body)})


def test_a_zero_based_board_stores_the_page_it_actually_starts_from() -> None:
    """DEFECT A, SECOND HALF. Discovery never emitted ``start_page``, so the runner
    used its default of 1 while Goldman's captured body says ``pageNumber: 0`` — the
    sweep skipped the board's whole first page.

    That is worse than twenty missing jobs. The short sweep still ends on a short page,
    so it reports ``terminated_cleanly`` and ``page_advance_ok`` and looks like a
    complete read; a board with a ``self_consistent`` oracle would VERIFY it, and only
    a VERIFIED run may close a job. ``test_recipe_corpus_regression`` pins that
    interaction end to end.
    """
    script = synthesize_recipe(
        _gs_candidate(), _gs_selection(), transport="http_json", origin_url=_GS_URL
    )
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["op"] == "paginate_page"
    assert paginate["start_page"] == 0


def test_a_one_based_board_still_stores_a_one() -> None:
    """The other believable base, stored explicitly rather than left to a default."""
    script = synthesize_recipe(
        _gs_candidate_with_page(1), _gs_selection(),
        transport="http_json", origin_url=_GS_URL,
    )
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["start_page"] == 1


def test_a_capture_taken_mid_sweep_stores_no_start_page_at_all() -> None:
    """A captured ``pageNumber: 7`` is not a base — it is a request from the middle of
    somebody's scroll, and the board's base is not knowable from it. Storing 7 would
    skip seven pages every night, which is strictly worse than the default; the honest
    answer is to store nothing and log."""
    script = synthesize_recipe(
        _gs_candidate_with_page(7), _gs_selection(),
        transport="http_json", origin_url=_GS_URL,
    )
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert "start_page" not in paginate


def test_a_nested_page_size_parameter_is_found_and_raised() -> None:
    """DEFECT A, THIRD SITE. ``_page_size_param`` scanned only ``body.items()``, so
    Goldman's ``pageSize`` — beside its ``pageNumber``, four levels down — was
    invisible and the acceptance ladder never offered the upgrade. The board honours
    100 (and 500s above it), so the nightly run bought 54 requests where 11 would do.
    """
    candidate, selection = _gs_candidate(), _gs_selection()
    assert page_size_attempts(candidate, selection) == (100, None)

    script = synthesize_recipe(
        candidate, selection, transport="http_json", origin_url=_GS_URL,
        page_size_override=100,
    )
    page = script["steps"][0]["body"]["variables"]["searchQueryInput"]["page"]
    # Raised WHERE THE BOARD CARRIES IT — a top-level write would leave the real
    # pageSize at 20 while paginate.page_size claimed 100, which ends the sweep one
    # page early and reports a partial board as a complete one.
    assert page["pageSize"] == 100
    assert "pageSize" not in script["steps"][0]["body"]
    (paginate,) = [s for s in script["steps"] if s["op"].startswith("paginate_")]
    assert paginate["page_size"] == 100


async def test_discovery_repoints_a_url_template_at_the_boards_own_route_key() -> None:
    """DEFECT B, through the whole orchestrator. The model maps ``{roleId}``; the
    board's own ``_next/data`` calls spell ``{externalSource.sourceId}``. Because
    higher.gs.com is a Next.js SPA that answers 200 for ``/roles/<anything>``, nothing
    downstream could ever have caught this — ``_validate_url_field`` checks link SHAPE
    and its own docstring concedes it cannot detect a well-formed URL that 404s.

    ``id`` is deliberately untouched: it is half of ``job_listings``' composite primary
    key and the default ``dedupe_key``, so re-pointing it would orphan every row the
    board already has.
    """
    repaired = "https://higher.gs.com/roles/{externalSource.sourceId}"
    outcome = await discover(
        _GS_URL,
        capture=_capturing("goldman"),
        select=_selecting(_gs_selection()),
        replay_http=_faithful_replay(
            "goldman", "data.roleSearch.items", {**_GS_MAP, "url": repaired},
            declared_total=1033,
        ),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.ok is True, outcome.refuse_reason
    script = outcome.script
    assert script is not None
    (extract,) = [s for s in script["steps"] if s["op"].startswith("extract_")]
    assert extract["fields"]["url"] == repaired
    assert extract["fields"]["id"] == "roleId"          # NEVER re-pointed
    # Defect C rides along: the bracket path survives the non-scalar prune, because it
    # now resolves to a string instead of raising.
    assert extract["fields"]["location"] == "locations[0].city"


async def test_a_board_whose_url_field_is_already_right_is_left_alone() -> None:
    """The asymmetry that makes the repair safe: a template whose id already appears in
    the board's own links can never be rewritten, so every board the model got right is
    untouched by construction rather than by a threshold."""
    already_right = "https://higher.gs.com/roles/{externalSource.sourceId}"
    selection = RequestSelection(
        chosen_request_index=0, records_path="data.roleSearch.items",
        field_map={**_GS_MAP, "url": already_right},
        pagination=PaginationHint(style="page", param="pageNumber", page_size=20),
    )
    outcome = await discover(
        _GS_URL,
        capture=_capturing("goldman"),
        select=_selecting(selection),
        replay_http=_faithful_replay(
            "goldman", "data.roleSearch.items", {**_GS_MAP, "url": already_right},
            declared_total=1033,
        ),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
    )
    assert outcome.script is not None
    (extract,) = [s for s in outcome.script["steps"] if s["op"].startswith("extract_")]
    assert extract["fields"]["url"] == already_right


# ==========================================================================
# THE JOB LINK — published, proved, or downgraded
# ==========================================================================


def _refusing_probe(label: str):
    """A probe that fails the test if it is called at all."""
    def probe(url: str) -> tuple[int, str]:
        raise AssertionError(f"{label}: the job link must not be fetched (asked for {url})")
    return probe


def _shell_probe(chars: int = 400, *, seen: list[str] | None = None):
    """The SPA that answers 200 with the same bytes for every job — Goldman's wrong
    route key, Walmart, Kakao. The shape a status check calls healthy."""
    def probe(url: str) -> tuple[int, str]:
        if seen is not None:
            seen.append(url)
        return 200, "<html><body>" + "x" * chars + "</body></html>"
    return probe


def _status_probe(status: int, *, seen: list[str] | None = None):
    """An error status with a per-URL body — a real 404 page, not an empty one.

    The bodies are deliberately DIFFERENT: an empty body would make the status the only
    thing distinguishing this board from a working one, so a build that dropped the
    status gate entirely would still refuse and the test would prove nothing.
    """
    def probe(url: str) -> tuple[int, str]:
        if seen is not None:
            seen.append(url)
        return status, f"<html><body>not found: {url}{'x' * (900 * len(url))}</body></html>"
    return probe


async def test_a_link_the_board_published_is_stored_without_being_fetched() -> None:
    """BRANCH 1. Amazon maps ``https://www.amazon.jobs{job_path}`` — the placeholder
    renders ``/en/jobs/...``, a PATH the board wrote — so there is nothing of ours to
    prove and the probe must never run.

    This is not an optimisation. The proof cannot tell a client-rendered job page from
    a client-rendered 404 shell, and Atlassian's iCIMS link (a live production link,
    three jobs, 18,086 chars each, no title on any of them) is exactly that shape. A
    probe here would reject working links to catch nothing.
    """
    outcome = await discover(
        _AMAZON_URL,
        capture=_capturing("amazon"),
        select=_selecting(_amazon_selection()),
        replay_http=_faithful_replay("amazon", "jobs", _AMAZON_MAP),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        probe_link=_refusing_probe("amazon"),
    )
    assert outcome.ok is True, outcome.refuse_reason
    (extract,) = [s for s in outcome.script["steps"] if s["op"].startswith("extract_")]
    assert extract["fields"]["url"] == _AMAZON_MAP["url"]      # byte-identical


async def test_the_repaired_goldman_template_is_the_one_that_gets_proved() -> None:
    """BRANCH 3, and the ORDER inside it. ``repair_url_template`` only fires when the
    model's id appears in ZERO of the board's own links, so its answer is the
    better-evidenced candidate and is fetched first. What lands in the recipe is the
    template we actually proved, not the one we merely preferred.
    """
    repaired = "https://higher.gs.com/roles/{externalSource.sourceId}"
    fetched: list[str] = []

    def probe(url: str) -> tuple[int, str]:
        fetched.append(url)
        return 200, f"<html><body>{url}{'x' * (600 + 500 * len(fetched))}</body></html>"

    outcome = await discover(
        _GS_URL,
        capture=_capturing("goldman"),
        select=_selecting(_gs_selection()),
        replay_http=_faithful_replay(
            "goldman", "data.roleSearch.items", {**_GS_MAP, "url": repaired},
            declared_total=1033,
        ),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        probe_link=probe,
    )
    assert outcome.ok is True, outcome.refuse_reason
    (extract,) = [s for s in outcome.script["steps"] if s["op"].startswith("extract_")]
    assert extract["fields"]["url"] == repaired
    # The REPAIRED urls were the ones fetched — bare numbers, not the compound roleId.
    assert fetched and all(url.rsplit("/", 1)[-1].isdigit() for url in fetched)
    assert len(fetched) == 2                       # two jobs, and no second candidate


async def test_a_template_that_serves_one_shell_for_every_job_is_not_stored() -> None:
    """THE GOLDMAN / WALMART / KAKAO SHAPE, end to end. Every job URL answers **200**
    with the same bytes, so a status check would store it and every "view job" link on
    the board would be dead.

    Both candidates are tried (the repair's answer and the model's), both fail, and the
    board is still TRACKED — its feed reads perfectly. Only the link is downgraded.
    """
    seen: list[str] = []
    outcome = await discover(
        _GS_URL,
        capture=_capturing("goldman"),
        select=_selecting(_gs_selection()),
        replay_http=_faithful_replay(
            "goldman", "data.roleSearch.items", _GS_MAP, declared_total=1033,
        ),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        probe_link=_shell_probe(seen=seen),
    )
    assert outcome.ok is True, outcome.refuse_reason      # the BOARD is fine
    (extract,) = [s for s in outcome.script["steps"] if s["op"].startswith("extract_")]
    assert extract["fields"]["url"] == f"{_GS_URL}#{{roleId}}"
    assert extract["fields"]["id"] == "roleId"            # NEVER re-pointed
    assert len(seen) == 4                                 # two candidates, two jobs each
    verify = next(s for s in outcome.progress["steps"] if s["key"] == "verify_read")
    assert "links to the board's own listing page" in verify["result"]


async def test_a_link_that_404s_is_not_stored_either() -> None:
    """The Jane Street shape: no shell, no ambiguity, just a 404 nobody looked at.
    Cheaper to detect than the shell — and the reason the status check stays as the
    first gate rather than being replaced by the comparison."""
    outcome = await discover(
        _GS_URL,
        capture=_capturing("goldman"),
        select=_selecting(_gs_selection()),
        replay_http=_faithful_replay(
            "goldman", "data.roleSearch.items", _GS_MAP, declared_total=1033,
        ),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        probe_link=_status_probe(404),
    )
    assert outcome.ok is True
    (extract,) = [s for s in outcome.script["steps"] if s["op"].startswith("extract_")]
    assert extract["fields"]["url"] == f"{_GS_URL}#{{roleId}}"


async def test_a_board_that_publishes_a_link_never_gets_an_invented_one() -> None:
    """BRANCH 2, direction #1 of the rule. The model answered a template it composed
    out of an id while the payload carries ``hostedUrl`` on every record. The board's
    own field wins outright and nothing is fetched — a link the board published is
    better evidence than any number of successful GETs against a path we guessed.
    """
    invented = {**_GROUPED_MAP, "url": "https://www.binance.com/careers/{id}"}
    selection = RequestSelection(
        chosen_request_index=0, records_path="*.postings",
        field_map=dict(invented), pagination=None,
    )
    outcome = await discover(
        "https://www.binance.com/en/careers/job-openings",
        capture=_capturing("grouped"),
        select=_selecting(selection),
        replay_http=_faithful_replay("grouped", "*.postings", _GROUPED_MAP),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        probe_link=_refusing_probe("binance"),
    )
    assert outcome.ok is True, outcome.refuse_reason
    (extract,) = [s for s in outcome.script["steps"] if s["op"].startswith("extract_")]
    assert extract["fields"]["url"] == "hostedUrl"


# --------------------------------------------------------------------------
# DERIVING the job link — the rung the proof could not reach
# --------------------------------------------------------------------------
#
# ``_prove_job_link`` is verification-only: it can show a template is wrong and cannot
# find the right one, so a board with no published link field fell to
# ``_board_page_link`` — a ``listing-page#{id}`` fragment. Measured on Jane Street:
# 233 jobs, every one linking to the same page. These prove the two new sources and,
# just as importantly, that neither is TRUSTED — every candidate still goes through the
# same two-real-jobs proof.

_JS_URL = "https://www.janestreet.com/join-jane-street/open-roles/"
_JS_FEED = "https://www.janestreet.com/jobs/main.json"
_JS_RECORDS = [
    {"id": f"{4273643 + i}002", "position": f"Role {i}", "city": "NYC",
     "overview": f"About role {i}"}
    for i in range(6)
]
_JS_MAP = {
    "id": "id", "title": "position",
    # The model's own guess, and it is a 404 on the live board.
    "url": "https://www.janestreet.com/jobs/{id}",
    "location": "city", "description": "overview",
}
# The one line of Jane Street's own bundle that matters. The board's page renders NO
# job anchors at all — it is a chooser that fetches all 233 roles and shows none — so
# this is the only place the shape exists.
_JS_BUNDLE = (
    'l="open"===t.status?`<a href="/join-jane-street/position/${t.id}/">`:'
    '`<a href="/join-jane-street/closed-internship/${i}-${a}-${s}/">`'
)


def _feed_response(url: str, records: list[dict[str, Any]]) -> Any:
    """One captured JSON response carrying ``records`` as its whole body."""
    original = _amazon_response({})
    return original.__class__(
        **{**original.__dict__, "url": url, "body": json.dumps(records)}
    )


def _capture_with(
    response: Any, *, final_url: str, links: tuple[str, ...] = (),
    scripts: tuple[str, ...] = (),
):
    async def _capture(url: str, **_: Any) -> CaptureResult:
        return CaptureResult(
            final_url=final_url, page_title="Careers", responses=[response],
            board_links=links, board_scripts=scripts,
        )
    return _capture


def _replay_script(records: list[dict[str, Any]]):
    """Replay through the recipe's OWN field map, so the stored url is what comes back."""
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        (extract,) = [s for s in script["steps"] if s["op"] == "extract_json_path"]
        rows = map_records(records, extract["fields"], script.get("base_url", ""))
        return rows, HarvestEvidence(
            declared_total=None, cap_hit=False, terminated_cleanly=True,
            page_advance_ok=None, pages_fetched=1, transport_ok=True,
        )
    return _replay


def _routing_probe(good_prefix: str, *, script_body: str = "", seen: list[str] | None = None):
    """A board that serves a REAL page under ``good_prefix`` and 404s everywhere else.

    Any ``.js`` URL answers with ``script_body`` — the same ``ProbeFn`` seam carries both
    the job-page proof and the script read, which is the point: one SSRF-guarded client,
    one test double.
    """
    lengths: dict[str, int] = {}

    def probe(url: str) -> tuple[int, str]:
        if seen is not None:
            seen.append(url)
        if url.endswith(".js"):
            return (200, script_body) if script_body else (404, "")
        if not url.startswith(good_prefix):
            return 404, ""
        nth = lengths.setdefault(url, len(lengths))
        return 200, "<html><body>" + "job " * (500 + 300 * nth) + "</body></html>"

    return probe


async def test_a_boards_own_anchors_become_the_job_link_after_being_proved() -> None:
    """The anchor source, end to end. The page links every posting; nothing read it
    before, so the model's invented template was stored or a fragment was."""
    outcome = await discover(
        "https://www.atlassian.com/company/careers/all-jobs",
        capture=_capture_with(
            _feed_response("https://www.atlassian.com/endpoint/careers/listings", _JS_RECORDS),
            final_url="https://www.atlassian.com/company/careers/all-jobs",
            links=tuple(
                f"/company/careers/details/{r['id']}" for r in _JS_RECORDS
            ) + ("/company/careers",),
        ),
        select=_selecting(RequestSelection(
            chosen_request_index=0, records_path="",
            field_map={**_JS_MAP, "url": "https://www.atlassian.com/jobs/{id}"},
            pagination=None,
        )),
        replay_http=_replay_script(_JS_RECORDS),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        probe_link=_routing_probe("https://www.atlassian.com/company/careers/details/"),
    )
    assert outcome.ok is True
    assert outcome.script is not None
    (extract,) = [s for s in outcome.script["steps"] if s["op"] == "extract_json_path"]
    assert extract["fields"]["url"] == (
        "https://www.atlassian.com/company/careers/details/{id}"
    )


async def test_a_board_that_renders_no_job_anchors_falls_back_to_its_own_code() -> None:
    """JANE STREET, the board this rung exists for. Its careers page is a chooser: it
    fetches all 233 roles as JSON and renders NONE of them, so there is not one job
    anchor to mine — measured 2026-08-30, zero job ids in the rendered DOM. The template
    lives in the bundle the page loads, and that is where this finds it."""
    seen: list[str] = []
    outcome = await discover(
        _JS_URL,
        capture=_capture_with(
            _feed_response(_JS_FEED, _JS_RECORDS),
            final_url=_JS_URL,
            links=("/join-jane-street/overview/", "/puzzles/"),
            scripts=("/assets/pg/open_positions-abc.js",),
        ),
        select=_selecting(RequestSelection(
            chosen_request_index=0, records_path="",
            field_map=dict(_JS_MAP), pagination=None,
        )),
        replay_http=_replay_script(_JS_RECORDS),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        probe_link=_routing_probe(
            "https://www.janestreet.com/join-jane-street/position/",
            script_body=_JS_BUNDLE, seen=seen,
        ),
    )
    assert outcome.ok is True
    assert outcome.script is not None
    (extract,) = [s for s in outcome.script["steps"] if s["op"] == "extract_json_path"]
    assert extract["fields"]["url"] == (
        "https://www.janestreet.com/join-jane-street/position/{id}/"
    )
    # ...and the ONE script was read from the board's own host, once.
    assert seen.count("https://www.janestreet.com/assets/pg/open_positions-abc.js") == 1


async def test_a_derived_template_that_does_not_route_is_still_refused() -> None:
    """DERIVING AND TRUSTING ARE DIFFERENT ACTS. The same bundle builds a site-wide
    search box (``/search/?query=${q}``), and a board that answers every query with the
    same page is not routing on the job id. Measured against the live board:
    ``/search/?query={id}`` serves 2,255 chars for two different jobs. It must lose to
    the honest fragment, not be stored."""
    outcome = await discover(
        _JS_URL,
        capture=_capture_with(
            _feed_response(_JS_FEED, _JS_RECORDS),
            final_url=_JS_URL,
            scripts=("/assets/main.js",),
        ),
        select=_selecting(RequestSelection(
            chosen_request_index=0, records_path="",
            field_map=dict(_JS_MAP), pagination=None,
        )),
        replay_http=_replay_script(_JS_RECORDS),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        # Every job URL answers 200 with the SAME page — the shape of a search box and
        # of an SPA shell alike.
        probe_link=lambda url: (
            (200, _JS_BUNDLE.replace("position/${t.id}", "search/?query=${q}"))
            if url.endswith(".js") else (200, "<html>same page every time</html>")
        ),
    )
    assert outcome.ok is True
    assert outcome.script is not None
    (extract,) = [s for s in outcome.script["steps"] if s["op"] == "extract_json_path"]
    assert extract["fields"]["url"] == f"{_JS_URL}#{{id}}"


async def test_a_published_link_still_costs_no_fetch_at_all() -> None:
    """Rung 1 is unchanged and must stay that way: a board that publishes its own link is
    the authority, and the proof CANNOT tell a client-rendered job page from a
    client-rendered 404 shell. Deriving does not get to change that."""
    records = [
        {**r, "hostedUrl": f"https://boards.example.com/j/{r['id']}"} for r in _JS_RECORDS
    ]
    seen: list[str] = []
    outcome = await discover(
        "https://example.com/careers",
        capture=_capture_with(
            _feed_response("https://example.com/api/jobs", records),
            final_url="https://example.com/careers",
            links=tuple(f"/careers/{r['id']}" for r in records),
            scripts=("/static/app.js",),
        ),
        select=_selecting(RequestSelection(
            chosen_request_index=0, records_path="",
            field_map={**_JS_MAP, "url": "hostedUrl"}, pagination=None,
        )),
        replay_http=_replay_script(records),
        replay_browser=_never_called_replay("browser_fetch"),
        validate_url=_allow_all,
        probe_link=_routing_probe("https://never-fetched.example", seen=seen),
    )
    assert outcome.ok is True
    assert seen == []


# --------------------------------------------------------------------------
# THE WALMART CATCH — a page index with nothing advancing it
# --------------------------------------------------------------------------

def test_a_page_index_with_nothing_advancing_it_is_refused() -> None:
    """``page_shape_refusal`` is checks 13a/13b of the nightly gate — pure, already
    written, and never called by discovery. So a recipe whose fetch says "page one" and
    whose steps say nothing about page two passed synthesis, passed acceptance (the
    replay reads back the SAME rows the browser saw, so match-the-capture is delighted)
    and was stored. Measured on careers.walmart.com: 10 jobs tracked out of 48,800, and
    every later gate agrees forever because the baseline came from this run."""
    candidate = prefilter_candidates([_untotalled_amazon()])[0]   # url carries ``offset``
    no_paging = RequestSelection(
        chosen_request_index=0, records_path="jobs",
        field_map=dict(_AMAZON_MAP), pagination=None,
    )
    with pytest.raises(Exception) as caught:
        synthesize_recipe(
            candidate, no_paging, transport="http_json", origin_url=_AMAZON_URL
        )
    assert "one page of results" in str(caught.value)


def test_the_boards_own_total_beats_the_shape_of_its_request() -> None:
    """The one exception, and it is the difference between a rule and a nuisance. When
    the board says N and hands us N, a page index in the request means "page one is the
    whole board" — refusing there would throw away boards we read correctly today."""
    body = _amazon_body()
    body["hits"] = 10                                   # == the captured record count
    candidate = prefilter_candidates([_amazon_response(body)])[0]
    script = synthesize_recipe(
        candidate,
        RequestSelection(
            chosen_request_index=0, records_path="jobs",
            field_map=dict(_AMAZON_MAP), pagination=None,
        ),
        transport="http_json", origin_url=_AMAZON_URL,
    )
    assert [s["op"] for s in script["steps"] if s["op"].startswith("paginate_")] == []


def test_a_recipe_that_actually_pages_is_never_caught_by_the_shape_check() -> None:
    """13a is about a page index NOTHING advances. A recipe with a paginate step is
    judged by the stronger checks (cap_hit / page_advance_ok) instead."""
    candidate = prefilter_candidates([_untotalled_amazon()])[0]
    script = synthesize_recipe(
        candidate,
        RequestSelection(
            chosen_request_index=0, records_path="jobs", field_map=dict(_AMAZON_MAP),
            pagination=PaginationHint(style="offset", param="offset", page_size=10),
        ),
        transport="http_json", origin_url=_AMAZON_URL,
    )
    assert [s["op"] for s in script["steps"] if s["op"].startswith("paginate_")] == [
        "paginate_offset"
    ]
