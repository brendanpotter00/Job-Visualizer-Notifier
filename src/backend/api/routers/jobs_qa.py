"""QA API endpoints - stats, scrape runs, trigger scrape."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..models import JobsStatsResponse, CompanyCountResponse, ScrapeRunResponse
from ..services.database import get_stats, get_scrape_runs

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats", response_model=JobsStatsResponse)
def stats(
    request: Request,
    conn: Connection = Depends(get_db),
    company: str | None = Query(default=None, pattern=r"^[a-zA-Z0-9_-]+$"),
):
    """Get job statistics with optional company filter."""
    env = request.app.state.env
    data = get_stats(conn, env, company=company)
    return JobsStatsResponse(
        total_jobs=data["total_jobs"],
        open_jobs=data["open_jobs"],
        closed_jobs=data["closed_jobs"],
        company_counts=[CompanyCountResponse(**c) for c in data["company_counts"]],
    )


@router.get("/scrape-runs", response_model=list[ScrapeRunResponse])
def scrape_runs(
    request: Request,
    conn: Connection = Depends(get_db),
    company: str | None = Query(default=None, pattern=r"^[a-zA-Z0-9_-]+$"),
    limit: int = Query(default=20, ge=1, le=1000),
):
    """Get scrape run history."""
    env = request.app.state.env
    runs = get_scrape_runs(conn, env, company=company, limit=limit)
    return [ScrapeRunResponse(**r) for r in runs]


@router.post("/trigger-scrape")
async def trigger_scrape(
    request: Request,
    background_tasks: BackgroundTasks,
    company: str = Query(default="google", pattern=r"^[a-zA-Z0-9_-]+$"),
):
    """Trigger a scrape run in the background. Returns 202 immediately."""
    from ..services.scraper_runner import run_scraper

    config = request.app.state.config

    async def _run_scraper_logged():
        try:
            result = await run_scraper(config, company)
            if result.exit_code != 0:
                logger.warning(
                    "Triggered scrape for %s finished with exit code %d: %s",
                    company, result.exit_code, result.error,
                )
            else:
                logger.info("Triggered scrape for %s completed successfully", company)
        except Exception:
            logger.exception("Triggered scrape for %s failed", company)

    background_tasks.add_task(_run_scraper_logged)

    return JSONResponse(
        status_code=202,
        content={"message": f"Scrape started for {company}", "company": company},
    )
