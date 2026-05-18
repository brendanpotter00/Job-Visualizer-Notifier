"""Tests for GET /api/jobs and GET /api/jobs/{source_id}/{id} endpoints."""

import json

import pytest

from scripts.shared.constants import SourceId

from .conftest import _make_job, _insert_job


@pytest.fixture(autouse=True)
def seed_jobs(db_conn):
    """Seed the 4 default test jobs used by most tests.

    `source_id` is set explicitly per company (google_scraper vs apple_scraper)
    so the seeded rows match the source they pretend to belong to. The default
    in `_make_job` is `google_scraper`, which would silently misfile apple rows
    if we relied on it — a future apple-route test addressing these ids would
    silently look in the wrong source namespace.
    """
    jobs = [
        _make_job({"id": "google-123", "title": "Software Engineer", "company": "google",
                    "source_id": SourceId.GOOGLE,
                    "location": "Mountain View, CA", "status": "OPEN",
                    "last_seen_at": "2025-01-15T10:00:00Z"}),
        _make_job({"id": "google-456", "title": "Data Scientist", "company": "google",
                    "source_id": SourceId.GOOGLE,
                    "location": "New York, NY", "status": "CLOSED",
                    "last_seen_at": "2025-01-12T10:00:00Z"}),
        _make_job({"id": "apple-789", "title": "Machine Learning Engineer", "company": "apple",
                    "source_id": SourceId.APPLE,
                    "location": "Cupertino, CA", "status": "OPEN",
                    "last_seen_at": "2025-01-16T10:00:00Z"}),
        _make_job({"id": "apple-101", "title": "iOS Developer", "company": "apple",
                    "source_id": SourceId.APPLE,
                    "location": "Austin, TX", "status": "OPEN",
                    "last_seen_at": "2025-01-14T10:00:00Z"}),
    ]
    for job in jobs:
        _insert_job(db_conn, job)


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
    resp = client.get(f"/api/jobs/{SourceId.GOOGLE}/google-123")
    assert resp.status_code == 200
    job = resp.json()
    assert job["id"] == "google-123"
    assert job["title"] == "Software Engineer"
    assert job["company"] == "google"


def test_get_job_returns_404_when_missing(client):
    resp = client.get(f"/api/jobs/{SourceId.GOOGLE}/nonexistent-id")
    assert resp.status_code == 404


def test_get_job_disambiguates_same_id_across_source_ids(client, db_conn):
    """Two jobs that share an `id` but differ in `source_id` must be
    addressable independently via /api/jobs/{source_id}/{id}. Catches a
    regression that drops `source_id = %s` from the WHERE clause — that
    bug would return the same row for both URLs.
    """
    shared_id = "collide-42"
    _insert_job(db_conn, _make_job({
        "id": shared_id,
        "source_id": SourceId.GOOGLE,
        "title": "Google Role",
        "company": "google",
    }))
    _insert_job(db_conn, _make_job({
        "id": shared_id,
        "source_id": SourceId.GREENHOUSE,
        "title": "Greenhouse Role",
        "company": "stripe",
    }))

    google_resp = client.get(f"/api/jobs/{SourceId.GOOGLE}/{shared_id}")
    assert google_resp.status_code == 200
    google_job = google_resp.json()
    assert google_job["id"] == shared_id
    assert google_job["title"] == "Google Role"
    assert google_job["company"] == "google"

    greenhouse_resp = client.get(f"/api/jobs/{SourceId.GREENHOUSE}/{shared_id}")
    assert greenhouse_resp.status_code == 200
    greenhouse_job = greenhouse_resp.json()
    assert greenhouse_job["id"] == shared_id
    assert greenhouse_job["title"] == "Greenhouse Role"
    assert greenhouse_job["company"] == "stripe"


