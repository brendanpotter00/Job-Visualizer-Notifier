"""E7 Stagehand pivot — the browser-agent runner. $0: the subprocess is MOCKED.

The runner is the agent-free parent of the Stagehand subprocess. These tests inject a
fake ``page_rows`` report (no Browserbase, no LLM, no real DNS) and prove: the
≤3-page bound is re-asserted; the id-field-aware stable-id proof RAISES on element-refs
/ non-URL urls; duplicate cross-page ids RAISE; a clean 2-page report yields the right
evidence; AND id-field SELECTION picks url → title → title|location → REFUSE (so
href-less boards like YC raindrop work off distinct titles).
"""

from __future__ import annotations

from typing import Any

import pytest

from api.services.browser_agent.runner import (
    run_browser_agent,
    run_browser_agent_selecting,
    select_id_field,
)
from api.services.recipe_runner import RecipeExecutionError

pytestmark = pytest.mark.asyncio

_ENTRY_URL = "https://board.example/jobs"


def _script(*, expected_min_jobs: int = 1, max_pages: int = 3, id_field: str = "url") -> dict:
    return {
        "script_version": 2,
        "transport": "browser_agent",
        "entry_url": _ENTRY_URL,
        "extract": {
            "instruction": "extract jobs",
            "schema": {"type": "object", "properties": {"jobs": {"type": "array"}}},
        },
        "pagination": {"next_action": "click next", "max_pages": max_pages},
        "id_field": id_field,
        "expected_min_jobs": expected_min_jobs,
        "oracle": {"kind": "self_consistent"},
    }


def _report(pages: list[list[dict]], *, terminated_cleanly: bool = True,
            pages_fetched: int | None = None, max_pages: int = 3) -> dict:
    return {
        "page_rows": pages,
        "pages_fetched": len(pages) if pages_fetched is None else pages_fetched,
        "terminated_cleanly": terminated_cleanly,
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": max_pages,
    }


def _noop_validate(url: str) -> None:
    return None


def _fake_subprocess(report: dict[str, Any]):
    async def _run(script: dict[str, Any]) -> dict[str, Any]:
        return report
    return _run


async def _replay(report: dict, *, script: dict | None = None):
    return await run_browser_agent(
        script or _script(), run_subprocess=_fake_subprocess(report), validate_url=_noop_validate
    )


async def _select(report: dict, *, script: dict | None = None):
    return await run_browser_agent_selecting(
        script or _script(), run_subprocess=_fake_subprocess(report), validate_url=_noop_validate
    )


# --- REPLAY with a stored url id_field ---------------------------------------

async def test_clean_two_page_report_yields_page_advance_and_clean_terminus() -> None:
    report = _report([
        [{"title": "A", "url": "/jobs/a"}, {"title": "B", "url": "/jobs/b"}],
        [{"title": "C", "url": "/jobs/c"}, {"title": "D", "url": "/jobs/d"}],
    ])
    rows, evidence = await _replay(report)
    assert {r["id"] for r in rows} == {"/jobs/a", "/jobs/b", "/jobs/c", "/jobs/d"}
    assert evidence.page_advance_ok is True
    assert evidence.terminated_cleanly is True
    assert evidence.cap_hit is False
    assert evidence.declared_total is None
    assert evidence.pages_fetched == 2


async def test_single_page_has_no_page_advance_signal() -> None:
    report = _report([[{"title": "A", "url": "/jobs/a"}, {"title": "B", "url": "/jobs/b"}]])
    rows, evidence = await _replay(report)
    assert len(rows) == 2
    assert evidence.page_advance_ok is None
    assert evidence.terminated_cleanly is True


async def test_unclean_terminus_is_carried_through() -> None:
    report = _report(
        [[{"title": f"J{i}", "url": f"/jobs/{i}"} for i in range(0, 2)],
         [{"title": f"J{i}", "url": f"/jobs/{i}"} for i in range(2, 4)],
         [{"title": f"J{i}", "url": f"/jobs/{i}"} for i in range(4, 6)]],
        terminated_cleanly=False,
    )
    _rows, evidence = await _replay(report)
    assert evidence.terminated_cleanly is False
    assert evidence.page_advance_ok is True


