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

from scripts.shared.constants import SourceId

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
                "('fetch_greenhouse_company', 'enqueue_greenhouse_fan_out', "
                "'fetch_ashby_company', 'enqueue_ashby_fan_out', "
                "'fetch_eightfold_company', 'enqueue_eightfold_fan_out')"
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
    provider_config: dict | None = None,
) -> None:
    import json as _json

    cur = conn.cursor()
    if provider_config is None:
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
    else:
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
                "provider_config) "
                "VALUES (%s, %s, %s, %s, %s, CAST(%s AS JSONB))"
            ).format(sql.Identifier("companies")),
            (
                company_id,
                company_id.title(),
                ats,
                board_token if board_token is not None else company_id,
                enabled,
                _json.dumps(provider_config),
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
    _insert_job(db_conn, _make_job({"id": "g1", "company": "google", "source_id": SourceId.GOOGLE, "status": "OPEN"}))
    _insert_job(db_conn, _make_job({"id": "g2", "company": "google", "source_id": SourceId.GOOGLE, "status": "CLOSED"}))
    _insert_job(db_conn, _make_job({"id": "a1", "company": "apple", "source_id": SourceId.APPLE, "status": "OPEN"}))

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
    _insert_job(db_conn, _make_job({"id": "g3", "company": "google", "source_id": SourceId.GOOGLE, "status": "OPEN"}))
    _insert_job(db_conn, _make_job({"id": "a2", "company": "apple", "source_id": SourceId.APPLE, "status": "OPEN"}))
    _insert_job(db_conn, _make_job({"id": "a3", "company": "apple", "source_id": SourceId.APPLE, "status": "CLOSED"}))

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


# --- trigger-ashby-fetch / trigger-ashby-fan-out ---


def _ashby_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'fetch_ashby_company' "
        "ORDER BY id"
    )
    return list(cur.fetchall())


def _ashby_fan_out_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'enqueue_ashby_fan_out' "
        "ORDER BY id"
    )
    return list(cur.fetchall())


@pytest.mark.asyncio
async def test_trigger_ashby_fetch_returns_202_and_enqueues_job(
    procrastinate_open, db_conn, client,
):
    _seed_company(db_conn, "notion", ats="ashby", board_token="notion")

    resp = client.post(
        "/api/jobs-qa/trigger-ashby-fetch",
        params={"company_id": "notion"},
    )
    db_conn.rollback()

    assert resp.status_code == 202
    body = resp.json()
    assert body["company_id"] == "notion"
    assert body["already_enqueued"] is False
    assert "deferred" in body["message"]

    jobs = _ashby_jobs(db_conn)
    assert len(jobs) == 1
    assert jobs[0]["queueing_lock"] == "ashby:notion"
    assert jobs[0]["args"]["company_id"] == "notion"
    assert jobs[0]["args"]["board_token"] == "notion"


@pytest.mark.asyncio
async def test_trigger_ashby_fetch_404_for_unknown_company(
    procrastinate_open, db_conn, client,
):
    resp = client.post(
        "/api/jobs-qa/trigger-ashby-fetch",
        params={"company_id": "does_not_exist"},
    )
    db_conn.rollback()

    assert resp.status_code == 404
    assert "does_not_exist" in resp.json()["detail"]
    assert _ashby_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_ashby_fetch_404_for_disabled_company(
    procrastinate_open, db_conn, client,
):
    _seed_company(db_conn, "off", ats="ashby", enabled=False)
    resp = client.post(
        "/api/jobs-qa/trigger-ashby-fetch",
        params={"company_id": "off"},
    )
    db_conn.rollback()
    assert resp.status_code == 404
    assert _ashby_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_ashby_fetch_404_for_non_ashby_ats(
    procrastinate_open, db_conn, client,
):
    _seed_company(db_conn, "stripe", ats="greenhouse")
    resp = client.post(
        "/api/jobs-qa/trigger-ashby-fetch",
        params={"company_id": "stripe"},
    )
    db_conn.rollback()
    assert resp.status_code == 404
    assert _ashby_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_ashby_fetch_second_call_reports_already_enqueued(
    procrastinate_open, db_conn, client,
):
    _seed_company(db_conn, "notion", ats="ashby")

    first = client.post(
        "/api/jobs-qa/trigger-ashby-fetch",
        params={"company_id": "notion"},
    )
    db_conn.rollback()
    assert first.status_code == 202
    assert first.json()["already_enqueued"] is False

    second = client.post(
        "/api/jobs-qa/trigger-ashby-fetch",
        params={"company_id": "notion"},
    )
    db_conn.rollback()
    assert second.status_code == 202
    assert second.json()["already_enqueued"] is True

    assert len(_ashby_jobs(db_conn)) == 1


