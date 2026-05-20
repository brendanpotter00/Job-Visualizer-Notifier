"""Integration tests: enqueue_workday_fan_out periodic task body."""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
import pytest_asyncio
from psycopg2 import sql

from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.enqueue_workday_fan_out import enqueue_workday_fan_out
from api.tasks.procrastinate_app import (
    ensure_schema_async,
    procrastinate_app,
)


pytestmark = pytest.mark.asyncio


_DEFAULT_PROVIDER_CONFIG: dict[str, Any] = {
    "base_url": "https://test.wd5.myworkdayjobs.com",
    "tenant_slug": "test",
    "career_site_slug": "TestCareerSite",
}


def _seed_company(
    conn,
    company_id: str,
    *,
    ats: str = "workday",
    enabled: bool = True,
    board_token: str | None = None,
    provider_config: dict[str, Any] | None = None,
) -> None:
    if provider_config is None:
        # Per-row provider_config so the assertions can verify the
        # fan-out forwards the right blob per company.
        provider_config = {
            **_DEFAULT_PROVIDER_CONFIG,
            "tenant_slug": company_id,
            "career_site_slug": f"{company_id}_site",
        }
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, provider_config) "
            "VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb))"
        ).format(sql.Identifier("companies")),
        (
            company_id,
            company_id.title(),
            ats,
            board_token if board_token is not None else company_id,
            enabled,
            json.dumps(provider_config),
        ),
    )
    conn.commit()


def _workday_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'fetch_workday_company' "
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
            # Wipe leftover workday task rows from prior tests in this
            # module, and TRUNCATE companies (conftest's autouse cleanup
            # does not include it). Mirrors the lever fan-out test
            # cleanup pattern.
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM procrastinate_jobs "
                "WHERE task_name IN "
                "('fetch_workday_company', 'enqueue_workday_fan_out')"
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


class TestEnqueueWorkdayFanOut:
    async def test_defers_one_job_per_enabled_workday_company(
        self, procrastinate_open, db_conn
    ):
        enabled_ids = [f"co{i}" for i in range(5)]
        for cid in enabled_ids:
            _seed_company(db_conn, cid)

        _seed_company(db_conn, "disabled_co", enabled=False)
        _seed_company(db_conn, "greenhouse_co", ats="greenhouse")

        deferred = await enqueue_workday_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 5

        jobs = _workday_jobs(db_conn)
        assert len(jobs) == 5

        locks = {j["queueing_lock"] for j in jobs}
        expected_locks = {f"workday:{cid}" for cid in enabled_ids}
        assert locks == expected_locks

        # Each deferred job must carry the right per-company provider_config.
        for j in jobs:
            args = j["args"]
            assert set(args.keys()) >= {
                "company_id", "board_token", "provider_config"
            }
            assert args["company_id"] in enabled_ids
            assert args["board_token"] == args["company_id"]

            # Per-company provider_config preserved through the fan-out.
            cfg = args["provider_config"]
            assert isinstance(cfg, dict)
            assert cfg["tenant_slug"] == args["company_id"]
            assert cfg["career_site_slug"] == f"{args['company_id']}_site"
            assert cfg["base_url"] == _DEFAULT_PROVIDER_CONFIG["base_url"]

    async def test_already_enqueued_per_company_continues_loop(
        self, procrastinate_open, db_conn
    ):
        """Re-running the fan-out while the prior tick's per-company jobs
        are still pending must raise AlreadyEnqueued per company (caught
        and logged), let the loop continue, and produce zero new defers.
        """
        for cid in ("a", "b", "c"):
            _seed_company(db_conn, cid)

        first = await enqueue_workday_fan_out(timestamp=0)
        db_conn.rollback()
        assert first == 3

        second = await enqueue_workday_fan_out(timestamp=1)
        db_conn.rollback()
        assert second == 0

        jobs = _workday_jobs(db_conn)
        assert len(jobs) == 3

    async def test_per_company_connector_error_does_not_abort_loop(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """A transient psycopg2 error on company N must NOT abort the
        loop. Same narrow-catch invariant as the lever fan-out test."""
        import psycopg2 as _psycopg2

        import api.tasks.enqueue_workday_fan_out as fan_out_mod

        ids = [f"co{i}" for i in range(5)]
        for cid in ids:
            _seed_company(db_conn, cid)

        real_configure = fan_out_mod.fetch_workday_company.configure
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
            fan_out_mod.fetch_workday_company,
            "configure",
            configure_with_flaky_defer,
        )

        deferred = await enqueue_workday_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 4, (
            f"expected 4 successful deferrals after one psycopg2 error; "
            f"got {deferred}. If the loop aborted, deferred would be 2."
        )
        assert call_count["n"] == 5

        jobs = _workday_jobs(db_conn)
        assert len(jobs) == 4

    async def test_programmer_error_propagates(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """A programmer error (AttributeError) inside the per-company
        defer path must propagate out of the fan-out — NOT be swallowed
        by the narrow `(ConnectorException, psycopg2.Error)` catch."""
        import api.tasks.enqueue_workday_fan_out as fan_out_mod

        for cid in ("a", "b", "c"):
            _seed_company(db_conn, cid)

        real_configure = fan_out_mod.fetch_workday_company.configure

        def configure_with_buggy_defer(*args, **kwargs):
            configured = real_configure(*args, **kwargs)

            async def buggy_defer_async(*a, **kw):
                raise AttributeError("typo: bad attribute access in caller")

            configured.defer_async = buggy_defer_async
            return configured

        monkeypatch.setattr(
            fan_out_mod.fetch_workday_company,
            "configure",
            configure_with_buggy_defer,
        )

        with pytest.raises(AttributeError):
            await enqueue_workday_fan_out(timestamp=0)
        db_conn.rollback()

    async def test_no_enabled_companies_returns_zero(
        self, procrastinate_open, db_conn
    ):
        _seed_company(db_conn, "x", enabled=False)
        _seed_company(db_conn, "y", enabled=False)
        deferred = await enqueue_workday_fan_out(timestamp=0)
        db_conn.rollback()
        assert deferred == 0
        assert _workday_jobs(db_conn) == []

    async def test_empty_provider_config_still_defers(
        self, procrastinate_open, db_conn
    ):
        """An out-of-band Workday row with `provider_config='{}'::jsonb`
        (e.g. an operator forgot to fill it in) still gets deferred —
        the per-company task will validate and record a clean error,
        which is the right place for that signal (visible in scrape_runs
        + Railway @level:error). The fan-out's job is to defer, not to
        gate on row content.
        """
        _seed_company(db_conn, "broken", provider_config={})

        deferred = await enqueue_workday_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 1
        jobs = _workday_jobs(db_conn)
        assert len(jobs) == 1
        # The empty dict made it through end-to-end.
        assert jobs[0]["args"]["provider_config"] == {}
