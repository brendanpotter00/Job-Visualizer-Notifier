"""Private custom-company endpoints — ``/api/users/companies`` (E7 Phase 1).

Mounted UNDER ``/api/users`` so the existing ``api/users.ts`` Vercel proxy (which
forwards the Authorization header) reaches these without a new proxy. Every
route requires a Bearer token (``get_current_user``) and is gated by the
``custom_company_sources_enabled`` flag — 503 when off, so the whole feature
ships dark and rolls back by flipping the flag.

The load-bearing invariant: ``visibility='user'`` jobs are served ONLY by
``GET /api/users/companies/{id}/jobs``, which 403s any caller that does not own
the company. The public ``/api/jobs`` never serves them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlparse

import httpx
import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Path, Response
from fastapi.responses import JSONResponse
from psycopg2.extensions import connection as Connection

from scripts.shared.constants import custom

from ..auth.claims import TokenClaims
from ..auth.dependencies import get_current_user
from ..auth.jwt import get_normalized_subject
from ..config import settings
from ..dependencies import get_db
from ..models import (
    AddUserCompanyRequest,
    JobListingResponse,
    UserCompanyListResponse,
    UserCompanyResponse,
)
from ..services import custom_companies_service as svc
from ..services.ats_discovery import discover_ats, probe_candidate
from ..services.database import get_user_company_jobs
from ..services.user_service import get_or_create_user, get_user_by_email

logger = logging.getLogger(__name__)

router = APIRouter()

# Same aggregate outbound budget the resolve endpoint uses: one add can fan out
# to ~36 third-party requests (discovery ladder) plus a probe, so the monotonic
# deadline is threaded into every guarded hop and the outer wait_for is the
# backstop for anything the deadline doesn't cover.
_RESOLVE_BUDGET_S = 25.0
_RESOLVE_GRACE_S = 2.0
_RESOLVE_CLIENT_TIMEOUT_S = 30.0


def _http_client() -> httpx.AsyncClient:
    """The client discovery + probe share for one add. Module-level so tests can
    swap in an ``httpx.MockTransport`` without monkeypatching httpx itself.
    ``follow_redirects=False`` — the discovery path follows every redirect
    manually so each hop is re-validated by ``url_guard`` before its request."""
    return httpx.AsyncClient(
        follow_redirects=False, timeout=_RESOLVE_CLIENT_TIMEOUT_S
    )


def _require_flag() -> None:
    if not settings.custom_company_sources_enabled:
        raise HTTPException(
            status_code=503, detail="Custom company sources are not enabled"
        )


def _to_response(row: dict) -> UserCompanyResponse:
    return UserCompanyResponse(
        id=row["id"],
        display_name=row["display_name"],
        ats=row["ats"],
        board_token=row["board_token"],
        source_id=row.get("source_id") or custom(row["id"]),
        health_state=row.get("health_state"),
        open_job_count=int(row.get("open_job_count") or 0),
        last_success_at=row.get("last_success_at"),
        tracking_started_at=row.get("tracking_started_at"),
    )


def _reject(status: int, reason: str, detail: str, final_url: str | None = None) -> JSONResponse:
    body: dict[str, object] = {"reason": reason, "detail": detail}
    if final_url is not None:
        body["finalUrl"] = final_url
    return JSONResponse(status_code=status, content=body)


def _discovery_display_name(final_url: str) -> str:
    """A human label for a discovered company — the host of its final URL."""
    host = urlparse(final_url).netloc
    return host or final_url


async def _defer_discovery(
    *, user_id: str, submitted_url: str, normalized_url: str, display_name: str
) -> None:
    """Enqueue the one-time ``discover_custom_company`` task on its own queue.

    Module-level + lazily importing the task (which pulls in the discovery
    package, and thus ``anthropic``) so the router's import graph stays light and
    tests can monkeypatch this seam without opening a live worker. A per-URL
    queueing lock collapses a double-submit into one discovery run.
    """
    from ..tasks.discover_custom_company import discover_custom_company

    await discover_custom_company.configure(
        queueing_lock=f"discover:{normalized_url}",
    ).defer_async(
        user_id=user_id,
        submitted_url=submitted_url,
        normalized_url=normalized_url,
        display_name=display_name,
    )


@router.post("", response_model=UserCompanyResponse)
async def add_company(
    payload: AddUserCompanyRequest,
    response: Response,
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> UserCompanyResponse | JSONResponse:
    """Resolve a pasted careers URL, probe it, and create a private company.

    Requires ``job_count > 0``. Idempotent per ``UNIQUE(user_id,
    canonical_source_key)`` — re-adding the same board returns the existing
    company (200) instead of erroring. A non-ATS / unresolvable URL writes a
    ``company_add_attempts`` row with ``outcome='unsupported'`` and returns 422
    (Phase 3 will handle these); a resolvable board that probes 0 jobs or errors
    returns 422 with ``outcome='empty'`` / ``'probe_failed'``.
    """
    _require_flag()

    auth0_id = get_normalized_subject(user)
    email = user.get("email")
    if not auth0_id:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    try:
        user_row = get_or_create_user(
            conn,
            auth0_id=auth0_id,
            email=email,
            given_name=user.get("given_name"),
            family_name=user.get("family_name"),
            picture_url=user.get("picture"),
        )
    except psycopg2.Error:
        logger.exception("Failed to get/create user for custom-company add")
        raise HTTPException(status_code=500, detail="Failed to load user profile")
    user_id = user_row["id"]

    deadline = time.monotonic() + _RESOLVE_BUDGET_S
    async with _http_client() as http:
        try:
            result = await asyncio.wait_for(
                discover_ats(payload.url, http, deadline=deadline),
                timeout=_RESOLVE_BUDGET_S + _RESOLVE_GRACE_S,
            )
        except asyncio.TimeoutError:
            svc.record_add_attempt(
                conn, user_id=user_id, submitted_url=payload.url,
                normalized_url=None, outcome="unsupported",
                error_detail="deadline_exceeded",
            )
            return _reject(422, "deadline_exceeded", "Resolving the URL timed out.")

        if result.candidate is None:
            # Non-ATS URL. With the discovery sub-flag on, hand it to the one-time
            # async discovery agent (browser + LLM) and return 202; otherwise it
            # stays 422 'unsupported' — discovery (and its spend) ships dark and
            # rolls back by the flag. (The parent flag is already asserted on by
            # ``_require_flag`` above.)
            if settings.custom_company_discovery_enabled and result.final_url:
                normalized_url = result.final_url
                source_key = svc.discovered_source_key(normalized_url)
                existing = svc.find_owned_company_by_source_key(
                    conn, user_id, source_key
                )
                if existing is not None:
                    # Idempotent re-add of an already-discovered (or refused) board:
                    # resolve to the existing row instead of re-spending on discovery.
                    svc.record_add_attempt(
                        conn, user_id=user_id, submitted_url=payload.url,
                        normalized_url=normalized_url, outcome="discovery_pending",
                        resolved_ats="discovered", company_id=existing["id"],
                    )
                    existing["source_id"] = custom(existing["id"])
                    existing["open_job_count"] = svc.count_open_jobs(
                        conn, existing["id"]
                    )
                    response.status_code = 200
                    return _to_response(existing)

                svc.record_add_attempt(
                    conn, user_id=user_id, submitted_url=payload.url,
                    normalized_url=normalized_url, outcome="discovery_pending",
                    resolved_ats="discovered",
                )
                try:
                    await _defer_discovery(
                        user_id=user_id,
                        submitted_url=payload.url,
                        normalized_url=normalized_url,
                        display_name=_discovery_display_name(normalized_url),
                    )
                except Exception:
                    logger.exception(
                        "Failed to enqueue discovery for %s", normalized_url
                    )
                    raise HTTPException(
                        status_code=500, detail="Failed to start discovery"
                    )
                return JSONResponse(
                    status_code=202,
                    content={
                        "status": "discovery_pending",
                        "detail": (
                            "One-time setup — we're figuring out how to read this "
                            "board; jobs appear after the first scan."
                        ),
                        "finalUrl": normalized_url,
                    },
                )

            svc.record_add_attempt(
                conn, user_id=user_id, submitted_url=payload.url,
                normalized_url=result.final_url, outcome="unsupported",
                error_detail=result.reason or "no_ats_detected",
            )
            return _reject(
                422, result.reason or "no_ats_detected",
                "No supported ATS board was found behind this URL.",
                final_url=result.final_url,
            )

        candidate = result.candidate
        source_key = svc.canonical_source_key(candidate.ats, candidate.board_token)

        # Idempotent re-add: resolve to the caller's existing company, skip the
        # probe + create, but still record the attempt for the audit trail.
        existing = svc.find_owned_company_by_source_key(conn, user_id, source_key)
        if existing is not None:
            svc.record_add_attempt(
                conn, user_id=user_id, submitted_url=payload.url,
                normalized_url=result.final_url, outcome="added",
                resolved_ats=candidate.ats, board_token=candidate.board_token,
                company_id=existing["id"],
            )
            existing["source_id"] = custom(existing["id"])
            existing["open_job_count"] = svc.count_open_jobs(conn, existing["id"])
            response.status_code = 200
            return _to_response(existing)

        # New board — probe it. probe_candidate never raises; a failure is data.
        probe = await probe_candidate(candidate, http, deadline=deadline)

    if not probe.ok:
        svc.record_add_attempt(
            conn, user_id=user_id, submitted_url=payload.url,
            normalized_url=result.final_url, outcome="probe_failed",
            error_detail=probe.error, resolved_ats=candidate.ats,
            board_token=candidate.board_token,
        )
        return _reject(422, "probe_failed", probe.error or "The board could not be probed.")

    if probe.job_count <= 0:
        svc.record_add_attempt(
            conn, user_id=user_id, submitted_url=payload.url,
            normalized_url=result.final_url, outcome="empty",
            error_detail="board resolved but has 0 open jobs",
            resolved_ats=candidate.ats, board_token=candidate.board_token,
        )
        return _reject(422, "empty", "This board resolved but currently has no open jobs.")

    try:
        created = svc.add_custom_company(
            conn,
            user_id=user_id,
            ats=candidate.ats,
            board_token=candidate.board_token,
            provider_config=dict(candidate.provider_config),
            display_name=candidate.board_token,
            submitted_url=payload.url,
            normalized_url=result.final_url,
        )
    except psycopg2.Error:
        logger.exception("Failed to create custom company for user=%s", user_id)
        raise HTTPException(status_code=500, detail="Failed to add company")

    response.status_code = 201
    return _to_response(created)


@router.get("", response_model=UserCompanyListResponse)
async def list_companies(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> UserCompanyListResponse:
    """The caller's private companies with health, open-job count, last success."""
    _require_flag()
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    row = get_user_by_email(conn, email)
    if row is None:
        return UserCompanyListResponse(companies=[])
    try:
        companies = svc.list_owned_companies(conn, row["id"])
    except psycopg2.Error:
        conn.rollback()
        logger.exception("Failed to list custom companies for user=%s", row["id"])
        raise HTTPException(status_code=500, detail="Failed to load companies")
    return UserCompanyListResponse(companies=[_to_response(c) for c in companies])