@pytest.mark.asyncio
async def test_trigger_ashby_fan_out_returns_202_and_enqueues_task(
    procrastinate_open, db_conn, client,
):
    resp = client.post("/api/jobs-qa/trigger-ashby-fan-out")
    db_conn.rollback()

    assert resp.status_code == 202
    body = resp.json()
    assert body["already_enqueued"] is False
    assert "deferred" in body["message"]

    jobs = _ashby_fan_out_jobs(db_conn)
    assert len(jobs) == 1
    assert jobs[0]["args"]["timestamp"] == 0


@pytest.mark.asyncio
async def test_trigger_ashby_fetch_after_fan_out_defer_collapses_via_lock(
    procrastinate_open, db_conn, client,
):
    """PLAN invariant: a manual /trigger-ashby-fetch issued AFTER the
    periodic fan-out has already deferred a per-company job for the same
    company collapses via the `ashby:<company_id>` queueing lock. The
    cross-origin race covers the case where the operator hits the manual
    trigger button while the periodic tick is mid-flight or has just
    landed its defers in the queue.

    Asserts: the manual trigger returns 202 with already_enqueued=True
    and exactly 1 fetch_ashby_company row exists for the company.
    """
    from api.tasks.enqueue_ashby_fan_out import enqueue_ashby_fan_out

    _seed_company(db_conn, "notion", ats="ashby")
    db_conn.rollback()

    # Periodic fan-out runs first — defers fetch_ashby_company with
    # queueing_lock="ashby:notion".
    deferred = await enqueue_ashby_fan_out(timestamp=0)
    db_conn.rollback()
    assert deferred == 1, (
        f"periodic fan-out should defer exactly 1 job for the seeded "
        f"company; got {deferred}"
    )

    # Manual trigger arrives second — must collapse via the same lock.
    resp = client.post(
        "/api/jobs-qa/trigger-ashby-fetch",
        params={"company_id": "notion"},
    )
    db_conn.rollback()
    assert resp.status_code == 202
    body = resp.json()
    assert body["already_enqueued"] is True, (
        "manual trigger after periodic fan-out must report "
        "already_enqueued=True; the queueing lock did not dedupe across "
        "the two origins"
    )

    jobs = _ashby_jobs(db_conn)
    assert len(jobs) == 1, (
        f"expected exactly 1 fetch_ashby_company row after fan-out + "
        f"manual trigger collision; got {len(jobs)}. Locks: "
        f"{[j['queueing_lock'] for j in jobs]}"
    )
    assert jobs[0]["queueing_lock"] == "ashby:notion"
    assert jobs[0]["args"]["company_id"] == "notion"


def test_trigger_ashby_fetch_without_admin_returns_403(test_app, db_conn):
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
            "/api/jobs-qa/trigger-ashby-fetch",
            params={"company_id": "notion"},
        )
        assert resp.status_code == 403
    finally:
        if saved_override is not None:
            test_app.dependency_overrides[require_admin] = saved_override


def test_trigger_ashby_fetch_without_auth_returns_401(test_app):
    """Sibling to the _without_admin_returns_403 test above: pop BOTH the
    require_admin and get_current_user overrides so the real auth chain
    runs without an Authorization header. Locks in the 401 branch — if the
    auth dependency order ever changes, regression here would otherwise be
    silent (the 403 test alone can't tell the difference)."""
    from fastapi.testclient import TestClient
    from api.auth.dependencies import get_current_user, require_admin

    saved_admin = test_app.dependency_overrides.pop(require_admin, None)
    saved_user = test_app.dependency_overrides.pop(get_current_user, None)
    try:
        local_client = TestClient(test_app)
        resp = local_client.post(
            "/api/jobs-qa/trigger-ashby-fetch",
            params={"company_id": "notion"},
        )
        assert resp.status_code == 401
    finally:
        if saved_admin is not None:
            test_app.dependency_overrides[require_admin] = saved_admin
        if saved_user is not None:
            test_app.dependency_overrides[get_current_user] = saved_user


