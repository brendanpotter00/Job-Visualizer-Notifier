"""E7 Stagehand pivot — the browser-agent runner. $0: the subprocess is MOCKED.

The runner is the agent-free parent of the Stagehand subprocess. These tests inject a
fake report (no Browserbase, no LLM, no real DNS) and prove the load-bearing safety:
the ≤3-page bound is re-asserted, a DOM row-index id RAISES, duplicate cross-page ids
RAISE, and a clean 2-page report yields the right ``page_advance_ok`` /
``terminated_cleanly`` evidence.
"""

from __future__ import annotations

from typing import Any

import pytest

from api.services.browser_agent.runner import run_browser_agent
from api.services.recipe_runner import RecipeExecutionError

pytestmark = pytest.mark.asyncio


def _script(*, expected_min_jobs: int = 1, max_pages: int = 3, id_field: str = "url") -> dict:
    return {
        "script_version": 2,
        "transport": "browser_agent",
        "entry_url": "https://board.example/jobs",
        "extract": {
            "instruction": "extract jobs",
            "schema": {"type": "object", "properties": {"jobs": {"type": "array"}}},
        },
        "pagination": {"next_action": "click next", "max_pages": max_pages},
        "id_field": id_field,
        "expected_min_jobs": expected_min_jobs,
        "oracle": {"kind": "self_consistent"},
    }


def _noop_validate(url: str) -> None:
    return None


def _fake_subprocess(report: dict[str, Any]):
    async def _run(script: dict[str, Any]) -> dict[str, Any]:
        return report
    return _run


async def _run(report: dict, *, script: dict | None = None, validate_url=_noop_validate):
    return await run_browser_agent(
        script or _script(),
        run_subprocess=_fake_subprocess(report),
        validate_url=validate_url,
    )


# --- clean 2-page → correct evidence -----------------------------------------

