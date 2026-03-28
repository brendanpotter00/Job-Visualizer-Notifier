"""Jobs API endpoints - GET /api/jobs, GET /api/jobs/{id}."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..models import JobListingResponse
from ..services.database import get_jobs, get_job_by_id

router = APIRouter()


@router.get("", response_model=list[JobListingResponse])
def list_jobs(
    request: Request,
    conn: Connection = Depends(get_db),
    company: str | None = Query(default=None, pattern=r"^[a-zA-Z0-9_-]+$"),
    status: str | None = Query(default=None, pattern=r"^(OPEN|CLOSED)$"),
    limit: int = Query(default=5000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
):
    """List jobs with optional filtering by company and status."""
    env = request.app.state.env
    jobs = get_jobs(conn, env, company=company, status=status, limit=limit, offset=offset)
    return [JobListingResponse(**job) for job in jobs]


@router.get("/{job_id}", response_model=JobListingResponse)
def get_job(
    request: Request,
    job_id: str,
    conn: Connection = Depends(get_db),
):
    """Get a single job by ID."""
    env = request.app.state.env
    job = get_job_by_id(conn, env, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobListingResponse(**job)
