"""The reserved interactive lane, and the signal bug that killed the worker.

Two things are pinned here, and they are the same story: work that nobody
notices has stopped.

1. **Lane assignment.** `custom_discovery` and the add-time first harvest are
   drained by their own Procrastinate worker with their own slots, not by the
   bulk worker that carries the six public fan-outs and `normalize`. The
   regression that motivated this — a user pastes a careers URL and the
   discovery job sits in `todo` behind a bulk backlog — is pinned by
   `test_a_discovery_job_runs_while_the_bulk_lane_is_saturated`, which really
   runs both workers against a real Procrastinate schema.

2. **Silence.** The worker died on 2026-08-26 because Procrastinate's default
   `install_signal_handlers=True` clobbered uvicorn's SIGTERM handler with
   `loop.add_signal_handler`: one SIGTERM stopped only the worker,
   `run_worker_async` returned *normally* (nothing to log), and uvicorn kept
   serving with no worker for 14 hours. Both halves are pinned — that we do not
   touch process signals, and that a worker ending for any reason is loud.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from api.main import (
    _BULK_QUEUES,
    _BULK_WORKER_CONCURRENCY,
    _INTERACTIVE_QUEUES,
    _INTERACTIVE_WORKER_CONCURRENCY,
    _WORKER_LANES,
    _WORKER_QUEUES,
    _supervised_worker,
    start_worker_lanes,
)
from api.tasks.procrastinate_app import (
    CUSTOM_ATS_FIRST_FETCH_QUEUE,
    ensure_schema_async,
    procrastinate_app,
)


# --- lane membership ---------------------------------------------------------


def test_discovery_is_on_the_interactive_lane_and_not_the_bulk_lane():
    """THE regression. `custom_discovery` shared one worker with
    `greenhouse_fetch`/`workday_fetch`/`normalize` at concurrency=5; those
    queues carry tens of thousands of jobs, so a fan-out tick could hold every
    slot while a human watched an Add-Companies spinner. Moving it back onto
    the bulk lane must fail here.
    """
    assert "custom_discovery" in _INTERACTIVE_QUEUES, (
        "'custom_discovery' must ride the reserved interactive lane — somebody "
        "pasted a URL and is watching a five-step checklist wait on this job"
    )
    assert "custom_discovery" not in _BULK_QUEUES, (
        "'custom_discovery' is back on the bulk lane, where it competes for "
        f"slots with {list(_BULK_QUEUES)!r} — that is the starvation this split fixed"
    )


def test_the_add_time_first_harvest_is_on_the_interactive_lane():
    """The checklist's fifth step ("Fetching all current jobs") is closed by
    the FIRST `fetch_custom_company`. It rides its own queue so it is
    interactive, while the nightly re-harvest of every tracked board stays bulk.
    """
    assert CUSTOM_ATS_FIRST_FETCH_QUEUE in _INTERACTIVE_QUEUES
    assert CUSTOM_ATS_FIRST_FETCH_QUEUE not in _BULK_QUEUES
    # ...and the nightly path is emphatically NOT interactive.
    assert "custom_ats_fetch" in _BULK_QUEUES, (
        "the */15 claim tick and the nightly re-harvests are bulk; putting them "
        "in the reserved lane would let 130 boards crowd out the one add a user "
        "is actually watching"
    )
    assert "custom_ats_fetch" not in _INTERACTIVE_QUEUES


def test_the_lanes_are_disjoint():
    """Two workers on the same queue would double-drain it and defeat the
    reservation — the interactive worker would end up doing bulk work.
    """
    overlap = set(_BULK_QUEUES) & set(_INTERACTIVE_QUEUES)
    assert not overlap, f"queues drained by BOTH workers: {sorted(overlap)}"


def test_every_queue_is_drained_by_exactly_one_lane():
    """`_WORKER_QUEUES` is the union and several tests still assert against it
    (heartbeat, normalize). If a queue is added to one lane, the union must
    follow — a queue in neither lane is a queue nothing drains.
    """
    assert set(_WORKER_QUEUES) == set(_BULK_QUEUES) | set(_INTERACTIVE_QUEUES)
    assert len(_WORKER_QUEUES) == len(_BULK_QUEUES) + len(_INTERACTIVE_QUEUES)


def test_the_reserved_lane_does_not_take_capacity_from_the_bulk_lane():
    """A reserved lane must be capacity ADDED, not capacity moved. The bulk
    worker keeps the 5 slots it had before the split.
    """
    assert _BULK_WORKER_CONCURRENCY == 5
    assert _INTERACTIVE_WORKER_CONCURRENCY >= 1


def test_each_lane_has_its_own_heartbeat_queue():
    """Observability: /health/worker must be able to tell WHICH worker died.
    Each lane drains a heartbeat queue only it drains, so a fresh row on that
    queue proves that specific worker is dequeuing.
    """
    assert "heartbeat" in _BULK_QUEUES
    assert "interactive_heartbeat" in _INTERACTIVE_QUEUES
    assert "interactive_heartbeat" not in _BULK_QUEUES, (
        "if the bulk worker drains the interactive heartbeat, a dead "
        "interactive worker keeps writing fresh rows and stays invisible"
    )


# --- start_worker_lanes: what actually gets run ------------------------------


@pytest.mark.asyncio
async def test_start_worker_lanes_runs_one_worker_per_lane():
    """Two `run_worker_async` calls, each with its own lane's queues and
    concurrency. One call over the union would be the old, starving shape.
    """
    calls: list[dict] = []

    async def _fake_run_worker(**kwargs):
        calls.append(kwargs)
        await asyncio.Event().wait()

    with patch.object(
        procrastinate_app, "run_worker_async", side_effect=_fake_run_worker
    ):
        tasks = start_worker_lanes()
        await asyncio.sleep(0.05)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    assert len(calls) == 2, f"expected one worker per lane, got {len(calls)}"
    by_queues = {tuple(c["queues"]): c for c in calls}
    assert tuple(_BULK_QUEUES) in by_queues
    assert tuple(_INTERACTIVE_QUEUES) in by_queues
    assert by_queues[tuple(_BULK_QUEUES)]["concurrency"] == _BULK_WORKER_CONCURRENCY
    assert (
        by_queues[tuple(_INTERACTIVE_QUEUES)]["concurrency"]
        == _INTERACTIVE_WORKER_CONCURRENCY
    )


@pytest.mark.asyncio
async def test_workers_never_install_process_signal_handlers():
    """THE ROOT CAUSE of the 2026-08-26 dead worker.

    Procrastinate defaults to `install_signal_handlers=True`, which calls
    `loop.add_signal_handler(SIGTERM, worker.stop)`; asyncio implements that by
    calling `signal.signal(SIGTERM, _sighandler_noop)`, replacing the handler
    uvicorn installed in `Server.capture_signals()`. One SIGTERM then stopped
    the worker instead of the server, and the server kept running with no
    worker.

    Asserted behaviourally, not just as a kwarg: a sentinel handler installed
    before the workers start must still be the SIGTERM handler afterwards.
    """
    sentinel = lambda *_: None  # noqa: E731
    previous = signal.signal(signal.SIGTERM, sentinel)
    try:

        async def _fake_run_worker(**kwargs):
            # Faithfully reproduce what procrastinate would do if we let it.
            if kwargs.get("install_signal_handlers", True):
                asyncio.get_running_loop().add_signal_handler(
                    signal.SIGTERM, lambda: None
                )
            await asyncio.Event().wait()

        with patch.object(
            procrastinate_app, "run_worker_async", side_effect=_fake_run_worker
        ):
            tasks = start_worker_lanes()
            await asyncio.sleep(0.05)
            handler_after = signal.getsignal(signal.SIGTERM)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        assert handler_after is sentinel, (
            "the Procrastinate worker replaced this process's SIGTERM handler. "
            "uvicorn owns signals here; letting procrastinate install its own "
            "means one SIGTERM stops the worker and leaves a headless server "
            "holding the port (2026-08-26)"
        )
    finally:
        signal.signal(signal.SIGTERM, previous)


async def _run_supervisor_until(lane: str, side_effect, restarted: asyncio.Event):
    """Drive `_supervised_worker` until it has restarted once, then cancel it.

    Deliberately does NOT stub out `asyncio.sleep`: the supervisor's backoff is
    the real 1s, and patching `api.main.asyncio.sleep` would patch the module
    object shared with this test, so our own `await asyncio.sleep(0)` would stop
    yielding to the loop and the supervisor would never get scheduled.
    """
    with patch.object(procrastinate_app, "run_worker_async", side_effect=side_effect):
        task = asyncio.create_task(_supervised_worker(lane, ("q",), 1))
        try:
            await asyncio.wait_for(restarted.wait(), timeout=10)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_a_worker_that_returns_without_raising_is_loud_and_restarts(caplog):
    """The old supervisor `return`ed when `run_worker_async` came back normally.
    That ended the asyncio task with NO exception, so the done-callback logged
    nothing — the worker was gone and the only symptom was 14 hours of silence.
    A clean return must now be logged as an error AND retried.
    """
    calls = 0
    restarted = asyncio.Event()

    async def _returns_immediately(**_kwargs):
        nonlocal calls
        calls += 1
        if calls >= 2:
            restarted.set()

    with caplog.at_level(logging.ERROR, logger="api.main"):
        await _run_supervisor_until("bulk", _returns_immediately, restarted)

    assert calls >= 2, "a worker that returned normally was not restarted"
    assert any("returned without raising" in r.message for r in caplog.records), (
        "a silently-returning worker logged nothing — that is exactly how the "
        f"2026-08-26 outage stayed invisible: {[r.message for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_a_crashing_worker_is_logged_and_restarted(caplog):
    """Pre-existing behaviour, kept: a raising worker is logged and retried."""
    calls = 0
    restarted = asyncio.Event()

    async def _boom(**_kwargs):
        nonlocal calls
        calls += 1
        if calls >= 2:
            restarted.set()
        raise RuntimeError("connector went away")

    with caplog.at_level(logging.ERROR, logger="api.main"):
        await _run_supervisor_until("interactive", _boom, restarted)

    assert calls >= 2
    assert any("worker crashed" in r.message for r in caplog.records)


def test_the_lane_table_matches_the_queue_constants():
    """`_WORKER_LANES` is what `start_worker_lanes` iterates. If a lane's queue
    tuple drifts from the constant above it, the reservation silently stops
    matching what the deferrers target.
    """
    table = {lane: (queues, conc) for lane, queues, conc in _WORKER_LANES}
    assert table["bulk"] == (_BULK_QUEUES, _BULK_WORKER_CONCURRENCY)
    assert table["interactive"] == (
        _INTERACTIVE_QUEUES,
        _INTERACTIVE_WORKER_CONCURRENCY,
    )


# --- /health/worker must be able to see ONE dead lane -------------------------


def _seed_lane_health(db_conn, *, bulk_age_s: float, interactive_age_s: float) -> None:
    """Fresh event stream + one heartbeat per lane at the given ages."""
    now = datetime.now(timezone.utc)
    cur = db_conn.cursor()
    cur.execute("DELETE FROM procrastinate_events")
    cur.execute("DELETE FROM worker_heartbeats")
    cur.execute(
        "INSERT INTO procrastinate_jobs (queue_name, task_name, args, status) "
        "VALUES ('test_q', 'test_task', '{}'::jsonb, 'succeeded') RETURNING id"
    )
    job_id = cur.fetchone()["id"]
    cur.execute(
        "INSERT INTO procrastinate_events (job_id, type, at) "
        "VALUES (%s, 'succeeded', %s)",
        (job_id, now - timedelta(seconds=60)),
    )
    for lane, age in (("bulk", bulk_age_s), ("interactive", interactive_age_s)):
        cur.execute(
            "INSERT INTO worker_heartbeats (at, lane) VALUES (%s, %s)",
            (now - timedelta(seconds=age), lane),
        )
    db_conn.commit()


def test_health_worker_reports_each_lane_separately(client, db_conn):
    _seed_lane_health(db_conn, bulk_age_s=60, interactive_age_s=90)
    resp = client.get("/health/worker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["stale_lanes"] == []
    assert body["lanes"]["bulk"]["gap_seconds"] < 120
    assert body["lanes"]["interactive"]["gap_seconds"] < 180


def test_health_worker_is_503_when_only_the_interactive_lane_is_dead(client, db_conn):
    """The one that matters. The bulk worker keeps `MAX(at)` fresh, so the
    combined `heartbeat_gap_seconds` looks healthy — exactly the blind spot that
    let a dead worker go unnoticed for 14 hours. Only the per-lane check sees it,
    and a dead interactive lane means every pasted URL hangs on "Setting up…".
    """
    _seed_lane_health(db_conn, bulk_age_s=60, interactive_age_s=15 * 60)
    resp = client.get("/health/worker")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "stale"
    assert body["stale_lanes"] == ["interactive"]
    # The combined signal really is green — proving the lane check is load-bearing
    # and not merely restating `heartbeat_gap_seconds`.
    assert body["heartbeat_gap_seconds"] < 10 * 60


def test_health_worker_is_503_when_only_the_bulk_lane_is_dead(client, db_conn):
    _seed_lane_health(db_conn, bulk_age_s=15 * 60, interactive_age_s=60)
    resp = client.get("/health/worker")

    assert resp.status_code == 503
    assert resp.json()["stale_lanes"] == ["bulk"]


def test_health_worker_stays_cold_on_a_lane_that_has_never_ticked(client, db_conn):
    """A lane with no rows at all is a cold start, not a dead worker — the
    first tick lands within 5 minutes. Failing here would 503 every fresh
    deploy for its first few minutes.
    """
    now = datetime.now(timezone.utc)
    cur = db_conn.cursor()
    cur.execute("DELETE FROM procrastinate_events")
    cur.execute("DELETE FROM worker_heartbeats")
    cur.execute(
        "INSERT INTO worker_heartbeats (at, lane) VALUES (%s, 'bulk')",
        (now - timedelta(seconds=30),),
    )
    db_conn.commit()

    resp = client.get("/health/worker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale_lanes"] == []
    assert body["lanes"]["interactive"]["latest_heartbeat"] is None


# --- the real thing: a saturated bulk lane must not delay a discovery job -----


@pytest_asyncio.fixture
async def procrastinate_open(db_conn):
    """Open a Procrastinate connector pinned to the TEST database.

    NOT the module-level `procrastinate_app.connector`. That one is built at
    IMPORT time from `settings.database_url`, which local dev resolves from
    `.env.local` — so it points at the real `jobscraper` database no matter what
    `TEST_DATABASE_URL` says, and setting `DATABASE_URL` from a fixture is far
    too late to change it. This test starts REAL workers that claim and execute
    whatever they find, so an unpinned connector would have them draining a real
    local queue (and it did, until this fixture existed).

    `App.replace_connector` is Procrastinate's supported seam for exactly this;
    the tasks stay registered on the same app object.
    """
    from procrastinate import PsycopgConnector

    from scripts.shared.database import augment_db_url
    from api.tests.conftest import TEST_DB_URL

    schema = os.environ.get("PYTEST_SCHEMA")
    assert schema, "db_conn fixture must set PYTEST_SCHEMA"

    connector = PsycopgConnector(
        conninfo=augment_db_url(
            TEST_DB_URL, application_name="lanetest", statement_timeout_ms=60_000
        )
    )
    with procrastinate_app.replace_connector(connector):
        await connector.open_async()
        try:
            await ensure_schema_async(procrastinate_app)
            yield
        finally:
            await connector.close_async()


# Test-only tasks registered on the app singleton. They stand in for the real
# leaf tasks so the test can control exactly how long a bulk job occupies a slot
# without doing any network or LLM work.
#
# Saturation is tracked with IN-PROCESS counters rather than by polling
# `procrastinate_jobs`: the tasks run in this very process, so the counter is
# authoritative and needs no assumptions about which schema the connector
# resolved `procrastinate_jobs` to.
_bulk_running = 0
_bulk_saturated = asyncio.Event()
_interactive_ran = asyncio.Event()
_release_bulk = asyncio.Event()


@procrastinate_app.task(queue="workday_fetch", name="_lanetest_slow_bulk")
async def _lanetest_slow_bulk() -> None:
    global _bulk_running
    _bulk_running += 1
    if _bulk_running >= _BULK_WORKER_CONCURRENCY:
        _bulk_saturated.set()
    try:
        # Holds its slot until the test releases it. The timeout is only a
        # safety net so a failing test cannot wedge the suite.
        await asyncio.wait_for(_release_bulk.wait(), timeout=120)
    finally:
        _bulk_running -= 1


@procrastinate_app.task(queue="custom_discovery", name="_lanetest_interactive")
async def _lanetest_interactive() -> None:
    _interactive_ran.set()


async def _delete_lanetest_jobs() -> None:
    """Remove this module's throwaway jobs from the shared Procrastinate tables.

    Procrastinate's schema is installed once per DATABASE, so these rows outlive
    this module's test schema. A leftover `todo` row would hand a long wait to
    whichever later module opens a worker on `workday_fetch`. Routed through the
    CONNECTOR, not the `db_conn` fixture: the connector's conninfo carries its
    own libpq `options`, which takes precedence over the PGOPTIONS search_path
    the fixtures pin, so the two do not necessarily resolve the table alike.
    """
    # The pattern goes through a PARAMETER, never inlined: psycopg reads a bare
    # `%` in the SQL text as a placeholder marker and raises on the literal.
    pattern = "\\_lanetest%"
    await procrastinate_app.connector.execute_query_async(
        "DELETE FROM procrastinate_events WHERE job_id IN "
        "(SELECT id FROM procrastinate_jobs WHERE task_name LIKE %(pattern)s)",
        pattern=pattern,
    )
    await procrastinate_app.connector.execute_query_async(
        "DELETE FROM procrastinate_jobs WHERE task_name LIKE %(pattern)s",
        pattern=pattern,
    )


@contextlib.contextmanager
def _no_periodic_deferrer():
    """Empty the periodic registry while a REAL Procrastinate worker runs.

    Not tidiness — without it this test hangs forever, and the hang is in
    teardown, not in anything the test asserts.

    `Worker.run` always starts a `periodic_deferrer` side-coroutine, and on a
    freshly-opened app that deferrer immediately backfills every cron tick
    inside the last 10 minutes (`MAX_DELAY=600` in procrastinate 2.15.1), so
    it is doing real DB round-trips at exactly the moment this test cancels
    the workers. `utils.run_tasks` cancels the side coroutines — and if the
    deferrer is inside `pool.connection()` when that cancel lands, psycopg_pool
    swallows it: `_getconn_with_check_loop` catches `CLIENT_EXCEPTIONS`, which
    on the async pool is `(Exception, asyncio.CancelledError)`, returns the
    connection and loops. The deferrer never dies, so `run_tasks` never
    finishes awaiting it, so `Worker.run` never returns — and
    `App.run_worker_async` *shields* that task, cancelling only into an
    unbounded `worker.stop(); await task`. The `asyncio.gather` in this test's
    `finally` then blocks until pytest-timeout kills the whole test at 120s.
    Observed as a genuine race: roughly one run in three, which is why it
    looks like load sensitivity rather than what it is. The six
    `test_fetch_*_company.py` drains already suspend the registry the same
    way, for a different reason (a fan-out that double-counts misses); this
    is a second reason to do it around any real worker.

    Nothing here is under test: this test asserts lane reservation, and
    suppressing the periodics also keeps `worker_heartbeat` / `scan_unnormalized`
    jobs from competing for the very bulk slots whose saturation it checks.
    """
    registry = procrastinate_app.periodic_registry
    saved = registry.periodic_tasks
    registry.periodic_tasks = {}
    try:
        yield
    finally:
        registry.periodic_tasks = saved


@pytest.mark.asyncio
async def test_a_discovery_job_runs_while_the_bulk_lane_is_saturated(
    procrastinate_open,
):
    """THE regression the owner hit, end to end.

    Fill every bulk slot with jobs that will not let go, then defer one job on
    `custom_discovery`. With the reserved lane it runs immediately. With ONE
    shared worker at concurrency=5 — the shape before this change — all five
    slots are occupied and the discovery job sits in `todo` until one frees,
    which is exactly what the owner saw ("Opening the page" forever,
    `attempts: 0`).
    """
    global _bulk_running
    _bulk_running = 0
    _bulk_saturated.clear()
    _interactive_ran.clear()
    _release_bulk.clear()

    # More blockers than the bulk lane has slots, so it is genuinely saturated
    # with nothing spare.
    #
    # priority is NOT decoration. `procrastinate_fetch_job` orders by
    # `priority DESC, id ASC`, and Procrastinate's schema is shared by every
    # test module in the session, so earlier modules leave older `todo` rows on
    # the bulk queues. Without a priority these jobs queue BEHIND those, the
    # bulk lane never fills, and the test fails for a reason that has nothing to
    # do with what it is checking.
    for _ in range(_BULK_WORKER_CONCURRENCY + 2):
        await _lanetest_slow_bulk.configure(priority=100).defer_async()

    with _no_periodic_deferrer():
        tasks = start_worker_lanes()
        try:
            # Saturation is a CHECKED PRECONDITION, not an assumption. Without
            # it the test could pass vacuously on a bulk lane that had a free
            # slot.
            await asyncio.wait_for(_bulk_saturated.wait(), timeout=30)
            assert _bulk_running >= _BULK_WORKER_CONCURRENCY

            await _lanetest_interactive.configure(priority=100).defer_async()
            await asyncio.wait_for(_interactive_ran.wait(), timeout=30)

            # ...and it ran while the bulk lane was STILL full. If the blockers
            # had drained, a bulk slot came free and this run would not
            # demonstrate a reserved lane at all.
            assert _bulk_running >= _BULK_WORKER_CONCURRENCY, (
                f"the bulk lane drained to {_bulk_running} busy slots before the "
                "interactive job ran — this run does not prove the reservation"
            )
        finally:
            _release_bulk.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await _delete_lanetest_jobs()

    assert _interactive_ran.is_set()


@pytest.mark.asyncio
async def test_the_first_harvest_is_deferred_onto_the_interactive_queue(
    procrastinate_open, db_conn
):
    """`start_first_harvest` must target the reserved lane's queue. If it
    defers onto `custom_ats_fetch`, the just-added company's first harvest
    queues behind the nightly fleet and the checklist's last step hangs.
    """
    from api.tasks import claim_custom_companies as claim_mod

    company_id = "u-lanetest01"
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO companies (id, display_name, ats, board_token, enabled, "
            "provider_config, visibility, cadence_hours, next_run_at, health_state, "
            "consecutive_failures) VALUES (%s, %s, 'discovered', 'x', TRUE, "
            "'{}'::jsonb, 'user', 24, now(), 'unverified', 0)",
            (company_id, "Lane Test"),
        )
    db_conn.commit()

    try:
        await claim_mod.start_first_harvest(
            db_conn, company_id=company_id, transport="http_json"
        )

        rows = await procrastinate_app.connector.execute_query_all_async(
            "SELECT queue_name FROM procrastinate_jobs "
            "WHERE task_name = 'fetch_custom_company' "
            "AND args->>'company_id' = %(cid)s",
            cid=company_id,
        )
        assert [r["queue_name"] for r in rows] == [CUSTOM_ATS_FIRST_FETCH_QUEUE], (
            "the add-time first harvest must ride the reserved interactive queue, "
            f"got {rows!r}"
        )
    finally:
        await procrastinate_app.connector.execute_query_async(
            "DELETE FROM procrastinate_jobs WHERE args->>'company_id' = %(cid)s",
            cid=company_id,
        )
