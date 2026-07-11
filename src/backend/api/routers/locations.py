"""Public canonical-location search — GET /api/locations/search.

Substring autocomplete over the read-only ``locations`` table, used by the
Location filter dropdown on the (signed-out-friendly) Recent Job Postings and
company hiring-trend pages. Unlike the rest of the location tooling this is
**not** auth-gated — the pages it serves are public — but it still sits behind
the ``require_internal_key`` middleware (server-to-server key added by the
Vercel proxy), exactly like ``/api/jobs``.

The query logic is shared with the saved-filters feature via
``saved_filters_service.search_locations``; only the auth posture differs.
"""

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..models import LocationSearchResult
from ..services import saved_filters_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/search", response_model=list[LocationSearchResult])
def search_locations(
    conn: Connection = Depends(get_db),
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    open_only: bool = Query(default=False, alias="openOnly"),
) -> list[LocationSearchResult]:
    """Substring autocomplete over canonical location names (public)."""
    try:
        rows = saved_filters_service.search_locations(conn, q, limit, open_only)
    except psycopg2.Error:
        logger.exception("Failed to search locations for q=%r", q)
        raise HTTPException(status_code=500, detail="Failed to search locations")
    return [
        LocationSearchResult(
            id=r["id"],
            canonical_name=r["canonical_name"],
            kind=r["kind"],
            city=r["city"],
            region=r["region"],
            country=r["country"],
            remote_scope=r["remote_scope"],
        )
        for r in rows
    ]
