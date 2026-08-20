"""Tests that verify JSON responses use camelCase keys matching the frontend TypeScript interfaces.

This is the single most critical test file — if these fail, the frontend breaks.
"""

import json

from .conftest import _make_job, _insert_job, _insert_scrape_run

# Expected camelCase keys from BackendJobListing (src/frontend/src/api/types.ts)
EXPECTED_JOB_KEYS = {
    "id", "title", "company", "location", "url",
    "sourceId", "details", "createdAt", "postedOn", "closedOn",
    "status", "hasMatched", "aiMetadata", "firstSeenAt", "lastSeenAt",
    "consecutiveMisses", "detailsScraped", "locations",
    "category", "level", "tags", "enrichmentStatus",
    # ORDERED SWE subcategory slugs, tri-state (null | [] | [..]). Serialized
    # even when null — `null` (never evaluated) and `[]` (evaluated, nothing
    # applies) are different facts about the row.
    "subcategories",
}

# Expected camelCase keys from ScrapeRun (src/frontend/src/pages/QAPage/QAPage.tsx)
EXPECTED_SCRAPE_RUN_KEYS = {
    "runId", "company", "startedAt", "completedAt", "mode",
    "jobsSeen", "newJobs", "closedJobs", "detailsFetched", "errorCount",
    # Tri-state safety-guard flag (true / false / null-for-pre-column rows).
    # Serialized even when null so the QA table can distinguish "guard did not
    # trip" from "this row predates the column".
    "skippedUpdate",
}

# Expected camelCase keys from JobsStats response
EXPECTED_STATS_KEYS = {"totalJobs", "openJobs", "closedJobs", "companyCounts"}
EXPECTED_COMPANY_COUNT_KEYS = {"company", "count"}


def test_job_response_has_camel_case_keys(client, db_conn):
    _insert_job(db_conn, _make_job({"id": "shape-test-1"}))
    resp = client.get("/api/jobs")
    jobs = resp.json()
    assert len(jobs) == 1
    assert set(jobs[0].keys()) == EXPECTED_JOB_KEYS


def test_job_detail_response_has_camel_case_keys(client, db_conn):
    _insert_job(db_conn, _make_job({"id": "shape-test-2"}))
    resp = client.get("/api/jobs/google_scraper/shape-test-2")
    assert set(resp.json().keys()) == EXPECTED_JOB_KEYS


def test_job_response_has_no_snake_case_keys(client, db_conn):
    _insert_job(db_conn, _make_job({"id": "shape-test-3"}))
    resp = client.get("/api/jobs")
    job = resp.json()[0]
    snake_case_keys = {"source_id", "created_at", "posted_on", "closed_on",
                       "has_matched", "ai_metadata", "first_seen_at", "last_seen_at",
                       "consecutive_misses", "details_scraped"}
    assert not snake_case_keys.intersection(job.keys()), f"Found snake_case keys: {snake_case_keys.intersection(job.keys())}"


def test_details_and_ai_metadata_are_strings(client, db_conn):
    """Frontend expects details and aiMetadata as JSON strings, not parsed objects."""
    _insert_job(db_conn, _make_job({
        "id": "shape-test-4",
        "details": json.dumps({"salary_range": "$100k"}),
        "ai_metadata": json.dumps({"matched": True}),
    }))
    resp = client.get("/api/jobs/google_scraper/shape-test-4")
    job = resp.json()
    assert isinstance(job["details"], str)
    assert isinstance(job["aiMetadata"], str)
    # Should be valid JSON strings
    parsed_details = json.loads(job["details"])
    assert parsed_details["salary_range"] == "$100k"
    parsed_meta = json.loads(job["aiMetadata"])
    assert parsed_meta["matched"] is True


def test_scrape_run_response_has_camel_case_keys(client, db_conn):
    _insert_scrape_run(db_conn, {"run_id": "shape-run-1"})
    resp = client.get("/api/jobs-qa/scrape-runs")
    runs = resp.json()
    assert len(runs) == 1
    assert set(runs[0].keys()) == EXPECTED_SCRAPE_RUN_KEYS


def test_stats_response_has_camel_case_keys(client, db_conn):
    _insert_job(db_conn, _make_job({"id": "shape-stat-1"}))
    resp = client.get("/api/jobs-qa/stats")
    stats = resp.json()
    assert set(stats.keys()) == EXPECTED_STATS_KEYS
    assert len(stats["companyCounts"]) >= 1
    assert set(stats["companyCounts"][0].keys()) == EXPECTED_COMPANY_COUNT_KEYS


def test_health_returns_plain_text_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.text == "OK"
    assert resp.headers["content-type"].startswith("text/plain")


def test_trigger_scrape_response_shape(client):
    resp = client.post("/api/jobs-qa/trigger-scrape", params={"company": "google"})
    assert resp.status_code == 202
    body = resp.json()
    assert set(body.keys()) == {"message", "company"}


# --- Input validation ---

def test_jobs_rejects_negative_limit(client):
    resp = client.get("/api/jobs", params={"limit": -1})
    assert resp.status_code == 422


def test_jobs_rejects_limit_above_max(client):
    resp = client.get("/api/jobs", params={"limit": 99999})
    assert resp.status_code == 422


def test_jobs_rejects_negative_offset(client):
    resp = client.get("/api/jobs", params={"offset": -1})
    assert resp.status_code == 422


def test_jobs_rejects_invalid_company_pattern(client):
    resp = client.get("/api/jobs", params={"company": "; DROP TABLE"})
    assert resp.status_code == 422


def test_jobs_rejects_invalid_status(client):
    resp = client.get("/api/jobs", params={"status": "INVALID"})
    assert resp.status_code == 422