def test_trigger_ashby_fan_out_without_admin_returns_403(test_app, db_conn):
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
        resp = local_client.post("/api/jobs-qa/trigger-ashby-fan-out")
        assert resp.status_code == 403
    finally:
        if saved_override is not None:
            test_app.dependency_overrides[require_admin] = saved_override


def test_trigger_ashby_fan_out_without_auth_returns_401(test_app):
    """Sibling to the _without_admin_returns_403 test above: pop BOTH the
    require_admin and get_current_user overrides so the real auth chain
    runs without an Authorization header. Mirrors
    test_trigger_ashby_fetch_without_auth_returns_401."""
    from fastapi.testclient import TestClient
    from api.auth.dependencies import get_current_user, require_admin

    saved_admin = test_app.dependency_overrides.pop(require_admin, None)
    saved_user = test_app.dependency_overrides.pop(get_current_user, None)
    try:
        local_client = TestClient(test_app)
        resp = local_client.post("/api/jobs-qa/trigger-ashby-fan-out")
        assert resp.status_code == 401
    finally:
        if saved_admin is not None:
            test_app.dependency_overrides[require_admin] = saved_admin
        if saved_user is not None:
            test_app.dependency_overrides[get_current_user] = saved_user


# --- Eightfold trigger endpoints (Unit 6) ---


VALID_NETFLIX_PROVIDER_CONFIG = {
    "tenant_host": "explore.jobs.netflix.net",
    "domain": "netflix.com",
}


def _eightfold_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'fetch_eightfold_company' "
        "ORDER BY id"
    )
    return list(cur.fetchall())


def _eightfold_fan_out_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'enqueue_eightfold_fan_out' "
        "ORDER BY id"
    )
    return list(cur.fetchall())


@pytest.mark.asyncio
async def test_trigger_eightfold_fetch_returns_202_and_enqueues_job(
    procrastinate_open, db_conn, client,
):
    _seed_company(
        db_conn, "netflix",
        ats="eightfold",
        provider_config=VALID_NETFLIX_PROVIDER_CONFIG,
    )

    resp = client.post(
        "/api/jobs-qa/trigger-eightfold-fetch",
        params={"company_id": "netflix"},
    )
    db_conn.rollback()

    assert resp.status_code == 202
    body = resp.json()
    assert body["company_id"] == "netflix"
    assert body["already_enqueued"] is False
    assert "deferred" in body["message"]

    jobs = _eightfold_jobs(db_conn)
    assert len(jobs) == 1
    assert jobs[0]["queueing_lock"] == "eightfold:netflix"
    assert jobs[0]["args"]["company_id"] == "netflix"
    assert jobs[0]["args"]["board_token"] == "netflix"
    assert jobs[0]["args"]["provider_config"] == VALID_NETFLIX_PROVIDER_CONFIG


@pytest.mark.asyncio
async def test_trigger_eightfold_fetch_404_for_unknown_company(
    procrastinate_open, db_conn, client,
):
    resp = client.post(
        "/api/jobs-qa/trigger-eightfold-fetch",
        params={"company_id": "nope_co"},
    )
    db_conn.rollback()

    assert resp.status_code == 404
    assert "nope_co" in resp.json()["detail"]
    assert _eightfold_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_eightfold_fetch_404_for_non_eightfold_ats(
    procrastinate_open, db_conn, client,
):
    _seed_company(db_conn, "stripe", ats="greenhouse")
    resp = client.post(
        "/api/jobs-qa/trigger-eightfold-fetch",
        params={"company_id": "stripe"},
    )
    db_conn.rollback()
    assert resp.status_code == 404
    assert _eightfold_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_eightfold_fetch_404_for_disabled_company(
    procrastinate_open, db_conn, client,
):
    _seed_company(
        db_conn, "off_co",
        ats="eightfold",
        enabled=False,
        provider_config=VALID_NETFLIX_PROVIDER_CONFIG,
    )
    resp = client.post(
        "/api/jobs-qa/trigger-eightfold-fetch",
        params={"company_id": "off_co"},
    )
    db_conn.rollback()
    assert resp.status_code == 404
    assert _eightfold_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_eightfold_fetch_400_for_missing_tenant_host(
    procrastinate_open, db_conn, client,
):
    """L2 SSRF defense at the trigger endpoint: missing tenant_host → 400."""
    _seed_company(
        db_conn, "bad_cfg",
        ats="eightfold",
        provider_config={"domain": "netflix.com"},  # tenant_host missing
    )
    resp = client.post(
        "/api/jobs-qa/trigger-eightfold-fetch",
        params={"company_id": "bad_cfg"},
    )
    db_conn.rollback()
    assert resp.status_code == 400
    assert "tenant_host" in resp.json()["detail"]
    assert _eightfold_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_eightfold_fetch_400_for_off_allowlist_tenant_host(
    procrastinate_open, db_conn, client,
):
    """L2 SSRF defense at the trigger endpoint: off-allowlist host → 400."""
    _seed_company(
        db_conn, "evil_cfg",
        ats="eightfold",
        provider_config={"tenant_host": "evil.com", "domain": "netflix.com"},
    )
    resp = client.post(
        "/api/jobs-qa/trigger-eightfold-fetch",
        params={"company_id": "evil_cfg"},
    )
    db_conn.rollback()
    assert resp.status_code == 400
    assert "SSRF allowlist" in resp.json()["detail"]
    assert _eightfold_jobs(db_conn) == []


