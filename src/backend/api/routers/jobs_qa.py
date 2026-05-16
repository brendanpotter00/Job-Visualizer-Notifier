"""QA API endpoints - stats, scrape runs, trigger scrape."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse
from procrastinate import exceptions as procrastinate_exceptions
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, require_admin
from ..config import settings
from ..dependencies import get_db
from ..models import COMPANY_PATTERN, JobsStatsResponse, CompanyCountResponse, ScrapeRunResponse
from ..services.database import get_stats, get_scrape_runs
from ..services.scraper_lock import scraper_lock
from ..tasks.enqueue_greenhouse_fan_out import enqueue_greenhouse_fan_out
from ..tasks.fetch_greenhouse_company import fetch_greenhouse_company

from scripts.shared import database as scripts_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stats", response_model=JobsStatsResponse)
def stats(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
    company: str | None = Query(default=None, pattern=COMPANY_PATTERN),
):
    """Get job statistics with optional company filter. Admin-only."""
    data = get_stats(conn, company=company)
    return JobsStatsResponse(
        total_jobs=data["total_jobs"],
        open_jobs=data["open_jobs"],
        closed_jobs=data["closed_jobs"],
        company_counts=[CompanyCountResponse(**c) for c in data["company_counts"]],
    )


@router.get("/scrape-runs", response_model=list[ScrapeRunResponse])
def scrape_runs(
    conn: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
    company: str | None = Query(default=None, pattern=COMPANY_PATTERN),
    limit: int = Query(default=20, ge=1, le=1000),
):
    """Get scrape run history. Admin-only."""
    runs = get_scrape_runs(conn, company=company, limit=limit)
    return [ScrapeRunResponse(**r) for r in runs]


@router.post("/trigger-scrape")
async def trigger_scrape(
    request: Request,
    background_tasks: BackgroundTasks,
    _admin: TokenClaims = Depends(require_admin),
    company: str = Query(default="google", pattern=COMPANY_PATTERN),
):
    """Trigger a scrape run in the background. Returns 202 immediately. Admin-only."""
    from ..services.scraper_runner import run_scraper

    if scraper_lock.locked():
        return JSONResponse(
            status_code=409,
            content={"detail": "A scrape is already in progress"},
        )

    # Acquire lock now to eliminate TOCTOU race between the check above and
    # background task execution.  asyncio.Lock.acquire() returns immediately
    # when unlocked (no event-loop yield), so no concurrent coroutine can
    # sneak in between the locked() check and here.
    await scraper_lock.acquire()

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
        finally:
            scraper_lock.release()

    background_tasks.add_task(_run_scraper_logged)

    return JSONResponse(
        status_code=202,
        content={"message": f"Scrape started for {company}", "company": company},
    )


@router.post("/trigger-greenhouse-fetch")
async def trigger_greenhouse_fetch(
    company_id: str = Query(
        ...,
        pattern=COMPANY_PATTERN,
        description="Company id (e.g. 'stripe'). Must exist in companies table with ats='greenhouse' and enabled=true.",
    ),
):
    """Manually defer a single fetch_greenhouse_company task.

    Looks up the company in the companies table to (a) defend against
    typos in manual triggers and (b) source the canonical board_token
    rather than trusting a query param.

    Returns 202 on successful defer, 202 with already_enqueued=true if
    a prior run for the same company is still pending/running, or 404
    if the company is unknown / disabled / not greenhouse.
    """
    conn = scripts_db.get_connection(settings.database_url)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, board_token FROM companies "
            "WHERE id = %s AND ats = 'greenhouse' AND enabled = true",
            (company_id,),
        )
        row = cur.fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            logger.warning(
                "Error closing trigger-greenhouse-fetch connection",
                exc_info=True,
            )

    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    f"No enabled greenhouse company with id={company_id!r}"
                ),
            },
        )

    board_token = row["board_token"]

    try:
        await fetch_greenhouse_company.configure(
            queueing_lock=f"greenhouse:{company_id}",
        ).defer_async(
            company_id=company_id,
            board_token=board_token,
        )
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-greenhouse-fetch: fetch_greenhouse_company already "
            "enqueued for %s; manual trigger collapsed by queueing_lock",
            company_id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    f"fetch_greenhouse_company already in flight for "
                    f"{company_id}; manual trigger deduped"
                ),
                "company_id": company_id,
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": f"fetch_greenhouse_company deferred for {company_id}",
            "company_id": company_id,
            "already_enqueued": False,
        },
    )


@router.post("/trigger-greenhouse-fan-out")
async def trigger_greenhouse_fan_out():
    """Manually defer the enqueue_greenhouse_fan_out task.

    The fan-out task does not carry a queueing lock (per-company locks
    live on the children). We catch AlreadyEnqueued defensively so a
    future decision to add a fan-out lock won't break this endpoint.
    """
    try:
        await enqueue_greenhouse_fan_out.defer_async(timestamp=0)
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-greenhouse-fan-out: enqueue_greenhouse_fan_out "
            "already enqueued; manual trigger collapsed"
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    "enqueue_greenhouse_fan_out already enqueued; "
                    "manual trigger deduped"
                ),
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": "enqueue_greenhouse_fan_out deferred",
            "already_enqueued": False,
        },
    )
