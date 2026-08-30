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
import re
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

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


# --------------------------------------------------------------------------
# AC-19 clause (b) — Oracle Fusion pages inside its composite finder
# --------------------------------------------------------------------------

#: The board's own later pages append this to the finder value. The capture records
#: several of them: the page scrolls itself during the observation window.
_OFFSET_TOKEN = "%2Coffset%3D25"


class TestAC19OracleFusionPagination:
    """AC-19 clause (b) — **the paging parameter the model cannot see**.

    Oracle Fusion Recruiting carries its whole search in ONE query value::

        finder=findReqs;siteNumber=CX_1001,facetsList=...,limit=25,sortBy=...,offset=75

    The selector prompt asks for "an obvious paging parameter you can see in its URL",
    and measured 2026-08-30 the real Haiku call answered ``pagination: null`` on **6 of
    6** candidates — correctly by its own instructions, because ``offset`` is not a
    parameter of that URL, it is a token inside one. No paging step was synthesised, the
    recipe reached 25 records against a self-declared 7,181, and the coverage floor
    refused the board at 0.35%.

    Measured again after the fix, same board, same day, through the real ``discover()``
    and then the real ``run_recipe``:

    * ``ok=True``, ``transport=http_json``, ``oracle=declared_probed`` on
      ``items.0.TotalJobsCount``, ``paginate_offset`` on ``offset`` at 25/page,
      ``max_pages=290``;
    * the harvest read **7,124 distinct rows over 285 pages in 195s** against a declared
      **7,181** — ``cap_hit=False``, ``terminated_cleanly=True``, ``page_advance_ok=True``.

    Hermetic, over the real page-1 bytes. A live JPMorgan case would spend a 195s,
    7,124-row harvest on every suite run, and what is under test is a URL shape a
    fixture holds perfectly still.
    """

    def _paged_capture(self) -> CaptureResult:
        """The captured feed at the offset the board's own scrolling reached."""
        captured = load_capture("oracle_fusion_jpmc")
        (response,) = captured.responses
        return replace(
            captured, responses=[replace(response, url=response.url + _OFFSET_TOKEN)]
        )

    def test_ac19b_offset_is_not_a_query_parameter_of_this_board(self) -> None:
        """The premise, asserted rather than assumed."""
        raw = json.loads((FIXTURES / "oracle_fusion_jpmc.json").read_text())["url"]
        names = {name for name, _ in parse_qsl(urlsplit(raw + _OFFSET_TOKEN).query)}
        assert names == {"onlyData", "expand", "finder"}, (
            f"AC-19b: this case is about a token INSIDE a value; got {names}"
        )
        assert "offset=25" in dict(
            parse_qsl(urlsplit(raw + _OFFSET_TOKEN).query)
        )["finder"]

    def test_ac19b_the_recipe_pages_and_carries_the_declared_total(self) -> None:
        from api.services.recipe_runner import map_records

        captured = self._paged_capture()
        payload = json.loads(captured.responses[0].body)
        records = payload["items"][0]["requisitionList"]

        async def _select(candidates: list[Any], **_: Any):
            # ``pagination=None`` is EXACTLY what the real model returns for this board.
            return [CandidateAnswer(
                candidate_index=0,
                selection=replace(ORACLE_SELECTION, pagination=None),
                confidence="high",
            )]

        async def _replay(script: dict[str, Any]) -> tuple[list[dict], HarvestEvidence]:
            (extract,) = [
                st for st in script["steps"] if st["op"] == "extract_json_path"
            ]
            rows = map_records(records, extract["fields"], script.get("base_url", ""))
            return rows, HarvestEvidence(
                declared_total=7181, cap_hit=False, terminated_cleanly=True,
                page_advance_ok=True, pages_fetched=2, transport_ok=True,
            )

        outcome = asyncio.run(discover(
            "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs",
            capture=capturing(captured),
            select=_select,
            replay_http=_replay,
            replay_browser=failing_replay(AssertionError("http_json must be enough")),
            validate_url=allow_all,
            probe_link=one_page_per_job(),
            collect_sources=no_well_known,
        ))

        assert outcome.ok is True, (
            "AC-19b: the coverage floor refused this board at 25-against-7,181 before "
            f"the paging landed; it must pass now. Got: {outcome.refuse_reason!r}"
        )
        assert outcome.script is not None
        (paginate,) = [
            st for st in outcome.script["steps"] if st["op"].startswith("paginate_")
        ]
        assert (paginate["op"], paginate["param"]) == ("paginate_offset", "offset")
        assert outcome.script["oracle"] == {
            "kind": "declared_probed", "total_path": "items.0.TotalJobsCount",
        }, (
            "AC-19b: Oracle wraps its whole envelope in a one-element list, so the "
            "total-path walk has to enter it; without that the board stores "
            f"self_consistent and makes no completeness claim. Got "
            f"{outcome.script['oracle']!r}"
        )
        assert paginate["max_pages"] >= 7181 // paginate["page_size"], (
            "AC-19b: the stored budget must be able to REACH the end of the board, or "
            "the completeness gate can never answer anything but UNVERIFIED"
        )

    def test_ac19b_the_cursor_is_written_inside_the_finder_not_beside_it(self) -> None:
        """The half that decides whether the sweep is 285 pages or page one, 285 times.

        ``httpx.URL.copy_merge_params`` appends ``&offset=0``, which this board does not
        read. Both transports have to agree — that parity is pinned in
        ``src/backend/api/tests/test_browser_fetch_runner.py``.
        """
        from api.services.recipe_runner import merge_query_params

        raw = json.loads((FIXTURES / "oracle_fusion_jpmc.json").read_text())["url"]
        merged = merge_query_params(raw + _OFFSET_TOKEN, {"offset": 0})
        finder = merged.params["finder"]
        assert "offset=0" in finder and "offset=25" not in finder
        assert "offset" not in merged.params, (
            "AC-19b: a top-level `&offset=` beside the finder is what the board ignores"
        )
        assert "sortBy=POSTING_DATES_DESC" in finder and "limit=25" in finder, (
            "AC-19b: nothing else in the composite value may move"
        )

    def test_ac19b_check_13_can_see_the_hidden_page_index_too(self) -> None:
        """The never-wrong-close half, and it is not a bonus — the fix makes it
        reachable. Check 13a refuses a stored recipe that carries a page index with
        nothing advancing it; scanning only real query parameters, it saw NEITHER the
        index nor the page size on a request that carries both. A composite board with
        no declared total to contradict it could then read 25 of 7,181 and be free to
        VERIFY and close the rest.
        """
        from api.services.harvest_verification import page_shape_refusal

        raw = json.loads((FIXTURES / "oracle_fusion_jpmc.json").read_text())["url"]
        unswept = {"steps": [{"op": "fetch", "url": raw + _OFFSET_TOKEN}]}
        assert page_shape_refusal(unswept, 25) == "page_param_unpaginated"
        swept = {"steps": unswept["steps"] + [
            {"op": "paginate_offset", "param": "offset", "page_size": 25,
             "max_pages": 290},
        ]}
        assert page_shape_refusal(swept, 25) is None, (
            "AC-19b: a recipe that DOES sweep is judged by checks 5 and 6, which are "
            "strictly stronger — firing 13a here would refuse every healthy board"
        )


