"""FastAPI application entry point."""

import asyncio
import logging
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
from psycopg2.extensions import connection as Connection
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from .auth.internal_key import require_internal_key, warn_if_unset
from .config import settings
from .dependencies import get_db, init_pool, close_pool, pool_is_healthy
from .routers import (
    admin,
    companies,
    feedback,
    features,
    internal_enrichment,
    jobs,
    jobs_qa,
    locations,
    saved_filters,
    user_companies,
    users,
)
from .tasks import procrastinate_app
from .tasks.heartbeat import LANE_BULK as _LANE_BULK
from .tasks.heartbeat import LANE_INTERACTIVE as _LANE_INTERACTIVE
from .tasks.procrastinate_app import CUSTOM_ATS_FIRST_FETCH_QUEUE
from .tasks.procrastinate_app import ensure_schema_async
from .migrations import apply_alembic_migrations_with_retry
from .services.db_watchdog import DbWatchdog
from .services.posthog_client import init_posthog, shutdown_posthog


# Liveness threshold for `procrastinate_events` freshness. 35 min is a
# hard floor — in healthy operation events are written every */5 by the
# heartbeat task (and far more frequently by fan-out + per-task transitions),
# so anything older than 35 min indicates the connector / scheduler is dead.
# The 35 = 30 (worst-case */30 fan-out tick) + 5 (slack) framing covers the
# fallback case where the heartbeat is also stuck. Consulted by Railway's
# healthcheckPath at deploy cutover only (see railway.toml).
_WORKER_FRESHNESS_SECONDS = 35 * 60

# Heartbeat freshness threshold. The heartbeat task fires every 5 min;
# 10 min covers a single missed tick plus slack. The heartbeat's *write*
# path is independent of Procrastinate's event-stream (it opens a fresh
# psycopg2 connection, not the connector pool), so a sick connector whose
# event-writes hang but whose dequeue path still functions will surface
# here even when `procrastinate_events.at` is unreliable.
_HEARTBEAT_FRESHNESS_SECONDS = 10 * 60

# TWO LANES, TWO WORKERS.
#
# Everything below used to be one queue list drained by one worker at
# concurrency=5. That is wrong for the reason a user can feel: the six public
# fan-outs and `normalize` carry tens of thousands of jobs, and a single
# fan-out tick can hold every slot for minutes. Nobody is watching a Greenhouse
# harvest. Somebody IS watching the Add-Companies checklist tick over after
# pasting a URL — and their discovery job sat behind the bulk backlog in
# `todo`. Interactive work must not queue behind bulk work, so it gets its own
# worker with its own slots rather than sharing one pool.
#
# Splitting by QUEUE (a second `run_worker_async` on a disjoint queue set) and
# not by priority is deliberate: `procrastinate_fetch_job` orders by
# `priority DESC, id ASC`, which only decides who is picked next when a slot
# frees up. It does nothing when all five slots are already busy with
# multi-minute harvests — which is exactly the starvation we hit. Separate
# workers give the interactive lane slots that bulk work can never occupy.

# Bulk lane: scheduled, unattended, high-volume. No human is waiting on any of
# these, so they keep the larger share of the concurrency budget.
_BULK_QUEUES: tuple[str, ...] = (
    "greenhouse_fetch",
    "ashby_fetch",
    "lever_fetch",
    "gem_fetch",
    "eightfold_fetch",
    "workday_fetch",
    # Custom (user-added, private) companies ride their OWN queue — the claim
    # task (*/15) and the per-company leaf task — never the six public fan-outs.
    # This is the NIGHTLY re-harvest of every tracked private board plus the
    # */15 claim tick: bulk by definition. The add-time FIRST harvest is not
    # here; it rides `custom_ats_first_fetch` in the interactive lane below.
    "custom_ats_fetch",
    "heartbeat",
    "normalize",
)

