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
    map_records,
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


# --- the same contract, one layer up: an op we cannot RUN is a raise, not a shrug ------
#
# RAISES-never-empty is usually read as "zero rows is a failure". Its real subject is
# wider: a harvest must never come back looking complete while quietly having done less.
# ``parse_plan``'s dispatch had no ``else``, so a ``lookup_join`` step — a per-job detail
# fetch, fully specified by ``_v_lookup_join`` and implemented by nothing — validated on
# write and was then dropped on the floor at parse. The board scraped green every night
# with the detail data missing and no error anywhere. Same silence, same answer.


def test_inv5b_unrunnable_op_raises_at_parse_naming_the_op() -> None:
    """The recipe asks for a per-job detail fetch; the engine has no executor for one.

    Built by hand rather than through ``validate_recipe`` on purpose: the schema now
    refuses ``lookup_join`` on write (below), and this asserts the SECOND line of defence —
    a stored script that drifted, or the next op someone adds to the vocabulary without an
    executor, still cannot reach a nightly run and be silently skipped.
    """
    script = _json_script()
    script["steps"].append({
        "op": "lookup_join",
        "detail_fetch": {"url_template": "https://ex.com/job/{id}"},
        "join_key": "id",
        "fields": {"description": "body"},
    })
    with pytest.raises(RecipeError, match="lookup_join"):
        recipe_runner.parse_plan(script)


def test_inv5b_every_op_the_runner_implements_still_parses() -> None:
    """The other half, and the one that would catch an over-eager ``else``: every op in the
    closed vocabulary that the runner DOES handle — folded onto the plan or enforced
    structurally — must still parse. A raise here would take working boards offline."""
    script = _json_script()
    script["steps"] = [
        {"op": "fetch", "method": "GET", "url": "https://ex.com/api", "headers": {}},
        {"op": "paginate_offset", "param": "offset", "page_size": 2, "max_pages": 20},
        {"op": "extract_json_path", "records_path": "jobs",
         "fields": {"id": "id", "title": "title", "url": "url"}},
        {"op": "transform", "field": "url", "kind": "base_url_join",
         "base_url": "https://ex.com"},
        {"op": "parse_date", "field": "posted_at", "mode": "iso"},
        {"op": "dedupe_key", "field": "id"},
        {"op": "assert_no_inband_error", "error_keys": ["error"]},
        {"op": "assert_unique", "field": "id"},
        # The four the runner enforces structurally rather than folding onto the plan.
        {"op": "assert_status"},
        {"op": "assert_page_advances"},
        {"op": "assert_unique_ids_vs_total"},
        {"op": "assert_delta_vs_last_run"},
    ]
    validate_recipe(script)  # it is a real, storable recipe, not just a parse fixture
    plan = recipe_runner.parse_plan(script)
    assert [s["op"] for s in plan.shaping] == ["transform", "parse_date"]
    assert plan.unique_field == "id" and plan.error_keys == ("error",)


def test_inv5b_lookup_join_is_refused_on_write_not_stored_and_failed_nightly() -> None:
    """Front half of the fix. Refusing at validate time means discovery records a refusal
    the owner can read, instead of storing a recipe that FAILs every replay forever."""
    script = _json_script()
    script["steps"].append({
        "op": "lookup_join",
        "detail_fetch": {"url_template": "https://ex.com/job/{id}"},
        "join_key": "id",
        "fields": {"description": "body"},
    })
    with pytest.raises(RecipeError, match="lookup_join.*not implemented"):
        validate_recipe(script)


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


# --- multi-value optionals: a list of scalars is data, not a mis-map ----------
#
# These lock the fold that stopped a SILENT, TOTAL location loss. A board publishing
# ``locations`` as a list of strings had its correctly-mapped location pruned out of the
# stored recipe by ``request_selector._prune_non_scalar_optionals``, so every job landed
# with NULL location + ``normalization_status='failed'``. Measured in the owner's dev DB:
# Atlassian 235/235 and Microsoft 2,055/2,055 jobs with zero canonical locations.


def test_a_list_of_location_strings_is_folded_rather_than_lost() -> None:
    """Atlassian's real record shape, verbatim from the live board. ``'; '`` is not a
    cosmetic choice — it is the multi-location separator the Tier-2 prompt documents and
    few-shots, so the folded string canonicalizes into the TWO ``job_locations`` rows the
    posting actually has instead of one invented place."""
    rows = map_records(
        [{
            "id": 25583,
            "title": "Account Executive - Japanese Speaking",
            "portalJobPost": {"portalUrl": "https://x.icims.com/jobs/25583/job"},
            "locations": ["Remote - Japan - Remote", "Remote - Remote"],
            "category": "Sales",
        }],
        {"id": "id", "title": "title", "url": "portalJobPost.portalUrl",
         "location": "locations", "department": "category"},
    )
    assert rows[0]["location"] == "Remote - Japan - Remote; Remote - Remote"


def test_a_one_element_location_list_folds_to_the_bare_string() -> None:
    """Microsoft's real shape (``standardizedLocations: ["US"]``) — the same 100% loss as
    Atlassian, out of a list carrying exactly one value. The fold must leave no separator
    and no brackets behind, or Tier-2 is asked to canonicalize a place that does not
    exist."""
    rows = map_records(
        [{"id": "1", "title": "SWE", "positionUrl": "/j/1", "standardizedLocations": ["US"]}],
        {"id": "id", "title": "title", "url": "https://h{positionUrl}",
         "location": "standardizedLocations"},
    )
    assert rows[0]["location"] == "US"


