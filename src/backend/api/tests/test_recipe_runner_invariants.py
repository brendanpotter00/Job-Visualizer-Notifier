"""E7 Phase 3a — the ported spike safety invariants + the new Phase-3 ones. $0.

Ports ``scripts/one_off/recipe_spike/test_invariants.py`` (10 offline invariants),
adapted to the production runner/gate SPLIT: the spike's ``check_completeness``
*raised* on an incomplete harvest; in production the runner computes the oracle
total onto ``HarvestEvidence.declared_total`` and the GATE decides
(``count_mismatch`` → UNVERIFIED, never a close — invariant #3, tolerance 0). The
runner still RAISES on the things that mean "we learned nothing": non-2xx, a
vanished oracle, zero rows, and a count below ``expected_min_jobs``.

New Phase-3 invariants: paginate_facet sweep determinism, cap-hit evidence,
offset-wrap page-advance detection, and playwright in the forbidden set.
"""

from __future__ import annotations

import httpx
import pytest

from api.services.custom_baseline import Baseline
from api.services.harvest_meta import HarvestEvidence
from api.services.harvest_verification import (
    UNVERIFIED,
    VERIFIED,
    GateResult,
    verify_harvest,
)
from api.services.recipe_runner import (
    FORBIDDEN_MODULES,
    RecipeExecutionError,
    assert_no_agent_imports,
    run_recipe,
)
from api.services.recipe_schema import RecipeError, validate_recipe


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _json_script(records_path: str = "jobs", expected_min_jobs: int = 5, oracle: dict | None = None) -> dict:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": expected_min_jobs,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://ex.com/api", "headers": {}},
            {"op": "paginate_offset", "param": "offset", "page_size": 2, "max_pages": 20},
            {"op": "extract_json_path", "records_path": records_path,
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
            {"op": "assert_page_advances"},
        ],
        "oracle": oracle or {"kind": "declared_probed", "total_path": "total"},
    }


def _dataset_handler(n: int, total: int | None = None):
    data = [{"id": i, "title": f"t{i}", "url": f"https://ex.com/{i}"} for i in range(n)]

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        return httpx.Response(200, json={"jobs": data[offset:offset + 2],
                                         "total": total if total is not None else n})
    return handler


def _gate(n: int) -> GateResult:
    return GateResult(jobs=[], records_harvested=n, id_dedup_dropped=0, is_zero=False)


def _ev(total: int | None) -> HarvestEvidence:
    return HarvestEvidence(declared_total=total, cap_hit=False, terminated_cleanly=True,
                           page_advance_ok=True, pages_fetched=1)


# --- ported spike invariants (1-10), adapted to the runner/gate split -------

def test_inv1_incomplete_harvest_is_unverified_not_raised() -> None:
    """Spike raised on got<declared; production returns UNVERIFIED count_mismatch —
    an approximate/exact oracle may only ADD rows, never close (invariant #3)."""
    v = verify_harvest("declared_probed", _gate(10), _ev(4000), Baseline(None, 0, 0.5))
    assert v.verdict == UNVERIFIED and v.reason == "count_mismatch"


def test_inv2_complete_harvest_verifies() -> None:
    v = verify_harvest("declared_probed", _gate(76), _ev(76), Baseline(None, 0, 0.5))
    assert v.verdict == VERIFIED


def test_inv3_one_short_is_unverified_tolerance_zero() -> None:
    """The deliberate change from the spike's 5% tolerance: 99 of 100 is UNVERIFIED."""
    v = verify_harvest("declared_probed", _gate(99), _ev(100), Baseline(None, 0, 0.5))
    assert v.verdict == UNVERIFIED and v.reason == "count_mismatch"


def test_inv4_vanished_oracle_raises() -> None:
    script = _json_script(oracle={"kind": "declared_probed", "total_path": "renamed_total"})
    with _client(_dataset_handler(6)) as http:
        with pytest.raises(RecipeExecutionError, match="did not resolve"):
            run_recipe(script, http)


def test_inv5_zero_records_raises_never_empty() -> None:
    with _client(_dataset_handler(0, total=0)) as http:
        with pytest.raises(RecipeExecutionError, match="zero records"):
            run_recipe(_json_script(expected_min_jobs=1), http)


