"""``stop_on_empty_page`` — the sweep terminus for a board that serves a SHORT page
in the MIDDLE of its own result set. $0, fully offline.

THE MEASURED DEFECT (careers.oracle.com, siteNumber CX_45001, 2026-09-09). Oracle
Fusion Recruiting declines to serve exactly one record inside the 200-wide window that
starts at absolute index 2000: ``limit=200,offset=2000`` answers **199** rows while
``offset=2200`` still has 37 more, and ``offset=2237`` is the first empty one. The
sweep's stop rule is "a page shorter than ``page_size`` was the last page", so it halts
there with **2,199 of 2,236** rows and reports ``terminated_cleanly=True``,
``cap_hit=False`` — a partial read that calls itself complete.

That combination is not merely a short harvest. Replayed against the real gate, the
same evidence VERIFIES under ``self_consistent`` (``self_consistent_ok``) and under
``none`` (``history_delta_ok``), and a VERIFIED harvest is allowed to close — so the
37 jobs the sweep never fetched get closed, every night, by a recipe that looks like it
paginates correctly. It is the board-side twin of the wildcard-skip defect
``recipe_runner._dig_page_records`` already defends against on our side of the path.

Every test below pins one half of the fix:

* the flag is OPT-IN and its absence is byte-identical to the old behaviour (that is
  the whole safety argument, so it is asserted on the runner AND over the stored
  corpus, not just asserted in a comment);
* with the flag the sweep reads THROUGH the mid-board short page and stops on the empty
  one, still ``terminated_cleanly``;
* the page it read through is RECORDED (``HarvestEvidence.mid_sweep_short_page``) and
  routed to UNVERIFIED under every oracle kind — the flag recovers the rows after the
  gap, never the ones inside it, so it buys completeness of DISPLAY and never permission
  to close;
* a board that never serves an empty page runs out of pages and reports
  ``terminated_cleanly=False`` → UNVERIFIED → closes nothing, which is the safe
  direction for the one way this flag can go wrong.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from api.services.custom_baseline import Baseline
from api.services.harvest_verification import (
    UNVERIFIED,
    VERIFIED,
    GateResult,
    read_untruncated,
    verify_harvest,
)
from api.services.recipe_runner import run_recipe
from api.services.recipe_schema import RecipeError, validate_recipe

_FIXTURES = Path(__file__).parent / "fixtures" / "recipes"

# The board shape, in miniature. 25 addressable positions, the record at absolute index
# 10 unservable inside any bulk window that covers it, page_size 10 — so:
#   offset=0  -> 10 (full)      offset=10 -> 9 (SHORT, and NOT the end)
#   offset=20 -> 5              offset=30 -> 0 (the real end)
# Declared total 25 vs 24 actually servable mirrors Oracle's 2,239-vs-2,236 exactly.
_BOARD_POSITIONS = 25
_DROPPED_INDEX = 10
_PAGE_SIZE = 10
_SERVABLE = _BOARD_POSITIONS - 1


def _gap_board_handler(request: httpx.Request) -> httpx.Response:
    offset = int(request.url.params.get("offset", "0"))
    window = [
        i for i in range(offset, min(offset + _PAGE_SIZE, _BOARD_POSITIONS))
        if i != _DROPPED_INDEX
    ]
    return httpx.Response(200, json={
        "total": _BOARD_POSITIONS,
        "jobs": [
            {"id": str(i), "title": f"job {i}", "url": f"https://ex.com/j/{i}"}
            for i in window
        ],
    })


def _endless_board_handler(request: httpx.Request) -> httpx.Response:
    """A board that NEVER serves an empty page — the flag's own failure mode."""
    offset = int(request.url.params.get("offset", "0"))
    return httpx.Response(200, json={
        "total": 10_000,
        "jobs": [
            {"id": str(i), "title": f"job {i}", "url": f"https://ex.com/j/{i}"}
            for i in range(offset, offset + _PAGE_SIZE)
        ],
    })