# Interactive lane: reserved for work a human is actively watching a spinner
# for. Kept deliberately tiny — an idle interactive worker costs one LISTEN
# connection and one heartbeat job every five minutes, nothing else.
_INTERACTIVE_QUEUES: tuple[str, ...] = (
    # One-time discovery (E7 Phase 3b). A pasted URL, a five-step checklist on
    # screen, and a browser + LLM run behind it.
    "custom_discovery",
    # The FIRST harvest of a just-added company — the same `fetch_custom_company`
    # task as the nightly re-harvest, deferred onto a different queue by
    # `tasks.claim_custom_companies.start_first_harvest`. It closes the
    # checklist's fifth step ("Fetching all current jobs"), so it is part of the
    # same interactive story and must not queue behind the nightly fleet.
    CUSTOM_ATS_FIRST_FETCH_QUEUE,
    # Proves THIS lane is draining. Without a lane-local heartbeat the
    # interactive worker could die silently while /health/worker stayed green
    # on the bulk worker's heartbeat — which is the exact failure mode that
    # went unnoticed for 14 hours. See `tasks/heartbeat.py`.
    "interactive_heartbeat",
)

# Every queue this process drains, across both lanes. Kept as a single name so
# tests can pin membership (in particular, that "heartbeat" and "normalize"
# stay present — removing either would only surface as production going red via
# the /health/worker freshness probe).
_WORKER_QUEUES: tuple[str, ...] = _BULK_QUEUES + _INTERACTIVE_QUEUES

# Concurrency per lane. The bulk lane keeps the 5 slots it has always had — a
# reserved lane must not be a lane that STEALS capacity from the fan-outs — and
# the interactive lane adds 2 on top, for 7 total. Two is enough: discovery is
# one job per add and is wall-clock-capped at 240s, and the first harvest is
# one job per add.
_BULK_WORKER_CONCURRENCY = 5
_INTERACTIVE_WORKER_CONCURRENCY = 2


# Railway derives its `@level` field from which OS stream a log line came out
# on: stdout → info, stderr → error. Python's default StreamHandler writes
# every level to stderr, which makes `@level:error` filters in Railway useless
# (they surface thousands of harmless INFO lines). Route by Python level so
# the platform field finally matches reality.
class _MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.max_level


def _configure_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(_MaxLevelFilter(logging.ERROR))
    stdout_handler.setFormatter(fmt)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Replace whatever basicConfig (or a prior import in --reload) left behind
    # so we don't get double-printing.
    root.handlers = [stdout_handler, stderr_handler]

    # uvicorn installs its own handlers; redirect them through ours so its
    # startup/info lines also follow the rule. Skip uvicorn.access — it
    # already writes to stdout and that's correct.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = [stdout_handler, stderr_handler]
        lg.propagate = False


_configure_logging()
logger = logging.getLogger(__name__)


# The lanes, as (name, queues, concurrency). Module-level and iterated rather
# than two hand-written call sites so a lane can never be added to the queue
# constants above and then forgotten here.
_WORKER_LANES: tuple[tuple[str, tuple[str, ...], int], ...] = (
    (_LANE_BULK, _BULK_QUEUES, _BULK_WORKER_CONCURRENCY),
    (_LANE_INTERACTIVE, _INTERACTIVE_QUEUES, _INTERACTIVE_WORKER_CONCURRENCY),
)


def _make_worker_done_callback(
    lane: str, queues: tuple[str, ...]
) -> Callable[[asyncio.Task], None]:
    """Done-callback that refuses to let a worker task die quietly."""

    def _worker_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            # The only legitimate end: lifespan shutdown cancels us.
            return
        exc = task.exception()
        if exc is not None:
            logger.error("%s worker task crashed: %s", lane, exc, exc_info=exc)
        else:
            # `_supervised_worker` never returns on its own, so reaching here
            # at all means the supervision loop itself was broken by an edit.
            # Say so loudly — the entire point of this callback is that a dead
            # worker must never be silent.
            logger.error(
                "%s worker task exited without raising — queues %s are no "
                "longer being drained and nothing will restart them",
                lane,
                list(queues),
            )

    return _worker_task_done