def test_inv6_count_below_expected_min_raises() -> None:
    with _client(_dataset_handler(3)) as http:
        with pytest.raises(RecipeExecutionError, match="below expected_min_jobs"):
            run_recipe(_json_script(expected_min_jobs=10), http)


def test_inv7_agent_free_guarantee_holds() -> None:
    assert assert_no_agent_imports() is None


def test_inv8_import_guard_fires_on_leak() -> None:
    import sys
    # ``stagehand`` stays in the forbidden set even though the tier that used it was
    # retired: the guard is about what may EVER become resident on the replay path,
    # not about which packages happen to be installed today.
    sys.modules["stagehand"] = object()  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError):
            assert_no_agent_imports()
    finally:
        del sys.modules["stagehand"]


def test_inv9_schema_rejects_missing_field() -> None:
    script = _json_script()
    del script["steps"][2]["fields"]["id"]
    with pytest.raises(RecipeError, match="fields.id"):
        validate_recipe(script)


def test_inv10_schema_rejects_non_https() -> None:
    script = _json_script()
    script["steps"][0]["url"] = "http://insecure.example/api"
    with pytest.raises(RecipeError, match="https"):
        validate_recipe(script)


# --- new Phase-3 invariants -------------------------------------------------

def _facet_script() -> dict:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 4,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://ex.com/search.json", "headers": {}},
            {"op": "paginate_facet", "facet_param": "f", "facet_values": ["a", "b"],
             "page_size": 2, "max_pages_per_facet": 10, "window_cap": 1000},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
            {"op": "assert_unique", "field": "id"},
        ],
        "oracle": {"kind": "self_consistent"},
    }


def _facet_handler():
    # facet "a" → ids 0..2 (3), facet "b" → ids 3..4 (2); union = 5 distinct.
    by_facet = {
        "a": [{"id": i, "title": f"t{i}", "url": f"https://ex.com/{i}"} for i in range(3)],
        "b": [{"id": i, "title": f"t{i}", "url": f"https://ex.com/{i}"} for i in range(3, 5)],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        facet = request.url.params.get("f")
        offset = int(request.url.params.get("offset", "0"))
        rows = by_facet.get(facet, [])
        return httpx.Response(200, json={"jobs": rows[offset:offset + 2]})
    return handler


def test_inv_facet_sweep_is_deterministic() -> None:
    with _client(_facet_handler()) as h1:
        rows1, ev1 = run_recipe(_facet_script(), h1)
    with _client(_facet_handler()) as h2:
        rows2, ev2 = run_recipe(_facet_script(), h2)
    assert rows1 == rows2
    assert sorted(r["id"] for r in rows1) == ["0", "1", "2", "3", "4"]
    assert ev1 == ev2
    assert ev1.declared_total is None  # self_consistent has no oracle total


def test_inv_cap_hit_is_recorded_in_evidence() -> None:
    """When offset+page_size would breach window_cap, the sweep stops and cap_hit
    is surfaced so the gate can refuse to VERIFY (check 5)."""
    script = _json_script(expected_min_jobs=1, oracle={"kind": "self_consistent"})
    script["steps"][1]["window_cap"] = 4  # page_size 2 → stops before offset 4
    with _client(_dataset_handler(50)) as http:
        rows, ev = run_recipe(script, http)
    assert ev.cap_hit is True
    assert ev.terminated_cleanly is False
    assert len(rows) == 4


def test_inv_offset_wrap_sets_page_advance_false() -> None:
    """A board that re-serves the same page on every offset (offset-wrap, the Intel
    shape) must surface page_advance_ok=False, not silently union duplicates away."""
    def wrapped(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [{"id": 0, "title": "a", "url": "u0"},
                                                  {"id": 1, "title": "b", "url": "u1"}],
                                         "total": 2})
    script = _json_script(expected_min_jobs=1, oracle={"kind": "self_consistent"})
    script["steps"][1]["max_pages"] = 3
    with _client(wrapped) as http:
        rows, ev = run_recipe(script, http)
    assert ev.page_advance_ok is False
    assert len(rows) == 2  # dedupe keeps the harvest usable, evidence flags the wrap


def test_inv_playwright_is_in_forbidden_set() -> None:
    assert "playwright" in FORBIDDEN_MODULES
