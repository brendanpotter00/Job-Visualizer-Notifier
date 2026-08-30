"""AC-16 .. AC-20 — the board-failure backfill
(``docs/implementations/custom-company-sources/BOARD-FAILURE-TRIAGE.md`` §5).

Eleven boards were driven through the live stack AND through a real browser on
2026-08-30, and every failure was traced to a named line. This file is the
regression half of that work: one case per root cause, each pinning the
MECHANISM the fix changed rather than the board that exposed it.

**Hermetic by default, and that is a decision, not a shortcut.** Every defect in
this batch is expressible as a payload shape — an Oracle ``finder=`` composite,
an Elasticsearch ``hits.hits[]._source`` body, a ``text/x-component``
content-type, a Greenhouse ``absolute_url`` with no path — and a shape can be
frozen. A live board cannot: it changes under you, and a regression test that
turns pink because a third party shipped a redesign stops being read. The live
proof for each of these fixes was taken by hand once, with the numbers recorded
in the triage doc; what is checked in is the shape.

The three cases that DO reach the network say so in their docstring, and are
marked ``live``.

Like AC-06a / AC-13a / AC-15, the hermetic cases import the REAL production
code (``api.services.capture.*``) through the ``src/backend`` root conftest.py
puts on ``sys.path`` — never a reimplementation of it.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# Imported directly — same import root e2e_app.py and AC-15 use.
from api.services.capture.discover import discover  # noqa: E402
from api.services.capture.network_capture import (  # noqa: E402
    CaptureResult,
    CapturedResponse,
)
from api.services.capture.request_selector import (  # noqa: E402
    CandidateAnswer,
    NoJobsFeedError,
    PaginationHint,
    RequestSelection,
)
from api.services.capture.sources import WellKnownEvidence  # noqa: E402
from api.services.harvest_meta import HarvestEvidence  # noqa: E402
from api.services.recipe_runner import RecipeExecutionError  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
_BACKEND = Path(__file__).resolve().parents[3] / "src" / "backend"
_REPO_ROOT = Path(__file__).resolve().parents[3]
# ``_capture_main`` is the capture SUBPROCESS entrypoint and the only module on this
# side that imports playwright. It is exercised in a child process for the same reason
# ``src/backend/api/tests/test_network_capture.py`` does: importing it in-process makes
# playwright resident, and the agent-free-replay import guard then raises everywhere.
_SUBPROC_ENV = {
    **os.environ,
    "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), str(_BACKEND)]),
}


def run_in_capture_child(code: str, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


# --------------------------------------------------------------------------
# Shared seams. discover() takes every collaborator as an injectable keyword,
# so a hermetic case runs the WHOLE ladder with no browser, no LLM, no network.
# --------------------------------------------------------------------------

def load_capture(name: str) -> CaptureResult:
    """One recorded response, exactly as the capture child would have handed it up."""
    raw = json.loads((FIXTURES / f"{name}.json").read_text())
    return CaptureResult(
        final_url=raw["url"],
        page_title=raw.get("page_title", ""),
        responses=[
            CapturedResponse(
                url=raw["url"],
                method=raw["method"],
                status=raw["status"],
                content_type=raw["content_type"],
                request_headers={},
                post_data=raw.get("post_data"),
                body=json.dumps(raw["body"]),
                truncated=False,
                body_bytes=len(json.dumps(raw["body"])),
            )
        ],
        board_links=tuple(raw.get("board_links", ())),
    )


def capturing(result: CaptureResult):
    async def _capture(url: str, **_: Any) -> CaptureResult:
        return result
    return _capture


async def no_well_known(_url: str) -> WellKnownEvidence:
    """No robots.txt, no sitemap. These cases are about the captured bytes."""
    return WellKnownEvidence()


def one_page_per_job() -> Any:
    """A job-link probe that answers 200 with a per-job body, without a network."""
    def _probe(url: str) -> tuple[int, str]:
        return 200, f"<html><body>{url}</body></html>" + "x" * (len(url) * 97)
    return _probe


def allow_all(_url: str) -> None:
    return None


def failing_replay(exc: Exception):
    async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
        raise exc
    return _replay


# --------------------------------------------------------------------------
# AC-19 — Oracle Fusion (JPMorgan CX_1001)
# --------------------------------------------------------------------------
# Two root causes met on this one board, and the second hid the first for a day:
#
#   G  the paging lives INSIDE a composite query value
#      (``finder=findReqs;siteNumber=CX_1001,limit=25,offset=25``), so no
#      pagination step was synthesised and the recipe read 25 of 7,181;
#   H  the refusal then reported "none of the N JSON request(s) this page made is
#      a list of job postings" — while the fan-out's own log line for the same run
#      read "6 of 6 candidate(s) answered yes".
#
# Clause (a) is this class. Clause (b) is TestAC19OracleFusionPagination below.

ORACLE_SELECTION = RequestSelection(
    chosen_request_index=0,
    records_path="items.0.requisitionList",
    field_map={
        "id": "Id",
        "title": "Title",
        "url": "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/{Id}",
        "location": "PrimaryLocation",
        "posted_at": "PostedDate",
        "description": "ShortDescriptionStr",
    },
    pagination=PaginationHint(style="offset", param="offset", page_size=25),
)


class TestAC19RefusalNamesTheRealStep:
    """AC-19 clause (a) — **the refusal must name the step that actually failed**.

    Hermetic, over the REAL Oracle page-1 bytes (``fixtures/oracle_fusion_jpmc.json``,
    captured live 2026-08-30: 25 records, ``TotalJobsCount = 7181``). No LLM and no
    network — the model's two answers are the seam, because what is under test is what
    we do with the SECOND one, not whether Haiku produces it.

    The shape of the bug, measured: round one, the fan-out answers yes; something we
    measured then kills the candidate; round two is re-asked WITH THAT FAILURE ATTACHED
    as feedback and reasonably says "no, none of these is a jobs feed" — and the old
    code answered the user with the filter-step sentence, blaming the board for our own
    verdict. Four unrelated boards wore that identical sentence for four different
    reasons.

    A live JPMorgan add is deliberately NOT the vehicle here: once clause (b) landed the
    board SUCCEEDS, so a live case could no longer observe this at all.
    """

    def test_ac19a_a_second_round_no_reports_what_we_measured(self) -> None:
        captured = load_capture("oracle_fusion_jpmc")
        rounds: list[str | None] = []

        async def _select(candidates: list[Any], *, feedback: str | None = None):
            rounds.append(feedback)
            if len(rounds) == 1:
                return [CandidateAnswer(
                    candidate_index=0, selection=ORACLE_SELECTION, confidence="high",
                )]
            raise NoJobsFeedError(
                "none of the 1 captured array(s) is a list of job postings"
            )

        outcome = asyncio.run(discover(
            "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs",
            capture=capturing(captured),
            select=_select,
            replay_http=failing_replay(RecipeExecutionError("HTTP 500 from the board")),
            replay_browser=failing_replay(RecipeExecutionError("Chromium crashed")),
            validate_url=allow_all,
            probe_link=one_page_per_job(),
            collect_sources=no_well_known,
        ))

        assert outcome.ok is False
        assert len(rounds) == 2 and rounds[1] is not None, (
            "AC-19a: round two must be re-asked WITH the measured failure attached — "
            "that is the premise the whole case rests on"
        )
        reason = outcome.refuse_reason or ""
        assert "is a list of job postings" not in reason, (
            "AC-19a: the model's second-round no is downstream of the failure WE fed "
            f"it, so reporting it as 'this page publishes no jobs feed' is false. "
            f"Got: {reason!r}"
        )
        assert "verifying we can read it" in reason, (
            f"AC-19a: the refusal must name the step that actually decided it; "
            f"got {reason!r}"
        )
        assert "HTTP 500 from the board" in reason or "Chromium crashed" in reason, (
            f"AC-19a: ...and carry the reason we measured, not a generic sentence; "
            f"got {reason!r}"
        )
        (failed_step,) = [
            s for s in (outcome.progress or {}).get("steps", [])
            if s["status"] == "failed"
        ]
        assert failed_step["key"] == "verify_read", (
            "AC-19a: the checklist ✕ has to move with the sentence, or the UI keeps "
            f"telling the old story; got {failed_step['key']!r}"
        )

    def test_ac19a_a_first_round_no_still_blames_no_one(self) -> None:
        """The control, and the reason the old sentence is kept rather than deleted.

        When NOTHING we tried ever failed — the model simply read the captured requests
        and saw no jobs in them — that sentence is literally true and is the most useful
        thing the product can say.
        """
        async def _select(candidates: list[Any], **_: Any):
            raise NoJobsFeedError(
                "none of the 1 captured array(s) is a list of job postings"
            )

        outcome = asyncio.run(discover(
            "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs",
            capture=capturing(load_capture("oracle_fusion_jpmc")),
            select=_select,
            replay_http=failing_replay(AssertionError("must not replay")),
            replay_browser=failing_replay(AssertionError("must not replay")),
            validate_url=allow_all,
            probe_link=one_page_per_job(),
            collect_sources=no_well_known,
        ))
        assert outcome.ok is False
        reason = outcome.refuse_reason or ""
        assert "finding the jobs feed" in reason and "is a list of job postings" in reason, (
            f"AC-19a control: with nothing measured, the honest sentence must survive; "
            f"got {reason!r}"
        )


# --------------------------------------------------------------------------
# AC-16 — Meta, and the content-type aperture
# --------------------------------------------------------------------------

class TestAC16ContentTypeAperture:
    """AC-16 — **the recorder keeps a response on its BODY, not on its content-type**.

    ``metacareers.com/jobsearch/`` answers its ``POST /graphql`` with
    ``content-type: text/html`` over 186,957 bytes of pure JSON holding 877 job
    records. The recorder's keep test was ``"json" in content-type``, so the capture
    came back with **0** responses and discovery told the user the page loads its jobs
    without any JSON request we could record. Measured again after the fix, same board,
    same day: **4** recorded, the jobs feed among them.

    Hermetic, over the REAL bytes that capture returned
    (``fixtures/meta_graphql_text_html.json``, 2026-08-30, trimmed to id/title/teams).
    A live Meta add is deliberately not the vehicle: see
    ``test_ac16_the_honest_end_state_is_named`` — the board does NOT reach ``tracking``,
    and a live case asserting that it does would be asserting a thing that is not true.
    """

    #: The body probe, run in the capture child. Answers "kept?" for a (ct, body) pair.
    _PROBE = (
        "import asyncio, json, sys\n"
        "from api.services.capture._capture_main import _record\n"
        "ct, body = json.loads(sys.argv[1])\n"
        "class R:\n"
        "    resource_type='xhr'; url='https://www.metacareers.com/graphql'\n"
        "    method='POST'; post_data=None; headers={}\n"
        "class Resp:\n"
        "    request=R(); status=200\n"
        "    def __init__(self, ct, body):\n"
        "        self.headers={'content-type': ct}; self._body=body\n"
        "    async def text(self):\n"
        "        return self._body\n"
        "limits={'max_responses':40,'max_body_bytes':10**7,'max_total_body_bytes':10**8}\n"
        "out=[]\n"
        "asyncio.run(_record(Resp(ct, body), out, limits))\n"
        "print(json.dumps(bool(out)))\n"
    )

    def test_ac16_a_json_body_under_a_text_html_header_is_recorded(self) -> None:
        raw = json.loads((FIXTURES / "meta_graphql_text_html.json").read_text())
        content_type, body = raw["content_type"], json.dumps(raw["body"])

        assert "json" not in content_type.lower(), (
            "AC-16: the whole case rests on Meta answering with a NON-json "
            f"content-type; the fixture says {content_type!r}"
        )
        kept = json.loads(run_in_capture_child(
            self._PROBE, json.dumps([content_type, body])
        ))
        assert kept is True, (
            f"AC-16: a {content_type!r} response whose body is a JSON document must be "
            "recorded — this is the 877-job Meta feed, and the old header test dropped "
            "it and then blamed the board for loading its jobs without any JSON request"
        )

    def test_ac16_a_body_the_prefilter_could_never_read_is_still_dropped(self) -> None:
        """The other half, and the reason this is a PROBE and not "keep everything".

        ``_MAX_RESPONSES`` is 40, spent in arrival order. One ``jobs.uber.com`` page
        load produced 42 ``text/x-component`` (React Server Components) fetches at
        ~163 KB each — on their own enough to fill the budget and evict a real feed
        that arrived later. Nothing downstream can read RSC:
        ``prefilter_candidates`` keeps only what ``json.loads`` accepts. Admitting it
        would cost boards to gain none.
        """
        for content_type, body in (
            ("text/x-component", '0:["$","div",null,{"children":[]}]'),
            ("text/html", "<!DOCTYPE html><html><body>jobs</body></html>"),
        ):
            kept = json.loads(run_in_capture_child(
                self._PROBE, json.dumps([content_type, body])
            ))
            assert kept is False, (
                f"AC-16: {content_type!r} carrying {body[:24]!r} is not a JSON document "
                "and cannot become a candidate — recording it only spends one of the 40 "
                "slots the jobs feed has to fit in"
            )

    def test_ac16_the_recorded_feed_becomes_a_877_record_candidate(self) -> None:
        """...and it survives all the way to the pre-filter, which is the point."""
        from api.services.capture.request_selector import prefilter_candidates

        captured = load_capture("meta_graphql_text_html")
        (candidate,) = prefilter_candidates(captured.responses)
        assert candidate.records_path == "data.job_search_with_featured_jobs_v2.all_jobs"
        assert candidate.record_count == 877, (
            f"AC-16: expected Meta's 877 postings, got {candidate.record_count}"
        )

    def test_ac16_the_honest_end_state_is_named(self) -> None:
        """**THE TRIAGE DOC IS WRONG HERE AND THIS CASE IS THE RECORD OF IT.**

        BOARD-FAILURE-TRIAGE.md says the aperture "recovers Meta outright — 877 jobs, a
        declared total, and the feed replays with bare ``httpx``". Measured on
        2026-08-30 with the fix in place, all three claims fail:

        * the ``POST`` body is ``application/x-www-form-urlencoded``
          (``av=0&__user=0&__a=1&…&doc_id=…``), and ``recipe_schema`` requires
          ``fetch.body`` to be an OBJECT because that is what the pagination merge
          writes into — so no recipe can be synthesised;
        * a bare-``httpx`` replay of that exact request answers **HTTP 400**, with the
          captured headers and without them alike (it is cookie-bound, like Sequoia);
        * the 877-record payload declares no total, and its records carry no URL and
          no date — only ``id``, ``title``, ``locations``, ``teams``, ``sub_teams``.

        So Meta is a REFUSAL, and what this case pins is that the refusal is now the
        TRUE one. Before the aperture fix it read "this page loaded its jobs without
        any JSON request we could record", which is what sent the last investigation
        after a capture bug that was only half the story.
        """
        selection = RequestSelection(
            chosen_request_index=0,
            records_path="data.job_search_with_featured_jobs_v2.all_jobs",
            field_map={
                "id": "id",
                "title": "title",
                "url": "https://www.metacareers.com/jobs/{id}/",
            },
            pagination=None,
        )

        async def _select(candidates: list[Any], **_: Any):
            return [CandidateAnswer(
                candidate_index=0, selection=selection, confidence="high",
            )]

        outcome = asyncio.run(discover(
            "https://www.metacareers.com/jobsearch/",
            capture=capturing(load_capture("meta_graphql_text_html")),
            select=_select,
            replay_http=failing_replay(AssertionError("must not reach a replay")),
            replay_browser=failing_replay(AssertionError("must not reach a replay")),
            validate_url=allow_all,
            probe_link=one_page_per_job(),
            collect_sources=no_well_known,
        ))
        reason = outcome.refuse_reason or ""
        assert outcome.ok is False, (
            "AC-16: if Meta ever starts succeeding, this case is the place to record "
            "why — do not delete it, rewrite it"
        )
        assert "without any JSON request we could record" not in reason, (
            f"AC-16: the capture DID record it; got {reason!r}"
        )
        assert "writing the replay recipe" in reason and "non-JSON body" in reason, (
            "AC-16: the refusal must name the form-encoded POST body — the step that "
            f"actually stops this board; got {reason!r}"
        )


# --------------------------------------------------------------------------
# AC-18 — IBM, and the per-element wrapper
# --------------------------------------------------------------------------

class TestAC18PerElementWrapper:
    """AC-18 — **a record nested one level inside each element must still be seen**.

    ``_walk_record_arrays`` scored only an array's DIRECT elements. Elasticsearch wraps
    each job in ``{_index, _id, _score, _source, sort}`` (job score **1**, under the
    floor) and Relay wraps it in ``{cursor, node}`` (score **0**), so the walk returned
    nothing and ``prefilter_candidates`` dropped the whole response with the tracking
    pings.

    Measured live 2026-08-30 on ``ibm.com/careers/search``: 38 responses recorded, the
    jobs feed among them at ``www-api.ibm.com/search/api/v2`` with
    ``hits.total.value = 1806`` and 30 records at ``hits.hits[]._source``. The
    pre-filter returned **two** candidates for that page, neither of them the feed, and
    the user was told none of the requests the page made is a list of job postings.
    After the fix the same bytes rank the jobs feed **first**.

    Hermetic and PARAMETRISED, because the point is the shape and not the employer:
    the Elasticsearch half is IBM's real payload
    (``fixtures/ibm_elasticsearch_hits.json``), the Relay half is the same defect in
    the ``edges[].node`` dialect that every GraphQL board speaks.
    """

    RELAY = {"data": {"jobSearch": {"edges": [
        {"cursor": f"cursor-{i}",
         "node": {"id": f"R{i}", "title": f"Engineer {i}",
                  "locationName": "Austin, TX", "absoluteUrl": f"https://b/{i}"}}
        for i in range(12)
    ]}}}

    def test_ac18_an_elasticsearch_hits_hits_source_body_is_a_candidate(self) -> None:
        from api.services.capture.request_selector import prefilter_candidates
        from api.services.recipe_schema import dig_records

        captured = load_capture("ibm_elasticsearch_hits")
        payload = json.loads(captured.responses[0].body)
        assert payload["hits"]["total"]["value"] == 1806, (
            "AC-18: the fixture must keep IBM's own declared total — it is what makes "
            "the 30-record page a sliver rather than the board"
        )
        wrapper_keys = sorted(payload["hits"]["hits"][0])
        assert wrapper_keys == ["_id", "_index", "_score", "_source", "sort"], (
            f"AC-18: the fixture stopped being the wrapper shape: {wrapper_keys}"
        )

        (candidate,) = prefilter_candidates(captured.responses)
        assert candidate.records_path == "hits.hits.*._source", (
            "AC-18: the records are one level inside each element and the walk must say "
            f"so; got {candidate.records_path!r}"
        )
        assert candidate.record_count == 30
        resolved = dig_records(candidate.payload, candidate.records_path)
        assert len(resolved) == 30 and all("title" in r for r in resolved), (
            "AC-18: the path must RESOLVE to the 30 job objects, not merely be emitted"
        )

    def test_ac18_a_relay_edges_node_body_is_a_candidate(self) -> None:
        """The same defect in the dialect every GraphQL board speaks."""
        from api.services.capture.network_capture import (
            CaptureResult,
            CapturedResponse,
        )
        from api.services.capture.request_selector import prefilter_candidates
        from api.services.recipe_schema import dig_records

        response = CapturedResponse(
            url="https://boards.example/graphql", method="POST", status=200,
            content_type="application/json", request_headers={}, post_data="{}",
            body=json.dumps(self.RELAY), truncated=False,
            body_bytes=len(json.dumps(self.RELAY)),
        )
        captured = CaptureResult(
            final_url="https://boards.example/careers", page_title="",
            responses=[response],
        )
        (candidate,) = prefilter_candidates(captured.responses)
        assert candidate.records_path == "data.jobSearch.edges.*.node"
        assert candidate.record_count == 12
        assert len(dig_records(candidate.payload, candidate.records_path)) == 12

    def test_ac18_the_unwrap_never_offers_a_duplicate_or_a_coin_flip(self) -> None:
        """The three ways this could go wrong, all measured or reasoned:

        * an array whose elements are ALREADY job-shaped needs no unwrapping, and
          offering both paths spends one of the model's six candidate slots twice;
        * a ONE-element array cannot be told apart from a record — on the live IBM
          capture that admitted an Adobe analytics blob with job score 8 that then
          outranked the 30-record jobs feed;
        * TWO dict-valued keys is a record with two nested objects, and unwrapping it
          would pick one of them arbitrarily.
        """
        from api.services.capture.network_capture import (
            CaptureResult,
            CapturedResponse,
        )
        from api.services.capture.request_selector import prefilter_candidates

        def _candidates(payload: Any) -> list[Any]:
            body = json.dumps(payload)
            return prefilter_candidates(CaptureResult(
                final_url="https://b.example/careers", page_title="",
                responses=[CapturedResponse(
                    url="https://b.example/api", method="GET", status=200,
                    content_type="application/json", request_headers={},
                    post_data=None, body=body, truncated=False, body_bytes=len(body),
                )],
            ).responses)

        already = {"jobs": [
            {"id": str(i), "title": f"E{i}", "meta": {"team": "x", "location": "y"}}
            for i in range(8)
        ]}
        (only,) = _candidates(already)
        assert only.records_path == "jobs", (
            f"AC-18: no second path to the same records; got {only.records_path!r}"
        )

        single = {"items": [{"meta": {
            "title": "t", "id": "1", "url": "u", "location": "l", "posted": "p",
        }}]}
        assert _candidates(single) == []

        ambiguous = {"rows": [
            {"node": {"title": f"E{i}", "id": str(i)},
             "extra": {"title": "no", "id": "no"}}
            for i in range(6)
        ]}
        assert _candidates(ambiguous) == []

    def test_ac18_the_honest_end_state_is_named(self) -> None:
        """**THE TRIAGE DOC OVERSTATES THIS ONE TOO.** It says the wrapper fix "recovers
        IBM — 1,806 jobs". Measured live with the fix in place, IBM gets FURTHER and
        still refuses, for a reason that has nothing to do with the walk: its captured
        request carries ``size: 30`` and **no** ``from``/``offset`` field at all, so no
        pagination step can be synthesised from it, and a 30-of-1,806 read is refused —
        correctly, and by the guard that exists to stop exactly that
        (``page_limit_reached``). Its records also carry no id: ``entitled`` is ``""``
        and the only identity is a ``jobId`` inside ``url``.

        What the fix bought is real and is what this case pins: the feed is now VISIBLE
        to the pipeline. What it did not buy is a stored recipe, and inventing a
        pagination parameter the board never sent is not a thing to do quietly.
        """
        from api.services.capture.request_selector import prefilter_candidates

        captured = load_capture("ibm_elasticsearch_hits")
        (candidate,) = prefilter_candidates(captured.responses)
        request_body = json.loads(candidate.post_data or "{}")
        assert request_body.get("size") == 30
        assert "from" not in request_body and "offset" not in request_body, (
            "AC-18: if IBM starts sending its page offset, this board becomes "
            "readable and this case should be rewritten rather than deleted"
        )
