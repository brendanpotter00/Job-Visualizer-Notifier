"""Tests for /api/jobs-qa endpoints (stats, scrape runs, trigger scrape)."""

import os

import pytest
import pytest_asyncio
from psycopg2 import sql

from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.procrastinate_app import (
    ensure_schema_async,
    procrastinate_app,
)

from .conftest import _make_job, _insert_job, _insert_scrape_run


@pytest_asyncio.fixture
async def procrastinate_open(db_conn):
    schema = os.environ.get("PYTEST_SCHEMA")
    assert schema, "db_conn fixture must set PYTEST_SCHEMA"

    prev_pgoptions = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = f'-c search_path="{schema}",public'
    try:
        await procrastinate_app.open_async()
        try:
            await ensure_schema_async(procrastinate_app)
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM procrastinate_jobs "
                "WHERE task_name IN "
                "('fetch_greenhouse_company', 'enqueue_greenhouse_fan_out')"
            )
            cur.execute(
                sql.SQL("TRUNCATE {} CASCADE").format(
                    sql.Identifier("companies"),
                )
            )
            db_conn.commit()
            yield
        finally:
            await procrastinate_app.close_async()
    finally:
        if prev_pgoptions is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = prev_pgoptions


def _seed_company(
    conn,
    company_id: str,
    *,
    ats: str = "greenhouse",
    enabled: bool = True,
    board_token: str | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled) "
            "VALUES (%s, %s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (
            company_id,
            company_id.title(),
            ats,
            board_token if board_token is not None else company_id,
            enabled,
        ),
    )
    conn.commit()


def _greenhouse_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'fetch_greenhouse_company' "
        "ORDER BY id"
    )
    return list(cur.fetchall())


def _fan_out_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'enqueue_greenhouse_fan_out' "
        "ORDER BY id"
    )
    return list(cur.fetchall())


# --- trigger-scrape ---

