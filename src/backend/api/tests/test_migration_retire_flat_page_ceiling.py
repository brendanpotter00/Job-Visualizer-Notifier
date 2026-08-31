"""Migration ``9d2f7ae5c1b4`` — retiring the flat 100-page http ceiling on stored recipes.

Same shape as ``test_migration_capture_page_budget.py`` (the revision it chains off):
the rewrite is a pure function over rows, so it is tested as one — no DB fixture, no
Alembic runner. What is locked here is the decision table, which is the part that
silently rots. The end-to-end behaviour was exercised by hand against a throwaway
Postgres seeded with a real discovered recipe.

The property that matters: a recipe stored under the retired ceiling comes out able to
reach its whole board, and NOTHING else moves — not a budget discovery derived below
the ceiling, not a ``browser_fetch`` row (whose own ceiling did not move, and which
``validate_recipe`` REJECTS above it on every nightly read).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from api.services.recipe_runner import MAX_HARVEST_RECORDS
from api.services.recipe_schema import BROWSER_FETCH_MAX_PAGES

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions"
    / "20260824_120000_9d2f7ae5c1b4_retire_the_flat_http_page_ceiling_on_capture_recipes.py"
)


def _module() -> Any:
    """Load the revision file by path — its name is not an importable identifier."""
    spec = importlib.util.spec_from_file_location("_mig_9d2f7ae5c1b4", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _script(*, page_size: int = 10, max_pages: int = 100, op: str = "paginate_offset") -> dict:
    return {
        "script_version": 1,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://x.example/j", "headers": {}},
            {"op": op, "param": "offset", "page_size": page_size, "max_pages": max_pages},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "t", "url": "u"}},
        ],
    }


def _paginate(row: dict) -> dict:
    steps = json.loads(row["script"])["steps"]
    (step,) = [s for s in steps if s["op"].startswith("paginate_")]
    return step


def test_the_retired_ceiling_is_raised_through_the_recipes_own_page_size() -> None:
    """The whole point: the new ceiling is denominated in JOBS, so a 10-per-page board
    (Microsoft's Eightfold shape — 2,111 jobs, hard-wired to 10) gets five times the
    pages a 50-per-page board gets, and both end up able to read 50,000 jobs.

    Under the retired ceiling both got 100 pages, which is 1,000 jobs of the first board
    and 5,000 of the second — the same constant meaning two different things.
    """
    changed = _module()._rewrite([
        ("u-ten", "http_json", _script(page_size=10)),
        ("u-fifty", "http_json", _script(page_size=50)),
        ("u-html", "http_html", _script(page_size=10)),
    ])
    by_id = {row["company_id"]: row for row in changed}

    assert _paginate(by_id["u-ten"])["max_pages"] == MAX_HARVEST_RECORDS // 10
    assert _paginate(by_id["u-fifty"])["max_pages"] == MAX_HARVEST_RECORDS // 50
    assert _paginate(by_id["u-html"])["max_pages"] == MAX_HARVEST_RECORDS // 10


def test_browser_fetch_rows_are_left_alone() -> None:
    """The browser tier's ceiling did NOT move — a page there holds a Chromium renderer,
    not an httpx socket — and ``validate_recipe`` rejects a browser recipe above it on
    every read. A transport-blind rewrite would store rows that FAIL every night.
    """
    assert BROWSER_FETCH_MAX_PAGES < 100
    assert _module()._rewrite([("u-browser", "browser_fetch", _script())]) == []


def test_a_derived_budget_below_the_ceiling_does_not_move() -> None:
    """A budget a discovery run computed from the board's own total was never truncated.
    Rewriting it would replace a number derived from bytes with a blanket one."""
    assert _module()._rewrite([
        ("u-derived", "http_json", _script(max_pages=52)),
        ("u-tiny", "http_json", _script(max_pages=1)),
    ]) == []


def test_a_budget_is_never_lowered() -> None:
    """A 500-per-page recipe derives 100 from the job ceiling — which is the number
    being retired. Writing it back would be a no-op that reads like a repair, and on any
    page size above 500 it would be an actual TRUNCATION performed by the fix."""
    assert _module()._rewrite([("u-huge-page", "http_json", _script(page_size=500))]) == []
    assert _module()._rewrite([("u-huger", "http_json", _script(page_size=1000))]) == []


def test_facet_pagination_is_left_alone() -> None:
    """``paginate_facet``'s budget is PER FACET and multiplies by the facet count, so the
    same number does not mean the same thing — 5,000 pages per facet over 38 facets is
    190,000 requests, not 5,000."""
    facet = {
        "script_version": 1,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://x.example/j", "headers": {}},
            {"op": "paginate_facet", "facet_param": "c", "facet_values": ["a"],
             "page_size": 10, "max_pages_per_facet": 100},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "t", "url": "u"}},
        ],
    }
    assert _module()._rewrite([("u-facet", "http_json", facet)]) == []


def test_a_shape_the_migration_does_not_understand_is_a_no_op() -> None:
    """A Phase-1 ``ats_client`` script has no steps list at all. The migration runs on
    every ``company_scripts`` row, so an unfamiliar shape must be a no-op, never a crash
    that wedges the whole upgrade."""
    assert _module()._rewrite([
        ("u-ats", "ats_client", {"kind": "ats_client", "provider": "greenhouse"}),
        ("u-null", "http_json", None),
        ("u-nosteps", "http_json", {"script_version": 1, "steps": "not-a-list"}),
        ("u-nopagesize", "http_json", _script(page_size=0)),
    ]) == []