async def _supervised_worker(
    lane: str, queues: tuple[str, ...], concurrency: int
) -> None:
    """Run one Procrastinate worker forever, restarting it on any end.

    run_worker_async returns with RunTaskError when any of its concurrency=N
    sub-coroutines dies — e.g. when the connector pool times out during a
    Railway DNS blip. Without supervision the lifespan-spawned task ends and
    close-detection pauses until the next process restart. See
    docs/incidents/2026-05-19-procrastinate-worker-died-on-dns-blip.md.
    """
    backoff = 1.0
    max_backoff = 60.0
    while True:
        try:
            await procrastinate_app.run_worker_async(
                queues=list(queues),
                concurrency=concurrency,
                # NEVER let Procrastinate touch process signals. It installs
                # `loop.add_signal_handler(SIGINT/SIGTERM, worker.stop)`, which
                # asyncio implements by calling
                # `signal.signal(sig, _sighandler_noop)` — clobbering the
                # `signal.signal(sig, server.handle_exit)` that uvicorn
                # installed in `Server.capture_signals()` before the lifespan
                # ran. The result, reproduced in local dev on 2026-08-26: ONE
                # SIGTERM stopped only the worker, `run_worker_async` returned
                # normally (no exception to log), uvicorn never saw the signal
                # and kept serving — so the process stayed up holding port
                # 8100, drained no jobs for 14 hours, and the operator's
                # replacement uvicorn died on "address already in use".
                # Uvicorn owns this process's signals; we are a task inside it
                # and get shut down by the lifespan's cancel.
                install_signal_handlers=False,
            )
            # A NORMAL return means the worker stopped without raising. With
            # signal handlers off there is no legitimate way for that to happen
            # while the app is up, so treat it exactly like a crash instead of
            # returning — the old code `return`ed here, which ended the task
            # with no exception and therefore logged NOTHING at all.
            logger.error(
                "%s worker returned without raising (queues=%s); restarting in %.1fs",
                lane,
                list(queues),
                backoff,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s worker crashed; restarting in %.1fs", lane, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)


def start_worker_lanes() -> list[asyncio.Task]:
    """Start one supervised Procrastinate worker per lane; return the tasks.

    Separate workers, not one worker over the union of the queues: see the
    `_BULK_QUEUES` / `_INTERACTIVE_QUEUES` comments above. The caller owns
    cancelling these at shutdown.
    """
    tasks: list[asyncio.Task] = []
    for lane, queues, concurrency in _WORKER_LANES:
        task = asyncio.create_task(_supervised_worker(lane, queues, concurrency))
        task.add_done_callback(_make_worker_done_callback(lane, queues))
        tasks.append(task)
        logger.info(
            "Procrastinate %s worker background task started "
            "(queues=%s, concurrency=%d)",
            lane,
            list(queues),
            concurrency,
        )
    return tasks


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    warn_if_unset()
    if settings.posthog_project_token:
        try:
            init_posthog(settings.posthog_project_token, settings.posthog_host)
            logger.info("PostHog initialized")
        except Exception:
            logger.warning("PostHog init failed — analytics disabled", exc_info=True)
    # DB watchdog (services/db_watchdog.py): detects a database that hangs
    # rather than errors and exits the process so Railway restarts the
    # container. Started before migrations so a frozen DB can't wedge boot.
    db_watchdog: DbWatchdog | None = None
    if settings.db_watchdog_enabled:
        db_watchdog = DbWatchdog(
            settings.database_url,
            probe_interval_s=settings.db_watchdog_probe_interval_seconds,
            probe_deadline_s=settings.db_watchdog_probe_deadline_seconds,
            failure_window_s=settings.db_watchdog_failure_window_seconds,
        )
        db_watchdog.start()

    logger.info("Applying database migrations...")
    try:
        # Connectivity failures retry for up to db_boot_connect_retry_seconds
        # so a restart during a DB outage doesn't crash-loop in seconds and
        # burn railway.toml's restartPolicyMaxRetries budget (2026-08-10).
        apply_alembic_migrations_with_retry(
            settings.database_url,
            max_wait_seconds=settings.db_boot_connect_retry_seconds,
        )
    except Exception:
        logger.exception("Failed to apply migrations during startup")
        raise

    # Procrastinate brings its own schema (procrastinate_jobs etc.).
    # open_async() spins up the async pool; ensure_schema_async then probes
    # for the procrastinate_jobs table and installs the bundled schema only
    # if missing (the bundled DDL isn't idempotent on its own, so we gate it).
    # Must come AFTER apply_alembic_migrations and BEFORE the worker task is
    # created — the worker queries procrastinate_jobs on tick.
    try:
        await procrastinate_app.open_async()
        await ensure_schema_async(procrastinate_app)
    except Exception:
        logger.exception("Failed to open Procrastinate connector during startup")
        raise

    try:
        init_pool(
            settings.database_url,
            minconn=settings.db_pool_min,
            maxconn=settings.db_pool_max,
            timeout=settings.db_pool_timeout,
        )
    except Exception:
        logger.exception("Failed to initialize database connection pool")
        raise
    app.state.config = settings

    # Imports live OUTSIDE the guard so any import failure surfaces loudly
    # rather than getting swallowed alongside the seed itself. Only the
    # DB-bound work (get_db + seed call) is allowed to fail soft: a
    # psycopg2.Error from the seed INSERTs or a RuntimeError from
    # get_db()/the pool lookup is a data-plane hiccup that should not
    # prevent the rest of the lifespan from continuing.
    from .services.features_seed import seed_starter_features
    from .services.companies_seed import seed_company_profiles
    from .dependencies import get_db

    try:
        gen = get_db()
        seed_conn = next(gen)
        try:
            seed_starter_features(seed_conn)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
    except (psycopg2.Error, RuntimeError):
        logger.exception("Failed to seed starter features during startup")

    # Seed curated company directory content (blurb + accomplishment) and the
    # script-scraped rows (google/apple/microsoft). Same soft-fail contract as
    # the feature seed, but a BROADER except: this seed also reads + parses a
    # committed JSON file, so a malformed/unreadable company_profiles.json (or a
    # wrongly-shaped entry) raises JSONDecodeError/OSError/AttributeError — none
    # of which are psycopg2/RuntimeError. The directory seed is non-critical;
    # a content problem must degrade to last-good DB content, never crash-loop
    # boot. (The JSON is loaded lazily inside the seeder so it's covered here.)
    try:
        gen = get_db()
        seed_conn = next(gen)
        try:
            seed_company_profiles(seed_conn)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
    except Exception:
        logger.exception("Failed to seed company profiles during startup")

    # Start background auto-scraper
    from .services.auto_scraper import auto_scraper_loop

    def _scraper_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Auto-scraper task crashed: %s", exc, exc_info=exc)

    scraper_task = asyncio.create_task(auto_scraper_loop(settings))
    scraper_task.add_done_callback(_scraper_task_done)
    logger.info("Auto-scraper background task started")

    worker_tasks = start_worker_lanes()

    yield

    # Shutdown
    if db_watchdog is not None:
        db_watchdog.stop()
    for task in worker_tasks:
        task.cancel()
    for task in worker_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    try:
        await procrastinate_app.close_async()
    except Exception:
        logger.warning("Error closing Procrastinate connector during shutdown", exc_info=True)
    scraper_task.cancel()
    try:
        await scraper_task
    except asyncio.CancelledError:
        pass
    try:
        close_pool()
    except Exception:
        logger.warning("Error closing database pool during shutdown", exc_info=True)
    try:
        shutdown_posthog()
    except Exception:
        logger.warning("Error flushing PostHog during shutdown", exc_info=True)
    logger.info("Shutdown complete")


app = FastAPI(title="Jobs API", lifespan=lifespan)

# Register the internal-key gate FIRST so CORSMiddleware ends up on the
# outside of the stack. Starlette runs middleware in reverse-registration
# order; if CORS is inside the gate, preflight OPTIONS without the header
# would be rejected before CORS can answer.
app.middleware("http")(require_internal_key)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # ``allow_headers`` governs REQUEST headers; a browser can only read a
    # non-safelisted RESPONSE header if it is named here. Without this,
    # ``GET /api/jobs`` keyset paging silently loses its next-page token for any
    # cross-origin caller (e.g. the Vite dev server on :5173 hitting the backend
    # on :8000 directly) — the array arrives fine and the walk just stops after
    # page 1 with no error. Production goes through the same-origin Vercel proxy,
    # which is a separate hop and re-emits the header itself (``api/jobs.ts``).
    expose_headers=[jobs.NEXT_CURSOR_HEADER],
)