def test_scrape_runs_rejects_invalid_limit(client):
    resp = client.get("/api/jobs-qa/scrape-runs", params={"limit": 0})
    assert resp.status_code == 422


def test_trigger_scrape_rejects_invalid_company(client):
    resp = client.post("/api/jobs-qa/trigger-scrape", params={"company": "a;b"})
    assert resp.status_code == 422


# --- SWE subcategories on the enrichment write path -------------------------
#
# `EnrichmentResultItem` has NO `extra='forbid'`, so before the field existed
# Pydantic's default `ignore` ACCEPTED an unknown `subcategories` key and threw
# it away — while `POST /results` returned 200 and reported `written: N`. These
# tests pin both halves of that: the field is declared, and the reason it had to
# be is a silent drop that inflates exactly the number an operator would check.


def test_unknown_key_is_ignored_not_rejected():
    """The mechanism that made the drop silent, asserted directly.

    This is what makes the round-trip test meaningful: without a declared field,
    the round trip fails while the endpoint still returns 200 and `written: 1`.
    """
    from api.models import EnrichmentResultItem

    item = EnrichmentResultItem(**{"jobListingId": "1", "sourceId": "s", "zzz": 1})
    assert "zzz" not in item.model_dump()


def test_result_item_declares_the_subcategory_triple():
    from api.models import EnrichmentResultItem

    item = EnrichmentResultItem(
        **{
            "jobListingId": "1",
            "sourceId": "s",
            "subcategories": ["backend"],
            "subcategoryConfidence": 0.82,
            "subcategorySource": "classify",
        }
    )
    assert item.subcategories == ["backend"]
    assert item.subcategory_confidence == 0.82
    assert item.subcategory_source == "classify"


def test_absent_subcategories_key_is_distinguishable_from_an_explicit_null():
    """`model_fields_set` is the ONLY thing separating the two, and the
    difference is whether an ordinary v6 tick NULLs the column on every row."""
    from api.models import EnrichmentResultItem

    absent = EnrichmentResultItem(**{"jobListingId": "1", "sourceId": "s"})
    assert absent.subcategories is None
    assert "subcategories" not in absent.model_fields_set

    explicit = EnrichmentResultItem(
        **{"jobListingId": "1", "sourceId": "s", "subcategories": None}
    )
    assert explicit.subcategories is None
    assert "subcategories" in explicit.model_fields_set


import pytest  # noqa: E402 — kept beside the parametrize that needs it


@pytest.mark.parametrize(
    "value",
    [
        "backend",                       # a bare string
        {"primary": "backend"},          # a dict
        [1, 2],                          # a list of non-strings
        [],                              # evaluated, nothing applies
        None,                            # never evaluated
    ],
)
def test_malformed_subcategories_validate_without_raising(value):
    """NEVER route the whole item to `failed[]`.

    Same contract as `locations`: a malformed value degrades in the writer with
    a warning, so the item's good category/level/tags still land. A stricter
    type here would discard them at `model_validate`.
    """
    from api.models import EnrichmentResultItem

    item = EnrichmentResultItem(
        **{"jobListingId": "1", "sourceId": "s", "subcategories": value}
    )
    assert item.model_dump()["job_listing_id"] == "1"


def test_missing_subcategories_key_validates():
    from api.models import EnrichmentResultItem

    EnrichmentResultItem(**{"jobListingId": "1", "sourceId": "s"})


def test_job_facets_response_constructs_without_subcategories():
    """A phase-1 backend must still be able to build the facets response."""
    from api.models import JobFacetsResponse

    resp = JobFacetsResponse(categories=[], levels=[])
    assert resp.subcategories == []


def test_subcategories_round_trip_through_results(client, db_conn, seed_taxonomy):
    """⚠ THE CERTIFIED ROUND TRIP: POST /results -> GET the job -> the array is there.

    NEVER assert on `written: N` here. `written` is exactly the number a silent
    Pydantic drop inflates: before `EnrichmentResultItem.subcategories` existed,
    this endpoint accepted the key, discarded it, persisted nothing, and reported
    `written: 1`. The only honest proof is reading the value back out of the
    public read path.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.dependencies import get_db
    from api.routers import internal_enrichment

    _insert_job(db_conn, _make_job({"id": "rt-1", "source_id": "rt-src"}))
    db_conn.commit()

    internal_app = FastAPI()
    internal_app.include_router(
        internal_enrichment.router, prefix="/api/internal/enrichment"
    )
    internal_app.dependency_overrides[get_db] = lambda: db_conn
    internal_client = TestClient(internal_app)

    resp = internal_client.post(
        "/api/internal/enrichment/results",
        json={
            "results": [
                {
                    "jobListingId": "rt-1",
                    "sourceId": "rt-src",
                    "category": "software_engineering",
                    "level": "senior",
                    "subcategories": ["backend"],
                    "subcategorySource": "classify",
                    "subcategoryConfidence": 0.82,
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text

    detail = client.get("/api/jobs/rt-src/rt-1")
    assert detail.status_code == 200, detail.text
    assert detail.json()["subcategories"] == ["backend"]


def test_unevaluated_job_serializes_subcategories_as_null_not_empty(client, db_conn):
    """The tri-state has to survive all the way to the SPA: `null` (never
    evaluated) is a different fact from `[]` (evaluated, nothing applies)."""
    _insert_job(db_conn, _make_job({"id": "rt-null", "source_id": "rt-src"}))
    db_conn.commit()

    body = client.get("/api/jobs/rt-src/rt-null").json()
    assert body["subcategories"] is None
