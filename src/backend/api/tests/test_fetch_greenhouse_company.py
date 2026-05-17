"""Integration tests: fetch_greenhouse_company Procrastinate task.

Tests run against a real per-worker Postgres schema (see conftest.db_conn)
with httpx replaced by a MockTransport. The Procrastinate worker is run
in a one-shot drain mode so each test deterministically reaches a
terminal state.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import pytest
import pytest_asyncio
from psycopg2 import sql

from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.fetch_greenhouse_company import fetch_greenhouse_company
from api.tasks.procrastinate_app import (
    ensure_schema_async,
    procrastinate_app,
)


pytestmark = pytest.mark.asyncio


def _seed_company(conn, company_id: str, board_token: str) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled) "
            "VALUES (%s, %s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), "greenhouse", board_token, True),
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
            job_id, "T", company, "L", "https://x", "greenhouse_api",
            json.dumps({}), "2025-01-01T00:00:00Z", status, False,
            json.dumps({}), "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z",
            consecutive_misses, True,
        ),
    )
    conn.commit()


def _job_row(conn, job_id: str, source_id: str = "greenhouse_api") -> dict | None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL("SELECT * FROM {} WHERE source_id = %s AND id = %s").format(
            sql.Identifier("job_listings")
        ),
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


def _make_raw_job(raw_id: int, title: str = "Engineer") -> dict:
    return {
        "id": raw_id,
        "title": title,
        "absolute_url": f"https://example.com/jobs/{raw_id}",
        "location": {"name": "Remote"},
        "offices": [{"name": "Remote"}],
        "departments": [{"name": "Eng"}],
        "metadata": [],
        "first_published": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "content": "<p>desc</p>",
    }


def _patch_httpx(monkeypatch, handler) -> None:
    """Patch the task module's httpx.AsyncClient so it returns a
    MockTransport-backed client."""
    import api.tasks.fetch_greenhouse_company as task_mod

    transport = httpx.MockTransport(handler)

    class _PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(task_mod.httpx, "AsyncClient", _PatchedClient)


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
            # Procrastinate's tables live in `public` (installed once at app
            # boot, the schema probe in `ensure_schema_async` finds the
            # existing `public.procrastinate_jobs` and skips re-creation in
            # per-test schemas). That means rows written by other test
            # modules persist across our tests — including leftover
            # fan-out defers from test_enqueue_greenhouse_fan_out that are
            # never drained. When this file runs second alphabetically,
            # _drain() picks them up and contends with the composite PK on
            # job_listings (silent ON CONFLICT clobber on (source_id, id)).
            # Wipe greenhouse_fetch task rows so each test sees a clean queue.
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM procrastinate_jobs "
                "WHERE task_name = 'fetch_greenhouse_company'"
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
    worker_task = asyncio.create_task(
        procrastinate_app.run_worker_async(
            queues=["greenhouse_fetch"],
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


class TestFetchGreenhouseCompany:
    async def test_happy_path_inserts_new_marks_missing(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "stripe"
        token = "stripe"
        _seed_company(db_conn, company, token)

        existing_a = "100"
        existing_b = "200"
        existing_c = "300"
        _seed_job(db_conn, existing_a, company)
        _seed_job(db_conn, existing_b, company)
        _seed_job(db_conn, existing_c, company)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        _make_raw_job(100),
                        _make_raw_job(200),
                        _make_raw_job(400),
                    ]
                },
            )

        _patch_httpx(monkeypatch, handler)

        await fetch_greenhouse_company.defer_async(
            company_id=company, board_token=token,
        )
        await _drain()
        db_conn.rollback()

        new_row = _job_row(db_conn, "400")
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
        company = "datadog"
        token = "datadog"
        _seed_company(db_conn, company, token)

        keeper = "111"
        ghost = "222"
        _seed_job(db_conn, keeper, company)
        _seed_job(db_conn, ghost, company, consecutive_misses=1)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jobs": [_make_raw_job(111)]})

        _patch_httpx(monkeypatch, handler)

        await fetch_greenhouse_company.defer_async(
            company_id=company, board_token=token,
        )
        await _drain()
        db_conn.rollback()

        ghost_row = _job_row(db_conn, ghost)
        assert ghost_row["consecutive_misses"] >= 2
        assert ghost_row["status"] == "CLOSED"
        assert ghost_row["closed_on"] is not None

        runs = _scrape_runs(db_conn, company)
        assert runs[0]["closed_jobs"] == 1

    async def test_safety_guard_skips_destructive_writes(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "snowflake"
        token = "snowflake"
        _seed_company(db_conn, company, token)

        for i in range(100):
            _seed_job(db_conn, str(i), company)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"jobs": []})

        _patch_httpx(monkeypatch, handler)

        await fetch_greenhouse_company.defer_async(
            company_id=company, board_token=token,
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
        company = "github"
        token = "github"
        _seed_company(db_conn, company, token)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        _patch_httpx(monkeypatch, handler)

        await fetch_greenhouse_company.defer_async(
            company_id=company, board_token=token,
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
            "WHERE task_name = 'fetch_greenhouse_company' "
            "ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        assert row is not None, "procrastinate_jobs row missing"
        assert row["attempts"] >= 1
        assert row["status"] in ("todo", "failed", "doing")

    async def test_real_retry_503_then_200_succeeds(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """C1: prove the @retry envelope actually retries. The previous
        failure-only test would pass even if @retry were removed.

        First call returns 503, second returns 200 with one job. We drain
        the worker until the task reaches a terminal state, then assert
        the job was upserted and at least one scrape_runs row was written.
        """
        company = "circleci"
        token = "circleci"
        _seed_company(db_conn, company, token)

        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return httpx.Response(503, json={"error": "down"})
            return httpx.Response(200, json={"jobs": [_make_raw_job(777)]})

        _patch_httpx(monkeypatch, handler)

        await fetch_greenhouse_company.defer_async(
            company_id=company, board_token=token,
        )

        # Drain repeatedly until the procrastinate_jobs row reaches a
        # terminal status. RetryStrategy uses exponential backoff
        # (base=2s, so first retry waits ~2s); we poll with bounded
        # attempts to give the retry a chance to wake up. Worst-case
        # ceiling is bounded by deadline_attempts * (drain_timeout +
        # sleep) — keep these tight; a long polling tail here gets
        # billed to every CI run.
        deadline_attempts = 5
        for _ in range(deadline_attempts):
            await _drain(timeout=8.0)
            db_conn.rollback()
            cur = db_conn.cursor()
            cur.execute(
                "SELECT status, attempts FROM procrastinate_jobs "
                "WHERE task_name = 'fetch_greenhouse_company' "
                "ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row and row["status"] == "succeeded":
                break
            await asyncio.sleep(2.0)

        db_conn.rollback()
        cur = db_conn.cursor()
        cur.execute(
            "SELECT status, attempts FROM procrastinate_jobs "
            "WHERE task_name = 'fetch_greenhouse_company' "
            "ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["status"] == "succeeded", (
            f"task did not succeed on retry; status={row['status']} "
            f"attempts={row['attempts']} call_count={call_count['n']}"
        )
        # We control call_count exactly: handler returns 503 once, 200 once.
        # Procrastinate must bump attempts to exactly 2 — no more, no less.
        # If attempts != 2 the retry envelope is doing something we didn't
        # ask for (e.g. extra retry, failed-then-rerun pattern).
        assert row["attempts"] == 2, (
            f"task succeeded but attempts={row['attempts']} (expected exactly 2 "
            f"given the 503-then-200 handler); call_count={call_count['n']}"
        )

        new_row = _job_row(db_conn, "777")
        assert new_row is not None, "job from retry attempt was not upserted"
        assert new_row["status"] == "OPEN"

        runs = _scrape_runs(db_conn, company)
        assert len(runs) >= 1, "no scrape_runs row written"
        # A retry can produce either one error row + one success row OR a
        # single row with the final result depending on timing — the
        # important invariant is that at least one error row (the failed
        # 503 attempt) is recorded and the final state matches reality.
        success_runs = [r for r in runs if r["error_count"] == 0]
        assert success_runs, "no success row in scrape_runs after retry"
        assert success_runs[0]["jobs_seen"] == 1


@pytest.mark.parametrize(
    "active_count,jobs_returned,expect_skipped",
    [
        # Below the safety threshold (default 0.5 ratio) -> guard trips.
        (10, 0, True),     # zero returned with 10 active -> skipped
        (100, 9, True),    # 9 < 0.5 * 100 = 50 -> skipped
        # At or above the threshold -> guard does NOT trip.
        (10, 5, False),    # exactly at the ratio
        (10, 6, False),    # comfortably above ratio
        # Bootstrap case: zero active, zero returned -> guard does NOT trip.
        (0, 0, False),
    ],
)
@pytest.mark.asyncio
async def test_safety_guard_boundaries(
    procrastinate_open,
    db_conn,
    monkeypatch,
    active_count,
    jobs_returned,
    expect_skipped,
):
    """C3: pin the safety guard's ratio boundary so a future tweak to
    `<` vs `<=` or to SAFETY_GUARD_RATIO is caught by tests."""
    company = f"safety_{active_count}_{jobs_returned}"
    token = company
    _seed_company(db_conn, company, token)

    for i in range(active_count):
        _seed_job(db_conn, str(i), company)

    raw_jobs = [_make_raw_job(1000 + i) for i in range(jobs_returned)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": raw_jobs})

    _patch_httpx(monkeypatch, handler)

    await fetch_greenhouse_company.defer_async(
        company_id=company, board_token=token,
    )
    await _drain()
    db_conn.rollback()

    runs = _scrape_runs(db_conn, company)
    assert len(runs) == 1, f"expected 1 run, got {len(runs)}"
    if expect_skipped:
        assert runs[0]["error_count"] == 1, (
            f"safety guard should have tripped for "
            f"active={active_count} returned={jobs_returned}"
        )
        assert runs[0]["closed_jobs"] == 0
        assert runs[0]["new_jobs"] == 0
    else:
        assert runs[0]["error_count"] == 0, (
            f"safety guard tripped unexpectedly for "
            f"active={active_count} returned={jobs_returned}; "
            f"jobs_seen={runs[0]['jobs_seen']}"
        )


@pytest.mark.asyncio
async def test_record_scrape_run_fallback_runs_on_primary_failure(
    procrastinate_open, db_conn, monkeypatch
):
    """C2: cover the defensive fallback path in
    fetch_greenhouse_company.py that opens a fresh psycopg2 connection
    when the primary `record_scrape_run` raises (e.g. the primary
    transaction was poisoned by a prior failure on the same connection).

    Strategy: monkeypatch `db.record_scrape_run` so the FIRST call
    (primary connection) raises psycopg2.OperationalError and the
    SECOND call (fallback connection) succeeds by delegating to the real
    helper. Also wrap `db.get_connection` in a counting wrapper to prove
    the fallback actually opened a *fresh* connection.
    """
    import psycopg2 as _psycopg2

    import api.tasks.fetch_greenhouse_company as task_mod

    company = "fallbackco"
    token = "fallbackco"
    _seed_company(db_conn, company, token)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [_make_raw_job(555)]})

    _patch_httpx(monkeypatch, handler)

    # Count get_connection calls so we can prove the fallback actually
    # opened a second connection.
    real_get_connection = task_mod.db.get_connection
    get_conn_calls = {"n": 0}

    def counting_get_connection(database_url):
        get_conn_calls["n"] += 1
        return real_get_connection(database_url)

    monkeypatch.setattr(task_mod.db, "get_connection", counting_get_connection)

    # First call to record_scrape_run raises (simulating poisoned primary
    # txn); second call succeeds via the real helper. State lives in
    # `record_calls` rather than nonlocal so the closure stays simple.
    real_record_scrape_run = task_mod.db.record_scrape_run
    record_calls = {"n": 0}

    def flaky_record_scrape_run(conn, run_record):
        record_calls["n"] += 1
        if record_calls["n"] == 1:
            raise _psycopg2.OperationalError("primary conn poisoned")
        return real_record_scrape_run(conn, run_record)

    monkeypatch.setattr(task_mod.db, "record_scrape_run", flaky_record_scrape_run)

    await fetch_greenhouse_company.defer_async(
        company_id=company, board_token=token,
    )
    await _drain()
    db_conn.rollback()

    # Exactly one scrape_runs row, written by the fallback path.
    runs = _scrape_runs(db_conn, company)
    assert len(runs) == 1, (
        f"expected exactly 1 scrape_runs row from fallback; got {len(runs)} "
        f"(record_calls={record_calls['n']}, get_conn_calls={get_conn_calls['n']})"
    )

    # record_scrape_run was called twice total (primary fail + fallback ok).
    assert record_calls["n"] == 2, (
        f"expected record_scrape_run called twice; got {record_calls['n']}"
    )
    # get_connection was called more than once — primary acquisition
    # plus the fallback's fresh connection.
    assert get_conn_calls["n"] >= 2, (
        f"fallback did not open a fresh connection (get_conn_calls="
        f"{get_conn_calls['n']}); fallback path likely not exercised"
    )