@pytest.mark.asyncio
async def test_trigger_eightfold_fetch_second_call_reports_already_enqueued(
    procrastinate_open, db_conn, client,
):
    _seed_company(
        db_conn, "netflix",
        ats="eightfold",
        provider_config=VALID_NETFLIX_PROVIDER_CONFIG,
    )

    first = client.post(
        "/api/jobs-qa/trigger-eightfold-fetch",
        params={"company_id": "netflix"},
    )
    db_conn.rollback()
    assert first.status_code == 202
    assert first.json()["already_enqueued"] is False

    second = client.post(
        "/api/jobs-qa/trigger-eightfold-fetch",
        params={"company_id": "netflix"},
    )
    db_conn.rollback()
    assert second.status_code == 202
    assert second.json()["already_enqueued"] is True

    assert len(_eightfold_jobs(db_conn)) == 1


@pytest.mark.asyncio
async def test_trigger_eightfold_fan_out_returns_202_and_enqueues_task(
    procrastinate_open, db_conn, client,
):
    resp = client.post("/api/jobs-qa/trigger-eightfold-fan-out")
    db_conn.rollback()

    assert resp.status_code == 202
    body = resp.json()
    assert body["already_enqueued"] is False
    assert "deferred" in body["message"]

    jobs = _eightfold_fan_out_jobs(db_conn)
    assert len(jobs) == 1
    assert jobs[0]["args"]["timestamp"] == 0


def test_trigger_eightfold_fetch_without_admin_returns_403(test_app, db_conn):
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
            "/api/jobs-qa/trigger-eightfold-fetch",
            params={"company_id": "netflix"},
        )
        assert resp.status_code == 403
    finally:
        if saved_override is not None:
            test_app.dependency_overrides[require_admin] = saved_override


def test_trigger_eightfold_fetch_without_auth_returns_401(test_app):
    from fastapi.testclient import TestClient
    from api.auth.dependencies import get_current_user, require_admin

    saved_admin = test_app.dependency_overrides.pop(require_admin, None)
    saved_user = test_app.dependency_overrides.pop(get_current_user, None)
    try:
        local_client = TestClient(test_app)
        resp = local_client.post(
            "/api/jobs-qa/trigger-eightfold-fetch",
            params={"company_id": "netflix"},
        )
        assert resp.status_code == 401
    finally:
        if saved_admin is not None:
            test_app.dependency_overrides[require_admin] = saved_admin
        if saved_user is not None:
            test_app.dependency_overrides[get_current_user] = saved_user


def test_trigger_eightfold_fan_out_without_admin_returns_403(test_app, db_conn):
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
        resp = local_client.post("/api/jobs-qa/trigger-eightfold-fan-out")
        assert resp.status_code == 403
    finally:
        if saved_override is not None:
            test_app.dependency_overrides[require_admin] = saved_override


def test_trigger_eightfold_fan_out_without_auth_returns_401(test_app):
    from fastapi.testclient import TestClient
    from api.auth.dependencies import get_current_user, require_admin

    saved_admin = test_app.dependency_overrides.pop(require_admin, None)
    saved_user = test_app.dependency_overrides.pop(get_current_user, None)
    try:
        local_client = TestClient(test_app)
        resp = local_client.post("/api/jobs-qa/trigger-eightfold-fan-out")
        assert resp.status_code == 401
    finally:
        if saved_admin is not None:
            test_app.dependency_overrides[require_admin] = saved_admin
        if saved_user is not None:
            test_app.dependency_overrides[get_current_user] = saved_user