def test_a_list_of_objects_stays_a_container_so_the_prune_still_deletes_it() -> None:
    """The guard the fold must NOT weaken. TikTok's location leaf sits one level down
    (``city_info.en_name``) and the model reaches for the container; joining reprs would
    write ``{'en_name': 'San Jose'}`` into the location column. A list holding a container
    stays one, so ``_prune_non_scalar_optionals`` still drops the mapping."""
    rows = map_records(
        [{"id": "1", "title": "T", "url": "/x", "city_info": [{"en_name": "San Jose"}]}],
        {"id": "id", "title": "title", "url": "url", "location": "city_info"},
    )
    assert rows[0]["location"] == [{"en_name": "San Jose"}]


def test_an_empty_location_list_folds_to_none_not_empty_string() -> None:
    """A board that published no location for this one job. ``None`` is what every
    downstream reader already means by absent (``recipe_rows`` stores NULL,
    ``normalize_location`` short-circuits to 'no-location'); ``""`` would be a second
    spelling of the same thing that only some of them test for."""
    rows = map_records(
        [{"id": "1", "title": "T", "url": "/x", "locations": []}],
        {"id": "id", "title": "title", "url": "url", "location": "locations"},
    )
    assert rows[0]["location"] is None


def test_posted_at_is_never_folded() -> None:
    """A posting has ONE publish date, so a list under ``posted_at`` is a mis-mapped path
    rather than multi-value data. Folding it would hand ``parse_date``
    ``"2026-01-01; 2026-02-02"`` — a string it can only fail on — instead of leaving the
    container visible for the prune to delete the bad mapping outright."""
    rows = map_records(
        [{"id": "1", "title": "T", "url": "/x", "dates": ["2026-01-01", "2026-02-02"]}],
        {"id": "id", "title": "title", "url": "url", "posted_at": "dates"},
    )
    assert rows[0]["posted_at"] == ["2026-01-01", "2026-02-02"]


def test_the_required_three_are_never_folded() -> None:
    """id/title/url are REFUSED, not repaired: ``_validate_field_map`` raises on a
    non-scalar id so a board we cannot identify is not half-read. Folding here would turn
    that refusal into a plausible-looking joined id and make the dedupe/close key a
    fiction — a board that closes and reopens every job every night."""
    rows = map_records(
        [{"ids": ["a", "b"], "title": "T", "url": "/x"}],
        {"id": "ids", "title": "title", "url": "url"},
    )
    assert rows[0]["id"] == "['a', 'b']"


# --- HTML entities: decoded once, at the seam, and never on the key --------------------
#
# A discovered board hands us its own page markup. 19 of 85 custom Spotify titles arrive as
# ``Client Partner, Emerging &amp; Scaled``, which renders literally in the job list AND
# breaks every exact-match comparison against another board (it measured the Spotify title
# overlap at 56/81 instead of the true 70/81).


def test_an_entity_in_a_title_is_decoded() -> None:
    """Spotify's real title, verbatim."""
    rows = map_records(
        [{"id": "1", "title": "Client Partner, Emerging &amp; Scaled", "url": "/x"}],
        {"id": "id", "title": "title", "url": "url"},
    )
    assert rows[0]["title"] == "Client Partner, Emerging & Scaled"


def test_a_double_encoded_entity_is_decoded_exactly_once() -> None:
    """THE reason there is one unescape site and not two. A board that publishes the five
    literal characters ``&amp;`` encodes them as ``&amp;amp;``; decoding twice (once here,
    once in ``recipe_rows``) would silently corrupt it to a bare ``&`` and there would be
    no way to tell that from a board that published ``&`` in the first place."""
    rows = map_records(
        [{"id": "1", "title": "Tips &amp;amp; Tricks", "url": "/x"}],
        {"id": "id", "title": "title", "url": "url"},
    )
    assert rows[0]["title"] == "Tips &amp; Tricks"


def test_a_title_with_no_entity_is_byte_identical() -> None:
    """The no-op case, pinned because this runs over every field of every row of every
    board: a decode that "helpfully" touched anything else would be a silent rewrite of
    2,000-job boards that were already correct."""
    rows = map_records(
        [{"id": "1", "title": "Staff Engineer, Data & AI", "url": "/x"}],
        {"id": "id", "title": "title", "url": "url"},
    )
    assert rows[0]["title"] == "Staff Engineer, Data & AI"


def test_the_id_is_never_unescaped_so_the_close_key_cannot_move() -> None:
    """The never-wrong-close guard on this change. ``id`` is half of ``job_listings``'
    composite key and the default ``dedupe_key`` field: decoding it would make tonight's
    harvest disagree with every row already stored, closing and re-inserting the entire
    board — a mass close caused by a cosmetic fix. ``url`` rides along for the weaker
    reason that it is a transport value, not prose."""
    rows = map_records(
        [{"id": "a&amp;b", "title": "T", "url": "https://ex.com/j?x=1&amp;y=2"}],
        {"id": "id", "title": "title", "url": "url"},
    )
    assert rows[0]["id"] == "a&amp;b"
    assert rows[0]["url"] == "https://ex.com/j?x=1&amp;y=2"


def test_a_folded_multi_value_field_is_decoded_after_the_join() -> None:
    """Fold first, decode once. Decoding per element would be identical today and would
    quietly stop being so the moment a separator or a joiner changes — this pins the order
    that makes the ``'; '`` spelling the Tier-2 location prompt documents survive."""
    rows = map_records(
        [{"id": "1", "title": "T", "url": "/x",
          "locations": ["Z&uuml;rich", "S&atilde;o Paulo"]}],
        {"id": "id", "title": "title", "url": "url", "location": "locations"},
    )
    assert rows[0]["location"] == "Zürich; São Paulo"
