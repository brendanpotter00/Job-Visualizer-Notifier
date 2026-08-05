"""Integration tests: fetch_workday_company Procrastinate task.

Mirrors test_fetch_lever_company verbatim, adapted for Workday's POST +
provider_config shape. Tests run against a real per-worker Postgres
schema (see conftest.db_conn) with httpx replaced by a MockTransport.
The Procrastinate worker is run in one-shot drain mode so each test
reaches a terminal state deterministically.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
import pytest
import pytest_asyncio
from psycopg2 import sql

from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.fetch_workday_company import fetch_workday_company
from api.tasks.procrastinate_app import (
    ensure_schema_async,
    procrastinate_app,
)
from scripts.shared.constants import SourceId


pytestmark = pytest.mark.asyncio


_PROVIDER_CONFIG: dict[str, Any] = {
    "base_url": "https://test.wd5.myworkdayjobs.com",
    "tenant_slug": "test",
    "career_site_slug": "TestCareerSite",
}


def _seed_company(
    conn,
    company_id: str,
    board_token: str,
    provider_config: dict[str, Any] | None = None,
) -> None:
    """Insert a Workday companies row with a JSONB provider_config.

    Workday-specific: also writes provider_config (other ATS seeds
    leave it as the server default '{}'::jsonb).
    """
    if provider_config is None:
        provider_config = _PROVIDER_CONFIG
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, provider_config) "
            "VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb))"
        ).format(sql.Identifier("companies")),
        (
            company_id, company_id.title(), "workday", board_token, True,
            json.dumps(provider_config),
        ),
    )
    conn.commit()


def _seed_job(
    conn,
    job_id: str,
    company: str,
    *,
    status: str = "OPEN",
    consecutive_misses: int = 0,
) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier("job_listings"),
            sql.SQL(", ").join(
                sql.Identifier(c)
                for c in (
                    "id", "title", "company", "location", "url", "source_id",
                    "details", "created_at", "status", "has_matched",
                    "ai_metadata", "first_seen_at", "last_seen_at",
                    "consecutive_misses", "details_scraped",
                )
            ),
            sql.SQL(", ").join(sql.Placeholder() for _ in range(15)),
        ),
        (
            job_id, "T", company, "L", "https://x", SourceId.WORKDAY,
            json.dumps({}), "2025-01-01T00:00:00Z", status, False,
            json.dumps({}), "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z",
            consecutive_misses, True,
        ),
    )
    conn.commit()
    # The AFTER INSERT trigger seeded job_freshness at consecutive_misses=0;
    # mirror the seeded value into the sidecar (freshness is authoritative there).
    if consecutive_misses:
        cur.execute(
            "UPDATE job_freshness SET consecutive_misses = %s "
            "WHERE source_id = %s AND id = %s",
            (consecutive_misses, SourceId.WORKDAY, job_id),
        )
        conn.commit()


def _job_row(conn, job_id: str, source_id: str = SourceId.WORKDAY) -> dict | None:
    cur = conn.cursor()
    cur.execute(
        # f.last_seen_at/f.consecutive_misses follow {0}.* in the select list,
        # so on the duplicate column names the RealDictCursor row keeps the
        # sidecar (authoritative) values, not the stale job_listings columns.
        sql.SQL(
            "SELECT {0}.*, f.last_seen_at, f.consecutive_misses "
            "FROM {0} JOIN job_freshness f "
            "ON f.source_id = {0}.source_id AND f.id = {0}.id "
            "WHERE {0}.source_id = %s AND {0}.id = %s"
        ).format(sql.Identifier("job_listings")),
        (source_id, job_id),
    )
    return cur.fetchone()


def _scrape_runs(conn, company: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "SELECT * FROM {} WHERE company = %s ORDER BY started_at DESC"
        ).format(sql.Identifier("scrape_runs")),
        (company,),
    )
    return list(cur.fetchall())


def _make_raw_workday_posting(req_id: str, title: str = "Engineer") -> dict:
    """Single-page Workday CXS posting fixture."""
    return {
        "title": title,
        "externalPath": f"/job/US-CA-Santa-Clara/{title.replace(' ', '-')}_{req_id}",
        "locationsText": "Santa Clara, CA",
        "postedOn": "Posted Today",
        "bulletFields": [req_id],
    }


def _make_workday_response(jobs: list[dict], total: int | None = None) -> dict:
    if total is None:
        total = len(jobs)
    return {"total": total, "jobPostings": jobs}


def _patch_httpx(monkeypatch, handler) -> None:
    """Patch the task module's httpx.AsyncClient so it returns a
    MockTransport-backed client."""
    import api.tasks.fetch_workday_company as task_mod

    transport = httpx.MockTransport(handler)

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(task_mod.httpx, "AsyncClient", _PatchedClient)


def _patch_normalize_defer(monkeypatch):
    """Patch normalize_location.configure so .defer_async is an AsyncMock.

    Canonical edge coverage (AlreadyEnqueued, safety-guard) lives in
    test_fetch_greenhouse_company.py. Returns (defer_mock, configure_calls).
    """
    from unittest.mock import AsyncMock, MagicMock

    import api.tasks.fetch_workday_company as task_mod

    defer_mock = AsyncMock(return_value=None)
    configure_calls = []

    def fake_configure(*args, **kwargs):
        configure_calls.append(kwargs)
        configured = MagicMock()
        configured.defer_async = defer_mock
        return configured

    monkeypatch.setattr(task_mod.normalize_location, "configure", fake_configure)
    return defer_mock, configure_calls


@pytest_asyncio.fixture
async def procrastinate_open(db_conn):
    """Open Procrastinate against the active test schema."""
    schema = os.environ.get("PYTEST_SCHEMA")
    assert schema, "db_conn fixture must set PYTEST_SCHEMA"

    prev_pgoptions = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = f'-c search_path="{schema}",public'
    try:
        await procrastinate_app.open_async()
        try:
            await ensure_schema_async(procrastinate_app)
            # Wipe leftover workday task rows from prior tests in this
            # module so each case starts with an empty queue. Mirrors
            # the cleanup pattern in test_fetch_lever_company.
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM procrastinate_jobs "
                "WHERE task_name IN "
                "('fetch_workday_company', 'enqueue_workday_fan_out')"
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


async def _drain(timeout: float = 15.0) -> None:
    # Disable periodic registry during drain — see test_fetch_lever_company
    # for the load-bearing explanation (Procrastinate's deferrer backfills
    # the last 10 minutes of cron ticks on a fresh App.open_async()).
    saved_periodics = procrastinate_app.periodic_registry.periodic_tasks
    procrastinate_app.periodic_registry.periodic_tasks = {}
    try:
        worker_task = asyncio.create_task(
            procrastinate_app.run_worker_async(
                queues=["workday_fetch"],
                concurrency=1,
                wait=False,
                install_signal_handlers=False,
            )
        )
        try:
            await asyncio.wait_for(worker_task, timeout=timeout)
        except asyncio.TimeoutError:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            raise
    finally:
        procrastinate_app.periodic_registry.periodic_tasks = saved_periodics


class TestFetchWorkdayCompany:
    async def test_happy_path_inserts_new_marks_missing(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "nvidia"
        token = "nvidia"
        _seed_company(db_conn, company, token)

        existing_a = "JR-AAA"
        existing_b = "JR-BBB"
        existing_c = "JR-CCC"
        _seed_job(db_conn, existing_a, company)
        _seed_job(db_conn, existing_b, company)
        _seed_job(db_conn, existing_c, company)

        # Workday returns JR-AAA, JR-BBB, JR-DDD; JR-CCC disappears.
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            jobs = [
                _make_raw_workday_posting("JR-AAA"),
                _make_raw_workday_posting("JR-BBB"),
                _make_raw_workday_posting("JR-DDD"),
            ]
            return httpx.Response(200, json=_make_workday_response(jobs))

        _patch_httpx(monkeypatch, handler)

        await fetch_workday_company.defer_async(
            company_id=company, board_token=token, provider_config=_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        new_row = _job_row(db_conn, "JR-DDD")
        assert new_row is not None, "new job not inserted"
        assert new_row["status"] == "OPEN"

        a_row = _job_row(db_conn, existing_a)
        b_row = _job_row(db_conn, existing_b)
        assert a_row["consecutive_misses"] == 0
        assert b_row["consecutive_misses"] == 0

        c_row = _job_row(db_conn, existing_c)
        assert c_row["consecutive_misses"] == 1
        assert c_row["status"] == "OPEN"

        runs = _scrape_runs(db_conn, company)
        assert len(runs) == 1
        assert runs[0]["mode"] == "full"
        assert runs[0]["jobs_seen"] == 3
        assert runs[0]["new_jobs"] == 1
        assert runs[0]["closed_jobs"] == 0
        assert runs[0]["error_count"] == 0

    async def test_second_run_closes_persistently_missing(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "adobe"
        token = "adobe"
        _seed_company(db_conn, company, token)

        keeper = "JR-KEEP"
        ghost = "JR-GHOST"
        _seed_job(db_conn, keeper, company)
        _seed_job(db_conn, ghost, company, consecutive_misses=1)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_make_workday_response([_make_raw_workday_posting("JR-KEEP")]),
            )

        _patch_httpx(monkeypatch, handler)

        await fetch_workday_company.defer_async(
            company_id=company, board_token=token, provider_config=_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        ghost_row = _job_row(db_conn, ghost)
        assert ghost_row["consecutive_misses"] >= 2
        assert ghost_row["status"] == "CLOSED"
        assert ghost_row["closed_on"] is not None

        runs = _scrape_runs(db_conn, company)
        assert runs[0]["closed_jobs"] == 1

    async def test_cold_start_does_not_trip_safety_guard(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """No active jobs + 0 jobs from API must NOT trip the guard.

        Mirrors the cold-start invariant from fetch_lever_company tests.
        The ``active_count > 0`` precondition is what protects brand-new
        Workday boards being onboarded — without it, every cold-start
        tick would record error_count=1 and mask real outages later.
        """
        company = "freshboard"
        token = "freshboard"
        _seed_company(db_conn, company, token)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_make_workday_response([], total=0))

        _patch_httpx(monkeypatch, handler)

        await fetch_workday_company.defer_async(
            company_id=company, board_token=token, provider_config=_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        runs = _scrape_runs(db_conn, company)
        assert len(runs) == 1
        assert runs[0]["error_count"] == 0
        assert runs[0]["jobs_seen"] == 0
        assert runs[0]["new_jobs"] == 0
        assert runs[0]["closed_jobs"] == 0

    async def test_safety_guard_skips_destructive_writes(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "snap"
        token = "snap"
        _seed_company(db_conn, company, token)

        for i in range(100):
            _seed_job(db_conn, f"JR-{i:04d}", company)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_make_workday_response([], total=0))

        _patch_httpx(monkeypatch, handler)

        await fetch_workday_company.defer_async(
            company_id=company, board_token=token, provider_config=_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        cur = db_conn.cursor()
        cur.execute(
            sql.SQL(
                "SELECT COUNT(*) AS n FROM {} "
                "WHERE company = %s AND (consecutive_misses > 0 OR status = 'CLOSED')"
            ).format(sql.Identifier("job_listings")),
            (company,),
        )
        assert cur.fetchone()["n"] == 0

        runs = _scrape_runs(db_conn, company)
        assert len(runs) == 1
        assert runs[0]["error_count"] == 1
        assert runs[0]["closed_jobs"] == 0
        assert runs[0]["jobs_seen"] == 0

    async def test_http_5xx_records_failed_run_and_raises(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "expedia"
        token = "expedia"
        _seed_company(db_conn, company, token)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        _patch_httpx(monkeypatch, handler)

        await fetch_workday_company.defer_async(
            company_id=company, board_token=token, provider_config=_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        runs = _scrape_runs(db_conn, company)
        assert len(runs) == 1
        assert runs[0]["error_count"] == 1
        assert runs[0]["jobs_seen"] == 0

        cur = db_conn.cursor()
        cur.execute(
            "SELECT status, attempts FROM procrastinate_jobs "
            "WHERE task_name = 'fetch_workday_company' "
            "ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        assert row is not None, "procrastinate_jobs row missing"
        assert row["attempts"] >= 1
        assert row["status"] in ("todo", "failed", "doing")

    async def test_missing_provider_config_keys_records_failed_run(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """A malformed `provider_config` (missing required keys) is
        data-driven, not a programmer error — it should record a failed
        run via the narrow except path (error_count=1) rather than
        bubble unhandled.
        """
        company = "blueorigin"
        token = "blueorigin"
        # Seed with a "valid" provider_config in the DB; the task will
        # be invoked with a corrupt one via defer_async kwargs.
        _seed_company(db_conn, company, token)

        # No httpx handler patched — should never be called.
        bad_config = {"base_url": "https://x.wd5.myworkdayjobs.com"}  # missing 2 keys

        await fetch_workday_company.defer_async(
            company_id=company, board_token=token, provider_config=bad_config,
        )
        await _drain()
        db_conn.rollback()

        runs = _scrape_runs(db_conn, company)
        assert len(runs) == 1
        assert runs[0]["error_count"] == 1
        assert runs[0]["jobs_seen"] == 0

    async def test_programmer_error_propagates(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """AttributeError (and other programmer errors) must propagate
        rather than be swallowed by the narrow `except` block. Mirrors
        the same invariant in fetch_lever_company.
        """
        import api.tasks.fetch_workday_company as task_mod

        company = "turo"
        token = "turo"
        _seed_company(db_conn, company, token)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_make_workday_response([_make_raw_workday_posting("JR-X")]),
            )

        _patch_httpx(monkeypatch, handler)

        def boom(*args, **kwargs):
            raise AttributeError("simulated programmer error")

        monkeypatch.setattr(task_mod, "transform_to_job_listings", boom)

        await fetch_workday_company.defer_async(
            company_id=company, board_token=token, provider_config=_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        runs = _scrape_runs(db_conn, company)
        assert len(runs) >= 1, "scrape_run finally block did not record"
        assert runs[0]["error_count"] == 0, (
            "AttributeError was caught by the narrow except (error_count=1); "
            "it should have propagated past the except block"
        )

    async def test_defers_normalize_for_new_ids_only(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """Unit 6: after a successful scrape, normalize_location is deferred
        for the NEW ids only, with a per-id queueing_lock. Canonical edge
        coverage (AlreadyEnqueued, safety-guard) lives in
        test_fetch_greenhouse_company.py.
        """
        company = "normwd"
        token = "normwd"
        _seed_company(db_conn, company, token)

        _seed_job(db_conn, "JR-AAA", company)
        _seed_job(db_conn, "JR-BBB", company)

        def handler(request: httpx.Request) -> httpx.Response:
            jobs = [
                _make_raw_workday_posting("JR-AAA"),
                _make_raw_workday_posting("JR-BBB"),
                _make_raw_workday_posting("JR-DDD"),
            ]
            return httpx.Response(200, json=_make_workday_response(jobs))

        _patch_httpx(monkeypatch, handler)
        defer_mock, configure_calls = _patch_normalize_defer(monkeypatch)

        await fetch_workday_company.defer_async(
            company_id=company, board_token=token, provider_config=_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        deferred_ids = {
            c.kwargs["job_id"] for c in defer_mock.await_args_list
        }
        assert deferred_ids == {"JR-DDD"}
        assert defer_mock.await_count == 1
        assert configure_calls == [{"queueing_lock": "normalize:JR-DDD"}]

        runs = _scrape_runs(db_conn, company)
        assert len(runs) == 1
        assert runs[0]["new_jobs"] == 1
        assert runs[0]["error_count"] == 0


@pytest.mark.asyncio
async def test_record_scrape_run_fallback_runs_on_primary_failure(
    procrastinate_open, db_conn, monkeypatch
):
    """Cover the defensive fallback path that opens a fresh psycopg2
    connection when the primary `record_scrape_run` raises (e.g. the
    primary transaction was poisoned by a prior failure on the same
    connection). Mirrors test_fetch_lever_company's verbatim test.
    """
    import psycopg2 as _psycopg2

    import api.tasks.fetch_workday_company as task_mod

    company = "workdayfallbackco"
    token = "workdayfallbackco"
    _seed_company(db_conn, company, token)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_make_workday_response([_make_raw_workday_posting("JR-FB")]),
        )

    _patch_httpx(monkeypatch, handler)

    # Count get_connection calls so we can prove the fallback actually
    # opened a second connection.
    real_get_connection = task_mod.db.get_connection
    get_conn_calls = {"n": 0}

    def counting_get_connection(database_url, **kwargs):
        get_conn_calls["n"] += 1
        return real_get_connection(database_url, **kwargs)

    monkeypatch.setattr(task_mod.db, "get_connection", counting_get_connection)

    # First call to record_scrape_run raises; second succeeds.
    real_record_scrape_run = task_mod.db.record_scrape_run
    record_calls = {"n": 0}

    def flaky_record_scrape_run(conn, run_record):
        record_calls["n"] += 1
        if record_calls["n"] == 1:
            raise _psycopg2.OperationalError("primary conn poisoned")
        return real_record_scrape_run(conn, run_record)

    monkeypatch.setattr(task_mod.db, "record_scrape_run", flaky_record_scrape_run)

    await fetch_workday_company.defer_async(
        company_id=company, board_token=token, provider_config=_PROVIDER_CONFIG,
    )
    await _drain()
    db_conn.rollback()

    runs = _scrape_runs(db_conn, company)
    assert len(runs) == 1, (
        f"expected exactly 1 scrape_runs row from fallback; got {len(runs)} "
        f"(record_calls={record_calls['n']}, get_conn_calls={get_conn_calls['n']})"
    )
    assert record_calls["n"] == 2
    assert get_conn_calls["n"] >= 2


async def test_task_timeout_records_failed_run(
    procrastinate_open, db_conn, monkeypatch
):
    """A task that hangs past `_TASK_TIMEOUT_S` raises asyncio.TimeoutError
    inside the handler and is recorded with error_count=1.

    We monkeypatch the constant to 1.0s and patch httpx to sleep 5s. With
    the wait_for in place, the timeout fires after ~1s and the finally
    block still records a scrape_runs row — proving the cancellation
    propagates through the outer try/finally cleanly. Without the
    wait_for, the inner await would block for the full 5s sleep and the
    task would record a *successful* run (jobs_seen=0), which is the
    exact silent-hang failure class this PR exists to prevent.
    """
    import api.tasks.fetch_workday_company as task_mod

    monkeypatch.setattr(task_mod, "_TASK_TIMEOUT_S", 1.0)

    company = "workdaytimeoutco"
    token = "workdaytimeoutco"
    _seed_company(db_conn, company, token)

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5.0)  # > _TASK_TIMEOUT_S → wait_for fires
        return httpx.Response(200, json=_make_workday_response([]))

    _patch_httpx(monkeypatch, slow_handler)

    await fetch_workday_company.defer_async(
        company_id=company, board_token=token, provider_config=_PROVIDER_CONFIG,
    )
    # Drain with a generous timeout — the task itself caps at 1s.
    await _drain(timeout=10.0)
    db_conn.rollback()

    runs = _scrape_runs(db_conn, company)
    assert len(runs) == 1, "timed-out task must still record a scrape_runs row"
    assert runs[0]["error_count"] == 1
    assert runs[0]["jobs_seen"] == 0
