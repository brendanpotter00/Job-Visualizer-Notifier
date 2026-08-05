"""Companies router: the public directory read, plus the ATS resolve probe.

``GET ""`` is read-only, no auth, no query params: every enabled company with
its directory content (blurb + accomplishment), alphabetically by display name.
The frontend does search / alphabetical sort / infinite-scroll reveal
client-side over this single payload (~130 short rows), mirroring the
``/api/features`` + Changelog design.

``POST /resolve`` takes a careers-page URL a signed-in user pasted and answers
"is there an ATS board behind this, and does it actually have jobs?". It
**persists nothing** — no ``companies`` row, no audit row (that arrives with
PR 3's ``company_add_attempts``). Rollback for the whole custom-sources feature
is leaving ``custom_company_sources_enabled`` off, which 503s this route, or
deleting it outright.
"""

import logging

import httpx
import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from psycopg2.extensions import connection as Connection

from ..auth.claims import TokenClaims
from ..auth.dependencies import get_current_user
from ..config import settings
from ..dependencies import get_db
from ..models import (
    AtsCandidateResponse,
    CompanyListResponse,
    CompanyProfileResponse,
    ProbeResultResponse,
    ResolveUrlRequest,
    ResolveUrlResponse,
)
from ..services.ats_discovery import discover_ats, probe_candidate
from ..services.companies_service import list_enabled_companies_with_profiles

logger = logging.getLogger(__name__)

router = APIRouter()

# Outer bound on one resolve call: up to 5 guarded redirect hops plus up to 4
# sniff fetches plus the 12s probe. Individual steps carry their own, tighter
# timeouts in ``ats_discovery``; this is the backstop.
_RESOLVE_CLIENT_TIMEOUT_S = 30.0


def _http_client() -> httpx.AsyncClient:
    """The client discovery + probe share for one request.

    A module-level factory rather than an inline constructor so tests can swap
    in an ``httpx.MockTransport`` without monkeypatching httpx itself.
    ``follow_redirects=False`` is load-bearing: every redirect in the discovery
    path is followed manually by ``url_guard.guarded_get`` so each hop can be
    revalidated before its request goes out.
    """
    return httpx.AsyncClient(
        follow_redirects=False, timeout=_RESOLVE_CLIENT_TIMEOUT_S
    )


@router.get("", response_model=CompanyListResponse)
def list_companies(conn: Connection = Depends(get_db)) -> CompanyListResponse:
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


@router.post("/resolve", response_model=ResolveUrlResponse)
async def resolve_company_url(
    payload: ResolveUrlRequest,
    _user: TokenClaims = Depends(get_current_user),
) -> ResolveUrlResponse | JSONResponse:
    """Resolve a pasted careers URL to an ATS candidate and probe it.

    Writes nothing. Returns 503 when the feature flag is off, 401 without a
    Bearer token (via ``get_current_user``), and 422 with a stable, machine-
    readable ``reason`` when no board could be found or the URL was rejected by
    the SSRF guard. The 422 body is flat (``reason`` / ``finalUrl`` / ``hops``)
    rather than nested under ``detail`` because the frontend and PR 3's audit
    log both key off ``reason``.
    """
    if not settings.custom_company_sources_enabled:
        raise HTTPException(
            status_code=503, detail="Custom company sources are not enabled"
        )

    async with _http_client() as http:
        result = await discover_ats(payload.url, http)
        if result.candidate is None:
            logger.info(
                "Resolve miss for %r: reason=%s via=%s hops=%d",
                payload.url, result.reason, result.via, len(result.hops),
            )
            return JSONResponse(
                status_code=422,
                content={
                    "reason": result.reason or "no_ats_detected",
                    "finalUrl": result.final_url,
                    "hops": list(result.hops),
                },
            )
        probe = await probe_candidate(result.candidate, http)

    logger.info(
        "Resolve hit for %r: ats=%s token=%s via=%s probe_ok=%s jobs=%d",
        payload.url, result.candidate.ats, result.candidate.board_token,
        result.via, probe.ok, probe.job_count,
    )
    return ResolveUrlResponse(
        candidate=AtsCandidateResponse(
            ats=result.candidate.ats,
            board_token=result.candidate.board_token,
            provider_config=result.candidate.provider_config,
            source_url=result.candidate.source_url,
        ),
        probe=ProbeResultResponse(
            ok=probe.ok, job_count=probe.job_count, error=probe.error
        ),
        via=result.via,
        hops=list(result.hops),
        final_url=result.final_url,
    )