# --- REPLAY: the stable-id proof (§3.4), id-field-aware -----------------------

async def test_replay_url_id_that_is_element_ref_raises() -> None:
    report = _report([[{"title": "SDR", "url": "0-650"}, {"title": "AE", "url": "0-661"}]])
    with pytest.raises(RecipeExecutionError, match="is not stable"):
        await _replay(report)


async def test_replay_url_id_that_is_short_int_raises() -> None:
    report = _report([[{"title": "Software Engineer", "url": "3363"}]])
    with pytest.raises(RecipeExecutionError, match="is not stable"):
        await _replay(report)


async def test_replay_url_id_that_is_churning_slug_raises() -> None:
    for churning_id in ("job-1", "item-0", "row-5", "sess_9f3ab21c"):
        report = _report([[{"title": "Engineer", "url": churning_id}]])
        with pytest.raises(RecipeExecutionError, match="is not stable"):
            await _replay(report)


async def test_replay_duplicate_cross_page_ids_raise() -> None:
    report = _report([
        [{"title": "A", "url": "/jobs/a"}, {"title": "B", "url": "/jobs/b"}],
        [{"title": "A2", "url": "/jobs/a"}, {"title": "C", "url": "/jobs/c"}],
    ])
    with pytest.raises(RecipeExecutionError, match="repeat across pages"):
        await _replay(report)


async def test_replay_url_and_path_ids_pass() -> None:
    report = _report([[
        {"title": "A", "url": "/companies/acme/jobs/security-engineer"},
        {"title": "B", "url": "https://acme.example/careers/ml-engineer-42"},
    ]])
    rows, _evidence = await _replay(report)
    assert {r["id"] for r in rows} == {
        "/companies/acme/jobs/security-engineer",
        "https://acme.example/careers/ml-engineer-42",
    }


async def test_replay_with_stored_title_id_field() -> None:
    """A board discovered as id_field='title' replays keyed on the title; the element-ref
    urls are sanitized to the board entry_url (never stored as a job link)."""
    script = _script(id_field="title")
    report = _report([[
        {"title": "Security Engineer", "location": "SF", "url": "0-650"},
        {"title": "ML Engineer", "location": "SF", "url": "0-732"},
    ]])
    rows, _evidence = await _replay(report, script=script)
    assert {r["id"] for r in rows} == {"Security Engineer", "ML Engineer"}
    assert all(r["url"] == _ENTRY_URL for r in rows)   # href-less → entry_url fallback


async def test_replay_element_ref_title_raises() -> None:
    script = _script(id_field="title")
    report = _report([[{"title": "0-650", "url": "0-650"}]])
    with pytest.raises(RecipeExecutionError, match="is not stable"):
        await _replay(report, script=script)


# --- THE BOUND (§4) ----------------------------------------------------------

async def test_over_budget_page_count_raises() -> None:
    report = _report(
        [[{"title": f"J{i}", "url": f"/jobs/{i}"}] for i in range(4)],  # 4 pages > cap 3
    )
    with pytest.raises(RecipeExecutionError, match="bound is 3"):
        await _replay(report)


async def test_page_rows_length_must_match_pages_fetched() -> None:
    report = _report([[{"title": "A", "url": "/jobs/a"}]], pages_fetched=2)
    with pytest.raises(RecipeExecutionError, match="inconsistent"):
        await _replay(report)


# --- zero / below-floor / SSRF -----------------------------------------------

async def test_zero_rows_raise() -> None:
    report = _report([[]])
    with pytest.raises(RecipeExecutionError, match="zero usable rows"):
        await _replay(report)


async def test_below_expected_min_jobs_raises() -> None:
    report = _report([[{"title": "A", "url": "/jobs/a"}, {"title": "B", "url": "/jobs/b"}]])
    with pytest.raises(RecipeExecutionError, match="below expected_min_jobs"):
        await _replay(report, script=_script(expected_min_jobs=5))


