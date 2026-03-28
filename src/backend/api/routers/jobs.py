"""Jobs API endpoints - GET /api/jobs, GET /api/jobs/{id}."""

from fastapi import APIRouter, HTTPException, Query, Request

from ..models import JobListingResponse
from ..services.database import get_jobs, get_job_by_id

router = APIRouter()


@router.get("", response_model=list[JobListingResponse])
def list_jobs(
    request: Request,
    company: str | None = None,
    status: str = "OPEN",
    limit: int = Query(default=5000, ge=1),
    offset: int = Query(default=0, ge=0),
):
    """List jobs with optional filtering. Status param accepted but not applied (matches C# behavior)."""
    conn = request.app.state.db_conn
    env = request.app.state.env
    jobs = get_jobs(conn, env, company=company, limit=limit, offset=offset)
    return [JobListingResponse(**job) for job in jobs]


@router.get("/{job_id}", response_model=JobListingResponse)
def get_job(request: Request, job_id: str):
    """Get a single job by ID."""
    conn = request.app.state.db_conn
    env = request.app.state.env
    job = get_job_by_id(conn, env, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobListingResponse(**job)
