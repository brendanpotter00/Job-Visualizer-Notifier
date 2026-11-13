"""The PUBLISHED recipe-board fan-out: what it selects, where it defers, and that it runs.

``enqueue_recipe_fan_out`` is the seventh fan-out — a ``*/30`` cron over
``companies.ats = 'recipe'``, deferring the SAME ``fetch_custom_company`` leaf task
the private custom lane uses. Three things have to hold, and each has a silent
failure mode:

1. **Selection.** Only ``ats='recipe' AND enabled AND visibility='public'``. A
   private board leaking in would be harvested by a public cron into a public
   namespace; a vendor board leaking in would be harvested twice.
2. **Lane separation.** It defers onto ``recipe_fetch``, not ``custom_ats_fetch``,
   so the private lane's backpressure ceiling of 3 is not spent on curated boards.
   (The budget half of that is pinned in ``test_claim_custom_companies.py``.)
3. **Registration.** A periodic task that is never imported is never scheduled, and
   nothing anywhere fails — the boards simply stop being harvested. Proven in a
   subprocess that imports only the ``api.tasks`` package.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from psycopg2 import sql

from api.main import _BULK_QUEUES, _INTERACTIVE_QUEUES
from api.services import custom_companies_service as ccs
from api.tasks import procrastinate_app as task_module_pkg  # noqa: F401
from api.tasks.enqueue_recipe_fan_out import enqueue_recipe_fan_out
from api.tasks.procrastinate_app import (
    CUSTOM_ATS_BULK_FETCH_QUEUE,
    CUSTOM_ATS_FIRST_FETCH_QUEUE,
    RECIPE_FETCH_QUEUE,
    ensure_schema_async,
    procrastinate_app,
)
from scripts.shared.constants import RECIPE_ATS

# NOT a module-level ``pytestmark``: the last two tests here are sync (lane
# membership and a subprocess import probe), and a blanket asyncio mark makes
# pytest-asyncio warn about them on every run.

_BACKEND = Path(__file__).resolve().parents[2]  # src/backend
_REPO_ROOT = _BACKEND.parents[1]


def _seed_company(
    db_conn,
    company_id: str,
    *,
    ats: str = RECIPE_ATS,
    enabled: bool = True,
    visibility: str = "public",
) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), ats, company_id, enabled, visibility),
    )
    db_conn.commit()


def _recipe_jobs(db_conn) -> list[dict]:
    cur = db_conn.cursor()
    cur.execute(
        "SELECT id, task_name, queue_name, args, queueing_lock, status "
        "FROM procrastinate_jobs "
        "WHERE task_name = 'fetch_custom_company' "
        "ORDER BY id"
    )
    return list(cur.fetchall())


@pytest_asyncio.fixture
async def procrastinate_open(db_conn):
    """Open the app against the per-test schema and start from a clean queue.

    Same shape as ``test_enqueue_ashby_fan_out``'s fixture, and for the same
    reasons: PGOPTIONS pins ``search_path`` BEFORE ``open_async`` so Procrastinate's
    tables land in ``test_<hex>``, and the module-scoped ``db_conn`` keeps that
    schema alive across every test here — so leftover defers must be wiped between
    cases, along with the per-test ``companies`` table (conftest's autouse cleanup
    does not include it).
    """
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
                "('fetch_custom_company', 'enqueue_recipe_fan_out')"
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


# --- selection ----------------------------------------------------------------


@pytest.mark.asyncio
class TestSelection:
    async def test_selects_only_enabled_public_recipe_companies(
        self, procrastinate_open, db_conn
    ):
        """THE selection contract, with one row per way it can be violated.

        A disabled recipe board, a PRIVATE recipe board, and a public vendor board
        are all seeded alongside the three that should be picked up. The private
        one is the important negative: it is ``ats='recipe'`` and enabled, so
        ``visibility`` is the only thing that can exclude it — and if it were
        included, a user's private board would be harvested by a public cron.
        """
        wanted = ["atlassian", "dell", "oracle"]
        for cid in wanted:
            _seed_company(db_conn, cid)

        _seed_company(db_conn, "disabled-recipe", enabled=False)
        _seed_company(db_conn, "u-privaterec", visibility="user")
        _seed_company(db_conn, "stripe", ats="greenhouse")

        deferred = await enqueue_recipe_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 3
        jobs = _recipe_jobs(db_conn)
        assert {j["args"]["company_id"] for j in jobs} == set(wanted)

    async def test_a_private_recipe_board_is_never_deferred_even_when_alone(
        self, procrastinate_open, db_conn
    ):
        """The negative on its own, so it cannot pass by being outvoted.

        With ONLY private recipe rows in the table the tick must return 0 and
        defer nothing — not "3 of 4", which a broken filter would still produce in
        the mixed case above if the assertion were only on the count.
        """
        _seed_company(db_conn, "u-priv1", visibility="user")
        _seed_company(db_conn, "u-priv2", visibility="user")

        deferred = await enqueue_recipe_fan_out(timestamp=0)
        db_conn.rollback()

        assert deferred == 0
        assert _recipe_jobs(db_conn) == []

    async def test_no_recipe_companies_returns_zero(self, procrastinate_open, db_conn):
        _seed_company(db_conn, "stripe", ats="greenhouse")
        deferred = await enqueue_recipe_fan_out(timestamp=0)
        db_conn.rollback()
        assert deferred == 0
        assert _recipe_jobs(db_conn) == []


# --- what the deferred job says -----------------------------------------------


@pytest.mark.asyncio
class TestDeferShape:
    async def test_the_job_rides_the_recipe_queue_with_the_shared_company_lock(
        self, procrastinate_open, db_conn
    ):
        """Queue, lock and args, all three.

        * ``recipe_fetch``, NOT ``custom_ats_fetch`` — the lane split, at the defer.
        * the lock comes from ``ccs.harvest_queueing_lock``, the SAME per-company
          string the private lane and the removal path use, so "never two concurrent
          harvests of one board" holds across both lanes rather than within each.
        * ``visibility='public'`` in the args is what selects the ``recipe:<id>``
          source_id namespace in the leaf task. Without it the leaf task's default
          would write these published rows into the private ``custom:`` namespace
          and they would land in the 10% custom enrichment slice.
        """
        _seed_company(db_conn, "atlassian")

        assert await enqueue_recipe_fan_out(timestamp=0) == 1
        db_conn.rollback()

        (job,) = _recipe_jobs(db_conn)
        assert job["queue_name"] == RECIPE_FETCH_QUEUE
        assert job["queue_name"] != CUSTOM_ATS_BULK_FETCH_QUEUE
        assert job["queueing_lock"] == ccs.harvest_queueing_lock("atlassian")
        assert job["args"] == {"company_id": "atlassian", "visibility": "public"}

    async def test_a_still_queued_board_is_not_deferred_twice(
        self, procrastinate_open, db_conn
    ):
        """The per-company queueing lock, exercised across two ticks. The second
        tick raises ``AlreadyEnqueued`` per company, catches it, and adds nothing."""
        for cid in ("atlassian", "dell"):
            _seed_company(db_conn, cid)

        assert await enqueue_recipe_fan_out(timestamp=0) == 2
        db_conn.rollback()
        assert await enqueue_recipe_fan_out(timestamp=1) == 0
        db_conn.rollback()

        assert len(_recipe_jobs(db_conn)) == 2

    async def test_a_transient_error_on_one_board_does_not_abort_the_tick(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """Per-company isolation. A connector blip on board N must not leave every
        alphabetically-later board unharvested for the whole 30-minute window —
        the same narrow ``(ConnectorException, psycopg2.Error)`` catch the vendor
        fan-outs carry."""
        import psycopg2 as _psycopg2

        import api.tasks.enqueue_recipe_fan_out as fan_out_mod

        for cid in ("aaa", "bbb", "ccc", "ddd"):
            _seed_company(db_conn, cid)

        real_configure = fan_out_mod.fetch_custom_company.configure
        calls = {"n": 0}

        def configure_with_flaky_defer(*args, **kwargs):
            configured = real_configure(*args, **kwargs)
            real_defer = configured.defer_async

            async def flaky_defer_async(*a, **kw):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise _psycopg2.OperationalError("transient blip on board 2")
                return await real_defer(*a, **kw)

            configured.defer_async = flaky_defer_async
            return configured

        monkeypatch.setattr(
            fan_out_mod.fetch_custom_company, "configure", configure_with_flaky_defer
        )

        deferred = await enqueue_recipe_fan_out(timestamp=0)
        db_conn.rollback()

        assert calls["n"] == 4, "the loop aborted instead of isolating one failure"
        assert deferred == 3

    async def test_a_programmer_error_propagates(
        self, procrastinate_open, db_conn, monkeypatch
    ):
        """A deterministic bug must NOT be swallowed by the transient-blip catch —
        it has to fail the task so the tick is visibly lost rather than silently
        half-done."""
        import api.tasks.enqueue_recipe_fan_out as fan_out_mod

        _seed_company(db_conn, "atlassian")

        real_configure = fan_out_mod.fetch_custom_company.configure

        def configure_with_buggy_defer(*args, **kwargs):
            configured = real_configure(*args, **kwargs)

            async def buggy_defer_async(*a, **kw):
                raise AttributeError("typo in caller")

            configured.defer_async = buggy_defer_async
            return configured

        monkeypatch.setattr(
            fan_out_mod.fetch_custom_company, "configure", configure_with_buggy_defer
        )

        with pytest.raises(AttributeError):
            await enqueue_recipe_fan_out(timestamp=0)
        db_conn.rollback()


# --- registration + lane membership (no DB) -----------------------------------


def test_importing_the_tasks_package_registers_the_periodic_tick():
    """THE SILENT FAILURE MODE: a missing side-effect import in ``api/tasks/__init__``.

    Procrastinate schedules a periodic task only if its module has been imported
    into the app singleton. Drop the ``from . import enqueue_recipe_fan_out`` line
    and NOTHING raises anywhere — the cron simply never fires and four published
    boards quietly stop being harvested, which surfaces days later as stale data.

    A subprocess is the only honest check: importing the task module in THIS
    process (the imports at the top of this file) registers it regardless of what
    ``api/tasks/__init__`` says, so an in-process assertion could never fail.
    """
    code = (
        "import api.tasks\n"
        "from api.tasks.procrastinate_app import procrastinate_app\n"
        "keys = set(procrastinate_app.periodic_registry.periodic_tasks)\n"
        "print(('enqueue_recipe_fan_out', 'recipe_fan_out') in keys)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_BACKEND),
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(_REPO_ROOT), str(_BACKEND)]),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("True"), (
        "importing `api.tasks` did not register the recipe fan-out — the "
        "side-effect import is missing from api/tasks/__init__.py, so the */30 "
        "cron will never fire and no published recipe board will be harvested"
    )


def test_the_recipe_queue_is_drained_by_the_bulk_lane_and_is_its_own_queue():
    """A queue nothing drains is a queue that fills forever, and a queue shared
    with the private lane is the backpressure bug this split exists to avoid."""
    assert RECIPE_FETCH_QUEUE in _BULK_QUEUES, (
        "nothing drains `recipe_fetch` — every deferred recipe harvest would sit "
        "in `todo` until the queue is added to a worker lane"
    )
    assert RECIPE_FETCH_QUEUE not in _INTERACTIVE_QUEUES, (
        "the reserved interactive lane is for work a human is watching a spinner "
        "for; a */30 cron over curated boards is bulk"
    )
    assert RECIPE_FETCH_QUEUE not in (
        CUSTOM_ATS_BULK_FETCH_QUEUE,
        CUSTOM_ATS_FIRST_FETCH_QUEUE,
    )