app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(jobs_qa.router, prefix="/api/jobs-qa", tags=["jobs-qa"])
app.include_router(locations.router, prefix="/api/locations", tags=["locations"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(
    saved_filters.router, prefix="/api/users/saved-filters", tags=["saved-filters"]
)
app.include_router(
    user_companies.router, prefix="/api/users/companies", tags=["user-companies"]
)
app.include_router(features.router, prefix="/api/features", tags=["features"])
app.include_router(companies.router, prefix="/api/companies", tags=["companies"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(
    internal_enrichment.router,
    prefix="/api/internal/enrichment",
    tags=["internal-enrichment"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Return structured JSON for any unhandled server error."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
def health() -> PlainTextResponse:
    if not pool_is_healthy():
        return PlainTextResponse("UNAVAILABLE", status_code=503)
    return PlainTextResponse("OK")


@app.get("/health/worker", response_model=None)
def health_worker(
    conn: Connection = Depends(get_db),
) -> dict[str, Any] | JSONResponse:
    """Procrastinate worker liveness probe.

    Returns 503 when ANY stream is stale:
      - the most recent `procrastinate_events` row is older than
        _WORKER_FRESHNESS_SECONDS (35 min — one */30 cron tick + slack), OR
      - the most recent `worker_heartbeats` row is older than
        _HEARTBEAT_FRESHNESS_SECONDS (10 min — one */5 cron tick + slack), OR
      - EITHER LANE's own most recent `worker_heartbeats` row is older than
        _HEARTBEAT_FRESHNESS_SECONDS. There are two workers (bulk and
        interactive, see `_BULK_QUEUES` / `_INTERACTIVE_QUEUES`); the
        combined `MAX(at)` above cannot distinguish "both alive" from
        "one alive, one dead", and a dead interactive lane means every
        pasted URL sits forever on "Setting up…" while the probe reports
        a healthy worker.

    The streams are checked independently so a sick connector that
    breaks event-writes but leaves the periodic scheduler alive still
    surfaces a freshness signal. This is Railway's healthcheckPath, which
    gates deploy cutover only (see railway.toml); runtime liveness is
    owned by services/db_watchdog.py.

    Uses the FastAPI sync pool (NOT Procrastinate's async connector) so a
    sick Procrastinate connector doesn't mask a sick worker.

    Failure modes:
    - `psycopg2.Error` from the probe queries -> 503 with status="db_error".
      A liveness probe that can't read its own data plane IS a liveness
      failure; surfacing 503 lets Railway restart the container.
    - During the brief startup window before `init_pool` runs, `get_db`
      raises RuntimeError → FastAPI returns 500. Railway's
      `healthcheckTimeout` (5min) absorbs this until lifespan completes.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(at) AS latest FROM procrastinate_events")
            events_row = cur.fetchone()
            cur.execute("SELECT MAX(at) AS latest FROM worker_heartbeats")
            heartbeat_row = cur.fetchone()
            # Per-lane freshness. `MAX(at)` above is the OR of both lanes and
            # therefore cannot see one dead lane; these two can. Kept as a
            # separate query so the existing combined field keeps its exact
            # meaning for anything already reading it.
            cur.execute(
                "SELECT lane, MAX(at) AS latest FROM worker_heartbeats "
                "WHERE lane = ANY(%s) GROUP BY lane",
                ([_LANE_BULK, _LANE_INTERACTIVE],),
            )
            lane_rows = {r["lane"]: {"latest": r["latest"]} for r in cur.fetchall()}
    except psycopg2.Error:
        logger.exception("health_worker DB query failed")
        return JSONResponse(
            status_code=503,
            content={"status": "db_error"},
        )
    finally:
        # End any txn the queries opened so the connection returns to the
        # pool clean. get_db's except path also rolls back on exception,
        # but doing it here keeps the intent local and covers the case
        # where the *second* SELECT raises after the first one's read
        # opened an implicit transaction.
        try:
            conn.rollback()
        except psycopg2.Error:
            logger.exception("health_worker rollback failed")

    now = datetime.now(timezone.utc)

    def _gap(row: dict[str, Any] | None) -> tuple[datetime | None, float | None]:
        latest = row["latest"] if row else None
        if latest is None:
            return None, None
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
        return latest, (now - latest).total_seconds()

    events_latest, events_gap = _gap(events_row)
    heartbeat_latest, heartbeat_gap = _gap(heartbeat_row)

    lanes: dict[str, Any] = {}
    stale_lanes: list[str] = []
    for lane in (_LANE_BULK, _LANE_INTERACTIVE):
        lane_latest, lane_gap = _gap(lane_rows.get(lane))
        lanes[lane] = {
            "latest_heartbeat": lane_latest.isoformat() if lane_latest else None,
            "gap_seconds": round(lane_gap, 1) if lane_gap is not None else None,
        }
        if lane_gap is not None and lane_gap > _HEARTBEAT_FRESHNESS_SECONDS:
            stale_lanes.append(lane)

    payload = {
        "latest_event": events_latest.isoformat() if events_latest else None,
        "gap_seconds": round(events_gap, 1) if events_gap is not None else None,
        "threshold_seconds": _WORKER_FRESHNESS_SECONDS,
        "latest_heartbeat": (
            heartbeat_latest.isoformat() if heartbeat_latest else None
        ),
        "heartbeat_gap_seconds": (
            round(heartbeat_gap, 1) if heartbeat_gap is not None else None
        ),
        "heartbeat_threshold_seconds": _HEARTBEAT_FRESHNESS_SECONDS,
        # Per-lane detail, so "which worker died" is answerable from the probe
        # alone. `stale_lanes` names them; an empty list means every lane that
        # has ever ticked is fresh.
        "lanes": lanes,
        "stale_lanes": stale_lanes,
    }

    if events_latest is None and heartbeat_latest is None:
        # Cold deploy — neither has run yet. Allow as healthy; the cron
        # will fire within ~5min (heartbeat) and write the first row.
        return {**payload, "status": "cold"}

    events_stale = events_gap is not None and events_gap > _WORKER_FRESHNESS_SECONDS
    heartbeat_stale = (
        heartbeat_gap is not None and heartbeat_gap > _HEARTBEAT_FRESHNESS_SECONDS
    )
    # A lane that has ticked before and has now gone quiet is a dead worker even
    # while the OTHER lane keeps the combined `heartbeat_gap_seconds` fresh.
    # This is the check that would have caught 2026-08-26 had there been two
    # lanes then, and the reason the split does not just double the number of
    # things that can die unnoticed.
    if events_stale or heartbeat_stale or stale_lanes:
        return JSONResponse(
            status_code=503,
            content={**payload, "status": "stale"},
        )
    return {**payload, "status": "ok"}
