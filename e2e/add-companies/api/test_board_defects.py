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