async def test_entry_url_ssrf_guard_raises_before_subprocess() -> None:
    spawned = {"count": 0}

    async def _must_not_spawn(script):
        spawned["count"] += 1
        return {}

    def _blocking_validator(url: str) -> None:
        raise RecipeExecutionError(f"blocked {url} (SSRF guard: link_local)")

    with pytest.raises(RecipeExecutionError, match="SSRF guard"):
        await run_browser_agent(
            _script(), run_subprocess=_must_not_spawn, validate_url=_blocking_validator
        )
    assert spawned["count"] == 0


# --- id-field SELECTION (discovery) ------------------------------------------

def _raindrop_page() -> list[dict]:
    titles = [
        "Sales Development Representative", "Account Executive",
        "Forward Deployed Engineer", "Founding Recruiter", "Security Engineer",
        "Developer Experience Engineer", "ML Engineer", "Backend Engineer",
        "Product Engineer",
    ]
    # href-less rows: Stagehand returns element-refs for url.
    return [{"title": t, "location": "SF", "url": f"0-{i}"} for i, t in enumerate(titles)]


async def test_selecting_falls_back_to_title_for_hrefless_board() -> None:
    """YC raindrop: element-ref urls, 9 DISTINCT titles → id_field='title', accepted."""
    rows, evidence, id_field = await _select(_report([_raindrop_page()]))
    assert id_field == "title"
    assert len(rows) == 9
    assert all(r["id"] == r["title"] for r in rows)
    assert all(r["url"] == _ENTRY_URL for r in rows)   # href-less → entry_url fallback
    assert evidence.declared_total is None


async def test_selecting_prefers_url_when_real_hrefs_present() -> None:
    rows, _evidence, id_field = await _select(
        _report([[{"title": "A", "url": "/jobs/a"}, {"title": "B", "url": "/jobs/b"}]])
    )
    assert id_field == "url"
    assert {r["id"] for r in rows} == {"/jobs/a", "/jobs/b"}


async def test_selecting_falls_back_to_title_location_on_duplicate_titles() -> None:
    rows, _evidence, id_field = await _select(_report([[
        {"title": "Engineer", "location": "SF", "url": "0-1"},
        {"title": "Engineer", "location": "NYC", "url": "0-2"},
    ]]))
    assert id_field == "title|location"
    assert {r["id"] for r in rows} == {"Engineer|SF", "Engineer|NYC"}


async def test_selecting_refuses_when_no_field_is_distinct() -> None:
    """Element-ref urls AND a non-distinct title+location → no stable id → REFUSE."""
    with pytest.raises(RecipeExecutionError, match="no stable id field"):
        await _select(_report([[
            {"title": "Engineer", "location": "SF", "url": "0-1"},
            {"title": "Engineer", "location": "SF", "url": "0-2"},
        ]]))


async def test_selecting_refuses_element_ref_titles() -> None:
    with pytest.raises(RecipeExecutionError, match="no stable id field"):
        await _select(_report([[
            {"title": "0-650", "location": "SF", "url": "0-1"},
            {"title": "0-661", "location": "NYC", "url": "0-2"},
        ]]))


# --- select_id_field as a pure function --------------------------------------

def test_select_id_field_priority_pure() -> None:
    assert select_id_field([{"title": "A", "url": "/a"}, {"title": "B", "url": "/b"}]) == "url"
    assert select_id_field([
        {"title": "Alpha", "url": "0-1"}, {"title": "Bravo", "url": "0-2"},
    ]) == "title"
    assert select_id_field([
        {"title": "Eng", "location": "SF", "url": "0-1"},
        {"title": "Eng", "location": "NY", "url": "0-2"},
    ]) == "title|location"
    with pytest.raises(RecipeExecutionError, match="no stable id field"):
        select_id_field([
            {"title": "Eng", "location": "SF", "url": "0-1"},
            {"title": "Eng", "location": "SF", "url": "0-2"},
        ])