def _script(
    *,
    stop_on_empty_page: bool | None = None,
    max_pages: int = 20,
    oracle: dict[str, Any] | None = None,
    style: str = "offset",
) -> dict[str, Any]:
    pagination: dict[str, Any] = {
        "op": "paginate_offset" if style == "offset" else "paginate_page",
        "param": "offset",
        "page_size": _PAGE_SIZE,
        "max_pages": max_pages,
    }
    if style == "page":
        pagination["start_page"] = 0
    if stop_on_empty_page is not None:
        pagination["stop_on_empty_page"] = stop_on_empty_page
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 1,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://ex.com/api", "headers": {}},
            pagination,
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
            {"op": "assert_page_advances"},
        ],
        "oracle": oracle or {"kind": "declared_probed", "total_path": "total"},
    }


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _verdict(kind: str, rows: list[dict], evidence, script: dict[str, Any]):
    n = len(rows)
    return verify_harvest(
        kind,
        GateResult(jobs=[], records_harvested=n, id_dedup_dropped=0, is_zero=n == 0),
        evidence,
        Baseline(float(n), 10, 0.5, tuple([n] * 10)),
        recipe=script,
    )


# --- the defect, locked in as the DEFAULT behaviour -------------------------
#
# This test asserts the BUG. It is here so the fix is provably opt-in: if a future edit
# makes empty-page paging the default, this fails and names the recipes it would change.

def test_without_the_flag_the_sweep_stops_at_the_mid_board_short_page() -> None:
    script = _script()
    with _client(_gap_board_handler) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) == 19                      # 10 + 9, and 5 more were still there
    assert evidence.pages_fetched == 2
    assert evidence.terminated_cleanly is True  # <- the lie the flag exists to fix
    assert evidence.cap_hit is False


@pytest.mark.parametrize("kind", ["self_consistent", "none"])
def test_the_short_read_would_VERIFY_and_therefore_close(kind: str) -> None:
    """Why the partial read is dangerous rather than merely incomplete.

    A VERIFIED harvest is allowed to close, so on either history-based oracle the jobs
    past the gap are closed by a sweep that never fetched them.
    """
    script = _script(oracle={"kind": kind})
    with _client(_gap_board_handler) as http:
        rows, evidence = run_recipe(script, http)
    assert _verdict(kind, rows, evidence, script).verdict == VERIFIED


# --- the fix ---------------------------------------------------------------

def test_with_the_flag_the_sweep_reads_through_the_gap_to_the_empty_page() -> None:
    script = _script(stop_on_empty_page=True)
    with _client(_gap_board_handler) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) == _SERVABLE               # 10 + 9 + 5, every record the board serves
    assert evidence.pages_fetched == 4          # the fourth is the empty terminus
    assert evidence.terminated_cleanly is True
    assert evidence.cap_hit is False
    assert evidence.page_advance_ok is True     # the empty page advances vacuously
    # ...and the run REPORTS the hole it read through. 24 of 25 is more rows than the
    # 19 the old terminus got, but it is still not the board.
    assert evidence.mid_sweep_short_page is True


def test_paginate_page_honours_the_flag_too() -> None:
    """Both offset styles run through the same sweep, so both must carry the flag."""
    script = _script(stop_on_empty_page=True, style="page")
    # ``paginate_page`` sends a page INDEX; the handler reads ``offset``, so scale the
    # board down to one page per index by making the cursor the offset directly.
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("offset", "0"))
        return _gap_board_handler(
            httpx.Request("GET", f"https://ex.com/api?offset={page * _PAGE_SIZE}")
        )

    with _client(handler) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) == _SERVABLE
    assert evidence.terminated_cleanly is True
    assert evidence.mid_sweep_short_page is True


# --- the hole the flag reads through is EVIDENCE, and it blocks the close ----
#
# Reading past a mid-board short page recovers the rows AFTER the gap. It cannot
# recover the rows INSIDE it — the cursor advances a full ``page_size`` over a window
# the board only partly served. Without recording that, the flag would swap a silently
# TRUNCATED read for a silently GAPPY one: still a wrong close, now with
# ``terminated_cleanly=True`` and ``cap_hit=False`` to recommend it.

