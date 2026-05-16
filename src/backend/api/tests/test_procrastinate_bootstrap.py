"""Smoke test: Procrastinate worker plumbing.

Defers the bootstrap no-op task, drains it via the in-process worker, and
asserts the job row reaches a terminal ``succeeded`` state. If any of the
following are broken, this test fails:

- procrastinate package missing or wrong major version
- App singleton not configured (wrong DATABASE_URL, bad connector)
- ensure_schema_async() doesn't install procrastinate_jobs in the active schema
- run_worker_async() doesn't pick up tasks on the configured queue
- task module never gets imported (so ``bootstrap_noop`` isn't registered)

The existing module-scoped ``db_conn`` fixture provides the per-worker
Postgres schema isolation; this test rides on top of it. Procrastinate's
own schema lands inside that test schema because we set ``PGOPTIONS`` to
pin ``search_path`` for the connector's pool BEFORE ``open_async`` runs.
psycopg honors ``PGOPTIONS`` at connection time, so the per-pool connection
inherits the same per-test schema as the rest of the fixture.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

from api.tasks.procrastinate_app import (
    bootstrap_noop,
    ensure_schema_async,
    procrastinate_app,
)


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def procrastinate_open(db_conn):
    """Open Procrastinate against the active test schema for one test.

    ``db_conn`` is requested only for its module-scoped side effects: it sets
    ``PYTEST_SCHEMA``, materializes our ORM tables, and stamps Alembic. The
    Procrastinate connector opens its own pool via DATABASE_URL; we set
    ``PGOPTIONS`` here so its psycopg3 connections inherit the test schema's
    ``search_path``. Without this, Procrastinate would install its tables in
    ``public`` and the per-test schema isolation would break.
    """
    schema = os.environ.get("PYTEST_SCHEMA")
    assert schema, "db_conn fixture must set PYTEST_SCHEMA"

    prev_pgoptions = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = f'-c search_path="{schema}",public'
    try:
        await procrastinate_app.open_async()
        try:
            await ensure_schema_async(procrastinate_app)
            yield
        finally:
            await procrastinate_app.close_async()
    finally:
        if prev_pgoptions is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = prev_pgoptions


async def _drain_one_job(timeout: float = 10.0) -> None:
    """Run a short-lived worker until the queue drains, then exit.

    Procrastinate 2.x's ``run_worker_async`` accepts ``wait=False``, which
    tells the worker to exit once the queue is empty rather than blocking
    on LISTEN/NOTIFY forever. That's the documented test idiom for 2.x.
    Wrap with a wall-clock timeout so a stuck worker can't hang CI.
    """
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


class TestProcrastinateBootstrap:
    async def test_noop_task_runs_to_completion(self, procrastinate_open, db_conn):
        # Defer the no-op task.
        job_id = await bootstrap_noop.defer_async(payload="hello")
        assert job_id is not None

        # Drain via a one-shot worker.
        await _drain_one_job(timeout=10.0)

        # Verify terminal state directly in procrastinate_jobs. Use the
        # already-pinned db_conn (search_path is test_<hex>, public).
        cur = db_conn.cursor()
        cur.execute(
            "SELECT status FROM procrastinate_jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
        assert row is not None, "deferred job row missing from procrastinate_jobs"
        # RealDictCursor → row is a dict.
        assert row["status"] in ("succeeded", "done"), (
            f"expected terminal success status, got {row['status']!r}"
        )

    async def test_app_is_singleton(self):
        """A second import returns the same App object — tests in Unit 4+ that
        register tasks on this app must hit the same instance the worker uses.
        """
        from api.tasks import procrastinate_app as p1
        from api.tasks.procrastinate_app import procrastinate_app as p2

        assert p1 is p2
