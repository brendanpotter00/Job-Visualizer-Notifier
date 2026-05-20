"""Jobs API endpoints - GET /api/jobs, GET /api/jobs/{source_id}/{id}."""

import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..models import COMPANY_PATTERN, ENABLED_COMPANY_ID_PATTERN, JobListingResponse
from ..services.database import get_jobs, get_job_by_id

router = APIRouter()

# Max IDs accepted in `?companies=a,b,c` to bound query size and prevent
# unbounded `IN`-list scans. Recent Jobs fans out across all backend-scraper
# companies — 102 today (Greenhouse + Ashby + Lever + Gem + Eightfold +
# Google/Apple/Microsoft). 150 keeps the original ~50% headroom posture
# (cap was 100 against 49 companies when added). The frontend chunks
# requests at 50 IDs/call so this server-side cap is a defense-in-depth
# bound, not the hot path.
_MAX_COMPANIES_PER_REQUEST = 150
_COMPANY_ID_RE = re.compile(ENABLED_COMPANY_ID_PATTERN)


@router.get("", response_model=list[JobListingResponse])
def list_jobs(
    conn: Connection = Depends(get_db),
    company: str | None = Query(default=None, pattern=COMPANY_PATTERN),
    companies: str | None = Query(
        default=None,
        description=(
            "Comma-separated list of company IDs. Mutually exclusive with "
            "`company`. Max 150 IDs."
        ),
        max_length=4096,
    ),
    status: str | None = Query(default=None, pattern=r"^(OPEN|CLOSED)$"),
    # Cap accommodates the Recent Jobs page's batched fetch across all
    # backend-scraper companies (~16k+ OPEN rows at the time of writing) in
    # one round trip. The per-company default remains 5000.
    limit: int = Query(default=5000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
):
    """List jobs with optional filtering by company and status.

    Accepts either a single ``company`` or a comma-separated ``companies``
    list (for batched per-company fetches from the Recent Jobs page).
    Passing both is a 400.
    """
    company_list: list[str] | None = None
    if companies is not None:
        if company is not None:
            raise HTTPException(
                status_code=400,
                detail="Use either 'company' or 'companies', not both.",
            )
        # Reject empty / whitespace-only values rather than silently treating
        # them as "no filter" — that would be surprising behavior on a typo.
        raw_ids = [c.strip() for c in companies.split(",")]
        if not raw_ids or any(not c for c in raw_ids):
            raise HTTPException(
                status_code=400,
                detail="'companies' must be a non-empty comma-separated list.",
            )
        if len(raw_ids) > _MAX_COMPANIES_PER_REQUEST:
            raise HTTPException(
                status_code=400,
                detail=f"'companies' accepts at most {_MAX_COMPANIES_PER_REQUEST} IDs.",
            )
        for cid in raw_ids:
            if not _COMPANY_ID_RE.match(cid):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid company id in 'companies': {cid!r}",
                )
        company_list = raw_ids

    jobs = get_jobs(
        conn,
        company=company,
        companies=company_list,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [JobListingResponse(**job) for job in jobs]


@router.get("/{source_id}/{job_id}", response_model=JobListingResponse)
def get_job(
    source_id: str = Path(max_length=100),
    job_id: str = Path(max_length=200),
    conn: Connection = Depends(get_db),
):
    """Get a single job by composite ``(source_id, id)`` key.

    Returns 404 if no row matches the composite key.
    """
    job = get_job_by_id(conn, source_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobListingResponse(**job)
