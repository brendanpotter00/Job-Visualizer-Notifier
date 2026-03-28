"""QA API endpoints - stats, scrape runs, trigger scrape."""

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse

from ..models import JobsStatsResponse, CompanyCountResponse, ScrapeRunResponse
from ..services.database import get_stats, get_scrape_runs

router = APIRouter()


@router.get("/stats", response_model=JobsStatsResponse)
def stats(request: Request, company: str | None = None):
    """Get job statistics with optional company filter."""
    conn = request.app.state.db_conn
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
    company: str | None = None,
    limit: int = Query(default=20, ge=1),
):
    """Get scrape run history."""
    conn = request.app.state.db_conn
    env = request.app.state.env
    runs = get_scrape_runs(conn, env, company=company, limit=limit)
    return [ScrapeRunResponse(**r) for r in runs]


@router.post("/trigger-scrape")
async def trigger_scrape(
    request: Request,
    background_tasks: BackgroundTasks,
    company: str = Query(default="google"),
):
    """Trigger a scrape run in the background. Returns 202 immediately."""
    from ..services.scraper_runner import run_scraper

    config = request.app.state.config
    background_tasks.add_task(run_scraper, config, company)

    return JSONResponse(
        status_code=202,
        content={"message": f"Scrape started for {company}", "company": company},
    )
