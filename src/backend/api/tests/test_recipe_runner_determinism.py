"""E7 Phase 3a — the deterministic replay engine. $0, fully offline (MockTransport).

Proves the load-bearing contract: same script + same responses ⇒ byte-identical
rows twice; the runner RAISES (never returns []) on non-2xx, unparseable JSON, a
path that does not resolve, zero rows, and a post-dedup count below
``expected_min_jobs``; and it emits ``HarvestEvidence`` the Phase-2 gate consumes.
"""

from __future__ import annotations

import json

import httpx
import pytest

from api.services.recipe_runner import RecipeExecutionError, run_recipe
from api.services.recipe_schema import RecipeError

# A dataset the mock transport paginates by ?offset=. Page size 2 → 3 pages
# (2, 2, 1); the short last page terminates the loop cleanly.
_DATASET = [
    {"id": i, "title": f"Engineer {i}", "url": f"https://ex.com/j/{i}"} for i in range(5)
]


def _paginated_handler(total_override: int | None = None) -> "callable":
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        page = _DATASET[offset:offset + 2]
        body = {"jobs": page, "total": total_override if total_override is not None else len(_DATASET)}
        return httpx.Response(200, json=body)
    return handler


def _client(handler: "callable") -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _paginated_script(expected_min_jobs: int = 5, records_path: str = "jobs") -> dict:
    return {
        "script_version": 1,
        "transport": "http_json",
        "expected_min_jobs": expected_min_jobs,
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://ex.com/api?q=1", "headers": {}},
            {"op": "paginate_offset", "param": "offset", "page_size": 2, "max_pages": 10},
            {"op": "extract_json_path", "records_path": records_path,
             "fields": {"id": "id", "title": "title", "url": "url"}},
            {"op": "dedupe_key", "field": "id"},
            {"op": "assert_page_advances"},
            {"op": "assert_unique", "field": "id"},
        ],
        "oracle": {"kind": "declared_probed", "total_path": "total"},
    }


# --- determinism ------------------------------------------------------------

def test_identical_output_on_two_runs() -> None:
    script = _paginated_script()
    with _client(_paginated_handler()) as http1:
        rows1, ev1 = run_recipe(script, http1)
    with _client(_paginated_handler()) as http2:
        rows2, ev2 = run_recipe(script, http2)
    assert rows1 == rows2                 # byte-identical rows
    assert [r["id"] for r in rows1] == ["0", "1", "2", "3", "4"]  # order preserved
    assert ev1 == ev2


def test_run_recipe_rechecks_column_drift_on_read() -> None:
    """run_recipe threads the stored transport/oracle_kind columns into the read-
    path validate_recipe, so a JSONB row edited out of sync is caught on replay
    (E7 3b review, Finding 3). Raised before any HTTP is issued."""
    script = _paginated_script()   # transport http_json, oracle declared_probed
    with _client(_paginated_handler()) as http:
        with pytest.raises(RecipeError, match="company_scripts.transport"):
            run_recipe(script, http, transport="http_html")
    with _client(_paginated_handler()) as http:
        with pytest.raises(RecipeError, match="company_scripts.oracle_kind"):
            run_recipe(script, http, oracle_kind="facet_sum")


def test_evidence_feeds_the_gate() -> None:
    script = _paginated_script()
    with _client(_paginated_handler()) as http:
        rows, ev = run_recipe(script, http)
    assert len(rows) == 5
    assert ev.declared_total == 5         # the oracle total rides declared_total
    assert ev.cap_hit is False
    assert ev.terminated_cleanly is True  # loop ended on the short last page
    assert ev.page_advance_ok is True     # every page's id-set disjoint
    assert ev.pages_fetched == 3
    assert ev.transport_ok is True


def test_gate_verifies_a_replayed_harvest() -> None:
    """End-to-end: runner evidence → run_gate → verify_harvest = VERIFIED."""
    from api.services.custom_baseline import Baseline
    from api.services.harvest_verification import VERIFIED, run_gate, verify_harvest
    from scripts.shared.models import JobListing

    script = _paginated_script()
    with _client(_paginated_handler()) as http:
        rows, ev = run_recipe(script, http)
    jobs = [
        JobListing(
            id=r["id"], title=r["title"], company="c", location="Remote", url=r["url"],
            source_id="custom:c", details={}, posted_on=None,
            created_at="2025-01-01T00:00:00.000Z", first_seen_at="2025-01-01T00:00:00.000Z",
            last_seen_at="2025-01-01T00:00:00.000Z", consecutive_misses=0,
            details_scraped=True, status="OPEN", has_matched=False, ai_metadata={}, closed_on=None,
        )
        for r in rows
    ]
    gate = run_gate(jobs, ev, oracle_kind="declared_probed")
    verdict = verify_harvest("declared_probed", gate, ev, Baseline(None, 0, 0.5))
    assert verdict.verdict == VERIFIED
    assert verdict.oracle_total == 5


