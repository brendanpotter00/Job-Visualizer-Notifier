"""Integration tests: enqueue_greenhouse_fan_out periodic task body."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from psycopg2 import sql

from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.enqueue_greenhouse_fan_out import enqueue_greenhouse_fan_out
from api.tasks.procrastinate_app import (
    ensure_schema_async,
    procrastinate_app,
)


pytestmark = pytest.mark.asyncio


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
            # Procrastinate's tables live in `public` (installed once at app
            # boot, the schema probe in `ensure_schema_async` finds the
            # existing `public.procrastinate_jobs` and skips re-creation in
            # per-test schemas). That means rows written by other test
            # modules persist across our tests. Wipe both greenhouse task
            # rows so each test sees a clean queue. Also truncate the
            # per-test `companies` table — conftest's autouse cleanup does
            # not include it.
            # Schema-qualify `public.procrastinate_jobs` so this cleanup
            # survives a future schema-management change (and so it does
            # not depend on the search_path resolution we set above).
            # Mirrors the IN-clause pattern from test_jobs_qa_router.py:31-34.
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM public.procrastinate_jobs "
                "WHERE task_name IN "
                "('fetch_greenhouse_company', 'enqueue_greenhouse_fan_out')"
            )
            cur.execute(
                sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier("companies"))
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


class TestEnqueueGreenhouseFanOut:
    async def test_defers_one_job_per_enabled_greenhouse_company(
        self, procrastinate_open, db_conn
    ):
        enabled_ids = [f"co{i}" for i in range(5)]
        for cid in enabled_ids:
            _seed_company(db_conn, cid)

        _seed_company(db_conn, "disabled_co", enabled=False)
        _seed_company(db_conn, "lever_co", ats="lever")

        deferred = await enqueue_greenhouse_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 5

        jobs = _greenhouse_jobs(db_conn)
        assert len(jobs) == 5

        locks = {j["queueing_lock"] for j in jobs}
        expected_locks = {f"greenhouse:{cid}" for cid in enabled_ids}
        assert locks == expected_locks

        for j in jobs:
            args = j["args"]
            assert "company_id" in args
            assert "board_token" in args
            assert args["company_id"] in enabled_ids
            assert args["board_token"] == args["company_id"]

    async def test_second_call_is_noop_while_locks_held(
        self, procrastinate_open, db_conn
    ):
        for cid in ("a", "b", "c"):
            _seed_company(db_conn, cid)

        first = await enqueue_greenhouse_fan_out(timestamp=0)
        db_conn.rollback()
        assert first == 3

        second = await enqueue_greenhouse_fan_out(timestamp=1)
        db_conn.rollback()
        assert second == 0

        jobs = _greenhouse_jobs(db_conn)
        assert len(jobs) == 3

    async def test_no_enabled_companies_returns_zero(
        self, procrastinate_open, db_conn
    ):
        deferred = await enqueue_greenhouse_fan_out(timestamp=0)
        db_conn.rollback()
        assert deferred == 0
        assert _greenhouse_jobs(db_conn) == []

    async def test_disabled_only_returns_zero(self, procrastinate_open, db_conn):
        _seed_company(db_conn, "x", enabled=False)
        _seed_company(db_conn, "y", enabled=False)
        deferred = await enqueue_greenhouse_fan_out(timestamp=0)
        db_conn.rollback()
        assert deferred == 0
        assert _greenhouse_jobs(db_conn) == []

    async def test_full_45_company_fan_out(
        self, procrastinate_open, db_conn
    ):
        """I1: production-scale fan-out. The earlier tests use 3-5
        companies; this exercises the full 45-company seed size to
        catch any per-company defer regression that only manifests at
        scale (e.g. lock-table contention, batched commit failure)."""
        ids = [f"company_{i:02d}" for i in range(45)]
        for cid in ids:
            _seed_company(db_conn, cid)

        deferred = await enqueue_greenhouse_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 45, (
            f"expected 45 deferrals, got {deferred} (per-company "
            f"isolation may have failed silently)"
        )

        jobs = _greenhouse_jobs(db_conn)
        assert len(jobs) == 45

        locks = {j["queueing_lock"] for j in jobs}
        expected_locks = {f"greenhouse:{cid}" for cid in ids}
        assert locks == expected_locks

    async def test_per_company_psycopg2_error_does_not_abort_loop(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """A transient psycopg2 error on company N must NOT abort the
        loop and leave alphabetically-later companies unprocessed for the
        full 30-min window. Pinned by the narrowed
        `(procrastinate_exceptions.ConnectorException, psycopg2.Error)`
        catch in enqueue_greenhouse_fan_out.

        Strategy: monkeypatch fetch_greenhouse_company.configure(...).defer_async
        so that the third defer_async call raises psycopg2.OperationalError;
        all others delegate to the real implementation. Assert the loop
        continued and recorded `failed=1` while still deferring the other
        4 companies.
        """
        import psycopg2 as _psycopg2

        import api.tasks.enqueue_greenhouse_fan_out as fan_out_mod

        ids = [f"co{i}" for i in range(5)]
        for cid in ids:
            _seed_company(db_conn, cid)

        real_configure = fan_out_mod.fetch_greenhouse_company.configure
        call_count = {"n": 0}

        def configure_with_flaky_defer(*args, **kwargs):
            configured = real_configure(*args, **kwargs)
            real_defer = configured.defer_async

            async def flaky_defer_async(*a, **kw):
                call_count["n"] += 1
                if call_count["n"] == 3:
                    raise _psycopg2.OperationalError(
                        "transient connector blip on company 3"
                    )
                return await real_defer(*a, **kw)

            configured.defer_async = flaky_defer_async
            return configured

        monkeypatch.setattr(
            fan_out_mod.fetch_greenhouse_company,
            "configure",
            configure_with_flaky_defer,
        )

        deferred = await enqueue_greenhouse_fan_out(timestamp=0)
        db_conn.rollback()

        # 4 of 5 deferred; loop must NOT have aborted on the 3rd company.
        assert deferred == 4, (
            f"expected 4 successful deferrals after one psycopg2 error; "
            f"got {deferred}. If the loop aborted, deferred would be 2."
        )
        assert call_count["n"] == 5, (
            f"expected all 5 defer attempts; got {call_count['n']}. "
            f"Loop aborted early."
        )

        jobs = _greenhouse_jobs(db_conn)
        assert len(jobs) == 4
