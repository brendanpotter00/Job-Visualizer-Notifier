"""Tests for GET /api/jobs and GET /api/jobs/{id} endpoints."""

from .conftest import _make_job, _insert_job


def _seed_default_jobs(db_conn, test_env):
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


def test_get_jobs_returns_all_when_no_filters(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 4


def test_get_jobs_filters_by_company_google(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"company": "google"})
    jobs = resp.json()
    assert len(jobs) == 2
    assert all(j["company"] == "google" for j in jobs)


def test_get_jobs_filters_by_company_apple(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"company": "apple"})
    jobs = resp.json()
    assert len(jobs) == 2
    assert all(j["company"] == "apple" for j in jobs)


def test_get_jobs_applies_limit(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"limit": 2})
    assert len(resp.json()) == 2


def test_get_jobs_applies_offset(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"offset": 2})
    assert len(resp.json()) == 2


def test_get_jobs_applies_limit_and_offset(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"limit": 1, "offset": 1})
    assert len(resp.json()) == 1


def test_get_jobs_returns_empty_for_unknown_company(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"company": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_jobs_orders_by_last_seen_at_descending(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs")
    jobs = resp.json()
    last_seen_values = [j["lastSeenAt"] for j in jobs]
    assert last_seen_values == sorted(last_seen_values, reverse=True)


def test_get_job_by_id(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs/google-123")
    assert resp.status_code == 200
    job = resp.json()
    assert job["id"] == "google-123"
    assert job["title"] == "Software Engineer"
    assert job["company"] == "google"


def test_get_job_by_id_apple(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs/apple-789")
    assert resp.status_code == 200
    job = resp.json()
    assert job["id"] == "apple-789"
    assert job["title"] == "Machine Learning Engineer"
    assert job["company"] == "apple"


def test_get_job_returns_404_when_missing(client, db_conn, test_env):
    resp = client.get("/api/jobs/nonexistent-id")
    assert resp.status_code == 404


def test_get_jobs_combines_company_and_pagination(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"company": "apple", "limit": 1, "offset": 0})
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["company"] == "apple"


def test_get_jobs_filters_by_status_open(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"status": "OPEN"})
    jobs = resp.json()
    assert len(jobs) == 3
    assert all(j["status"] == "OPEN" for j in jobs)


def test_get_jobs_filters_by_status_closed(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"status": "CLOSED"})
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "CLOSED"


def test_get_jobs_combines_company_and_status(client, db_conn, test_env):
    _seed_default_jobs(db_conn, test_env)
    resp = client.get("/api/jobs", params={"company": "google", "status": "OPEN"})
    jobs = resp.json()
    assert len(jobs) == 1
    assert jobs[0]["company"] == "google"
    assert jobs[0]["status"] == "OPEN"