@pytest.mark.parametrize("kind", ["self_consistent", "none", "declared_probed"])
def test_the_gappy_read_cannot_VERIFY_under_any_oracle(kind: str) -> None:
    """The fix, stated as the thing that actually matters: no close.

    All three oracle kinds, because the flag is admitted on any ``http_json`` recipe
    regardless of oracle. ``declared_probed`` is the one that matters most and the one
    a ``terminated_cleanly=False`` fix would have MISSED — it compares counts and never
    reads ``terminated_cleanly``, so a board whose declared total happened to equal its
    gappy harvest would still have verified.
    """
    script = _script(oracle={"kind": kind} if kind != "declared_probed" else None,
                     stop_on_empty_page=True)
    with _client(_gap_board_handler) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) == _SERVABLE and evidence.mid_sweep_short_page is True
    v = _verdict(kind, rows, evidence, script)
    assert v.verdict == UNVERIFIED and v.reason == "mid_sweep_short_page"


def test_a_gappy_read_is_not_comparable_either() -> None:
    """``read_untruncated`` gates the published-board SUGGESTION on "nothing says this
    read stopped early". A hole in the middle is not the end of the read, but it is the
    same defect for a title-set comparison: rows the public side has and this side does
    not, which silently misses a true match (and the comparison runs ONCE)."""
    script = _script(stop_on_empty_page=True, oracle={"kind": "self_consistent"})
    with _client(_gap_board_handler) as http:
        rows, evidence = run_recipe(script, http)
    assert read_untruncated(_verdict("self_consistent", rows, evidence, script),
                            evidence) is False


def test_the_NATURAL_short_last_page_is_not_a_hole() -> None:
    """The false positive this must not have.

    A board whose row count is not a multiple of ``page_size`` serves a short FINAL
    page and then an empty one. That is the terminus, not a gap, so the short page is
    only promoted to evidence once a LATER page comes back non-empty. 20 records at
    page_size 10 with nothing dropped: 10, 10, 0 — and 25 records: 10, 10, 5, 0.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        window = range(offset, min(offset + _PAGE_SIZE, _BOARD_POSITIONS))
        return httpx.Response(200, json={
            "total": _BOARD_POSITIONS,
            "jobs": [
                {"id": str(i), "title": f"job {i}", "url": f"https://ex.com/j/{i}"}
                for i in window
            ],
        })

    script = _script(stop_on_empty_page=True)
    with _client(handler) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) == _BOARD_POSITIONS        # the whole board, no gap
    assert evidence.mid_sweep_short_page is False
    assert evidence.terminated_cleanly is True
    v = _verdict("declared_probed", rows, evidence, script)
    assert v.verdict == VERIFIED and v.reason == "declared_exact"


def test_a_sweep_without_the_flag_never_sets_the_new_evidence_flag() -> None:
    """The default path is untouched: it stops AT the short page, so it can never have
    read through one. Pins that the new field cannot change any stored recipe's verdict."""
    script = _script()
    with _client(_gap_board_handler) as http:
        _, evidence = run_recipe(script, http)
    assert evidence.mid_sweep_short_page is False


def test_the_board_that_never_empties_reports_an_unfinished_sweep() -> None:
    """The flag's own failure mode, and it fails SAFE.

    Without an empty page the sweep exhausts ``max_pages`` — ``terminated_cleanly=False``
    → UNVERIFIED → the harvest shows its rows and closes nothing.
    """
    script = _script(stop_on_empty_page=True, max_pages=3,
                     oracle={"kind": "self_consistent"})
    with _client(_endless_board_handler) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) == 30
    assert evidence.terminated_cleanly is False
    v = _verdict("self_consistent", rows, evidence, script)
    assert v.verdict == UNVERIFIED and v.reason == "not_terminated_cleanly"


def test_a_declared_total_the_board_cannot_serve_stays_unverified() -> None:
    """Oracle's SECOND defect, unchanged by the first fix and deliberately so.

    The complete sweep reads 24 of a declared 25, so ``declared_probed``'s tolerance-0
    comparison could never pass anyway — the board shows all its jobs and closes none.
    That is the honest outcome, and relabelling the oracle to buy a close would be
    trading a measured disagreement for permission to make destructive writes.

    The verdict REASON is now the structural one rather than the arithmetic one, and
    that ordering is the point — see the test below.
    """
    script = _script(stop_on_empty_page=True)
    with _client(_gap_board_handler) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) == _SERVABLE and evidence.declared_total == _BOARD_POSITIONS
    assert len(rows) < evidence.declared_total          # count_mismatch would also hold
    v = _verdict("declared_probed", rows, evidence, script)
    assert v.verdict == UNVERIFIED and v.reason == "mid_sweep_short_page"