# --- RAISES, never returns [] -----------------------------------------------

def test_zero_rows_raises_not_empty() -> None:
    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [], "total": 0})
    script = _paginated_script(expected_min_jobs=1)
    with _client(empty) as http:
        with pytest.raises(RecipeExecutionError, match="zero records"):
            run_recipe(script, http)


def test_count_below_expected_min_raises() -> None:
    script = _paginated_script(expected_min_jobs=100)  # dataset only has 5
    with _client(_paginated_handler()) as http:
        with pytest.raises(RecipeExecutionError, match="below expected_min_jobs"):
            run_recipe(script, http)


def test_non_2xx_raises() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream is down")
    script = _paginated_script()
    with _client(boom) as http:
        with pytest.raises(RecipeExecutionError, match="HTTP 503"):
            run_recipe(script, http)


def test_unparseable_json_raises() -> None:
    def garbage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")
    script = _paginated_script()
    with _client(garbage) as http:
        with pytest.raises(RecipeExecutionError, match="unparseable JSON"):
            run_recipe(script, http)


def test_records_path_not_resolving_raises() -> None:
    script = _paginated_script(records_path="nope")
    with _client(_paginated_handler()) as http:
        with pytest.raises(RecipeExecutionError, match="did not resolve"):
            run_recipe(script, http)


def test_vanished_oracle_total_path_raises() -> None:
    """The declared_probed oracle moved (total_path gone) → FAILED, not a silent pass."""
    script = _paginated_script()
    script["oracle"]["total_path"] = "grand_total"  # not in the payload
    with _client(_paginated_handler()) as http:
        with pytest.raises(RecipeExecutionError, match="did not resolve"):
            run_recipe(script, http)


def test_http_html_embedded_island_extracts_rows() -> None:
    """The YC shape: an Inertia JSON island in div[data-page]. Proves the ported
    http_html embedded-island path works (base_url joins relative urls)."""
    import html as html_lib

    island = json.dumps({"props": {"jobPostings": [
        {"id": 11, "title": "Founding Engineer", "url": "/jobs/11", "location": "SF"},
        {"id": 12, "title": "Designer", "url": "/jobs/12", "location": "Remote"},
    ]}})
    page = f'<html><body><div data-page="{html_lib.escape(island, quote=True)}"></div></body></html>'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page, headers={"content-type": "text/html"})

    script = {
        "script_version": 1,
        "transport": "http_html",
        "expected_min_jobs": 1,
        "base_url": "https://www.ycombinator.com",
        "steps": [
            {"op": "fetch", "method": "GET", "url": "https://www.ycombinator.com/companies/x/jobs", "headers": {}},
            {"op": "extract_embedded_island", "selector": "div[data-page]", "source": "attribute",
             "attribute": "data-page", "records_path": "props.jobPostings",
             "fields": {"id": "id", "title": "title", "url": "url", "location": "location"}},
            {"op": "dedupe_key", "field": "id"},
        ],
        "oracle": {"kind": "self_consistent"},
    }
    with _client(handler) as http:
        rows, ev = run_recipe(script, http)
    assert [r["id"] for r in rows] == ["11", "12"]
    assert rows[0]["url"] == "https://www.ycombinator.com/jobs/11"  # relative url joined
    assert ev.declared_total is None


def test_in_band_error_key_raises() -> None:
    """A truthy error key in a 200 body is fatal (Amazon's HTTP-200 error shape)."""
    def inband(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Result limit cannot be greater than 100", "jobs": None})
    script = _paginated_script()
    script["steps"].insert(3, {"op": "assert_no_inband_error", "error_keys": ["error"]})
    with _client(inband) as http:
        with pytest.raises(RecipeExecutionError, match="in-band error"):
            run_recipe(script, http)
