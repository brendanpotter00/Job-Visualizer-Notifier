"""SOURCES 2 AND 6 — the DOCUMENT as evidence, and the split that keeps it honest. $0.

Two documents are already in the capture child's memory and both were being thrown
away: the SERVED navigation body (``_install_host_pin`` fetches it to read ``Location``
and discards it) and the RENDERED DOM (``page.content()``, already read for the link
harvest). Carrying them costs zero network requests and zero wall clock.

THE SPLIT IS THE POINT AND IT IS NOT OPTIONAL. ``recipe_runner.extract_embedded_island``
replays by issuing ONE plain GET and running a CSS selector over the SERVER's bytes. So
an island in the served document is a RECORD source; an island that only exists after
hydration is reproducible by no transport we admit, and may contribute ids and nothing
else. ``EvidenceSource.replay_transport`` is where that is stated once — a source no
transport can replay can never become a stored recipe, whatever anything says about it.

The rendered DOM stays a LINK and COUNTING source for the same reason, and making it a
record source is out of scope by name: ``browser_fetch`` hard-requires
``extract_json_path`` (``recipe_schema.py:741``) and every DOM transport is a rejected
Phase-4 capability (``:86``), so there is no transport that replays markup.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from api.services.capture.network_capture import CaptureResult, _islands_from_report
from api.services.capture.sources import (
    _MAX_HTML_CANDIDATES,
    _MIN_HTML_RECORDS,
    anchor_candidate,
    document_candidates,
    island_candidates,
    island_sources,
)

_BOARD = "https://boards.example.com/careers"
_HOST = "boards.example.com"

_BACKEND = Path(__file__).resolve().parents[2]          # src/backend
_REPO_ROOT = _BACKEND.parents[1]
_SUBPROC_ENV = {**os.environ,
                "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), str(_BACKEND)])}


def _json_islands(markup: str, scope: str, budget: dict[str, int]) -> list[dict[str, Any]]:
    """Call the CHILD's island extractor in a SUBPROCESS.

    ``_capture_main`` is the one module on the discovery side that imports
    ``playwright``, and importing it here would make playwright resident in the pytest
    process — every later ``assert_no_agent_imports()`` in the suite would then raise,
    which is exactly what the agent-free boundary is for. Same convention as
    ``test_network_capture``'s child tests.
    """
    code = (
        "import json, sys\n"
        "from api.services.capture._capture_main import _json_islands\n"
        "markup, scope, budget = json.loads(sys.stdin.read())\n"
        "out = _json_islands(markup, scope, budget)\n"
        "print(json.dumps([out, budget]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], input=json.dumps([markup, scope, budget]),
        cwd=str(_BACKEND), env=_SUBPROC_ENV,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    islands, spent = json.loads(result.stdout.strip().splitlines()[-1])
    budget.update(spent)
    return islands


def _jobs(n: int, prefix: str = "J") -> list[dict[str, str]]:
    return [
        {"id": f"{prefix}{i}", "title": f"Engineer {i}", "team": "Platform"}
        for i in range(n)
    ]


def _next_data(records: list[dict[str, str]]) -> str:
    blob = json.dumps({"props": {"pageProps": {"jobs": records}}})
    return f'<script id="__NEXT_DATA__" type="application/json">{blob}</script>'


def _served_document(*, islands: str = "", anchors: int = 0, path: str = "/jobs/") -> str:
    links = "".join(
        f'<a href="{path}{i}-engineer">Staff Engineer {i}</a>' for i in range(anchors)
    )
    return (
        "<!doctype html><html><head><title>Careers</title></head>"
        f"<body><nav><a href=\"/about\">About</a></nav>{links}{islands}</body></html>"
    )


def _captured(**kwargs: Any) -> CaptureResult:
    base: dict[str, Any] = {
        "final_url": _BOARD,
        "page_title": "Careers",
        "responses": [],
        "server_html": "",
        "server_html_url": _BOARD,
        "islands": (),
    }
    base.update(kwargs)
    return CaptureResult(**base)


# --- the child's extraction --------------------------------------------------

def test_the_child_carries_a_next_data_island_with_the_selector_that_refinds_it() -> None:
    """``script#__NEXT_DATA__`` is the selector ``_run_embedded_island`` will pass to
    ``soup.select_one`` on every nightly replay. Carrying the blob without the selector
    would be carrying evidence nobody can act on."""
    markup = _served_document(islands=_next_data(_jobs(3)))
    islands = _json_islands(markup, "served", {"islands": 0})
    assert len(islands) == 1
    assert islands[0]["selector"] == "script#__NEXT_DATA__"
    assert islands[0]["scope"] == "served"
    assert json.loads(islands[0]["body"])["props"]["pageProps"]["jobs"][0]["id"] == "J0"


def test_an_ambiguous_selector_means_the_island_is_not_carried_at_all() -> None:
    """``_run_embedded_island`` replays with ``select_one``. A selector matching two
    blocks would silently read whichever one comes first in tomorrow's markup, so a
    document with two untyped-and-unnamed ld+json blocks yields NO island rather than a
    coin flip."""
    twice = (
        '<script type="application/ld+json">{"a": [1,2]}</script>'
        '<script type="application/ld+json">{"b": [3,4]}</script>'
    )
    assert _json_islands(twice, "served", {"islands": 0}) == []

    # ...and one of them alone IS unambiguous.
    once = '<script type="application/ld+json">{"a": [1,2]}</script>'
    assert len(_json_islands(once, "served", {"islands": 0})) == 1


def test_a_script_that_is_not_json_is_not_an_island() -> None:
    """The parse is a FILTER, not a judgement — the same class of thing as the
    resource-type test in ``_record``. It exists so two megabytes of minified JavaScript
    never go down the pipe."""
    js = '<script id="__NEXT_DATA__" type="application/json">window.x = 1;</script>'
    assert _json_islands(js, "served", {"islands": 0}) == []


def test_the_island_budget_is_shared_across_both_documents() -> None:
    """ONE budget, spent by the served document first and folded into the child's own
    aggregate body ceiling — so raising the per-island cap cannot raise the worst case,
    and the rendered document cannot double it."""
    heavy = "".join(
        f'<script id="blob{i}" type="application/json">'
        + json.dumps({"jobs": _jobs(2), "pad": "x" * 1_900_000})
        + "</script>"
        for i in range(4)
    )
    budget = {"islands": 0}
    served = _json_islands(heavy, "served", budget)
    assert len(served) == 3                     # 3 x 1.9 MB fits under 6 MB, a 4th does not
    assert _json_islands(heavy, "rendered", budget) == []


def test_at_most_eight_islands_per_document() -> None:
    markup = "".join(
        f'<script id="blob{i}" type="application/json">{{"jobs": [1]}}</script>'
        for i in range(20)
    )
    assert len(_json_islands(markup, "served", {"islands": 0})) == 8


# --- the parent's tolerance --------------------------------------------------

def test_a_report_from_an_older_child_degrades_to_todays_behaviour() -> None:
    """The same tolerance ``board_links``/``board_scripts`` already have. A rolling
    deploy, or a replayed fixture, must not fail a capture that recorded the whole
    board."""
    assert _islands_from_report(None) == ()
    assert _islands_from_report([]) == ()
    assert CaptureResult(final_url=_BOARD, page_title="", responses=[]).islands == ()
    assert CaptureResult(final_url=_BOARD, page_title="", responses=[]).server_html == ""


def test_an_island_with_an_unknown_scope_is_dropped_not_defaulted() -> None:
    """THE ONE PLACE A DEFAULT WOULD BE A BUG. Defaulting an unreadable scope to
    ``served`` would let an island no transport can replay become a stored recipe, which
    is the single thing the split exists to prevent."""
    rows = _islands_from_report([
        {"scope": "hydrated", "selector": "script#x", "body": "{}"},
        {"scope": "served", "selector": "script#y", "body": "{}"},
    ])
    assert [r["scope"] for r in rows] == ["served"]


# --- source 2a: the served island as a candidate -----------------------------

def test_a_served_island_becomes_an_http_html_candidate() -> None:
    captured = _captured(islands=_islands_from_report(
        _json_islands(_next_data(_jobs(12)), "served", {"islands": 0})
    ))
    (candidate,) = island_candidates(captured, _BOARD)
    assert candidate.html is not None
    assert candidate.html.op == "extract_embedded_island"
    assert candidate.html.selector == "script#__NEXT_DATA__"
    assert candidate.html.document_url == _BOARD
    assert candidate.records_path == "props.pageProps.jobs"
    assert candidate.record_count == 12


def test_a_rendered_only_island_never_becomes_a_candidate() -> None:
    """MUTATION TARGET. It is job-shaped, it parses, it has a selector — and no
    transport we admit can reproduce it, because the served document does not contain
    it. It contributes ids and nothing else."""
    captured = _captured(islands=_islands_from_report(
        _json_islands(_next_data(_jobs(12)), "rendered", {"islands": 0})
    ))
    assert island_candidates(captured, _BOARD) == []
    (source,) = island_sources(captured)
    assert source.replay_transport is None
    assert "records" not in source.contributions
    assert source.contributions == frozenset({"id_set"})


def test_a_served_island_declares_the_transport_that_can_replay_it() -> None:
    captured = _captured(islands=_islands_from_report(
        _json_islands(_next_data(_jobs(3)), "served", {"islands": 0})
    ))
    (source,) = island_sources(captured)
    assert source.replay_transport == "http_html"
    assert "records" in source.contributions


# --- source 6: the served document's own anchors -----------------------------

def test_the_served_documents_job_anchors_become_an_extract_css_candidate() -> None:
    """Wholly deterministic — no model is asked anything, because an ``<a href>`` carries
    exactly a link and a label. The rows are built with the same rule ``_run_css``
    replays with, so the candidate's ids and the replay's ids are equal by construction
    rather than by hope."""
    captured = _captured(server_html=_served_document(anchors=20))
    candidate = anchor_candidate(captured, _HOST)
    assert candidate is not None
    assert candidate.html is not None
    assert candidate.html.op == "extract_css"
    assert candidate.html.selector == 'a[href*="/jobs/"]'
    assert candidate.html.field_selectors == {
        "id": ".@href", "title": ".@text", "url": ".@href",
    }
    assert candidate.record_count == 20
    assert candidate.records[0] == {
        "id": "/jobs/0-engineer", "title": "Staff Engineer 0", "url": "/jobs/0-engineer",
    }


def test_a_pages_own_navigation_is_not_a_job_list() -> None:
    """The false positive this derivation is bounded twice against: enough anchors, AND
    a shared path that reads as a jobs path. A twenty-item ``/company/`` menu is a menu."""
    captured = _captured(server_html=_served_document(anchors=20, path="/company/"))
    assert anchor_candidate(captured, _HOST) is None


def test_too_few_anchors_is_not_a_job_list_either() -> None:
    captured = _captured(server_html=_served_document(anchors=_MIN_HTML_RECORDS - 1))
    assert anchor_candidate(captured, _HOST) is None


def test_anchors_pointing_off_the_board_host_are_ignored() -> None:
    """A stored ``extract_css`` recipe fetches ONE document — the board's. Counting an
    off-host link as one of its jobs would be counting somebody else's board."""
    elsewhere = "".join(
        f'<a href="https://other.example.net/jobs/{i}">Engineer {i}</a>'
        for i in range(20)
    )
    captured = _captured(server_html=f"<html><body>{elsewhere}</body></html>")
    assert anchor_candidate(captured, _HOST) is None


