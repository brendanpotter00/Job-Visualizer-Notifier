"""Public curated-companies directory endpoint.

Read-only, no auth, no query params: returns every enabled company with its
directory content (blurb + accomplishment), alphabetically by display name. The
frontend does search / alphabetical sort / infinite-scroll reveal client-side
over this single payload (~130 short rows), mirroring the ``/api/features`` +
Changelog design.
"""

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_db
from ..models import CompanyListResponse, CompanyProfileResponse
from ..services.companies_service import list_enabled_companies_with_profiles

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=CompanyListResponse)
def list_companies(conn=Depends(get_db)):
    try:
        rows = list_enabled_companies_with_profiles(conn)
    except psycopg2.Error:
        # Roll back so the pooled connection isn't returned in an aborted-
        # transaction state — the next get_db caller would otherwise hit
        # "current transaction is aborted" on their first statement.
        conn.rollback()
        logger.exception("Failed to list companies")
        raise HTTPException(status_code=500, detail="Failed to list companies")
    return CompanyListResponse(
        companies=[
            CompanyProfileResponse(
                id=r["id"],
                display_name=r["display_name"],
                ats=r["ats"],
                blurb=r["blurb"],
                accomplishment=r["accomplishment"],
            )
            for r in rows
        ]
    )
