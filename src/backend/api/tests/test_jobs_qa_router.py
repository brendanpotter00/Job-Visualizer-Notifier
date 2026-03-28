"""Tests for /api/jobs-qa endpoints (stats, scrape runs, trigger scrape)."""

from .conftest import _make_job, _insert_job, _insert_scrape_run


# --- trigger-scrape ---

def test_trigger_scrape_returns_202(client):
    resp = client.post("/api/jobs-qa/trigger-scrape", params={"company": "google"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["company"] == "google"
    assert "google" in body["message"]


def test_trigger_scrape_defaults_to_google(client):
    resp = client.post("/api/jobs-qa/trigger-scrape")
    assert resp.status_code == 202
    assert resp.json()["company"] == "google"


def test_trigger_scrape_accepts_any_company(client):
    resp = client.post("/api/jobs-qa/trigger-scrape", params={"company": "custom-company"})
    assert resp.status_code == 202
    assert resp.json()["company"] == "custom-company"


def test_trigger_scrape_message_contains_company(client):
    resp = client.post("/api/jobs-qa/trigger-scrape", params={"company": "mycompany"})
    body = resp.json()
    assert "mycompany" in body["message"]
    assert "Scrape started" in body["message"]


def test_trigger_scrape_accepts_apple(client):
    resp = client.post("/api/jobs-qa/trigger-scrape", params={"company": "apple"})
    assert resp.status_code == 202
    assert resp.json()["company"] == "apple"


def test_trigger_scrape_returns_409_when_scrape_in_progress(client):
    from api.services.scraper_lock import scraper_lock
    import asyncio

    loop = asyncio.get_event_loop()
    loop.run_until_complete(scraper_lock.acquire())
    try:
        resp = client.post("/api/jobs-qa/trigger-scrape", params={"company": "google"})
        assert resp.status_code == 409
        assert "already in progress" in resp.json()["detail"]
    finally:
        scraper_lock.release()


# --- stats ---

def test_stats_returns_counts_for_all_companies(client, db_conn, test_env):
    _insert_job(db_conn, test_env, _make_job({"id": "g1", "company": "google", "status": "OPEN"}))
    _insert_job(db_conn, test_env, _make_job({"id": "g2", "company": "google", "status": "CLOSED"}))
    _insert_job(db_conn, test_env, _make_job({"id": "a1", "company": "apple", "status": "OPEN"}))

    resp = client.get("/api/jobs-qa/stats")
    assert resp.status_code == 200
    stats = resp.json()

    assert stats["totalJobs"] == 3
    assert stats["openJobs"] == 2
    assert stats["closedJobs"] == 1
    assert len(stats["companyCounts"]) == 2
    assert any(c["company"] == "google" and c["count"] == 2 for c in stats["companyCounts"])
    assert any(c["company"] == "apple" and c["count"] == 1 for c in stats["companyCounts"])


def test_stats_filters_by_company(client, db_conn, test_env):
    _insert_job(db_conn, test_env, _make_job({"id": "g3", "company": "google", "status": "OPEN"}))
    _insert_job(db_conn, test_env, _make_job({"id": "a2", "company": "apple", "status": "OPEN"}))
    _insert_job(db_conn, test_env, _make_job({"id": "a3", "company": "apple", "status": "CLOSED"}))

    resp = client.get("/api/jobs-qa/stats", params={"company": "apple"})
    stats = resp.json()

    assert stats["totalJobs"] == 2
    assert stats["openJobs"] == 1
    assert stats["closedJobs"] == 1
    assert len(stats["companyCounts"]) == 1
    assert stats["companyCounts"][0]["company"] == "apple"
    assert stats["companyCounts"][0]["count"] == 2


# --- scrape-runs ---

def test_scrape_runs_returns_all(client, db_conn, test_env):
    _insert_scrape_run(db_conn, test_env, {"run_id": "r-g1", "company": "google", "started_at": "2025-01-15T10:00:00Z", "completed_at": "2025-01-15T10:30:00Z", "mode": "incremental", "jobs_seen": 100, "new_jobs": 10, "closed_jobs": 5})
    _insert_scrape_run(db_conn, test_env, {"run_id": "r-a1", "company": "apple", "started_at": "2025-01-15T11:00:00Z", "completed_at": "2025-01-15T11:45:00Z", "mode": "full", "jobs_seen": 200, "new_jobs": 50, "closed_jobs": 10})
    _insert_scrape_run(db_conn, test_env, {"run_id": "r-g2", "company": "google", "started_at": "2025-01-16T10:00:00Z", "completed_at": "2025-01-16T10:30:00Z", "mode": "incremental", "jobs_seen": 102, "new_jobs": 2, "closed_jobs": 1})

    resp = client.get("/api/jobs-qa/scrape-runs")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_scrape_runs_filters_by_company(client, db_conn, test_env):
    _insert_scrape_run(db_conn, test_env, {"run_id": "r-g3", "company": "google", "started_at": "2025-01-15T10:00:00Z"})
    _insert_scrape_run(db_conn, test_env, {"run_id": "r-a2", "company": "apple", "started_at": "2025-01-15T11:00:00Z"})
    _insert_scrape_run(db_conn, test_env, {"run_id": "r-a3", "company": "apple", "started_at": "2025-01-16T11:00:00Z"})

    resp = client.get("/api/jobs-qa/scrape-runs", params={"company": "apple"})
    runs = resp.json()
    assert len(runs) == 2
    assert all(r["company"] == "apple" for r in runs)


def test_scrape_runs_respects_limit(client, db_conn, test_env):
    for i in range(30):
        _insert_scrape_run(db_conn, test_env, {"run_id": f"r-{i}", "started_at": f"2025-01-{i + 1:02d}T10:00:00Z"})

    resp = client.get("/api/jobs-qa/scrape-runs", params={"limit": 5})
    assert len(resp.json()) == 5


def test_scrape_runs_orders_by_started_at_descending(client, db_conn, test_env):
    _insert_scrape_run(db_conn, test_env, {"run_id": "r-old", "started_at": "2025-01-10T10:00:00Z"})
    _insert_scrape_run(db_conn, test_env, {"run_id": "r-new", "started_at": "2025-01-16T10:00:00Z"})
    _insert_scrape_run(db_conn, test_env, {"run_id": "r-mid", "started_at": "2025-01-13T10:00:00Z"})

    resp = client.get("/api/jobs-qa/scrape-runs")
    runs = resp.json()
    assert runs[0]["runId"] == "r-new"
    assert runs[1]["runId"] == "r-mid"
    assert runs[2]["runId"] == "r-old"
