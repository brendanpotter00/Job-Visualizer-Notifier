"""E7 Phase 3a — the three richer oracles (facet_sum / header / sitemap). $0.

facet_sum is proven against a REAL global-board amazon.jobs capture: a single-valued
facet sums to the true total (22,191) while ``hits`` caps at the 10,000 ES window —
so the facet partition is the only path to the truth, and a multi-valued facet (the
GM 1,042-vs-835 double-count shape) is rejected. All three oracles are exact-match
(tolerance 0): ``n == total`` VERIFIES, ``n < total`` is ``count_mismatch`` (Amazon's
~43-job structural hole lands here and refuses to close), ``n > total`` is
``over_harvest``. The Phase-2 ``NotImplementedError`` seam is gone.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    RecipeExecutionError,
    _oracle_header,
    run_recipe,
    sum_single_valued_facet,
)

_CAPTURES = Path(__file__).parent / "fixtures" / "captures"
_ORACLES = Path(__file__).parent / "fixtures" / "oracles"

AMAZON_TRUE_TOTAL = 22191   # canonical BUILD-PLAN section 9 total (fixture pinned)
AMAZON_HITS_CAP = 10000     # the ES window `hits` caps at


def _client_returning(payload: dict, headers: dict | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, headers=headers or {})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_returning_text(text: str, media_type: str = "application/xml") -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=text, headers={"content-type": media_type})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _amazon_facet_script(facet_path: str, expected_min_jobs: int = 5) -> dict:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": expected_min_jobs,
        "steps": [
            {"op": "fetch", "method": "GET",
             "url": "https://www.amazon.jobs/en/search.json?facets[]=is_intern", "headers": {}},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id_icims", "title": "title",
                        "url": "https://www.amazon.jobs{job_path}"}},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "facet_sum", "facet_path": facet_path,
                   "single_valued": True, "window_cap": AMAZON_HITS_CAP, "total_path": "hits"},
    }


# --- facet_sum: the 22,191 vs 10,000-hits invariant -------------------------

def test_facet_sum_reaches_true_total_while_hits_caps() -> None:
    """A single-valued facet (is_intern) sums to 22,191 — the true total — while the
    payload's own `hits` is pinned at the 10,000 ES window. The facet is the ONLY
    path to the truth."""
    capture = json.loads((_CAPTURES / "amazon_global.json").read_text())
    assert capture["hits"] == AMAZON_HITS_CAP
    assert sum_single_valued_facet(capture, "facets.is_intern") == AMAZON_TRUE_TOTAL

    script = _amazon_facet_script("facets.is_intern")
    with _client_returning(capture) as http:
        rows, evidence = run_recipe(script, http)
    assert len(rows) >= 5
    assert evidence.declared_total == AMAZON_TRUE_TOTAL   # rides declared_total → the gate


def test_multi_valued_facet_is_rejected() -> None:
    """The state facet double-counts multi-location jobs (Σ=135 > hits=76 on an
    under-cap slice) — the GM 1,042-vs-835 shape. It must be REJECTED, not summed."""
    capture = json.loads((_CAPTURES / "amazon_filtered.json").read_text())
    assert capture["hits"] == 76
    script = _amazon_facet_script("facets.normalized_state_name_facet")
    with _client_returning(capture) as http:
        with pytest.raises(RecipeExecutionError, match="NOT single-valued"):
            run_recipe(script, http)


def test_single_valued_facet_on_under_cap_slice_is_accepted() -> None:
    """The country facet on the same under-cap slice partitions cleanly (Σ=76 ==
    hits=76) → accepted as the total."""
    capture = json.loads((_CAPTURES / "amazon_filtered.json").read_text())
    script = _amazon_facet_script("facets.normalized_country_code_facet")
    with _client_returning(capture) as http:
        _, evidence = run_recipe(script, http)
    assert evidence.declared_total == 76


# --- facet_sum: the tolerance-0 verdict ladder ------------------------------

def _gate_of(n: int) -> GateResult:
    return GateResult(jobs=[], records_harvested=n, id_dedup_dropped=0, is_zero=False)


def _ev(total: int) -> HarvestEvidence:
    return HarvestEvidence(
        declared_total=total, cap_hit=False, terminated_cleanly=True,
        page_advance_ok=True, pages_fetched=1,
    )


def test_facet_sum_exact_match_verifies() -> None:
    v = verify_harvest("facet_sum", _gate_of(AMAZON_TRUE_TOTAL), _ev(AMAZON_TRUE_TOTAL),
                       Baseline(None, 0, 0.5))
    assert v.verdict == VERIFIED
    assert v.reason == "oracle_exact"
    assert v.oracle_total == AMAZON_TRUE_TOTAL
    assert v.tolerance_used == 0.0


def test_facet_sum_structural_hole_is_count_mismatch_not_close() -> None:
    """Amazon's ~43 facet-invisible jobs: 22,148 harvested of 22,191. Tolerance 0
    REFUSES to close — a percentage (0.998) would have wrongly closed them."""
    v = verify_harvest("facet_sum", _gate_of(AMAZON_TRUE_TOTAL - 43), _ev(AMAZON_TRUE_TOTAL),
                       Baseline(None, 0, 0.5))
    assert v.verdict == UNVERIFIED
    assert v.reason == "count_mismatch"


def test_facet_sum_over_harvest_is_unverified() -> None:
    v = verify_harvest("facet_sum", _gate_of(AMAZON_TRUE_TOTAL + 9), _ev(AMAZON_TRUE_TOTAL),
                       Baseline(None, 0, 0.5))
    assert v.verdict == UNVERIFIED
    assert v.reason == "over_harvest"


def test_facet_sum_no_longer_raises_not_implemented() -> None:
    """Regression: the Phase-2 NotImplementedError seam is wired."""
    v = verify_harvest("facet_sum", _gate_of(10), _ev(10), Baseline(None, 0, 0.5))
    assert v.verdict == VERIFIED


# --- header oracle ----------------------------------------------------------

def _wp_script() -> dict:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 1,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://jobs.example.org/wp-json/jobs",
             "headers": {}},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "header", "header_name": "X-WP-Total"},
    }


def test_header_oracle_reads_total() -> None:
    body = json.loads((_ORACLES / "wp_jobs.json").read_text())
    with _client_returning(body, headers={"X-WP-Total": "873"}) as http:
        _, evidence = run_recipe(_wp_script(), http)
    assert evidence.declared_total == 873


def test_header_oracle_verifies_on_exact_match() -> None:
    v = verify_harvest("header", _gate_of(873), _ev(873), Baseline(None, 0, 0.5))
    assert v.verdict == VERIFIED
    assert v.reason == "oracle_exact"


def test_header_oracle_missing_header_raises() -> None:
    body = json.loads((_ORACLES / "wp_jobs.json").read_text())
    with _client_returning(body, headers={}) as http:   # X-WP-Total absent
        with pytest.raises(RecipeExecutionError, match="absent"):
            run_recipe(_wp_script(), http)


def test_header_oracle_non_int_header_raises() -> None:
    with pytest.raises(RecipeExecutionError, match="not an int"):
        _oracle_header({"X-WP-Total": "lots"}, {"kind": "header", "header_name": "X-WP-Total"})


# --- sitemap oracle ---------------------------------------------------------

def _sitemap_script() -> dict:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": 1,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://jobs.example.org/api/list",
             "headers": {}},
            {"op": "extract_json_path", "records_path": "jobs",
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "sitemap", "sitemap_url": "https://jobs.example.org/sitemap.xml",
                   "url_pattern": "/job/"},
    }


def test_sitemap_oracle_counts_matching_locs() -> None:
    """The sitemap has 5 /job/ <loc> entries + 2 non-job pages → total 5."""
    sitemap = (_ORACLES / "sitemap.xml").read_text()
    body = {"jobs": [{"id": "1001", "title": "Staff Engineer", "url": "https://jobs.example.org/job/1001"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("sitemap.xml"):
            return httpx.Response(200, text=sitemap, headers={"content-type": "application/xml"})
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        _, evidence = run_recipe(_sitemap_script(), http)
    assert evidence.declared_total == 5


def test_sitemap_oracle_verifies_on_exact_match() -> None:
    v = verify_harvest("sitemap", _gate_of(5), _ev(5), Baseline(None, 0, 0.5))
    assert v.verdict == VERIFIED


def test_sitemap_oracle_empty_raises() -> None:
    """A sitemap that matches nothing (oracle unusable) raises — never a silent pass."""
    empty_sitemap = '<?xml version="1.0"?><urlset><url><loc>https://x/about</loc></url></urlset>'
    body = {"jobs": [{"id": "1", "title": "t", "url": "https://x/job/1"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("sitemap.xml"):
            return httpx.Response(200, text=empty_sitemap, headers={"content-type": "application/xml"})
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(RecipeExecutionError, match="0 <loc> matching"):
            run_recipe(_sitemap_script(), http)
