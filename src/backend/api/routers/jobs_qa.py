"""QA API endpoints - stats, scrape runs, trigger scrape."""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse
from procrastinate import exceptions as procrastinate_exceptions
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, require_admin
from ..dependencies import get_db
from ..models import COMPANY_PATTERN, JobsStatsResponse, CompanyCountResponse, ScrapeRunResponse
from ..services.database import get_stats, get_scrape_runs
from ..services.scraper_lock import scraper_lock
from ..services.eightfold_client import _is_allowed_eightfold_host
from ..tasks.enqueue_ashby_fan_out import enqueue_ashby_fan_out
from ..tasks.enqueue_eightfold_fan_out import enqueue_eightfold_fan_out
from ..tasks.enqueue_gem_fan_out import enqueue_gem_fan_out
from ..tasks.enqueue_greenhouse_fan_out import enqueue_greenhouse_fan_out
from ..tasks.enqueue_lever_fan_out import enqueue_lever_fan_out
from ..tasks.fetch_ashby_company import fetch_ashby_company
from ..tasks.fetch_eightfold_company import fetch_eightfold_company
from ..tasks.fetch_gem_company import fetch_gem_company
from ..tasks.fetch_greenhouse_company import fetch_greenhouse_company
from ..tasks.fetch_lever_company import fetch_lever_company

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
                # ERROR (not WARNING): Railway routes by Python log level
                # to stdout/stderr, and a non-zero scraper exit must surface
                # in @level:error filters so failed scheduled scrapes are
                # actionable rather than buried in info noise.
                logger.error(
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
    db: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
):
    """Manually defer a single fetch_greenhouse_company task.

    Looks up the company in the companies table to (a) defend against
    typos in manual triggers and (b) source the canonical board_token
    rather than trusting a query param.

    Returns 202 on successful defer, 202 with already_enqueued=true if
    a prior run for the same company is still pending/running, or 404
    if the company is unknown / disabled / not greenhouse.

    Uses the shared bounded `ThreadedConnectionPool` via `Depends(get_db)`
    rather than a fresh connection so concurrent QA spam can't blow past
    `db_pool_max` and exhaust prod `max_connections`.
    """
    cur = db.cursor()
    cur.execute(
        "SELECT id, board_token FROM companies "
        "WHERE id = %s AND ats = 'greenhouse' AND enabled = true",
        (company_id,),
    )
    row = cur.fetchone()

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
async def trigger_greenhouse_fan_out(
    _admin: TokenClaims = Depends(require_admin),
):
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


@router.post("/trigger-ashby-fetch")
async def trigger_ashby_fetch(
    company_id: str = Query(
        ...,
        pattern=COMPANY_PATTERN,
        description="Company id (e.g. 'notion'). Must exist in companies table with ats='ashby' and enabled=true.",
    ),
    db: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
):
    """Manually defer a single fetch_ashby_company task.

    Looks up the company in the companies table to (a) defend against
    typos in manual triggers and (b) source the canonical board_token
    rather than trusting a query param.

    Returns 202 on successful defer, 202 with already_enqueued=true if
    a prior run for the same company is still pending/running, or 404
    if the company is unknown / disabled / not ashby.

    Uses the shared bounded `ThreadedConnectionPool` via `Depends(get_db)`
    rather than a fresh connection so concurrent QA spam can't blow past
    `db_pool_max` and exhaust prod `max_connections`.
    """
    cur = db.cursor()
    cur.execute(
        "SELECT id, board_token FROM companies "
        "WHERE id = %s AND ats = 'ashby' AND enabled = true",
        (company_id,),
    )
    row = cur.fetchone()

    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    f"No enabled ashby company with id={company_id!r}"
                ),
            },
        )

    board_token = row["board_token"]

    try:
        await fetch_ashby_company.configure(
            queueing_lock=f"ashby:{company_id}",
        ).defer_async(
            company_id=company_id,
            board_token=board_token,
        )
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-ashby-fetch: fetch_ashby_company already "
            "enqueued for %s; manual trigger collapsed by queueing_lock",
            company_id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    f"fetch_ashby_company already in flight for "
                    f"{company_id}; manual trigger deduped"
                ),
                "company_id": company_id,
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": f"fetch_ashby_company deferred for {company_id}",
            "company_id": company_id,
            "already_enqueued": False,
        },
    )


@router.post("/trigger-ashby-fan-out")
async def trigger_ashby_fan_out(
    _admin: TokenClaims = Depends(require_admin),
):
    """Manually defer the enqueue_ashby_fan_out task.

    The fan-out task does not carry a queueing lock (per-company locks
    live on the children). We catch AlreadyEnqueued defensively so a
    future decision to add a fan-out lock won't break this endpoint.
    """
    try:
        await enqueue_ashby_fan_out.defer_async(timestamp=0)
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-ashby-fan-out: enqueue_ashby_fan_out "
            "already enqueued; manual trigger collapsed"
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    "enqueue_ashby_fan_out already enqueued; "
                    "manual trigger deduped"
                ),
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": "enqueue_ashby_fan_out deferred",
            "already_enqueued": False,
        },
    )


