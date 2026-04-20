"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import settings
from .dependencies import init_pool, close_pool, pool_is_healthy
from .routers import features, jobs, jobs_qa, users
from .migrations import apply_alembic_migrations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Applying database migrations...")
    try:
        apply_alembic_migrations(settings.database_url, settings.scraper_environment)
    except Exception:
        logger.exception(
            "Failed to apply migrations during startup (env=%s)",
            settings.scraper_environment,
        )
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
    app.state.env = settings.scraper_environment
    app.state.config = settings

    try:
        from .services.features_seed import seed_starter_features
        from .dependencies import get_db

        gen = get_db()
        seed_conn = next(gen)
        try:
            seed_starter_features(seed_conn, settings.scraper_environment)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
    except Exception:
        logger.exception(
            "Failed to seed starter features during startup (env=%s)",
            settings.scraper_environment,
        )

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

    yield

    # Shutdown
    scraper_task.cancel()
    try:
        await scraper_task
    except asyncio.CancelledError:
        pass
    try:
        close_pool()
    except Exception:
        logger.warning("Error closing database pool during shutdown", exc_info=True)
    logger.info("Shutdown complete")


app = FastAPI(title="Jobs API", lifespan=lifespan)

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
app.include_router(features.router, prefix="/api/features", tags=["features"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return structured JSON for any unhandled server error."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get("/health")
def health():
    if not pool_is_healthy():
        return PlainTextResponse("UNAVAILABLE", status_code=503)
    return PlainTextResponse("OK")
