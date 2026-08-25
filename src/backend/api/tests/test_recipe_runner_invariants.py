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
from api.services import recipe_runner
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


# --- the two RUNTIME bounds that replaced the flat page ceiling --------------
#
# The stored budget used to be clamped at 100 pages so a full sweep would fit the leaf
# task's 120s timeout. That made the JOB ceiling a function of the board's own page
# size — 10,000 jobs of amazon.jobs, 1,000 of Microsoft's 10-per-page board — and
# truncated Microsoft at 47% of itself. The clamp is gone; these are what bound a sweep
# now, and the property that matters about both is not that they stop it but that a run
# they stopped can never present as a complete read.


class _FakeClock:
    """A monotonic clock that advances a fixed step per READING.

    Deterministic on purpose: a test that stops a sweep by really sleeping would be
    timing-dependent, and the thing under test (WHERE the sweep stops) is exactly what
    a flaky clock would blur.
    """

    def __init__(self, step: float = 1.0) -> None:
        self.now = 0.0
        self.step = step

    def monotonic(self) -> float:
        self.now += self.step
        return self.now


def _counting_handler(n: int, total: int | None = None):
    """``_dataset_handler`` plus a request tally — how far a sweep actually got."""
    calls: list[int] = []
    inner = _dataset_handler(n, total)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(int(request.url.params.get("offset", "0")))
        return inner(request)
    return handler, calls


def test_a_short_page_still_ends_the_sweep_at_a_huge_budget(monkeypatch) -> None:
    """THE PROPERTY THAT MAKES A BIG BUDGET SAFE. Dropping the flat ceiling raised the
    stored budget from 100 pages to thousands; if the short-page terminus had stopped
    being the real stop condition, a 5-job board would now cost 5,000 pointless requests
    a night instead of three. The budget is a CEILING, never a target — which is also
    why raising it on already-stored recipes needs no acceptance replay.
    """
    monkeypatch.setattr(recipe_runner, "HARVEST_TIME_BUDGET_S", 600.0)
    script = _json_script(expected_min_jobs=1, oracle={"kind": "self_consistent"})
    script["steps"][1]["max_pages"] = 5000

    handler, calls = _counting_handler(5)
    with _client(handler) as http:
        rows, ev = run_recipe(script, http)

    assert calls == [0, 2, 4]            # 2 + 2 + a SHORT page of 1, and then stop
    assert len(rows) == 5
    assert ev.cap_hit is False
    assert ev.terminated_cleanly is True


def test_the_wall_clock_budget_stops_the_sweep_mid_flight(monkeypatch) -> None:
    """Enforced BETWEEN pages, not hoped for. A budget that only existed as a page
    count would be a flat cap again, and one that was merely 'expected to be enough'
    would be enforced by the task timeout — which kills the run instead of ending it,
    losing the rows it did read.
    """
    clock = _FakeClock(step=1.0)
    monkeypatch.setattr(recipe_runner, "time", clock)
    monkeypatch.setattr(recipe_runner, "HARVEST_TIME_BUDGET_S", 5.0)

    script = _json_script(expected_min_jobs=1, oracle={"kind": "self_consistent"})
    script["steps"][1]["max_pages"] = 5000

    handler, calls = _counting_handler(500)
    with _client(handler) as http:
        rows, ev = run_recipe(script, http)

    # The clock is read once to stamp the deadline and once per page thereafter, so a
    # 5s budget at 1s/reading buys 5 pages of 2 — and then the sweep ENDS, with the
    # rows it read, instead of being killed.
    assert len(calls) == 5
    assert len(rows) == 10
    assert ev.cap_hit is True
    assert ev.terminated_cleanly is False


def test_a_budget_stopped_run_can_never_verify(monkeypatch) -> None:
    """...and therefore can never close a job (invariant #2). The whole reason the
    budget sets ``cap_hit`` rather than just breaking: an unfinished sweep that reported
    a clean terminus would let ``self_consistent`` certify it, and the destructive tail
    would close every job past the page the clock stopped on.
    """
    clock = _FakeClock(step=1.0)
    monkeypatch.setattr(recipe_runner, "time", clock)
    monkeypatch.setattr(recipe_runner, "HARVEST_TIME_BUDGET_S", 3.0)

    script = _json_script(expected_min_jobs=1, oracle={"kind": "self_consistent"})
    script["steps"][1]["max_pages"] = 5000
    with _client(_dataset_handler(500)) as http:
        rows, ev = run_recipe(script, http)

    verdict = verify_harvest(
        "self_consistent", _gate(len(rows)), ev, Baseline(None, 0, 0.5)
    )
    assert verdict.verdict == UNVERIFIED
    assert verdict.reason == "cap_hit"


def test_the_record_ceiling_stops_the_sweep_too(monkeypatch) -> None:
    """Time does not bound MEMORY. Every row is held until ``finalize_harvest``, so a
    board that pages fast enough to stay inside the clock could still stream itself into
    a worker that co-hosts the API. Same stop, same honesty: cap_hit, not a terminus.
    """
    monkeypatch.setattr(recipe_runner, "MAX_HARVEST_RECORDS", 6)
    script = _json_script(expected_min_jobs=1, oracle={"kind": "self_consistent"})
    script["steps"][1]["max_pages"] = 5000

    handler, calls = _counting_handler(500)
    with _client(handler) as http:
        rows, ev = run_recipe(script, http)

    assert len(calls) == 3       # 3 pages of 2 reaches the 6-row ceiling
    assert len(rows) == 6
    assert ev.cap_hit is True
    assert ev.terminated_cleanly is False


def test_the_clock_is_one_budget_across_the_whole_facet_fan_out(monkeypatch) -> None:
    """A facet fan-out is N sweeps of the SAME board. A per-sweep budget would multiply
    the wall clock by the facet count — amazon.jobs has 38 — which is the bound we are
    trying to hold, so the deadline is stamped once for the run and an exhausted clock
    ends the RUN rather than moving on to pay one wasted request per remaining facet.
    """
    clock = _FakeClock(step=1.0)
    monkeypatch.setattr(recipe_runner, "time", clock)
    monkeypatch.setattr(recipe_runner, "HARVEST_TIME_BUDGET_S", 2.0)

    facets: list[str | None] = []
    inner = _facet_handler()

    def handler(request: httpx.Request) -> httpx.Response:
        facets.append(request.url.params.get("f"))
        return inner(request)

    script = _facet_script()
    script["expected_min_jobs"] = 1
    with _client(handler) as http:
        _rows, ev = run_recipe(script, http)

    assert facets == ["a", "a"]   # facet "b" is never asked for
    assert ev.cap_hit is True
    assert ev.terminated_cleanly is False