@router.post("/trigger-lever-fetch")
async def trigger_lever_fetch(
    company_id: str = Query(
        ...,
        pattern=COMPANY_PATTERN,
        description="Company id (e.g. 'palantir'). Must exist in companies table with ats='lever' and enabled=true.",
    ),
    db: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
):
    """Manually defer a single fetch_lever_company task.

    Looks up the company in the companies table to (a) defend against
    typos in manual triggers and (b) source the canonical board_token
    rather than trusting a query param.

    Returns 202 on successful defer, 202 with already_enqueued=true if
    a prior run for the same company is still pending/running, or 404
    if the company is unknown / disabled / not lever.

    Uses the shared bounded `ThreadedConnectionPool` via `Depends(get_db)`
    rather than a fresh connection so concurrent QA spam can't blow past
    `db_pool_max` and exhaust prod `max_connections`.
    """
    cur = db.cursor()
    cur.execute(
        "SELECT id, board_token FROM companies "
        "WHERE id = %s AND ats = 'lever' AND enabled = true",
        (company_id,),
    )
    row = cur.fetchone()

    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    f"No enabled lever company with id={company_id!r}"
                ),
            },
        )

    board_token = row["board_token"]

    try:
        await fetch_lever_company.configure(
            queueing_lock=f"lever:{company_id}",
        ).defer_async(
            company_id=company_id,
            board_token=board_token,
        )
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-lever-fetch: fetch_lever_company already "
            "enqueued for %s; manual trigger collapsed by queueing_lock",
            company_id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    f"fetch_lever_company already in flight for "
                    f"{company_id}; manual trigger deduped"
                ),
                "company_id": company_id,
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": f"fetch_lever_company deferred for {company_id}",
            "company_id": company_id,
            "already_enqueued": False,
        },
    )


@router.post("/trigger-lever-fan-out")
async def trigger_lever_fan_out(
    _admin: TokenClaims = Depends(require_admin),
):
    """Manually defer the enqueue_lever_fan_out task.

    The fan-out task does not carry a queueing lock (per-company locks
    live on the children). We catch AlreadyEnqueued defensively so a
    future decision to add a fan-out lock won't break this endpoint.
    """
    try:
        await enqueue_lever_fan_out.defer_async(timestamp=0)
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-lever-fan-out: enqueue_lever_fan_out "
            "already enqueued; manual trigger collapsed"
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    "enqueue_lever_fan_out already enqueued; "
                    "manual trigger deduped"
                ),
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": "enqueue_lever_fan_out deferred",
            "already_enqueued": False,
        },
    )


@router.post("/trigger-gem-fetch")
async def trigger_gem_fetch(
    company_id: str = Query(
        ...,
        pattern=COMPANY_PATTERN,
        description="Company id (e.g. 'retool'). Must exist in companies table with ats='gem' and enabled=true.",
    ),
    db: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
):
    """Manually defer a single fetch_gem_company task.

    Looks up the company in the companies table to (a) defend against
    typos in manual triggers and (b) source the canonical board_token
    rather than trusting a query param.

    Returns 202 on successful defer, 202 with already_enqueued=true if
    a prior run for the same company is still pending/running, or 404
    if the company is unknown / disabled / not gem.

    Uses the shared bounded `ThreadedConnectionPool` via `Depends(get_db)`
    rather than a fresh connection so concurrent QA spam can't blow past
    `db_pool_max` and exhaust prod `max_connections`.
    """
    cur = db.cursor()
    cur.execute(
        "SELECT id, board_token FROM companies "
        "WHERE id = %s AND ats = 'gem' AND enabled = true",
        (company_id,),
    )
    row = cur.fetchone()

    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    f"No enabled gem company with id={company_id!r}"
                ),
            },
        )

    board_token = row["board_token"]

    try:
        await fetch_gem_company.configure(
            queueing_lock=f"gem:{company_id}",
        ).defer_async(
            company_id=company_id,
            board_token=board_token,
        )
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-gem-fetch: fetch_gem_company already "
            "enqueued for %s; manual trigger collapsed by queueing_lock",
            company_id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    f"fetch_gem_company already in flight for "
                    f"{company_id}; manual trigger deduped"
                ),
                "company_id": company_id,
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": f"fetch_gem_company deferred for {company_id}",
            "company_id": company_id,
            "already_enqueued": False,
        },
    )


@router.post("/trigger-gem-fan-out")
async def trigger_gem_fan_out(
    _admin: TokenClaims = Depends(require_admin),
):
    """Manually defer the enqueue_gem_fan_out task.

    The fan-out task does not carry a queueing lock (per-company locks
    live on the children). We catch AlreadyEnqueued defensively so a
    future decision to add a fan-out lock won't break this endpoint.
    """
    try:
        await enqueue_gem_fan_out.defer_async(timestamp=0)
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-gem-fan-out: enqueue_gem_fan_out "
            "already enqueued; manual trigger collapsed"
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    "enqueue_gem_fan_out already enqueued; "
                    "manual trigger deduped"
                ),
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": "enqueue_gem_fan_out deferred",
            "already_enqueued": False,
        },
    )