def test_a_client_rendered_board_publishes_no_anchor_candidate() -> None:
    """Measured on atlassian.com/company/careers/all-jobs: the SERVED document contains
    ``careers/details/`` zero times and the rendered DOM contains it 233 times. Source 6
    finds nothing there, silently, which is exactly right — that board's jobs come from
    an XHR and its candidate is unaffected."""
    captured = _captured(server_html=_served_document(anchors=0))
    assert anchor_candidate(captured, _HOST) is None


# --- the two together --------------------------------------------------------

def test_document_candidates_are_capped_and_islands_rank_first() -> None:
    """A board that publishes a real jobs XHR must never have its answer crowded out, so
    these are capped and the caller appends them AFTER the pre-filter's own list."""
    markup = _served_document(anchors=20, islands=_next_data(_jobs(30)))
    captured = _captured(
        server_html=markup,
        islands=_islands_from_report(_json_islands(markup, "served", {"islands": 0})),
    )
    derived = document_candidates(captured, _HOST, _BOARD)
    assert len(derived) <= _MAX_HTML_CANDIDATES
    assert derived[0].html is not None and derived[0].html.op == "extract_embedded_island"


def test_a_capture_with_no_document_at_all_derives_nothing() -> None:
    assert document_candidates(_captured(), _HOST, _BOARD) == []
