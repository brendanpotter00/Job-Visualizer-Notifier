"""Tests for GET /api/jobs and GET /api/jobs/{id} endpoints."""

import json

import pytest

from .conftest import _make_job, _insert_job


@pytest.fixture(autouse=True)
def seed_jobs(db_conn, test_env):
    """Seed the 4 default test jobs used by most tests."""
    jobs = [
        _make_job({"id": "google-123", "title": "Software Engineer", "company": "google",
                    "location": "Mountain View, CA", "status": "OPEN",
                    "last_seen_at": "2025-01-15T10:00:00Z"}),
        _make_job({"id": "google-456", "title": "Data Scientist", "company": "google",
                    "location": "New York, NY", "status": "CLOSED",
                    "last_seen_at": "2025-01-12T10:00:00Z"}),
        _make_job({"id": "apple-789", "title": "Machine Learning Engineer", "company": "apple",
                    "location": "Cupertino, CA", "status": "OPEN",
                    "last_seen_at": "2025-01-16T10:00:00Z"}),
        _make_job({"id": "apple-101", "title": "iOS Developer", "company": "apple",
                    "location": "Austin, TX", "status": "OPEN",
                    "last_seen_at": "2025-01-14T10:00:00Z"}),
    ]
    for job in jobs:
        _insert_job(db_conn, test_env, job)


def test_get_jobs_returns_all_when_no_filters(client):
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 4


def test_get_jobs_filters_by_company(client):
    resp = client.get("/api/jobs", params={"company": "google"})
    jobs = resp.json()
    assert len(jobs) == 2
    assert all(j["company"] == "google" for j in jobs)


def test_get_jobs_applies_limit(client):
    resp = client.get("/api/jobs", params={"limit": 2})
    assert len(resp.json()) == 2


def test_get_jobs_applies_offset(client):
    resp = client.get("/api/jobs", params={"offset": 2})
    assert len(resp.json()) == 2


def test_get_jobs_applies_limit_and_offset(client):
    resp = client.get("/api/jobs", params={"limit": 1, "offset": 1})
    assert len(resp.json()) == 1


def test_get_jobs_returns_empty_for_unknown_company(client):
    resp = client.get("/api/jobs", params={"company": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_jobs_orders_by_last_seen_at_descending(client):
    resp = client.get("/api/jobs")
    jobs = resp.json()
    last_seen_values = [j["lastSeenAt"] for j in jobs]
    assert last_seen_values == sorted(last_seen_values, reverse=True)


def test_get_job_by_id(client):
    resp = client.get("/api/jobs/google-123")
    assert resp.status_code == 200
    job = resp.json()
    assert job["id"] == "google-123"
    assert job["title"] == "Software Engineer"
    assert job["company"] == "google"


def test_get_job_returns_404_when_missing(client):
    resp = client.get("/api/jobs/nonexistent-id")
    assert resp.status_code == 404


def test_get_jobs_filters_by_status_open(client):
    resp = client.get("/api/jobs", params={"status": "OPEN"})
    jobs = resp.json()
    assert len(jobs) == 3
    assert all(j["status"] == "OPEN" for j in jobs)


def test_get_jobs_filters_by_status_closed(client):
    resp = client.get("/api/jobs", params={"status": "CLOSED"})
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "CLOSED"


def test_get_jobs_combines_company_and_status(client):
    resp = client.get("/api/jobs", params={"company": "google", "status": "OPEN"})
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["company"] == "google"
    assert jobs[0]["status"] == "OPEN"


# -- List endpoint returns trimmed details --


def test_list_endpoint_returns_trimmed_details(client, db_conn, test_env):
    """List endpoint strips large JSONB blobs, keeping only frontend-needed fields."""
    _insert_job(db_conn, test_env, _make_job({
        "id": "trim-test",
        "details": json.dumps({
            "experience_level": "Senior",
            "is_remote_eligible": True,
            "about_the_job": "A" * 5000,
            "minimum_qualifications": "B" * 5000,
        }),
        "ai_metadata": json.dumps({"scores": [1, 2, 3]}),
    }))
    resp = client.get("/api/jobs", params={"company": "google"})
    # Find our specific job (seed_jobs also inserts google jobs)
    job = next(j for j in resp.json() if j["id"] == "trim-test")
    details = json.loads(job["details"])
    assert details["experience_level"] == "Senior"
    assert details["is_remote_eligible"] is True
    assert "about_the_job" not in details
    assert "minimum_qualifications" not in details
    assert json.loads(job["aiMetadata"]) == {}


def test_detail_endpoint_returns_full_details(client, db_conn, test_env):
    """Detail endpoint still returns the full JSONB blobs."""
    full_details = {
        "experience_level": "Senior",
        "about_the_job": "Full description here",
    }
    _insert_job(db_conn, test_env, _make_job({
        "id": "detail-full-test",
        "details": json.dumps(full_details),
    }))
    resp = client.get("/api/jobs/detail-full-test")
    details = json.loads(resp.json()["details"])
    assert details["experience_level"] == "Senior"
    assert details["about_the_job"] == "Full description here"


def test_get_jobs_returns_iso8601_datetime_strings(client, db_conn, test_env):
    """After migrations 0003/0004, DB columns are timestamptz; Pydantic must
    serialize them as ISO 8601 strings matching the frontend BackendJobListing
    contract.
    """
    import re
    from datetime import datetime

    # Seed an extra job that populates the nullable timestamp fields so the
    # regex loop also exercises postedOn and closedOn (which are NULL on the
    # default seed fixture's rows).
    _insert_job(db_conn, test_env, _make_job({
        "id": "iso-fields-job",
        "status": "CLOSED",
        "posted_on": "2025-01-05T12:00:00Z",
        "closed_on": "2025-01-20T18:30:00Z",
        "last_seen_at": "2025-01-20T18:30:00Z",
    }))

    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) > 0

    # Conservative ISO 8601 regex: YYYY-MM-DDTHH:MM:SS with optional
    # microseconds and either a named offset or 'Z'.
    iso_re = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$"
    )

    saw_posted_on = False
    saw_closed_on = False
    for job in jobs:
        for field in ("createdAt", "firstSeenAt", "lastSeenAt"):
            value = job[field]
            assert isinstance(value, str), f"{field} must be str, got {type(value)}"
            assert iso_re.match(value), f"{field}={value!r} is not ISO 8601"
            # And it must round-trip via fromisoformat.
            datetime.fromisoformat(value)
        # postedOn / closedOn are nullable; check shape only when populated.
        for field in ("postedOn", "closedOn"):
            value = job.get(field)
            if value is None:
                continue
            assert isinstance(value, str), f"{field} must be str, got {type(value)}"
            assert iso_re.match(value), f"{field}={value!r} is not ISO 8601"
            datetime.fromisoformat(value)
            if field == "postedOn":
                saw_posted_on = True
            else:
                saw_closed_on = True

    # Guardrail: the seeded job above should have exercised both fields.
    assert saw_posted_on, "expected at least one job with non-null postedOn"
    assert saw_closed_on, "expected at least one job with non-null closedOn"
