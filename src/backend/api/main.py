"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from .config import settings
from .dependencies import init_pool, close_pool, pool_is_healthy
from .routers import jobs, jobs_qa
from scripts.shared.database import init_schema, get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Connecting to database...")
    try:
        # Ensure schema exists using a temporary connection
        temp_conn = get_connection(settings.database_url, settings.scraper_environment)
        try:
            init_schema(temp_conn, settings.scraper_environment)
        finally:
            temp_conn.close()
        # Create the connection pool for request handling
        init_pool(settings.database_url)
    except Exception:
        logger.exception("Failed to connect to database")
        raise
    app.state.env = settings.scraper_environment
    app.state.config = settings

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
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(jobs_qa.router, prefix="/api/jobs-qa", tags=["jobs-qa"])


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
