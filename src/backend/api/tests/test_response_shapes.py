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
    "consecutiveMisses", "detailsScraped",
}

# Expected camelCase keys from ScrapeRun (src/frontend/src/pages/QAPage/QAPage.tsx)
EXPECTED_SCRAPE_RUN_KEYS = {
    "runId", "company", "startedAt", "completedAt", "mode",
    "jobsSeen", "newJobs", "closedJobs", "detailsFetched", "errorCount",
}

# Expected camelCase keys from JobsStats response
EXPECTED_STATS_KEYS = {"totalJobs", "openJobs", "closedJobs", "companyCounts"}
EXPECTED_COMPANY_COUNT_KEYS = {"company", "count"}


def test_job_response_has_camel_case_keys(client, db_conn, test_env):
    _insert_job(db_conn, test_env, _make_job({"id": "shape-test-1"}))
    resp = client.get("/api/jobs")
    jobs = resp.json()
    assert len(jobs) == 1
    assert set(jobs[0].keys()) == EXPECTED_JOB_KEYS


def test_job_detail_response_has_camel_case_keys(client, db_conn, test_env):
    _insert_job(db_conn, test_env, _make_job({"id": "shape-test-2"}))
    resp = client.get("/api/jobs/shape-test-2")
    assert set(resp.json().keys()) == EXPECTED_JOB_KEYS


def test_job_response_has_no_snake_case_keys(client, db_conn, test_env):
    _insert_job(db_conn, test_env, _make_job({"id": "shape-test-3"}))
    resp = client.get("/api/jobs")
    job = resp.json()[0]
    snake_case_keys = {"source_id", "created_at", "posted_on", "closed_on",
                       "has_matched", "ai_metadata", "first_seen_at", "last_seen_at",
                       "consecutive_misses", "details_scraped"}
    assert not snake_case_keys.intersection(job.keys()), f"Found snake_case keys: {snake_case_keys.intersection(job.keys())}"


def test_details_and_ai_metadata_are_strings(client, db_conn, test_env):
    """Frontend expects details and aiMetadata as JSON strings, not parsed objects."""
    _insert_job(db_conn, test_env, _make_job({
        "id": "shape-test-4",
        "details": json.dumps({"salary_range": "$100k"}),
        "ai_metadata": json.dumps({"matched": True}),
    }))
    resp = client.get("/api/jobs/shape-test-4")
    job = resp.json()
    assert isinstance(job["details"], str)
    assert isinstance(job["aiMetadata"], str)
    # Should be valid JSON strings
    parsed_details = json.loads(job["details"])
    assert parsed_details["salary_range"] == "$100k"
    parsed_meta = json.loads(job["aiMetadata"])
    assert parsed_meta["matched"] is True


def test_scrape_run_response_has_camel_case_keys(client, db_conn, test_env):
    _insert_scrape_run(db_conn, test_env, {"run_id": "shape-run-1"})
    resp = client.get("/api/jobs-qa/scrape-runs")
    runs = resp.json()
    assert len(runs) == 1
    assert set(runs[0].keys()) == EXPECTED_SCRAPE_RUN_KEYS


def test_stats_response_has_camel_case_keys(client, db_conn, test_env):
    _insert_job(db_conn, test_env, _make_job({"id": "shape-stat-1"}))
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
