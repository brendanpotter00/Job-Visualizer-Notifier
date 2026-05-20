"""Integration tests: enqueue_eightfold_fan_out periodic task body."""

from __future__ import annotations

import json
import os

import pytest
import pytest_asyncio
from psycopg2 import sql

from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.enqueue_eightfold_fan_out import enqueue_eightfold_fan_out
from api.tasks.procrastinate_app import (
    ensure_schema_async,
    procrastinate_app,
)


pytestmark = pytest.mark.asyncio


VALID_NETFLIX_CONFIG = {
    "tenant_host": "explore.jobs.netflix.net",
    "domain": "netflix.com",
}


def _seed_company(
    conn,
    company_id: str,
    *,
    ats: str = "eightfold",
    enabled: bool = True,
    provider_config: dict | None = None,
) -> None:
    cur = conn.cursor()
    blob = json.dumps(provider_config or VALID_NETFLIX_CONFIG)
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config) "
            "VALUES (%s, %s, %s, %s, %s, CAST(%s AS JSONB))"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), ats, company_id, enabled, blob),
    )
    conn.commit()


def _eightfold_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'fetch_eightfold_company' "
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
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM procrastinate_jobs "
                "WHERE task_name IN "
                "('fetch_eightfold_company', 'enqueue_eightfold_fan_out')"
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


class TestEnqueueEightfoldFanOut:
    async def test_defers_one_job_per_enabled_eightfold_company(
        self, procrastinate_open, db_conn
    ):
        # All 'eightfold' companies must use a tenant_host on the SSRF
        # allowlist — synthesize subdomain.eightfold.ai hosts for testing
        # alongside the real Netflix vanity host.
        enabled_configs = {
            "netflix": VALID_NETFLIX_CONFIG,
            "synth_a": {"tenant_host": "a.eightfold.ai", "domain": "a.com"},
            "synth_b": {"tenant_host": "b.eightfold.ai", "domain": "b.com"},
        }
        for cid, cfg in enabled_configs.items():
            _seed_company(db_conn, cid, provider_config=cfg)

        # A disabled eightfold row + a Greenhouse row must be ignored.
        _seed_company(db_conn, "disabled_co", enabled=False)
        _seed_company(
            db_conn, "greenhouse_co",
            ats="greenhouse",
            provider_config={},
        )

        deferred = await enqueue_eightfold_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 3

        jobs = _eightfold_jobs(db_conn)
        assert len(jobs) == 3

        locks = {j["queueing_lock"] for j in jobs}
        assert locks == {f"eightfold:{cid}" for cid in enabled_configs}

        for j in jobs:
            args = j["args"]
            assert "company_id" in args
            assert "board_token" in args
            assert "provider_config" in args
            assert args["company_id"] in enabled_configs
            # board_token mirrors id in our seed shape
            assert args["board_token"] == args["company_id"]
            # provider_config flows through 1:1
            assert args["provider_config"] == enabled_configs[args["company_id"]]

    async def test_skips_row_with_missing_provider_config_keys(
        self, procrastinate_open, db_conn
    ):
        """L2 SSRF defense: bad provider_config rows are skipped, not deferred.

        Sub-cases:
          - missing tenant_host
          - missing domain
          - tenant_host off the SSRF allowlist
        """
        # Good row
        _seed_company(db_conn, "good_co", provider_config=VALID_NETFLIX_CONFIG)

        # Missing tenant_host
        _seed_company(
            db_conn, "missing_host",
            provider_config={"domain": "x.com"},
        )

        # Missing domain
        _seed_company(
            db_conn, "missing_domain",
            provider_config={"tenant_host": "explore.jobs.netflix.net"},
        )

        # Off-allowlist tenant_host
        _seed_company(
            db_conn, "evil_host",
            provider_config={
                "tenant_host": "evil.com",
                "domain": "evil.com",
            },
        )

        deferred = await enqueue_eightfold_fan_out(timestamp=0)
        db_conn.rollback()

        # Only the good row deferred.
        assert deferred == 1
        jobs = _eightfold_jobs(db_conn)
        assert len(jobs) == 1
        assert jobs[0]["args"]["company_id"] == "good_co"

    async def test_already_enqueued_per_company_continues_loop(
        self, procrastinate_open, db_conn
    ):
        for cid in ("netflix",):
            _seed_company(db_conn, cid)

        first = await enqueue_eightfold_fan_out(timestamp=0)
        db_conn.rollback()
        assert first == 1

        # Re-run while the prior tick's per-company job is still pending.
        second = await enqueue_eightfold_fan_out(timestamp=1)
        db_conn.rollback()
        assert second == 0

        jobs = _eightfold_jobs(db_conn)
        assert len(jobs) == 1

    async def test_per_company_connector_error_does_not_abort_loop(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """A transient psycopg2 error on company N must NOT abort the loop."""
        import psycopg2 as _psycopg2

        import api.tasks.enqueue_eightfold_fan_out as fan_out_mod

        configs = {
            f"co{i}": {
                "tenant_host": f"co{i}.eightfold.ai",
                "domain": f"co{i}.com",
            }
            for i in range(5)
        }
        for cid, cfg in configs.items():
            _seed_company(db_conn, cid, provider_config=cfg)

        real_configure = fan_out_mod.fetch_eightfold_company.configure
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
            fan_out_mod.fetch_eightfold_company,
            "configure",
            configure_with_flaky_defer,
        )

        deferred = await enqueue_eightfold_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 4
        assert call_count["n"] == 5

        jobs = _eightfold_jobs(db_conn)
        assert len(jobs) == 4

    async def test_programmer_error_propagates(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """AttributeError inside per-company defer must propagate."""
        import api.tasks.enqueue_eightfold_fan_out as fan_out_mod

        for cid in ("a", "b", "c"):
            _seed_company(
                db_conn, cid,
                provider_config={
                    "tenant_host": f"{cid}.eightfold.ai",
                    "domain": f"{cid}.com",
                },
            )

        real_configure = fan_out_mod.fetch_eightfold_company.configure

        def configure_with_buggy_defer(*args, **kwargs):
            configured = real_configure(*args, **kwargs)

            async def buggy_defer_async(*a, **kw):
                raise AttributeError("typo: bad attribute access in caller")

            configured.defer_async = buggy_defer_async
            return configured

        monkeypatch.setattr(
            fan_out_mod.fetch_eightfold_company,
            "configure",
            configure_with_buggy_defer,
        )

        with pytest.raises(AttributeError):
            await enqueue_eightfold_fan_out(timestamp=0)
        db_conn.rollback()

    async def test_no_enabled_companies_returns_zero(
        self, procrastinate_open, db_conn
    ):
        _seed_company(db_conn, "x", enabled=False)
        deferred = await enqueue_eightfold_fan_out(timestamp=0)
        db_conn.rollback()
        assert deferred == 0
        assert _eightfold_jobs(db_conn) == []
