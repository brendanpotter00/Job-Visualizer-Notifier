"""Migration ``c4f0a91b2d73`` — the legacy flat page budget on stored capture recipes.

The rewrite is a pure function over rows, so it is tested as one: no DB fixture, no
Alembic runner, and the properties that matter are all about WHICH rows move and to
WHAT. The end-to-end behaviour (upgrade + downgrade + validate-on-read against a real
Postgres) was exercised by hand on a throwaway DB seeded from the dev rows; what this
locks is the decision table, which is the part that silently rots.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from api.services.recipe_schema import BROWSER_FETCH_MAX_PAGES

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions"
    / "20260820_190000_c4f0a91b2d73_raise_legacy_capture_recipe_page_budgets.py"
)


def _module() -> Any:
    """Load the revision file by path — its name is not an importable identifier."""
    spec = importlib.util.spec_from_file_location("_mig_c4f0a91b2d73", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _script(op: str = "paginate_offset", max_pages: int = 10) -> dict:
    return {
        "script_version": 1,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://x.example/j", "headers": {}},
            {"op": op, "param": "offset", "page_size": 10, "max_pages": max_pages},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "t", "url": "u"}},
        ],
    }


def _paginate(row: dict) -> dict:
    steps = json.loads(row["script"])["steps"]
    (step,) = [s for s in steps if s["op"].startswith("paginate_")]
    return step


def test_the_legacy_flat_budget_is_raised_per_transport() -> None:
    """The whole point of the migration: a recipe stored by the old code read ten pages
    of whatever the careers page's own layout asked for — 97 jobs of amazon.jobs — and
    could therefore never be VERIFIED. Raising it needs no acceptance proof because the
    budget is a CEILING: the sweep stops on the first short page, so a board smaller
    than the new number pays exactly nothing for it.

    The ceiling is per TRANSPORT, and getting that wrong is not cosmetic: a
    ``browser_fetch`` recipe over 25 pages is REJECTED by ``validate_recipe`` on every
    nightly read, so a transport-blind migration would store rows that FAIL forever.
    """
    changed = _module()._rewrite([
        ("u-http", "http_json", _script()),
        ("u-browser", "browser_fetch", _script()),
    ])
    by_id = {row["company_id"]: row for row in changed}
    assert _paginate(by_id["u-http"])["max_pages"] == 100
    assert _paginate(by_id["u-browser"])["max_pages"] == BROWSER_FETCH_MAX_PAGES


def test_only_the_legacy_flat_value_moves() -> None:
    """A budget a LATER discovery run derived is not a legacy budget, and rewriting it
    would replace a number computed from the board's own total with a blanket one."""
    changed = _module()._rewrite([
        ("u-derived", "http_json", _script(max_pages=52)),
        ("u-ceiling", "http_json", _script(max_pages=100)),
    ])
    assert changed == []


def test_facet_pagination_is_left_alone() -> None:
    """``paginate_facet``'s budget is PER FACET and multiplies by the facet count, so
    the same number does not mean the same thing — 100 pages per facet over 38 facets
    is 3,800 requests, not 100."""
    facet = {
        "script_version": 1,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://x.example/j", "headers": {}},
            {"op": "paginate_facet", "facet_param": "c", "facet_values": ["a"],
             "page_size": 10, "max_pages_per_facet": 10},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "t", "url": "u"}},
        ],
    }
    assert _module()._rewrite([("u-facet", "http_json", facet)]) == []


def test_a_row_with_no_pagination_or_a_junk_script_is_skipped() -> None:
    """A Phase-1 ``ats_client`` script has no steps list at all. The migration runs on
    every ``company_scripts`` row, so a shape it does not understand must be a no-op,
    never a crash that wedges the whole upgrade."""
    module = _module()
    assert module._rewrite([
        ("u-ats", "ats_client", {"kind": "ats_client", "provider": "greenhouse"}),
        ("u-null", "http_json", None),
        ("u-nosteps", "http_json", {"script_version": 1, "steps": "not-a-list"}),
    ]) == []