def test_get_job_returns_404_when_source_id_mismatches_real_id(client, db_conn):
    """A real `id` looked up under the wrong `source_id` must 404 — proves
    the WHERE clause uses both columns.
    """
    real_id = "real-id-7"
    _insert_job(db_conn, _make_job({
        "id": real_id,
        "source_id": SourceId.GOOGLE,
        "title": "Real Google Role",
        "company": "google",
    }))

    # Confirm the row IS reachable under its real source_id (guards against
    # the test passing just because of a typo / missing seed).
    ok = client.get(f"/api/jobs/{SourceId.GOOGLE}/{real_id}")
    assert ok.status_code == 200

    mismatch = client.get(f"/api/jobs/{SourceId.GREENHOUSE}/{real_id}")
    assert mismatch.status_code == 404


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


# -- Batched `companies` query param (Recent Jobs page) --


def test_get_jobs_companies_returns_jobs_for_each_listed_company(client):
    resp = client.get("/api/jobs", params={"companies": "google,apple"})
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 4
    assert {j["company"] for j in jobs} == {"google", "apple"}


def test_get_jobs_companies_combines_with_status(client):
    resp = client.get("/api/jobs", params={"companies": "google,apple", "status": "OPEN"})
    jobs = resp.json()
    assert len(jobs) == 3
    assert all(j["status"] == "OPEN" for j in jobs)
    assert {j["company"] for j in jobs} == {"google", "apple"}


def test_get_jobs_companies_preserves_last_seen_order(client):
    resp = client.get("/api/jobs", params={"companies": "google,apple"})
    jobs = resp.json()
    last_seen_values = [j["lastSeenAt"] for j in jobs]
    assert last_seen_values == sorted(last_seen_values, reverse=True)


def test_get_jobs_companies_unknown_id_returns_subset(client):
    resp = client.get("/api/jobs", params={"companies": "google,nonexistent"})
    assert resp.status_code == 200
    jobs = resp.json()
    assert {j["company"] for j in jobs} == {"google"}


def test_get_jobs_companies_rejects_empty_value(client):
    resp = client.get("/api/jobs", params={"companies": ""})
    assert resp.status_code in (400, 422)


def test_get_jobs_companies_rejects_empty_id_in_list(client):
    resp = client.get("/api/jobs", params={"companies": "google,,apple"})
    assert resp.status_code == 400


def test_get_jobs_rejects_both_company_and_companies(client):
    resp = client.get(
        "/api/jobs", params={"company": "google", "companies": "google,apple"}
    )
    assert resp.status_code == 400


def test_get_jobs_companies_rejects_too_many_ids(client):
    # 101 distinct ids
    ids = ",".join(f"co{i}" for i in range(101))
    resp = client.get("/api/jobs", params={"companies": ids})
    assert resp.status_code == 400


def test_get_jobs_companies_rejects_invalid_id_pattern(client):
    resp = client.get("/api/jobs", params={"companies": "google,bad id"})
    assert resp.status_code == 400


# -- List endpoint returns trimmed details --


def test_list_endpoint_returns_trimmed_details(client, db_conn):
    """List endpoint strips large JSONB blobs, keeping only frontend-needed fields."""
    _insert_job(db_conn, _make_job({
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


def test_detail_endpoint_returns_full_details(client, db_conn):
    """Detail endpoint still returns the full JSONB blobs."""
    full_details = {
        "experience_level": "Senior",
        "about_the_job": "Full description here",
    }
    _insert_job(db_conn, _make_job({
        "id": "detail-full-test",
        "details": json.dumps(full_details),
    }))
    resp = client.get(f"/api/jobs/{SourceId.GOOGLE}/detail-full-test")
    details = json.loads(resp.json()["details"])
    assert details["experience_level"] == "Senior"
    assert details["about_the_job"] == "Full description here"


def test_get_jobs_returns_iso8601_datetime_strings(client, db_conn):
    """After migrations 0003/0004, DB columns are timestamptz; Pydantic must
    serialize them as ISO 8601 strings matching the frontend BackendJobListing
    contract.
    """
    import re
    from datetime import datetime

    # Seed an extra job that populates the nullable timestamp fields so the
    # regex loop also exercises postedOn and closedOn (which are NULL on the
    # default seed fixture's rows).
    _insert_job(db_conn, _make_job({
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
