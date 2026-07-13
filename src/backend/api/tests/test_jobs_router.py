"""Tests for GET /api/jobs and GET /api/jobs/{source_id}/{id} endpoints."""

import json

import pytest

from scripts.shared.constants import SourceId

from .conftest import _make_job, _insert_job


def _insert_location(conn, *, id, canonical_name, kind="city", city=None,
                     region=None, country=None, remote_scope=None) -> None:
    """Insert a canonical ``locations`` row with an explicit id."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO locations"
        " (id, canonical_name, kind, city, region, country, remote_scope)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (id, canonical_name, kind, city, region, country, remote_scope),
    )
    conn.commit()


def _link_job_location(conn, *, job_listing_id, normalized_location_id,
                       is_primary=False) -> None:
    """Link a job to a canonical location via the ``job_locations`` join."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO job_locations"
        " (job_listing_id, normalized_location_id, is_primary)"
        " VALUES (%s, %s, %s)",
        (job_listing_id, normalized_location_id, is_primary),
    )
    conn.commit()


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


def _parse_iso(value: str):
    from datetime import datetime
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_read_path_reflects_sidecar_not_stale_job_listings(client, db_conn):
    """Unit 3: both /api/jobs and /api/jobs/{id} source last_seen_at /
    consecutive_misses from the job_freshness sidecar (via JOIN), NOT the
    now-stale job_listings columns. Diverge the two tables and confirm the read
    follows the sidecar."""
    _insert_job(db_conn, _make_job({
        "id": "sidecar-read-1", "company": "google", "source_id": SourceId.GOOGLE,
        "status": "OPEN", "last_seen_at": "2025-01-01T00:00:00Z",
    }))
    cur = db_conn.cursor()
    # Sidecar advances (as the Unit-2 write path would)...
    cur.execute(
        "UPDATE job_freshness SET last_seen_at = %s, consecutive_misses = %s "
        "WHERE source_id = %s AND id = %s",
        ("2025-06-30T12:00:00Z", 7, SourceId.GOOGLE, "sidecar-read-1"),
    )
    # ...while the wide job_listings columns are left at a stale, different value.
    cur.execute(
        "UPDATE job_listings SET last_seen_at = %s, consecutive_misses = %s "
        "WHERE source_id = %s AND id = %s",
        ("2020-01-01T00:00:00Z", 99, SourceId.GOOGLE, "sidecar-read-1"),
    )
    db_conn.commit()

    listed = next(j for j in client.get("/api/jobs").json() if j["id"] == "sidecar-read-1")
    assert _parse_iso(listed["lastSeenAt"]) == _parse_iso("2025-06-30T12:00:00Z")
    assert listed["consecutiveMisses"] == 7

    detail = client.get(f"/api/jobs/{SourceId.GOOGLE}/sidecar-read-1").json()
    assert _parse_iso(detail["lastSeenAt"]) == _parse_iso("2025-06-30T12:00:00Z")
    assert detail["consecutiveMisses"] == 7


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
    # 151 distinct ids (one over the 150 cap)
    ids = ",".join(f"co{i}" for i in range(151))
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


# -- Normalized location tags (job_locations join) --


def test_get_jobs_includes_normalized_location_tags(client, db_conn):
    """A multi-location job exposes all its canonical tags, primary first.

    This is the contract the Recent Jobs location filter relies on: one job ->
    N location tags, so selecting "Austin, TX, US" matches a job that is also
    tagged Atlanta.
    """
    _insert_location(db_conn, id=9001, canonical_name="Austin, TX, US",
                     city="Austin", region="TX", country="US")
    _insert_location(db_conn, id=9002, canonical_name="Atlanta, GA, US",
                     city="Atlanta", region="GA", country="US")
    _insert_job(db_conn, _make_job({
        "id": "multi-loc-1", "company": "google", "source_id": SourceId.GOOGLE,
        "location": "Austin, TX, USA; Atlanta, GA, USA",
    }))
    # Insert non-primary first to prove ordering is by is_primary, not insert order.
    _link_job_location(db_conn, job_listing_id="multi-loc-1",
                       normalized_location_id=9002, is_primary=False)
    _link_job_location(db_conn, job_listing_id="multi-loc-1",
                       normalized_location_id=9001, is_primary=True)

    resp = client.get("/api/jobs", params={"company": "google"})
    assert resp.status_code == 200
    job = next(j for j in resp.json() if j["id"] == "multi-loc-1")

    tags = job["locations"]
    assert [t["canonicalName"] for t in tags] == ["Austin, TX, US", "Atlanta, GA, US"]
    assert tags[0]["isPrimary"] is True
    assert tags[1]["isPrimary"] is False
    assert tags[0]["kind"] == "city"
    assert tags[0]["city"] == "Austin"
    assert tags[0]["region"] == "TX"
    assert tags[0]["country"] == "US"
    assert tags[0]["remoteScope"] is None


def test_get_jobs_returns_empty_locations_for_unnormalized_job(client):
    """A job with no job_locations rows (unnormalized) returns locations: []."""
    resp = client.get("/api/jobs", params={"company": "apple"})
    # apple-101 (Austin, TX) is seeded with no normalized tags.
    job = next(j for j in resp.json() if j["id"] == "apple-101")
    assert job["locations"] == []


def test_get_job_by_id_includes_location_tags(client, db_conn):
    """The detail endpoint also surfaces the canonical location tags."""
    _insert_location(db_conn, id=9100, canonical_name="Remote (US)",
                     kind="remote", country="US", remote_scope="us")
    _insert_job(db_conn, _make_job({
        "id": "detail-loc-1", "company": "google", "source_id": SourceId.GOOGLE,
        "location": "Remote - US",
    }))
    _link_job_location(db_conn, job_listing_id="detail-loc-1",
                       normalized_location_id=9100, is_primary=True)

    resp = client.get(f"/api/jobs/{SourceId.GOOGLE}/detail-loc-1")
    assert resp.status_code == 200
    tags = resp.json()["locations"]
    assert len(tags) == 1
    assert tags[0]["canonicalName"] == "Remote (US)"
    assert tags[0]["kind"] == "remote"
    assert tags[0]["city"] is None
    assert tags[0]["remoteScope"] == "us"