# --------------------------------------------------------------------------
# AC-17 — the anchor directory, and one character of trailing slash
# --------------------------------------------------------------------------

class TestAC17AnchorTrailingSlash:
    """AC-17 — **a trailing slash in a job URL must never split the group**.

    ``sources._anchor_rows`` grouped anchors by ``path.rsplit("/", 1)[0] + "/"``, which
    treats a trailing slash as a directory level. A board whose job hrefs end in one puts
    every posting in its OWN group of one, every group falls under
    ``_MIN_HTML_RECORDS = 8``, and ``anchor_candidate`` returns ``None`` for a board
    whose entire job list is sitting in the served document.

    Hermetic, over the REAL served document of ``jobs.uber.com/en/jobs/``
    (``fixtures/uber_jobs_document.html`` — every ``<a>`` of the live 280,667-byte page,
    verbatim, captured 2026-08-30). A/B'd live on that one character the same day:
    **before, 10 groups of 1 and no candidate; after, one group of 10 and an
    ``extract_css`` candidate.**

    **A correction to BOARD-FAILURE-TRIAGE.md.** It names Citadel as the board this
    recovers "outright", on the strength of ten
    ``<a class="careers-listing-card" href="…/careers/details/<slug>/">`` in the served
    document. That did not reproduce: measured 2026-08-30 through the real
    ``capture_board``, ``citadel.com/careers/open-opportunities/`` answers the host-pin
    fetch with a 5,939-byte Cloudflare interstitial (``<title>Just a moment...</title>``)
    and its RENDERED DOM carries 102 links, **none** of them under ``/careers/details/``.
    The Citadel shape is kept below as a shape — it is the exact one this fixes — but
    Uber is the board with the evidence, so Uber is the fixture.
    """

    def _rows(self, markup: str, host: str) -> dict:
        from api.services.capture.sources import _anchor_rows
        return _anchor_rows(markup, host)

    def test_ac17_uber_job_anchors_group_under_one_directory(self) -> None:
        from api.services.capture.sources import _MIN_HTML_RECORDS, anchor_candidate

        markup = (FIXTURES / "uber_jobs_document.html").read_text()
        assert 'href="/en/jobs/300235/"' in markup, (
            "AC-17: the fixture must keep the TRAILING SLASH — it is the defect"
        )
        rows = self._rows(markup, "jobs.uber.com")
        jobs = [d for d in rows if d.startswith("/en/jobs/")]
        assert jobs == ["/en/jobs/"], (
            f"AC-17: ten postings under one directory, not N singletons; got {jobs}"
        )
        assert len(rows["/en/jobs/"]) >= _MIN_HTML_RECORDS, (
            f"AC-17: the group has to clear _MIN_HTML_RECORDS={_MIN_HTML_RECORDS} or "
            f"anchor_candidate discards it; got {len(rows['/en/jobs/'])}"
        )

        captured = CaptureResult(
            final_url="https://jobs.uber.com/en/jobs/", page_title="", responses=[],
            server_html=markup, server_html_url="https://jobs.uber.com/en/jobs/",
        )
        candidate = anchor_candidate(captured, "jobs.uber.com")
        assert candidate is not None, (
            "AC-17: this board renders its whole job list into the served document and "
            "must produce an extract_css candidate"
        )
        assert candidate.html.selector == 'a[href*="/en/jobs/"]'
        assert candidate.records[0]["id"].endswith("/"), (
            "AC-17: the href is stored VERBATIM — _run_css stores exactly this string as "
            "the row id, so trimming it here would break the match-the-capture check"
        )

    def test_ac17_the_citadel_shape_groups_too(self) -> None:
        """The shape BOARD-FAILURE-TRIAGE.md names, kept as a shape.

        WordPress cards at ``https://www.citadel.com/careers/details/<slug>/``. The live
        board no longer serves these to us (see the class docstring), so this is the
        pattern under test rather than the employer.
        """
        cards = "".join(
            f'<a class="careers-listing-card" '
            f'href="https://www.citadel.com/careers/details/role-{i}/">Role {i}</a>'
            for i in range(10)
        )
        rows = self._rows(f"<html><body>{cards}</body></html>", "www.citadel.com")
        assert list(rows) == ["/careers/details/"]
        assert len(rows["/careers/details/"]) == 10

    def test_ac17_the_no_slash_control_is_unchanged(self) -> None:
        """Y Combinator is the natural control and the reason this path worked at all:
        its job hrefs carry NO trailing slash. Measured live 2026-08-30 —
        ``ycombinator.com/companies/raindrop/jobs`` still groups 9 anchors under
        ``/companies/raindrop/jobs/``. That grouping must not move."""
        plain = "".join(
            f'<a href="/companies/raindrop/jobs/{i}-engineer">Engineer {i}</a>'
            for i in range(9)
        )
        rows = self._rows(f"<html><body>{plain}</body></html>", "www.ycombinator.com")
        assert list(rows) == ["/companies/raindrop/jobs/"]
        assert len(rows["/companies/raindrop/jobs/"]) == 9

    def test_ac17_a_link_to_the_directory_itself_is_still_not_a_group(self) -> None:
        """``/jobs/`` strips to ``/jobs``, whose directory is the root — which the length
        guard drops. Stripping the slash must not promote a nav link into a group."""
        markup = (
            '<html><body><a href="/jobs/">All jobs</a>'
            '<a href="/careers/">Careers</a></body></html>'
        )
        assert self._rows(markup, "b.example") == {}