def test_trigger_scrape_returns_202(client):
    resp = client.post("/api/jobs-qa/trigger-scrape", params={"company": "google"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["company"] == "google"
    assert "Scrape started" in body["message"]
    assert "google" in body["message"]


def test_trigger_scrape_defaults_to_google(client):
    resp = client.post("/api/jobs-qa/trigger-scrape")
    assert resp.status_code == 202
    assert resp.json()["company"] == "google"


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

def test_stats_returns_counts_for_all_companies(client, db_conn):
    # Override source_id on apple rows so the (source_id, id) composite-PK
    # rows are filed in their real namespace instead of inheriting
    # `_make_job`'s `google_scraper` default. Stats group by `company` so
    # this didn't break tests, but the fixture was lying about data shape.
    # Mirror the symmetric fix in test_jobs_router.py::seed_jobs.
    _insert_job(db_conn, _make_job({"id": "g1", "company": "google", "source_id": "google_scraper", "status": "OPEN"}))
    _insert_job(db_conn, _make_job({"id": "g2", "company": "google", "source_id": "google_scraper", "status": "CLOSED"}))
    _insert_job(db_conn, _make_job({"id": "a1", "company": "apple", "source_id": "apple_scraper", "status": "OPEN"}))

    resp = client.get("/api/jobs-qa/stats")
    assert resp.status_code == 200
    stats = resp.json()

    assert stats["totalJobs"] == 3
    assert stats["openJobs"] == 2
    assert stats["closedJobs"] == 1
    assert len(stats["companyCounts"]) == 2
    assert any(c["company"] == "google" and c["count"] == 2 for c in stats["companyCounts"])
    assert any(c["company"] == "apple" and c["count"] == 1 for c in stats["companyCounts"])


def test_stats_filters_by_company(client, db_conn):
    _insert_job(db_conn, _make_job({"id": "g3", "company": "google", "source_id": "google_scraper", "status": "OPEN"}))
    _insert_job(db_conn, _make_job({"id": "a2", "company": "apple", "source_id": "apple_scraper", "status": "OPEN"}))
    _insert_job(db_conn, _make_job({"id": "a3", "company": "apple", "source_id": "apple_scraper", "status": "CLOSED"}))

    resp = client.get("/api/jobs-qa/stats", params={"company": "apple"})
    stats = resp.json()

    assert stats["totalJobs"] == 2
    assert stats["openJobs"] == 1
    assert stats["closedJobs"] == 1
    assert len(stats["companyCounts"]) == 1
    assert stats["companyCounts"][0]["company"] == "apple"
    assert stats["companyCounts"][0]["count"] == 2


# --- scrape-runs ---

def test_scrape_runs_returns_all(client, db_conn):
    _insert_scrape_run(db_conn, {"run_id": "r-g1", "company": "google", "started_at": "2025-01-15T10:00:00Z", "completed_at": "2025-01-15T10:30:00Z", "mode": "incremental", "jobs_seen": 100, "new_jobs": 10, "closed_jobs": 5})
    _insert_scrape_run(db_conn, {"run_id": "r-a1", "company": "apple", "started_at": "2025-01-15T11:00:00Z", "completed_at": "2025-01-15T11:45:00Z", "mode": "full", "jobs_seen": 200, "new_jobs": 50, "closed_jobs": 10})
    _insert_scrape_run(db_conn, {"run_id": "r-g2", "company": "google", "started_at": "2025-01-16T10:00:00Z", "completed_at": "2025-01-16T10:30:00Z", "mode": "incremental", "jobs_seen": 102, "new_jobs": 2, "closed_jobs": 1})

    resp = client.get("/api/jobs-qa/scrape-runs")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_scrape_runs_filters_by_company(client, db_conn):
    _insert_scrape_run(db_conn, {"run_id": "r-g3", "company": "google", "started_at": "2025-01-15T10:00:00Z"})
    _insert_scrape_run(db_conn, {"run_id": "r-a2", "company": "apple", "started_at": "2025-01-15T11:00:00Z"})
    _insert_scrape_run(db_conn, {"run_id": "r-a3", "company": "apple", "started_at": "2025-01-16T11:00:00Z"})

    resp = client.get("/api/jobs-qa/scrape-runs", params={"company": "apple"})
    runs = resp.json()
    assert len(runs) == 2
    assert all(r["company"] == "apple" for r in runs)


def test_scrape_runs_respects_limit(client, db_conn):
    for i in range(30):
        _insert_scrape_run(db_conn, {"run_id": f"r-{i}", "started_at": f"2025-01-{i + 1:02d}T10:00:00Z"})

    resp = client.get("/api/jobs-qa/scrape-runs", params={"limit": 5})
    assert len(resp.json()) == 5


def test_scrape_runs_orders_by_started_at_descending(client, db_conn):
    _insert_scrape_run(db_conn, {"run_id": "r-old", "started_at": "2025-01-10T10:00:00Z"})
    _insert_scrape_run(db_conn, {"run_id": "r-new", "started_at": "2025-01-16T10:00:00Z"})
    _insert_scrape_run(db_conn, {"run_id": "r-mid", "started_at": "2025-01-13T10:00:00Z"})

    resp = client.get("/api/jobs-qa/scrape-runs")
    runs = resp.json()
    assert runs[0]["runId"] == "r-new"
    assert runs[1]["runId"] == "r-mid"
    assert runs[2]["runId"] == "r-old"


# --- trigger-greenhouse-fetch / trigger-greenhouse-fan-out ---


@pytest.mark.asyncio
async def test_trigger_greenhouse_fetch_returns_202_and_enqueues_job(
    procrastinate_open, db_conn, client,
):
    _seed_company(db_conn, "stripe", board_token="stripe")

    resp = client.post(
        "/api/jobs-qa/trigger-greenhouse-fetch",
        params={"company_id": "stripe"},
    )
    db_conn.rollback()

    assert resp.status_code == 202
    body = resp.json()
    assert body["company_id"] == "stripe"
    assert body["already_enqueued"] is False
    assert "deferred" in body["message"]

    jobs = _greenhouse_jobs(db_conn)
    assert len(jobs) == 1
    assert jobs[0]["queueing_lock"] == "greenhouse:stripe"
    assert jobs[0]["args"]["company_id"] == "stripe"
    assert jobs[0]["args"]["board_token"] == "stripe"


@pytest.mark.asyncio
async def test_trigger_greenhouse_fetch_404_for_unknown_company(
    procrastinate_open, db_conn, client,
):
    resp = client.post(
        "/api/jobs-qa/trigger-greenhouse-fetch",
        params={"company_id": "does_not_exist"},
    )
    db_conn.rollback()

    assert resp.status_code == 404
    assert "does_not_exist" in resp.json()["detail"]
    assert _greenhouse_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_greenhouse_fetch_404_for_disabled_company(
    procrastinate_open, db_conn, client,
):
    _seed_company(db_conn, "off", enabled=False)
    resp = client.post(
        "/api/jobs-qa/trigger-greenhouse-fetch",
        params={"company_id": "off"},
    )
    db_conn.rollback()
    assert resp.status_code == 404
    assert _greenhouse_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_greenhouse_fetch_404_for_non_greenhouse_ats(
    procrastinate_open, db_conn, client,
):
    _seed_company(db_conn, "lev", ats="lever")
    resp = client.post(
        "/api/jobs-qa/trigger-greenhouse-fetch",
        params={"company_id": "lev"},
    )
    db_conn.rollback()
    assert resp.status_code == 404
    assert _greenhouse_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_greenhouse_fetch_second_call_reports_already_enqueued(
    procrastinate_open, db_conn, client,
):
    _seed_company(db_conn, "stripe")

    first = client.post(
        "/api/jobs-qa/trigger-greenhouse-fetch",
        params={"company_id": "stripe"},
    )
    db_conn.rollback()
    assert first.status_code == 202
    assert first.json()["already_enqueued"] is False

    second = client.post(
        "/api/jobs-qa/trigger-greenhouse-fetch",
        params={"company_id": "stripe"},
    )
    db_conn.rollback()
    assert second.status_code == 202
    assert second.json()["already_enqueued"] is True

    assert len(_greenhouse_jobs(db_conn)) == 1


@pytest.mark.asyncio
async def test_trigger_greenhouse_fan_out_returns_202_and_enqueues_task(
    procrastinate_open, db_conn, client,
):
    resp = client.post("/api/jobs-qa/trigger-greenhouse-fan-out")
    db_conn.rollback()

    assert resp.status_code == 202
    body = resp.json()
    assert body["already_enqueued"] is False
    assert "deferred" in body["message"]

    jobs = _fan_out_jobs(db_conn)
    assert len(jobs) == 1
    assert jobs[0]["args"]["timestamp"] == 0


# --- admin auth gate on greenhouse trigger endpoints ---
#
# The default test_app fixture overrides require_admin so the happy-path
# tests above can call the endpoints without issuing real tokens. These
# two tests pop that override so we actually exercise the real
# require_admin dependency, mirroring the pattern in test_admin_router.py.
# A future endpoint added here without Depends(require_admin) would go
# undetected because every other test bypasses the gate via the override.


def test_trigger_greenhouse_fetch_without_admin_returns_403(test_app, db_conn):
    from fastapi.testclient import TestClient
    from api.auth.dependencies import require_admin
    from .conftest import _insert_user, _make_user

    _insert_user(
        db_conn,
        _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}),
    )
    db_conn.commit()

    saved_override = test_app.dependency_overrides.pop(require_admin, None)
    try:
        local_client = TestClient(test_app)
        resp = local_client.post(
            "/api/jobs-qa/trigger-greenhouse-fetch",
            params={"company_id": "stripe"},
        )
        assert resp.status_code == 403
    finally:
        if saved_override is not None:
            test_app.dependency_overrides[require_admin] = saved_override


def test_trigger_greenhouse_fan_out_without_admin_returns_403(test_app, db_conn):
    from fastapi.testclient import TestClient
    from api.auth.dependencies import require_admin
    from .conftest import _insert_user, _make_user

    _insert_user(
        db_conn,
        _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}),
    )
    db_conn.commit()

    saved_override = test_app.dependency_overrides.pop(require_admin, None)
    try:
        local_client = TestClient(test_app)
        resp = local_client.post("/api/jobs-qa/trigger-greenhouse-fan-out")
        assert resp.status_code == 403
    finally:
        if saved_override is not None:
            test_app.dependency_overrides[require_admin] = saved_override