def test_the_gap_blocks_the_close_even_when_the_counts_AGREE() -> None:
    """FINDING 3 — "Oracle closes nothing" must be structural, not a coincidence.

    Today careers.oracle.com stays UNVERIFIED only because its declared
    ``TotalJobsCount`` does not equal what it serves. That is arithmetic the BOARD
    controls: fix its own count and the two numbers agree, ``declared_probed`` returns
    ``declared_exact``, and a read that structurally never sees the dropped record
    acquires permission to close.

    Here the board declares exactly what it serves (24) while still dropping index 10
    from the middle. The counts agree; the read still has a hole; the verdict must
    still refuse. Without ``mid_sweep_short_page`` this VERIFIES.
    """
    def handler(request: httpx.Request) -> httpx.Response:
        response = _gap_board_handler(request)
        body = response.json()
        body["total"] = _SERVABLE               # the board's own count, now honest
        return httpx.Response(200, json=body)

    script = _script(stop_on_empty_page=True)
    with _client(handler) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) == _SERVABLE == evidence.declared_total    # nothing to mismatch on
    assert evidence.terminated_cleanly is True and evidence.cap_hit is False
    v = _verdict("declared_probed", rows, evidence, script)
    assert v.verdict == UNVERIFIED and v.reason == "mid_sweep_short_page"


# --- the schema half -------------------------------------------------------

@pytest.mark.parametrize("style", ["offset", "page"])
@pytest.mark.parametrize("value", [True, False])
def test_the_flag_validates_as_a_bool_on_both_offset_styles(style: str, value: bool) -> None:
    assert validate_recipe(_script(stop_on_empty_page=value, style=style)) is not None


@pytest.mark.parametrize("value", ["true", 1, None, []])
def test_a_non_bool_flag_is_refused(value: Any) -> None:
    script = _script()
    script["steps"][1]["stop_on_empty_page"] = value
    with pytest.raises(RecipeError, match="stop_on_empty_page must be true or false"):
        validate_recipe(script)


def test_the_flag_is_refused_on_paginate_facet() -> None:
    """Not admitted there: the extra empty page is paid once PER FACET VALUE, and no
    measured board needs both. An unknown key must fail loudly, not be ignored."""
    script = _script()
    script["steps"][1] = {
        "op": "paginate_facet", "facet_param": "cat", "facet_values": ["a", "b"],
        "page_size": _PAGE_SIZE, "max_pages_per_facet": 5, "stop_on_empty_page": True,
    }
    with pytest.raises(RecipeError, match="unknown key"):
        validate_recipe(script)


def test_the_flag_is_refused_on_browser_fetch() -> None:
    """The browser tier's pagination loop lives in the Chromium subprocess and has its
    own short-page terminus. A browser_fetch script carrying this key would validate,
    store, and then sweep exactly as if it did not — silently doing less than it says."""
    script = _script(stop_on_empty_page=True, max_pages=5)
    script["transport"] = "browser_fetch"
    script["origin_url"] = "https://ex.com/careers"
    with pytest.raises(RecipeError, match="does not implement 'stop_on_empty_page'"):
        validate_recipe(script)


# --- the proof that no STORED recipe can change behaviour ------------------

@pytest.mark.parametrize("path", sorted(_FIXTURES.glob("*.json")), ids=lambda p: p.name)
def test_no_pre_existing_corpus_recipe_carries_the_flag(path: Path) -> None:
    """The safety argument, asserted rather than described.

    ``_reject_unknown_keys`` refused this key on write AND on every nightly read for the
    whole life of the vocabulary, so no stored ``company_scripts.script`` can carry it;
    the runner therefore takes ``stop_on_empty=False`` for every one of them, which is
    the same line of code it ran before. The corpus is the evidence: these are the real
    captured boards, and none of them names the key at any depth.
    """
    script = json.loads(path.read_text())
    assert "stop_on_empty_page" not in json.dumps(script)
    validate_recipe(script)