# --------------------------------------------------------------------------
# AC-20 — Nintendo, and the link rung 1 never fetched
# --------------------------------------------------------------------------

#: The same UA the capture browser sends — a job page fetched with httpx's default UA
#: is a different request, and some boards answer it differently.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_LINK_CHECK_TIMEOUT_S = 30.0


class TestAC20PublishedJobLink:
    """AC-20 — **a published link still has to name a page**.

    Rung 1 of the job-link ladder takes the board's own ``field_map["url"]`` VERBATIM
    and fetches nothing, on the theory that a path the board published must be right.
    **13 of the 19 corpus boards take rung 1** (JOB-LINK-RULE.md §"The corpus"), so it is
    the highest-exposure rung there is.

    Greenhouse EMBEDS disprove the theory. ``careers.nintendo.com/jobs/`` publishes
    ``absolute_url = "https://careers.nintendo.com/?gh_jid=4295098009"`` — distinct per
    job, link-shaped, HTTP 200 — and every test rung 1 applied passed it. Measured live
    2026-08-30 (and re-measured by ``test_ac20_the_two_links_differ_live`` below): that
    URL serves **64,408 bytes of the LISTING page**, titled *"Careers at Nintendo - Join
    Our Team"*, with the job's own title nowhere in it. The working link is
    ``/jobs/4295098009/`` — 82,962 bytes, titled *"Brand Ambassador [Part-Time] -
    Peoria, IL - Nintendo Careers"*.

    The guard is the one the codebase already states on the DERIVATION side
    (``repair_url_template``: *"the QUERY IS DROPPED … a board that keys its jobs by
    query parameter alone cannot be derived"*) and had no counterpart on the PUBLISHED
    side: a rendered URL whose path is ``/`` puts all its identity in the query string.
    It is free on the boards that are right — measured against the live payloads the
    same day, **10 of 10 publicly fetchable corpus boards still take rung 1** and only
    Nintendo's embed moves.

    The shared helper ``test_discovery._assert_two_job_links_resolve`` now applies the
    same path check to every stored row on AC-04 and AC-05, which is where the triage
    doc asked for it. It does NOT apply the title check there: measured the same day,
    Atlassian's published iCIMS link renders the posting in an IFRAME, so the fetched
    document carries the job's title **not at all** — asserting it would fail a board
    that works.
    """

    def _records(self) -> list[dict]:
        raw = json.loads((FIXTURES / "nintendo_greenhouse_embed.json").read_text())
        return raw["records"]

    def test_ac20_the_embed_link_is_declined_by_rung_one_and_rung_two(self) -> None:
        from api.services.capture.request_selector import (
            is_published_url_spec,
            published_url_fields,
        )

        records = self._records()
        assert len(records) > 8
        assert all(
            r["absolute_url"].startswith("https://careers.nintendo.com/?gh_jid=")
            for r in records
        ), "AC-20: the fixture must keep the path-less embed shape"

        assert is_published_url_spec(records, "absolute_url") is False, (
            "AC-20: rung 1 keeps this VERBATIM and fetches nothing, so declining it "
            "here is the only thing between the user and a link to the listing page"
        )
        assert "absolute_url" not in published_url_fields(records), (
            "AC-20: rung 2 hands back the board's own published field when the model "
            "invented one — the same string must not come back through that door"
        )

    def test_ac20_a_path_bearing_greenhouse_board_is_untouched(self) -> None:
        """The non-regression, and it is the whole risk of the guard. Every other
        Greenhouse board in the corpus publishes a path-bearing ``absolute_url``."""
        from api.services.capture.request_selector import is_published_url_spec

        for template in (
            "https://boards.greenhouse.io/spacex/jobs/86639380{i}?gh_jid=86639380{i}",
            "https://job-boards.greenhouse.io/anthropic/jobs/44612{i}",
            "https://careers.roblox.com/jobs/73500{i}?gh_jid=73500{i}",
            "https://stripe.com/jobs/search?gh_jid=75327{i}",
        ):
            records = [
                {"id": i, "title": f"Engineer {i}", "absolute_url": template.format(i=i)}
                for i in range(3)
            ]
            assert is_published_url_spec(records, "absolute_url") is True, template

    @pytest.mark.live
    def test_ac20_the_two_links_differ_live(self) -> None:
        """**The assertion that would have caught this**, against the live board.

        Two fetches, no LLM and no discovery: the published embed URL must NOT carry the
        job's own title, and the derived ``/jobs/{id}/`` URL must. If Nintendo ever fixes
        its embed, the first half fails and this case should be rewritten rather than
        deleted — the guard would then be costing us nothing and protecting nothing.
        """
        import httpx

        records = self._records()[:2]
        for record in records:
            title = record["title"].lower()
            pages = {}
            for label, url in (
                ("published", record["absolute_url"]),
                ("derived", f"https://careers.nintendo.com/jobs/{record['id']}/"),
            ):
                try:
                    resp = httpx.get(
                        url, timeout=_LINK_CHECK_TIMEOUT_S, follow_redirects=True,
                        headers={"User-Agent": _BROWSER_UA},
                    )
                except httpx.HTTPError as exc:
                    pytest.skip(f"BLOCKED: careers.nintendo.com unreachable ({exc!r})")
                assert resp.status_code < 400, (
                    f"AC-20: {label} link {url} answers HTTP {resp.status_code}"
                )
                stripped = re.sub(
                    r"(?is)<script.*?</script>|<style.*?</style>", " ", resp.text
                )
                stripped = " ".join(re.sub(r"<[^>]+>", " ", stripped).split()).lower()
                pages[label] = (len(resp.text), title in stripped)

            (_pub_bytes, pub_has_title) = pages["published"]
            (_der_bytes, der_has_title) = pages["derived"]
            assert der_has_title, (
                f"AC-20: the DERIVED link /jobs/{record['id']}/ must serve this job's "
                f"own page — {record['title']!r} was not on it. If this fails the guard "
                f"is sending boards somewhere worse than where they were."
            )
            assert not pub_has_title, (
                f"AC-20: the PUBLISHED embed link {record['absolute_url']} now carries "
                f"{record['title']!r}. Nintendo may have fixed its embed; re-measure "
                f"before assuming the guard is still earning its place."
            )
        print(
            f"AC-20: published vs derived — {records[0]['absolute_url']} carries no "
            f"job title; /jobs/{records[0]['id']}/ does"
        )