async def test_clean_two_page_report_yields_page_advance_and_clean_terminus() -> None:
    report = {
        "rows": [
            {"title": "A", "location": "X", "url": "/jobs/a"},
            {"title": "B", "location": "Y", "url": "/jobs/b"},
            {"title": "C", "location": "Z", "url": "/jobs/c"},
            {"title": "D", "location": "W", "url": "/jobs/d"},
        ],
        "pages_fetched": 2,
        "terminated_cleanly": True,
        "page_id_sets": [["/jobs/a", "/jobs/b"], ["/jobs/c", "/jobs/d"]],
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    rows, evidence = await _run(report)
    assert len(rows) == 4
    assert {r["id"] for r in rows} == {"/jobs/a", "/jobs/b", "/jobs/c", "/jobs/d"}
    assert evidence.page_advance_ok is True
    assert evidence.terminated_cleanly is True
    assert evidence.cap_hit is False
    assert evidence.declared_total is None
    assert evidence.pages_fetched == 2


async def test_single_page_has_no_page_advance_signal() -> None:
    report = {
        "rows": [
            {"title": "A", "url": "/jobs/a"},
            {"title": "B", "url": "/jobs/b"},
        ],
        "pages_fetched": 1,
        "terminated_cleanly": True,
        "page_id_sets": [["/jobs/a", "/jobs/b"]],
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    rows, evidence = await _run(report)
    assert len(rows) == 2
    assert evidence.page_advance_ok is None   # vacuous — no page N to compare
    assert evidence.terminated_cleanly is True


async def test_unclean_terminus_is_carried_through() -> None:
    """A paginated run that used its whole budget with a still-full final page is
    reported ``terminated_cleanly=False`` — the runner carries it so the gate lands
    UNVERIFIED (never closes)."""
    report = {
        "rows": [{"title": f"J{i}", "url": f"/jobs/{i}"} for i in range(6)],
        "pages_fetched": 3,
        "terminated_cleanly": False,
        "page_id_sets": [["/jobs/0", "/jobs/1"], ["/jobs/2", "/jobs/3"], ["/jobs/4", "/jobs/5"]],
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    _rows, evidence = await _run(report)
    assert evidence.terminated_cleanly is False
    assert evidence.page_advance_ok is True


# --- THE CRUX: stable-id proof (§3.4) ----------------------------------------

async def test_row_index_id_raises() -> None:
    """A ``"0-650"``-style DOM row index must RAISE → FAILED, never reach the close
    path (the whole point of the stable-id proof)."""
    report = {
        "rows": [
            {"title": "Sales Development Representative", "url": "0-650"},
            {"title": "Account Executive", "url": "0-661"},
        ],
        "pages_fetched": 1,
        "terminated_cleanly": True,
        "page_id_sets": [["0-650", "0-661"]],
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    with pytest.raises(RecipeExecutionError, match="row-index"):
        await _run(report)


async def test_short_bare_integer_id_raises() -> None:
    """amazon's ``"3363"`` (a short bare integer / DOM offset) is not a stable id."""
    report = {
        "rows": [{"title": "Software Engineer", "url": "3363"}],
        "pages_fetched": 1,
        "terminated_cleanly": True,
        "page_id_sets": [["3363"]],
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    with pytest.raises(RecipeExecutionError, match="row-index"):
        await _run(report)


async def test_duplicate_cross_page_ids_raise() -> None:
    """The amazon failure: page 2 re-served page 1's ids → collapses dedupe → RAISE."""
    report = {
        "rows": [
            {"title": "A", "url": "/jobs/a"},
            {"title": "B", "url": "/jobs/b"},
            {"title": "A2", "url": "/jobs/a"},   # same id on page 2
            {"title": "C", "url": "/jobs/c"},
        ],
        "pages_fetched": 2,
        "terminated_cleanly": True,
        "page_id_sets": [["/jobs/a", "/jobs/b"], ["/jobs/a", "/jobs/c"]],
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    with pytest.raises(RecipeExecutionError, match="repeat across pages"):
        await _run(report)


async def test_real_hrefs_and_long_req_ids_pass() -> None:
    report = {
        "rows": [
            {"title": "A", "url": "/companies/acme/jobs/security-engineer"},
            {"title": "B", "req_id": "4512340"},
        ],
        "pages_fetched": 1,
        "terminated_cleanly": True,
        "page_id_sets": [["/companies/acme/jobs/security-engineer", "4512340"]],
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    # id_field points at 'url' for row A; row B has no url → dropped by the mapper.
    rows, _evidence = await _run(report)
    assert [r["id"] for r in rows] == ["/companies/acme/jobs/security-engineer"]


# --- THE BOUND (§4) ----------------------------------------------------------

async def test_over_budget_page_count_raises() -> None:
    report = {
        "rows": [{"title": f"J{i}", "url": f"/jobs/{i}"} for i in range(8)],
        "pages_fetched": 4,                                   # > max_pages (3)
        "terminated_cleanly": True,
        "page_id_sets": [
            ["/jobs/0", "/jobs/1"], ["/jobs/2", "/jobs/3"],
            ["/jobs/4", "/jobs/5"], ["/jobs/6", "/jobs/7"],
        ],
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    with pytest.raises(RecipeExecutionError, match="bound is 3"):
        await _run(report)


async def test_page_id_sets_length_must_match_pages_fetched() -> None:
    report = {
        "rows": [{"title": "A", "url": "/jobs/a"}],
        "pages_fetched": 2,
        "terminated_cleanly": True,
        "page_id_sets": [["/jobs/a"]],   # only 1 set for 2 pages
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    with pytest.raises(RecipeExecutionError, match="inconsistent"):
        await _run(report)


# --- zero / below-floor / SSRF -----------------------------------------------

async def test_zero_rows_raise() -> None:
    report = {
        "rows": [],
        "pages_fetched": 1,
        "terminated_cleanly": True,
        "page_id_sets": [[]],
        "expected_min_jobs": 1,
        "observed_actions": [],
        "max_pages": 3,
    }
    with pytest.raises(RecipeExecutionError, match="zero usable rows"):
        await _run(report)


async def test_below_expected_min_jobs_raises() -> None:
    report = {
        "rows": [{"title": "A", "url": "/jobs/a"}, {"title": "B", "url": "/jobs/b"}],
        "pages_fetched": 1,
        "terminated_cleanly": True,
        "page_id_sets": [["/jobs/a", "/jobs/b"]],
        "expected_min_jobs": 5,
        "observed_actions": [],
        "max_pages": 3,
    }
    with pytest.raises(RecipeExecutionError, match="below expected_min_jobs"):
        await _run(report, script=_script(expected_min_jobs=5))


async def test_entry_url_ssrf_guard_raises_before_subprocess() -> None:
    """The entry-URL guard runs BEFORE the subprocess — a blocked host never spawns."""
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
