"""Integration tests: fetch_gem_company Procrastinate task.

Tests run against a real per-worker Postgres schema (see conftest.db_conn)
with httpx replaced by a MockTransport. The Procrastinate worker is run
in a one-shot drain mode so each test deterministically reaches a
terminal state.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest
import pytest_asyncio
from psycopg2 import sql

from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.fetch_gem_company import fetch_gem_company
from api.tasks.procrastinate_app import (
    ensure_schema_async,
    procrastinate_app,
)
from scripts.shared.constants import SourceId


pytestmark = pytest.mark.asyncio


def _seed_company(conn, company_id: str, board_token: str) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled) "
            "VALUES (%s, %s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), "gem", board_token, True),
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
            job_id, "T", company, "L", "https://x", SourceId.GEM,
            json.dumps({}), "2025-01-01T00:00:00Z", status, False,
            json.dumps({}), "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z",
            consecutive_misses, True,
        ),
    )
    conn.commit()


def _job_row(conn, job_id: str, source_id: str = SourceId.GEM) -> dict | None:
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


def _make_raw_job(raw_id: str, title: str = "Engineer") -> dict:
    return {
        "id": raw_id,
        "title": title,
        "absolute_url": f"https://jobs.gem.com/example/{raw_id}",
        "content": "<p>desc</p>",
        "content_plain": "desc",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "first_published_at": "2025-01-01T00:00:00Z",
        "employment_type": "full_time",
        "location_type": "remote",
        "location": {"name": "San Francisco"},
        "departments": [{"id": "d1", "name": "Engineering"}],
        "offices": [{"id": "o1", "name": "San Francisco"}],
        "internal_job_id": f"INT-{raw_id}",
        "requisition_id": f"REQ-{raw_id}",
    }


def _patch_httpx(monkeypatch, handler) -> None:
    """Patch the task module's httpx.AsyncClient so it returns a
    MockTransport-backed client."""
    import api.tasks.fetch_gem_company as task_mod

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
            # Procrastinate's tables are installed in the per-test schema
            # (see test_procrastinate_bootstrap.py — PGOPTIONS pins
            # search_path BEFORE open_async). Wipe any leftover Gem task
            # rows so each test sees a clean queue (mirrors the Ashby
            # test's cleanup of fan-out + per-company rows).
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM procrastinate_jobs "
                "WHERE task_name IN "
                "('fetch_gem_company', 'enqueue_gem_fan_out')"
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
    # Suspend the periodic registry while the test's worker is running.
    # Procrastinate's Worker unconditionally spins up a `periodic_deferrer`
    # side-coroutine; on a freshly-opened App, that deferrer backfills any
    # cron tick within the last 10 minutes (MAX_DELAY=600s in procrastinate
    # 2.15.1). For an `*/30 * * * *` periodic that means: if the test runs
    # within 10 minutes of :00 or :30 (i.e. roughly 1/3 of the clock), the
    # deferrer fires `enqueue_gem_fan_out`, the worker drains it, and the
    # fan-out defers a `fetch_gem_company` task for the test's seeded
    # company alongside the test's own deferred task. Both run, and the
    # missing-job `consecutive_misses` lifecycle gets incremented twice —
    # `assert c_row["consecutive_misses"] == 1` flakes to `2 == 1`.
    #
    # We disable the periodics by emptying the registry for the duration of
    # the drain. Tests that need fan-out semantics call the periodic task
    # directly via `await enqueue_gem_fan_out(timestamp=...)` and don't
    # rely on the deferrer.
    saved_periodics = procrastinate_app.periodic_registry.periodic_tasks
    procrastinate_app.periodic_registry.periodic_tasks = {}
    try:
        worker_task = asyncio.create_task(
            procrastinate_app.run_worker_async(
                queues=["gem_fetch"],
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


class TestFetchGemCompany:
    async def test_happy_path_inserts_new_marks_missing(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "retool"
        token = "retool"
        _seed_company(db_conn, company, token)

        # 3 existing jobs; API returns 2 of them + 1 new -> third becomes
        # missing (consecutive_misses=1). Mirrors the Ashby happy-path
        # coverage.
        existing_a = "gem-aaa"
        existing_b = "gem-bbb"
        existing_c = "gem-ccc"
        _seed_job(db_conn, existing_a, company)
        _seed_job(db_conn, existing_b, company)
        _seed_job(db_conn, existing_c, company)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    _make_raw_job("gem-aaa"),
                    _make_raw_job("gem-bbb"),
                    _make_raw_job("gem-ddd"),
                ],
            )

        _patch_httpx(monkeypatch, handler)

        await fetch_gem_company.defer_async(
            company_id=company, board_token=token,
        )
        await _drain()
        db_conn.rollback()

        new_row = _job_row(db_conn, "gem-ddd")
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
        company = "nominal"
        token = "nominal"
        _seed_company(db_conn, company, token)

        keeper = "gem-keep"
        ghost = "gem-ghost"
        _seed_job(db_conn, keeper, company)
        _seed_job(db_conn, ghost, company, consecutive_misses=1)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[_make_raw_job("gem-keep")])

        _patch_httpx(monkeypatch, handler)

        await fetch_gem_company.defer_async(
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

    async def test_cold_start_does_not_trip_safety_guard(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """No active jobs + 0 jobs from API must NOT trip the guard.

        Same cold-start guarantee as fetch_ashby_company. A brand-new
        Gem board with zero rows in ``job_listings`` and an empty (or
        temporarily empty) Gem response must record ``error_count=0``,
        not 1.
        """
        company = "freshgemboard"
        token = "freshgemboard"
        _seed_company(db_conn, company, token)

        # Critical: no _seed_job calls. active_count must be 0.

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        _patch_httpx(monkeypatch, handler)

        await fetch_gem_company.defer_async(
            company_id=company, board_token=token,
        )
        await _drain()
        db_conn.rollback()

        runs = _scrape_runs(db_conn, company)
        assert len(runs) == 1, (
            f"expected exactly 1 scrape_runs row for cold-start; "
            f"got {len(runs)}"
        )
        run = runs[0]
        assert run["error_count"] == 0, (
            "cold start (active=0, returned=0) must NOT trip the safety "
            "guard sentinel error_count=1; "
            f"got error_count={run['error_count']}"
        )
        assert run["jobs_seen"] == 0
        assert run["new_jobs"] == 0
        assert run["closed_jobs"] == 0

    async def test_safety_guard_skips_destructive_writes(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "gem"
        token = "gem"
        _seed_company(db_conn, company, token)

        for i in range(100):
            _seed_job(db_conn, f"gem-{i}", company)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        _patch_httpx(monkeypatch, handler)

        await fetch_gem_company.defer_async(
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
        company = "gem5xx"
        token = "gem5xx"
        _seed_company(db_conn, company, token)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        _patch_httpx(monkeypatch, handler)

        await fetch_gem_company.defer_async(
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
            "WHERE task_name = 'fetch_gem_company' "
            "ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        assert row is not None, "procrastinate_jobs row missing"
        assert row["attempts"] >= 1
        assert row["status"] in ("todo", "failed", "doing")

    async def test_programmer_error_propagates(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """AttributeError (and other programmer errors) must propagate
        rather than be swallowed by the narrow `except` block.

        Strategy: monkeypatch ``transform_to_job_listings`` to raise
        AttributeError. The narrow except in the task body catches only
        ``(httpx.HTTPError, ValueError, psycopg2.Error)``, so AttributeError
        must bubble up. Procrastinate marks the attempt failed/retried,
        but the scrape_runs ``finally`` block still records an error row
        with error_count=0 (because we never reach the ``scrape_error = e``
        assignment when the exception isn't caught by the narrow except).
        """
        import api.tasks.fetch_gem_company as task_mod

        company = "gemboom"
        token = "gemboom"
        _seed_company(db_conn, company, token)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[_make_raw_job("gem-x")])

        _patch_httpx(monkeypatch, handler)

        def boom(*args, **kwargs):
            raise AttributeError("simulated programmer error")

        monkeypatch.setattr(task_mod, "transform_to_job_listings", boom)

        await fetch_gem_company.defer_async(
            company_id=company, board_token=token,
        )
        await _drain()
        db_conn.rollback()

        runs = _scrape_runs(db_conn, company)
        assert len(runs) >= 1, "scrape_run finally block did not record"
        assert runs[0]["error_count"] == 0, (
            "AttributeError was caught by the narrow except (error_count=1); "
            "it should have propagated past the except block"
        )

        cur = db_conn.cursor()
        cur.execute(
            "SELECT status, attempts FROM procrastinate_jobs "
            "WHERE task_name = 'fetch_gem_company' "
            "ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        assert row is not None, "procrastinate_jobs row missing"
        assert row["attempts"] >= 1


@pytest.mark.asyncio
async def test_record_scrape_run_fallback_runs_on_primary_failure(
    procrastinate_open, db_conn, monkeypatch
):
    """Cover the defensive fallback path in fetch_gem_company.py that
    opens a fresh psycopg2 connection when the primary `record_scrape_run`
    raises (e.g. the primary transaction was poisoned by a prior failure
    on the same connection).
    """
    import psycopg2 as _psycopg2

    import api.tasks.fetch_gem_company as task_mod

    company = "gemfallbackco"
    token = "gemfallbackco"
    _seed_company(db_conn, company, token)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_make_raw_job("gem-fb")])

    _patch_httpx(monkeypatch, handler)

    real_get_connection = task_mod.db.get_connection
    get_conn_calls = {"n": 0}

    def counting_get_connection(database_url):
        get_conn_calls["n"] += 1
        return real_get_connection(database_url)

    monkeypatch.setattr(task_mod.db, "get_connection", counting_get_connection)

    real_record_scrape_run = task_mod.db.record_scrape_run
    record_calls = {"n": 0}

    def flaky_record_scrape_run(conn, run_record):
        record_calls["n"] += 1
        if record_calls["n"] == 1:
            raise _psycopg2.OperationalError("primary conn poisoned")
        return real_record_scrape_run(conn, run_record)

    monkeypatch.setattr(task_mod.db, "record_scrape_run", flaky_record_scrape_run)

    await fetch_gem_company.defer_async(
        company_id=company, board_token=token,
    )
    await _drain()
    db_conn.rollback()

    runs = _scrape_runs(db_conn, company)
    assert len(runs) == 1, (
        f"expected exactly 1 scrape_runs row from fallback; got {len(runs)} "
        f"(record_calls={record_calls['n']}, get_conn_calls={get_conn_calls['n']})"
    )

    assert record_calls["n"] == 2, (
        f"expected record_scrape_run called twice; got {record_calls['n']}"
    )
    assert get_conn_calls["n"] >= 2, (
        f"fallback did not open a fresh connection (get_conn_calls="
        f"{get_conn_calls['n']}); fallback path likely not exercised"
    )