@router.delete("/{company_id}", status_code=204)
async def delete_company(
    company_id: str = Path(max_length=64),
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> Response:
    """Remove the caller's ownership. If that was the last owner, disable the
    company (``enabled=false``) — rows are kept, never deleted."""
    _require_flag()
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    row = get_user_by_email(conn, email)
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    try:
        outcome = svc.delete_ownership(conn, row["id"], company_id)
    except psycopg2.Error:
        logger.exception("Failed to delete custom company %s for user=%s", company_id, row["id"])
        raise HTTPException(status_code=500, detail="Failed to remove company")
    if outcome == "not_owner":
        raise HTTPException(status_code=404, detail="Company not found")
    return Response(status_code=204)


@router.get("/{company_id}/jobs", response_model=list[JobListingResponse])
async def get_company_jobs(
    company_id: str = Path(max_length=64),
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> list[JobListingResponse]:
    """Owner-scoped jobs for a private company. 403 if the caller is not an owner.

    This is the ONLY path that serves ``visibility='user'`` jobs.
    """
    _require_flag()
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    row = get_user_by_email(conn, email)
    if row is None:
        raise HTTPException(status_code=403, detail="Not an owner of this company")
    if svc.get_company_if_owner(conn, row["id"], company_id) is None:
        raise HTTPException(status_code=403, detail="Not an owner of this company")
    jobs = get_user_company_jobs(conn, company_id, custom(company_id))
    return [JobListingResponse(**job) for job in jobs]
