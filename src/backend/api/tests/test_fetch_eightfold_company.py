"""Integration tests: fetch_eightfold_company Procrastinate task.

Mirrors test_fetch_ashby_company.py in shape, plus adds Eightfold-specific
SSRF / provider_config validation cases. Tests run against a real
per-worker Postgres schema (see conftest.db_conn) with httpx replaced by
a MockTransport. The Procrastinate worker is run in a one-shot drain
mode so each test deterministically reaches a terminal state.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest
import pytest_asyncio
from psycopg2 import sql

from api.services.eightfold_client import _clear_verify_cache_for_testing
from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.fetch_eightfold_company import fetch_eightfold_company
from api.tasks.procrastinate_app import (
    ensure_schema_async,
    procrastinate_app,
)
from scripts.shared.constants import SourceId


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_verify_cache():
    """Drop the Layer 1 URL-verifier refetch cache between tests.

    Without this, the verifier's 60-second TTL cache holds the previous
    test's mocked positions list, so a fresh test's ghost-id assertion
    can fail by seeing the prior fixture's set. Production never needs
    this — it's purely test-isolation hygiene.
    """
    _clear_verify_cache_for_testing()
    yield
    _clear_verify_cache_for_testing()


NETFLIX_PROVIDER_CONFIG = {
    "tenant_host": "explore.jobs.netflix.net",
    "domain": "netflix.com",
}


def _seed_company(
    conn,
    company_id: str,
    *,
    ats: str = "eightfold",
    provider_config: dict | None = None,
) -> None:
    cur = conn.cursor()
    blob = json.dumps(provider_config or NETFLIX_PROVIDER_CONFIG)
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, "
            "provider_config) "
            "VALUES (%s, %s, %s, %s, %s, CAST(%s AS JSONB))"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), ats, company_id, True, blob),
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
            # URL shape matches Eightfold's ``canonicalPositionUrl`` so the
            # Layer 1 URL verifier can parse tenant_host + microsite from it.
            # The path netloc is on the SSRF allowlist (vanity host). Without
            # this, the verifier returns ``"unknown"`` and ``unknown_policy=
            # "skip"`` (Eightfold has a registered verifier) prevents the
            # close, and the test assertion that ghost gets CLOSED fails.
            job_id, "T", company, "L",
            f"https://explore.jobs.netflix.net/careers/job/{job_id}?microsite=netflix.com",
            SourceId.EIGHTFOLD,
            json.dumps({}), "2025-01-01T00:00:00Z", status, False,
            json.dumps({}), "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z",
            consecutive_misses, True,
        ),
    )
    conn.commit()


def _job_row(conn, job_id: str, source_id: str = SourceId.EIGHTFOLD) -> dict | None:
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


def _make_raw_position(raw_id: int, *, name: str = "Engineer") -> dict:
    return {
        "id": raw_id,
        "ats_job_id": f"req-{raw_id}",
        "display_job_id": f"R{raw_id:04d}",
        "name": name,
        "canonicalPositionUrl": f"https://explore.jobs.netflix.net/jobs/{raw_id}",
        "location": "Los Gatos,California,United States",
        "locations": ["Los Gatos,California,United States"],
        "department": "Engineering",
        "team": "Platform",
        "is_remote_eligible": False,
        "show_remote_eligibility": False,
        "t_create": 1_700_000_000,
        "isPrivate": False,
    }


def _patch_httpx(monkeypatch, handler) -> None:
    """Patch the task module's httpx.AsyncClient to use a MockTransport."""
    import api.tasks.fetch_eightfold_company as task_mod

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
            # Wipe leftover task rows for our names so each test sees a
            # clean queue — mirrors the Ashby test fixture comment about
            # cross-file leftovers and ON CONFLICT clobbers on
            # (source_id, id).
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM procrastinate_jobs "
                "WHERE task_name IN "
                "('fetch_eightfold_company', 'enqueue_eightfold_fan_out')"
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
    # Suspend periodics to avoid cross-task contention — see the long
    # comment in test_fetch_ashby_company.py for the rationale.
    saved_periodics = procrastinate_app.periodic_registry.periodic_tasks
    procrastinate_app.periodic_registry.periodic_tasks = {}
    try:
        worker_task = asyncio.create_task(
            procrastinate_app.run_worker_async(
                queues=["eightfold_fetch"],
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


class TestProviderConfigValidation:
    """L3 SSRF defense: provider_config is re-validated at task entry."""

    async def test_missing_tenant_host_raises_without_http(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        called = {"hits": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["hits"] += 1
            return httpx.Response(200, json={"count": 0, "positions": []})

        _patch_httpx(monkeypatch, handler)

        company = "broken1"
        _seed_company(db_conn, company)

        await fetch_eightfold_company.defer_async(
            company_id=company,
            board_token=company,
            provider_config={"domain": "netflix.com"},  # tenant_host missing
        )
        await _drain()
        db_conn.rollback()

        # The task raised early — no HTTP, but ValueError was caught by the
        # narrow except (it's in the {httpx, ValueError, psycopg2} tuple),
        # OR raised before reaching the except. Either way, no upstream call.
        assert called["hits"] == 0

    async def test_off_allowlist_tenant_host_raises_without_http(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        called = {"hits": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["hits"] += 1
            return httpx.Response(200, json={"count": 0, "positions": []})

        _patch_httpx(monkeypatch, handler)

        company = "broken2"
        _seed_company(
            db_conn, company,
            provider_config={
                "tenant_host": "evil.com",
                "domain": "netflix.com",
            },
        )

        await fetch_eightfold_company.defer_async(
            company_id=company,
            board_token=company,
            provider_config={
                "tenant_host": "evil.com",
                "domain": "netflix.com",
            },
        )
        await _drain()
        db_conn.rollback()

        assert called["hits"] == 0


class TestFetchEightfoldCompany:
    async def test_happy_path_inserts_new_marks_missing(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "netflix"
        _seed_company(db_conn, company)

        existing_a = "111"
        existing_b = "222"
        existing_c = "333"
        _seed_job(db_conn, existing_a, company)
        _seed_job(db_conn, existing_b, company)
        _seed_job(db_conn, existing_c, company)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "explore.jobs.netflix.net"
            assert request.url.path == "/api/apply/v2/jobs"
            return httpx.Response(
                200,
                json={
                    "count": 3,
                    "positions": [
                        _make_raw_position(111),
                        _make_raw_position(222),
                        _make_raw_position(444),  # new
                    ],
                },
            )

        _patch_httpx(monkeypatch, handler)

        await fetch_eightfold_company.defer_async(
            company_id=company,
            board_token=company,
            provider_config=NETFLIX_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        new_row = _job_row(db_conn, "444")
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
        company = "netflix"
        _seed_company(db_conn, company)

        keeper = "k1"
        ghost = "g1"
        _seed_job(db_conn, keeper, company)
        _seed_job(db_conn, ghost, company, consecutive_misses=1)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"count": 1, "positions": [
                    {**_make_raw_position(0), "id": "k1"}
                ]},
            )

        _patch_httpx(monkeypatch, handler)

        await fetch_eightfold_company.defer_async(
            company_id=company,
            board_token=company,
            provider_config=NETFLIX_PROVIDER_CONFIG,
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
        company = "freshflix"
        _seed_company(db_conn, company)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"count": 0, "positions": []})

        _patch_httpx(monkeypatch, handler)

        await fetch_eightfold_company.defer_async(
            company_id=company,
            board_token=company,
            provider_config=NETFLIX_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        runs = _scrape_runs(db_conn, company)
        assert len(runs) == 1
        run = runs[0]
        assert run["error_count"] == 0
        assert run["jobs_seen"] == 0
        assert run["new_jobs"] == 0
        assert run["closed_jobs"] == 0

    async def test_safety_guard_skips_destructive_writes(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "netflix"
        _seed_company(db_conn, company)

        for i in range(100):
            _seed_job(db_conn, f"seed-{i}", company)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"count": 0, "positions": []})

        _patch_httpx(monkeypatch, handler)

        await fetch_eightfold_company.defer_async(
            company_id=company,
            board_token=company,
            provider_config=NETFLIX_PROVIDER_CONFIG,
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

    async def test_http_5xx_records_failed_run(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        company = "netflix"
        _seed_company(db_conn, company)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        _patch_httpx(monkeypatch, handler)

        await fetch_eightfold_company.defer_async(
            company_id=company,
            board_token=company,
            provider_config=NETFLIX_PROVIDER_CONFIG,
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
        """AttributeError must propagate (no narrow-except swallow)."""
        import api.tasks.fetch_eightfold_company as task_mod

        company = "netflix"
        _seed_company(db_conn, company)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"count": 1, "positions": [_make_raw_position(99)]},
            )

        _patch_httpx(monkeypatch, handler)

        def boom(*args, **kwargs):
            raise AttributeError("simulated programmer error")

        monkeypatch.setattr(task_mod, "transform_to_job_listings", boom)

        await fetch_eightfold_company.defer_async(
            company_id=company,
            board_token=company,
            provider_config=NETFLIX_PROVIDER_CONFIG,
        )
        await _drain()
        db_conn.rollback()

        runs = _scrape_runs(db_conn, company)
        assert len(runs) >= 1
        assert runs[0]["error_count"] == 0, (
            "AttributeError was caught by the narrow except (error_count=1); "
            "it should have propagated past the except block"
        )

    async def test_task_timeout_records_failed_run(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """A task that hangs past `_TASK_TIMEOUT_S` raises asyncio.TimeoutError
        and is recorded with error_count=1 by the outer finally.

        Mirrors test_fetch_workday_company.py — all 6 ATS task files share
        the same wait_for + finally pattern; the guarantee must hold for
        every one of them, not just Workday.
        """
        import api.tasks.fetch_eightfold_company as task_mod

        monkeypatch.setattr(task_mod, "_TASK_TIMEOUT_S", 1.0)

        company = "netflix"
        _seed_company(db_conn, company)

        async def slow_handler(request: httpx.Request) -> httpx.Response:
            await asyncio.sleep(5.0)  # > _TASK_TIMEOUT_S → wait_for fires
            return httpx.Response(200, json={"count": 0, "positions": []})

        _patch_httpx(monkeypatch, slow_handler)

        await fetch_eightfold_company.defer_async(
            company_id=company,
            board_token=company,
            provider_config=NETFLIX_PROVIDER_CONFIG,
        )
        await _drain(timeout=10.0)
        db_conn.rollback()

        runs = _scrape_runs(db_conn, company)
        assert len(runs) == 1, "timed-out task must still record a scrape_runs row"
        assert runs[0]["error_count"] == 1
        assert runs[0]["jobs_seen"] == 0
