"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from .config import settings
from .routers import jobs, jobs_qa
from scripts.shared.database import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Connecting to database...")
    conn = get_connection(settings.database_url, settings.scraper_environment)
    app.state.db_conn = conn
    app.state.env = settings.scraper_environment
    app.state.config = settings

    # Start background auto-scraper
    from .services.auto_scraper import auto_scraper_loop

    scraper_task = asyncio.create_task(auto_scraper_loop(settings))
    logger.info("Auto-scraper background task started")

    yield

    # Shutdown
    scraper_task.cancel()
    try:
        await scraper_task
    except asyncio.CancelledError:
        pass
    conn.close()
    logger.info("Shutdown complete")


app = FastAPI(title="Jobs API", lifespan=lifespan)

app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(jobs_qa.router, prefix="/api/jobs-qa", tags=["jobs-qa"])


@app.get("/health")
def health():
    return PlainTextResponse("OK")
