"""FastAPI application entry point."""

import asyncio
import logging
import sys
from collections.abc import AsyncIterator
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
    jobs,
    jobs_qa,
    saved_filters,
    users,
)
from .tasks import procrastinate_app
from .tasks.procrastinate_app import ensure_schema_async
from .migrations import apply_alembic_migrations
from .services.posthog_client import init_posthog, shutdown_posthog


# Liveness threshold for `procrastinate_events` freshness. 35 min is a
# hard floor — in healthy operation events are written every */5 by the
# heartbeat task (and far more frequently by fan-out + per-task transitions),
# so anything older than 35 min indicates the connector / scheduler is dead.
# The 35 = 30 (worst-case */30 fan-out tick) + 5 (slack) framing covers the
# fallback case where the heartbeat is also stuck. Railway healthcheckPath
# uses this to decide when to restart the container.
_WORKER_FRESHNESS_SECONDS = 35 * 60

# Heartbeat freshness threshold. The heartbeat task fires every 5 min;
# 10 min covers a single missed tick plus slack. The heartbeat's *write*
# path is independent of Procrastinate's event-stream (it opens a fresh
# psycopg2 connection, not the connector pool), so a sick connector whose
# event-writes hang but whose dequeue path still functions will surface
# here even when `procrastinate_events.at` is unreliable.
_HEARTBEAT_FRESHNESS_SECONDS = 10 * 60

# Queues the Procrastinate worker drains. Module-level constant so tests
# can pin the membership (in particular, that "heartbeat" stays present —
# removing it silently would only surface as production going red via the
# /health/worker freshness probe). Order doesn't matter for correctness;
# kept stable for grep-friendly log output.
_WORKER_QUEUES: tuple[str, ...] = (
    "greenhouse_fetch",
    "ashby_fetch",
    "lever_fetch",
    "gem_fetch",
    "eightfold_fetch",
    "workday_fetch",
    "heartbeat",
    "normalize",
)


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
    logger.info("Applying database migrations...")
    try:
        apply_alembic_migrations(settings.database_url)
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

    def _worker_task_done(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Procrastinate worker task crashed: %s", exc, exc_info=exc)

    async def _supervised_worker() -> None:
        # run_worker_async returns with RunTaskError when any of its
        # concurrency=N sub-coroutines dies — e.g. when the connector pool
        # times out during a Railway DNS blip. Without supervision the
        # lifespan-spawned task ends and close-detection pauses until the
        # next process restart. See
        # docs/incidents/2026-05-19-procrastinate-worker-died-on-dns-blip.md.
        backoff = 1.0
        max_backoff = 60.0
        while True:
            try:
                await procrastinate_app.run_worker_async(
                    queues=list(_WORKER_QUEUES),
                    concurrency=5,
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Procrastinate worker crashed; restarting in %.1fs",
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    worker_task = asyncio.create_task(_supervised_worker())
    worker_task.add_done_callback(_worker_task_done)
    logger.info(
        "Procrastinate worker background task started "
        "(queues=%s, concurrency=5)",
        list(_WORKER_QUEUES),
    )

    yield

    # Shutdown
    worker_task.cancel()
    try:
        await worker_task
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
    shutdown_posthog()
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
)

app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(jobs_qa.router, prefix="/api/jobs-qa", tags=["jobs-qa"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(
    saved_filters.router, prefix="/api/users/saved-filters", tags=["saved-filters"]
)
app.include_router(features.router, prefix="/api/features", tags=["features"])
app.include_router(companies.router, prefix="/api/companies", tags=["companies"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


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

    Returns 503 when EITHER stream is stale:
      - the most recent `procrastinate_events` row is older than
        _WORKER_FRESHNESS_SECONDS (35 min — one */30 cron tick + slack), OR
      - the most recent `worker_heartbeats` row is older than
        _HEARTBEAT_FRESHNESS_SECONDS (10 min — one */5 cron tick + slack).

    The two streams are checked independently so a sick connector that
    breaks event-writes but leaves the periodic scheduler alive still
    surfaces a freshness signal. Wire this as Railway's healthcheckPath
    so the platform restarts the container when the worker silently hangs
    (the original failure class the 2026-05-19 supervisor PR couldn't
    cover, since a hang produces no exception).

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
    }

    if events_latest is None and heartbeat_latest is None:
        # Cold deploy — neither has run yet. Allow as healthy; the cron
        # will fire within ~5min (heartbeat) and write the first row.
        return {**payload, "status": "cold"}

    events_stale = events_gap is not None and events_gap > _WORKER_FRESHNESS_SECONDS
    heartbeat_stale = (
        heartbeat_gap is not None and heartbeat_gap > _HEARTBEAT_FRESHNESS_SECONDS
    )
    if events_stale or heartbeat_stale:
        return JSONResponse(
            status_code=503,
            content={**payload, "status": "stale"},
        )
    return {**payload, "status": "ok"}