def _fetch_eightfold_row(db: Connection, company_id: str) -> dict | None:
    """Sync DB lookup. Wrapped in ``asyncio.to_thread`` at the call site so
    the FastAPI event loop isn't blocked by the cursor round-trip."""
    cur = db.cursor()
    cur.execute(
        "SELECT id, board_token, provider_config FROM companies "
        "WHERE id = %s AND ats = 'eightfold' AND enabled = true",
        (company_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None


@router.post("/trigger-eightfold-fetch")
async def trigger_eightfold_fetch(
    company_id: str = Query(
        ...,
        pattern=COMPANY_PATTERN,
        description=(
            "Company id (e.g. 'netflix'). Must exist in companies table with "
            "ats='eightfold' and enabled=true."
        ),
    ),
    db: Connection = Depends(get_db),
    _admin: TokenClaims = Depends(require_admin),
):
    """Manually defer a single fetch_eightfold_company task.

    Performs the L2 SSRF check (provider_config keys present + tenant_host
    on allowlist) before deferring, so a typo in the seed migration would
    surface here as a 400 rather than as a queue-time silent failure.

    Returns:
      - 202 on successful defer
      - 202 with ``already_enqueued=true`` if a prior run is still in
        flight (queueing_lock collision)
      - 404 if the company is unknown / disabled / not eightfold
      - 400 if the company's provider_config is missing required keys
        or tenant_host is off the SSRF allowlist

    Uses the shared bounded ``ThreadedConnectionPool`` via
    ``Depends(get_db)`` (matches Greenhouse + Ashby triggers) so concurrent
    QA spam can't blow past ``db_pool_max`` and exhaust prod
    ``max_connections``. The cursor work is wrapped in
    ``asyncio.to_thread`` to keep the event loop responsive during the
    round-trip — stricter than the Greenhouse/Ashby siblings, which call
    ``cur.execute`` directly; carrying the extra rigor forward.
    """
    row = await asyncio.to_thread(_fetch_eightfold_row, db, company_id)

    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "detail": (
                    f"No enabled eightfold company with id={company_id!r}"
                ),
            },
        )

    provider_config = row.get("provider_config") or {}
    if not isinstance(provider_config, dict):
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"eightfold company {company_id!r} has non-dict "
                    f"provider_config (got {type(provider_config).__name__})"
                ),
            },
        )
    tenant_host = provider_config.get("tenant_host")
    domain = provider_config.get("domain")
    if not tenant_host or not isinstance(tenant_host, str):
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"eightfold company {company_id!r} provider_config is "
                    f"missing/empty tenant_host"
                ),
            },
        )
    if not domain or not isinstance(domain, str):
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"eightfold company {company_id!r} provider_config is "
                    f"missing/empty domain"
                ),
            },
        )
    if not _is_allowed_eightfold_host(tenant_host):
        return JSONResponse(
            status_code=400,
            content={
                "detail": (
                    f"eightfold company {company_id!r} tenant_host "
                    f"{tenant_host!r} is not on the SSRF allowlist"
                ),
            },
        )

    board_token = row["board_token"]

    try:
        await fetch_eightfold_company.configure(
            queueing_lock=f"eightfold:{company_id}",
        ).defer_async(
            company_id=company_id,
            board_token=board_token,
            provider_config=provider_config,
        )
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-eightfold-fetch: fetch_eightfold_company already "
            "enqueued for %s; manual trigger collapsed by queueing_lock",
            company_id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    f"fetch_eightfold_company already in flight for "
                    f"{company_id}; manual trigger deduped"
                ),
                "company_id": company_id,
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": f"fetch_eightfold_company deferred for {company_id}",
            "company_id": company_id,
            "already_enqueued": False,
        },
    )


@router.post("/trigger-eightfold-fan-out")
async def trigger_eightfold_fan_out(
    _admin: TokenClaims = Depends(require_admin),
):
    """Manually defer the enqueue_eightfold_fan_out task.

    Used by DEPLOY.md to populate ``job_listings`` within ~30s of a deploy
    instead of waiting up to 30 min for the next cron tick.

    The fan-out task does not carry a queueing lock (per-company locks
    live on the children). We catch AlreadyEnqueued defensively so a
    future decision to add a fan-out lock won't break this endpoint.
    """
    try:
        await enqueue_eightfold_fan_out.defer_async(timestamp=0)
    except procrastinate_exceptions.AlreadyEnqueued:
        logger.info(
            "trigger-eightfold-fan-out: enqueue_eightfold_fan_out "
            "already enqueued; manual trigger collapsed"
        )
        return JSONResponse(
            status_code=202,
            content={
                "message": (
                    "enqueue_eightfold_fan_out already enqueued; "
                    "manual trigger deduped"
                ),
                "already_enqueued": True,
            },
        )

    return JSONResponse(
        status_code=202,
        content={
            "message": "enqueue_eightfold_fan_out deferred",
            "already_enqueued": False,
        },
    )
