"""Integration tests: enqueue_ashby_fan_out periodic task body."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from psycopg2 import sql

from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.enqueue_ashby_fan_out import enqueue_ashby_fan_out
from api.tasks.procrastinate_app import (
    ensure_schema_async,
    procrastinate_app,
)


pytestmark = pytest.mark.asyncio


def _seed_company(
    conn,
    company_id: str,
    *,
    ats: str = "ashby",
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


def _ashby_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'fetch_ashby_company' "
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
            # Procrastinate's tables are installed in the per-test schema
            # (see test_procrastinate_bootstrap.py:14-18 — PGOPTIONS pins
            # search_path BEFORE open_async, so apply_schema_async() lands
            # CREATE TABLE in test_<hex>, NOT in public). The module-scoped
            # db_conn keeps that schema alive for every test in this file,
            # so leftover defers from earlier tests in the module persist
            # across cases. Wipe both ashby task rows so each test sees a
            # clean queue. Also truncate the per-test `companies` table —
            # conftest's autouse cleanup does not include it.
            # Mirrors the IN-clause pattern from test_jobs_qa_router.py:31-34.
            # Do NOT schema-qualify as `public.procrastinate_jobs` — the
            # table lives in the per-test schema, resolved via the
            # PGOPTIONS search_path set above.
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM procrastinate_jobs "
                "WHERE task_name IN "
                "('fetch_ashby_company', 'enqueue_ashby_fan_out')"
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


class TestEnqueueAshbyFanOut:
    async def test_defers_one_job_per_enabled_ashby_company(
        self, procrastinate_open, db_conn
    ):
        enabled_ids = [f"co{i}" for i in range(5)]
        for cid in enabled_ids:
            _seed_company(db_conn, cid)

        _seed_company(db_conn, "disabled_co", enabled=False)
        _seed_company(db_conn, "greenhouse_co", ats="greenhouse")

        deferred = await enqueue_ashby_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 5

        jobs = _ashby_jobs(db_conn)
        assert len(jobs) == 5

        locks = {j["queueing_lock"] for j in jobs}
        expected_locks = {f"ashby:{cid}" for cid in enabled_ids}
        assert locks == expected_locks

        for j in jobs:
            args = j["args"]
            assert "company_id" in args
            assert "board_token" in args
            assert args["company_id"] in enabled_ids
            assert args["board_token"] == args["company_id"]

    async def test_already_enqueued_per_company_continues_loop(
        self, procrastinate_open, db_conn
    ):
        """Re-running the fan-out while the prior tick's per-company jobs
        are still pending must raise AlreadyEnqueued per company (caught
        and logged), let the loop continue, and produce zero new
        deferrals. The 3 jobs from the first run remain the only rows."""
        for cid in ("a", "b", "c"):
            _seed_company(db_conn, cid)

        first = await enqueue_ashby_fan_out(timestamp=0)
        db_conn.rollback()
        assert first == 3

        second = await enqueue_ashby_fan_out(timestamp=1)
        db_conn.rollback()
        assert second == 0

        jobs = _ashby_jobs(db_conn)
        assert len(jobs) == 3

    async def test_per_company_connector_error_does_not_abort_loop(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """A transient psycopg2 error on company N must NOT abort the
        loop and leave alphabetically-later companies unprocessed for the
        full 30-min window. Pinned by the narrowed
        `(procrastinate_exceptions.ConnectorException, psycopg2.Error)`
        catch in enqueue_ashby_fan_out.

        Strategy: monkeypatch fetch_ashby_company.configure(...).defer_async
        so that the third defer_async call raises psycopg2.OperationalError;
        all others delegate to the real implementation. Assert the loop
        continued and that companies BEFORE and AFTER company 3 still
        got deferred.
        """
        import psycopg2 as _psycopg2

        import api.tasks.enqueue_ashby_fan_out as fan_out_mod

        ids = [f"co{i}" for i in range(5)]
        for cid in ids:
            _seed_company(db_conn, cid)

        real_configure = fan_out_mod.fetch_ashby_company.configure
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
            fan_out_mod.fetch_ashby_company,
            "configure",
            configure_with_flaky_defer,
        )

        deferred = await enqueue_ashby_fan_out(timestamp=0)
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

        jobs = _ashby_jobs(db_conn)
        assert len(jobs) == 4

    async def test_programmer_error_propagates(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """A programmer error (AttributeError) inside the per-company defer
        path must propagate out of the fan-out — NOT be swallowed by the
        narrow `(ConnectorException, psycopg2.Error)` catch. Pinned by
        the same correctness-over-don't-crash rationale that narrows the
        catch in the first place: a deterministic bug masquerading as a
        transient blip would otherwise silently lose every tick."""
        import api.tasks.enqueue_ashby_fan_out as fan_out_mod

        for cid in ("a", "b", "c"):
            _seed_company(db_conn, cid)

        real_configure = fan_out_mod.fetch_ashby_company.configure

        def configure_with_buggy_defer(*args, **kwargs):
            configured = real_configure(*args, **kwargs)

            async def buggy_defer_async(*a, **kw):
                raise AttributeError("typo: bad attribute access in caller")

            configured.defer_async = buggy_defer_async
            return configured

        monkeypatch.setattr(
            fan_out_mod.fetch_ashby_company,
            "configure",
            configure_with_buggy_defer,
        )

        with pytest.raises(AttributeError):
            await enqueue_ashby_fan_out(timestamp=0)
        db_conn.rollback()

    async def test_no_enabled_companies_returns_zero(
        self, procrastinate_open, db_conn
    ):
        """Seed only disabled companies — fan-out returns 0 with no errors
        and no defers."""
        _seed_company(db_conn, "x", enabled=False)
        _seed_company(db_conn, "y", enabled=False)
        deferred = await enqueue_ashby_fan_out(timestamp=0)
        db_conn.rollback()
        assert deferred == 0
        assert _ashby_jobs(db_conn) == []
