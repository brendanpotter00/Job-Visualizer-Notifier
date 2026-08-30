"""THE FAN-OUT and THE REFEREE — one call per array, ranked on measurements. $0.

Discovery used to make ONE model call over the whole captured list and ask it to RANK
and MAP in a single answer. The crowding-out that actually happened was WITHIN one
source — a chatbot response and a real jobs response are both XHR JSON — which is why
fanning out per source KIND would have changed nothing, and why this fans out per
CANDIDATE.

Three properties are load-bearing and each is tested here:

* **saying no is cheap.** ``is_jobs_feed: false`` kills one array; the board survives.
  Under the old schema the only way to say no was about the WHOLE page.
* **one bad call kills one candidate.** A timeout, a 529 or an unbelievable answer used
  to burn the round — and on a single-feed board, the discovery.
* **code ranks, the model does not.** Several yeses are ordered on measurements the
  board published about itself; ``confidence`` is the last tie-break and nothing else.

There is deliberately NO model-interpreted check anywhere in the referee. Where the
measurements are ambiguous the answer is the conservative one.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from anthropic import APIError

from api.services.capture import request_selector as rs
from api.services.capture.discover import _rank_answers
from api.services.capture.request_selector import (
    _FANOUT_CONCURRENCY,
    _MAX_FANOUT_CALLS,
    Candidate,
    CandidateAnswer,
    HtmlSource,
    NoJobsFeedError,
    RequestSelectionError,
    SelectorKeyMissingError,
    select_candidates,
    session_token_keys,
)

pytestmark = pytest.mark.asyncio


def _jobs(n: int, prefix: str = "J") -> list[dict[str, Any]]:
    return [
        {"id": f"{prefix}{i}", "title": f"Engineer {i}", "location": "Remote"}
        for i in range(n)
    ]


def _candidate(
    index: int,
    *,
    records: list[dict[str, Any]] | None = None,
    url: str | None = None,
    post_data: str | None = None,
    extra: dict[str, Any] | None = None,
    html: HtmlSource | None = None,
    job_score: int = 4,
) -> Candidate:
    # Distinct records per candidate BY DEFAULT: identical arrays are deduped on a
    # sha256 of the records (islands duplicate XHR payloads byte for byte), and a test
    # about the call count must not accidentally be a test about the dedupe.
    rows = _jobs(10, f"C{index}-") if records is None else records
    payload: dict[str, Any] = {"jobs": rows}
    payload.update(extra or {})
    return Candidate(
        index=index,
        url=url or f"https://board.example.com/api/c{index:02d}/list",
        method="POST" if post_data else "GET",
        request_headers={},
        post_data=post_data,
        payload=payload,
        records_path="jobs",
        record_count=len(rows),
        job_score=job_score,
        sample_keys=("id", "title", "location"),
        source_index=index,
        html=html,
    )


def _yes(records_path: str = "jobs", confidence: str = "high") -> dict[str, Any]:
    return {
        "is_jobs_feed": True,
        "confidence": confidence,
        "records_path": records_path,
        "field_map": {
            "id": "id", "title": "title",
            "url": "https://board.example.com/j/{id}",
            "location": "location", "posted_at": None, "description": None,
        },
        "pagination": None,
    }


_NO = {
    "is_jobs_feed": False,
    "confidence": "high",
    "records_path": "",
    "field_map": {
        "id": "", "title": "", "url": "",
        "location": None, "posted_at": None, "description": None,
    },
    "pagination": None,
}


def _model(answers: dict[str, Any] | None = None, *, default: Any = None,
           seen: list[str] | None = None, live: list[int] | None = None,
           peak: list[int] | None = None):
    """A per-candidate model double keyed on the URL in the prompt."""
    answers = answers or {}

    async def _create(params: dict[str, Any]) -> Any:
        content = params["messages"][0]["content"]
        key = next((k for k in answers if k in content), None)
        if seen is not None:
            seen.append(key or "?")
        if live is not None:
            live.append(1)
            if peak is not None:
                peak.append(sum(live))
            await asyncio.sleep(0.01)
            live.pop()
        reply = answers.get(key, default if default is not None else _NO)
        if isinstance(reply, BaseException):
            raise reply
        if callable(reply):
            return await reply()
        return type("R", (), {
            "content": [type("B", (), {"type": "text", "text": json.dumps(reply)})()],
            "stop_reason": "end_turn",
        })()
    return _create


# --- one call per candidate --------------------------------------------------

async def test_every_record_bearing_candidate_gets_its_own_call() -> None:
    candidates = [_candidate(i) for i in range(3)]
    seen: list[str] = []
    answers = await select_candidates(
        candidates,
        create_message=_model(
            {c.url: _yes() for c in candidates}, seen=seen,
        ),
    )
    assert len(seen) == 3
    assert [a.candidate_index for a in answers] == [0, 1, 2]


async def test_saying_no_about_one_array_does_not_forfeit_the_board() -> None:
    """THE POINT OF THE FAN-OUT. The old schema's only way to say no was about the WHOLE
    page, so a chatbot response sitting beside a real jobs feed had to be ranked against
    it rather than simply declined."""
    chat, jobs = _candidate(0), _candidate(1)
    answers = await select_candidates(
        [chat, jobs],
        create_message=_model({chat.url: _NO, jobs.url: _yes()}),
    )
    assert [a.candidate_index for a in answers] == [1]


async def test_every_candidate_saying_no_is_a_stop_not_a_retry() -> None:
    """``NoJobsFeedError`` means asking again cannot change the answer. It has to stay
    distinguishable from "the calls went wrong", which IS worth re-asking."""
    with pytest.raises(NoJobsFeedError):
        await select_candidates([_candidate(0)], create_message=_model(default=_NO))


async def test_one_call_raising_kills_that_candidate_and_not_the_run() -> None:
    """A strict robustness gain. One call over the whole list meant one 529 burned the
    round — and on a single-feed board, the discovery."""
    broken, good = _candidate(0), _candidate(1)
    answers = await select_candidates(
        [broken, good],
        create_message=_model({
            broken.url: APIError("overloaded", request=None, body=None),  # type: ignore[arg-type]
            good.url: _yes(),
        }),
    )
    assert [a.candidate_index for a in answers] == [1]


async def test_one_call_timing_out_kills_that_candidate_and_not_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rs, "LLM_TIMEOUT_SECONDS", 0.05)
    slow, good = _candidate(0), _candidate(1)

    async def _hang() -> Any:
        await asyncio.sleep(5)

    answers = await select_candidates(
        [slow, good], create_message=_model({slow.url: _hang, good.url: _yes()}),
    )
    assert [a.candidate_index for a in answers] == [1]


async def test_every_call_failing_is_a_RETRYABLE_error_not_a_clean_no() -> None:
    """The difference between stopping and retrying. ``NoJobsFeedError`` ends the ladder;
    a ``RequestSelectionError`` costs the round and re-asks with the evidence attached."""
    with pytest.raises(RequestSelectionError, match="every candidate's selection call"):
        await select_candidates(
            [_candidate(0), _candidate(1)],
            create_message=_model(default=RuntimeError("connection reset")),
        )


async def test_a_missing_api_key_still_degrades_without_burning_an_attempt() -> None:
    """A misconfigured deployment is not the board's fault, and the caller distinguishes
    it by TYPE — so it must survive the gather rather than being folded into the
    generic failure."""
    with pytest.raises(SelectorKeyMissingError):
        await select_candidates(
            [_candidate(0)],
            create_message=_model(default=SelectorKeyMissingError("no key")),
        )


# --- the short-circuits: candidates that cost no tokens ----------------------

async def test_an_identical_array_is_never_paid_for_twice() -> None:
    """Islands frequently duplicate an XHR payload byte for byte — the served document
    embeds exactly what the page would otherwise fetch — and asking twice is one wasted
    call and two chances at a different answer."""
    rows = _jobs(10)
    xhr = _candidate(0, records=rows)
    island = _candidate(
        1, records=rows, url="https://board.example.com/careers",
        html=HtmlSource(document_url="https://board.example.com/careers",
                        op="extract_embedded_island", selector="script#__NEXT_DATA__"),
    )
    seen: list[str] = []
    answers = await select_candidates(
        [xhr, island],
        create_message=_model({xhr.url: _yes(), island.url: _yes()}, seen=seen),
    )
    assert len(seen) == 1
    assert [a.candidate_index for a in answers] == [0]


async def test_a_one_record_reply_from_a_chat_endpoint_costs_no_token() -> None:
    """A known non-feed BY STRUCTURE. Both halves are needed: a one-record jobs API is a
    small board, and a session key on a hundred records is a correlation id."""
    chat = _candidate(
        0, records=_jobs(1),
        post_data=json.dumps({"thread_id": "S-1788038636412-abc", "query": "engineer"}),
    )
    jobs = _candidate(1)
    seen: list[str] = []
    answers = await select_candidates(
        [chat, jobs], create_message=_model({jobs.url: _yes()}, seen=seen),
    )
    assert seen == [jobs.url]
    assert [a.candidate_index for a in answers] == [1]


def test_the_session_key_detector_reads_the_walmart_shape() -> None:
    """Walmart's stored fetch body carries ``thread_id: "S-1788038636412-<uuid>"`` whose
    embedded epoch decodes to six seconds after the company row was created — minted
    inside that one discovery browser session."""
    walmart = _candidate(0, post_data=json.dumps({
        "variables": {"input": {"thread_id": "S-1788038636412-8c1f", "job_page": 0}},
    }))
    assert session_token_keys(walmart) == ("thread_id",)
    assert session_token_keys(_candidate(1)) == ()
    assert session_token_keys(_candidate(2, post_data='{"correlationId": "x"}')) == (
        "correlationId",
    )


async def test_the_call_budget_truncates_the_least_job_shaped_tail() -> None:
    """Candidates arrive in pre-filter rank order, so the cap cuts from the bottom."""
    candidates = [_candidate(i) for i in range(_MAX_FANOUT_CALLS + 4)]
    seen: list[str] = []
    await select_candidates(
        candidates,
        create_message=_model({c.url: _yes() for c in candidates}, seen=seen),
    )
    assert len(seen) == _MAX_FANOUT_CALLS
    assert seen == [c.url for c in candidates[:_MAX_FANOUT_CALLS]]


async def test_the_semaphore_bounds_how_many_calls_are_in_flight() -> None:
    candidates = [_candidate(i) for i in range(_MAX_FANOUT_CALLS)]
    live: list[int] = []
    peak: list[int] = []
    await select_candidates(
        candidates,
        create_message=_model(
            {c.url: _yes() for c in candidates}, live=live, peak=peak,
        ),
    )
    assert max(peak) <= _FANOUT_CONCURRENCY


# --- the referee -------------------------------------------------------------

def _answer(index: int, confidence: str = "high") -> CandidateAnswer:
    return CandidateAnswer(
        candidate_index=index,
        selection=rs.RequestSelection(
            chosen_request_index=index, records_path="jobs",
            field_map={"id": "id", "title": "title",
                       "url": "https://board.example.com/j/{id}"},
        ),
        confidence=confidence,
    )


def test_a_sliver_of_the_board_ranks_below_a_whole_one() -> None:
    """THE MEASUREMENT THAT MATTERS. Walmart's chat endpoint returns ten records beside
    a self-declared 47,298; the board's real feed returns ten of ten. Both can be "a list
    of job postings" and only one is the board — and the difference is arithmetic the
    board itself published, not a judgement."""
    sliver = _candidate(0, records=_jobs(10), extra={"total_jobs": 47298})
    whole = _candidate(1, records=_jobs(10), extra={"total_jobs": 10})
    ranked = _rank_answers([_answer(0), _answer(1)], [sliver, whole])
    assert [a.candidate_index for a in ranked] == [1, 0]


def test_a_session_bound_request_sorts_below_every_candidate_without_one() -> None:
    """C15, as a DEMOTION and never a verdict. Code cannot prove a session key is fatal —
    plenty of boards send a correlation id the server ignores — and a recipe carrying one
    passes acceptance BY CONSTRUCTION, because acceptance runs minutes later while the
    token is still alive."""
    bound = _candidate(0, post_data=json.dumps({"thread_id": "S-1788038636412-8c1f"}))
    plain = _candidate(1)
    ranked = _rank_answers([_answer(0), _answer(1)], [bound, plain])
    assert [a.candidate_index for a in ranked] == [1, 0]


def test_a_board_that_publishes_a_total_outranks_one_that_publishes_nothing() -> None:
    """Oracle strength, which is the difference between a board that can ever be VERIFIED
    and one that is UNVERIFIED forever."""
    with_total = _candidate(0, records=_jobs(10), extra={"total_jobs": 10})
    without = _candidate(1, records=_jobs(10))
    ranked = _rank_answers([_answer(0), _answer(1)], [with_total, without])
    assert [a.candidate_index for a in ranked] == [0, 1]


def test_a_json_feed_outranks_a_document_when_everything_else_ties() -> None:
    """``http_json`` costs $0 a night and can paginate; ``http_html`` cannot paginate at
    all. A board readable both ways should be read the way that can see all of it."""
    document = _candidate(
        0, html=HtmlSource(document_url="https://board.example.com/careers",
                           op="extract_css", selector='a[href*="/jobs/"]'),
    )
    xhr = _candidate(1)
    ranked = _rank_answers([_answer(0), _answer(1)], [document, xhr])
    assert [a.candidate_index for a in ranked] == [1, 0]


def test_confidence_is_the_LAST_tie_break_and_nothing_more() -> None:
    """The model's own certainty may only ever separate two arrays that every
    measurement rates identically. If it could do more than that, the referee would be
    ranking on the model's opinion again — which is what the fan-out exists to stop."""
    left, right = _candidate(0), _candidate(1)
    ranked = _rank_answers([_answer(0, "low"), _answer(1, "high")], [left, right])
    assert [a.candidate_index for a in ranked] == [1, 0]

    # ...and it loses to every measurement above it: a high-confidence sliver still
    # ranks below a low-confidence whole board.
    sliver = _candidate(0, records=_jobs(10), extra={"total_jobs": 47298})
    whole = _candidate(1, records=_jobs(10))
    ranked = _rank_answers([_answer(0, "high"), _answer(1, "low")], [sliver, whole])
    assert [a.candidate_index for a in ranked] == [1, 0]
