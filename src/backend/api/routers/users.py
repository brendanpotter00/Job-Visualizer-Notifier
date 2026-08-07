"""User profile endpoints."""

import logging

import httpx
import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Response
from posthog import identify_context, new_context
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, get_current_user
from ..auth.jwt import get_normalized_subject
from ..config import settings
from ..dependencies import get_db
from ..models import (
    AddCompanyRequest,
    AddCompanyResponse,
    EnabledCompaniesResponse,
    EnabledCompaniesUpdateRequest,
    SubmissionStatusResponse,
    UserCompaniesResponse,
    UserCompanyDTO,
    UserResponse,
    UserUpdateRequest,
)
from ..services import company_add_service, company_submissions
from ..services.admin_service import is_admin_by_email
from ..services.company_add_service import company_to_dto
from ..services.posthog_client import get_posthog
from ..services.rate_limit import SlidingWindowRateLimiter
from ..services.url_guard import BlockedURLError
from ..services.user_preferences_service import (
    list_enabled_companies,
    set_enabled_companies,
)
from ..services.user_service import (
    UserRow,
    get_or_create_user,
    get_user_by_email,
    record_visit,
    update_user,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Per-user add-company quota (keyed on the token subject). Module-level singleton
# mirrors ``feedback_rate_limiter`` — authoritative because prod runs a single
# uvicorn process. See services/rate_limit.py.
_add_company_rate_limiter = SlidingWindowRateLimiter(
    settings.add_company_rate_limit_max,
    settings.add_company_rate_limit_window_seconds,
)

# Map the service outcome status to the wire status the frontend expects.
_ADD_STATUS_WIRE = {
    "added": "added",
    "already_tracked": "alreadyTracked",
    "needs_onboarding": "pending",
}


def _row_to_user_response(row: UserRow, *, is_admin: bool) -> UserResponse:
    """Map a DB row to the API response model.

    The DB column is ``auth0_id`` (legacy name) but the boundary field is
    ``provider_subject`` — see ``UserResponse`` docstring.

    ``is_admin`` is keyword-only with no default so a caller that forgets to
    compute it gets a TypeError at the helper, not a silent ``False`` that
    demotes an admin in the response.

    ``row`` is the ``UserRow`` TypedDict from ``user_service`` rather than an
    opaque ``dict`` — so a column rename in ``db_models.User`` becomes a
    mypy/pyright error at the per-field reads below instead of a runtime
    ``KeyError`` on the next ``/api/users`` request.
    """
    return UserResponse(
        id=row["id"],
        provider_subject=row["auth0_id"],
        email=row["email"],
        display_name=row["display_name"],
        given_name=row["given_name"],
        family_name=row["family_name"],
        picture_url=row["picture_url"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        is_admin=is_admin,
    )


@router.get("", response_model=UserResponse)
async def get_current_user_profile(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> UserResponse:
    """Get or create the authenticated user's profile.

    Catches only ``psycopg2.Error`` around ``get_or_create_user`` —
    ``RuntimeError`` (raised by the service on ambiguous identity) and
    ``HTTPException`` must propagate. The ambiguous-identity raise is
    load-bearing per ``docs/implementations/auth0/REVIEW_AUDIT.md``;
    swallowing it would hide a corrupted identity model.

    ``is_admin_by_email`` is intentionally called OUTSIDE the
    ``psycopg2.Error`` block so a failure surfaces as a 500 (per the
    service's "raise rather than silently deny" contract) instead of
    being demoted to ``isAdmin: false`` in the response.
    """
    auth0_id = get_normalized_subject(user)
    if not auth0_id:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    try:
        result = get_or_create_user(
            conn,
            auth0_id=auth0_id,
            email=email,
            given_name=user.get("given_name"),
            family_name=user.get("family_name"),
            picture_url=user.get("picture"),
        )
    except psycopg2.Error:
        logger.exception("Failed to get/create user profile for sub=%s", auth0_id)
        raise HTTPException(status_code=500, detail="Failed to load user profile")
    is_new_user = result["created_at"] == result["updated_at"]
    ph = get_posthog()
    if ph and is_new_user:
        try:
            with new_context():
                identify_context(auth0_id)
                ph.capture(
                    "user_signed_up",
                    distinct_id=auth0_id,
                    properties={"$set": {"email": email}},
                )
        except Exception:
            logger.warning(
                "PostHog capture failed for user_signed_up", exc_info=True
            )
    is_admin = is_admin_by_email(conn, email)
    return _row_to_user_response(result, is_admin=is_admin)


@router.post("/visit", status_code=204)
async def record_user_visit(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> Response:
    """Record one full-page-load visit for the authenticated user.

    The frontend calls this once per full page load / refresh (see the
    ``useRecordVisit`` hook); client-side SPA route navigation does NOT trigger
    it. Upserts the user row first — so a brand-new user's very first load,
    which can race ahead of ``GET /api/users``, is still counted — then
    atomically increments ``visit_count`` and stamps ``last_visit_at``.

    Subject/email resolution mirrors ``get_current_user_profile``. Only
    ``psycopg2.Error`` is caught (→ 500); ``RuntimeError`` from
    ``get_or_create_user`` on ambiguous identity must propagate, as in the GET.
    """
    auth0_id = get_normalized_subject(user)
    if not auth0_id:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    try:
        result = get_or_create_user(
            conn,
            auth0_id=auth0_id,
            email=email,
            given_name=user.get("given_name"),
            family_name=user.get("family_name"),
            picture_url=user.get("picture"),
        )
        record_visit(conn, result["id"])
    except psycopg2.Error:
        logger.exception("Failed to record visit for sub=%s", auth0_id)
        raise HTTPException(status_code=500, detail="Failed to record visit")
    return Response(status_code=204)


@router.put("", response_model=UserResponse)
async def update_current_user_profile(
    body: UserUpdateRequest,
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> UserResponse:
    """Update the authenticated user's display name.

    Keyed by ``email`` (the stable identifier) rather than ``auth0_id`` — a
    user's ``auth0_id`` can legitimately change when they switch providers,
    while their verified email is stable per row.
    """
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    try:
        result = update_user(conn, email=email, display_name=body.display_name)
    except psycopg2.Error:
        logger.exception("Failed to update user profile for email=%s", email)
        raise HTTPException(status_code=500, detail="Failed to update user profile")
    if result is None:
        # Surface the 404 BEFORE touching ``is_admin_by_email`` so the
        # admin-lookup failure mode isn't conflated with "no row" and so
        # the previous dead ``is_admin = False`` branch is removed.
        raise HTTPException(status_code=404, detail="User not found")
    # ``is_admin_by_email`` deliberately raises rather than silently
    # returning False on a driver error; let that propagate as 500 instead
    # of being caught above.
    is_admin = is_admin_by_email(conn, email)
    return _row_to_user_response(result, is_admin=is_admin)


@router.get("/enabled-companies", response_model=EnabledCompaniesResponse)
async def get_enabled_companies(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> EnabledCompaniesResponse:
    """Return the company IDs the authenticated user has enabled."""
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    row = get_user_by_email(conn, email)
    if row is None:
        return EnabledCompaniesResponse(company_ids=[])
    try:
        ids = list_enabled_companies(conn, row["id"])
    except psycopg2.Error:
        logger.exception("Failed to list enabled companies for user=%s", row["id"])
        raise HTTPException(
            status_code=500, detail="Failed to load enabled companies"
        )
    return EnabledCompaniesResponse(
        company_ids=ids,
        auto_enroll_new_companies=row["auto_enroll_new_companies"],
    )


@router.put("/enabled-companies", response_model=EnabledCompaniesResponse)
async def update_enabled_companies(
    body: EnabledCompaniesUpdateRequest,
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> EnabledCompaniesResponse:
    """Replace the authenticated user's enabled-companies set."""
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    row = get_user_by_email(conn, email)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        saved = set_enabled_companies(
            conn,
            row["id"],
            body.company_ids,
            body.auto_enroll_new_companies,
        )
    except psycopg2.Error:
        logger.exception("Failed to save enabled companies for user=%s", row["id"])
        raise HTTPException(
            status_code=500, detail="Failed to save enabled companies"
        )
    return EnabledCompaniesResponse(
        company_ids=saved,
        auto_enroll_new_companies=body.auto_enroll_new_companies,
    )


def _require_identity(user: TokenClaims) -> tuple[str, str]:
    """Return (subject, email) or raise 401. Shared by the company endpoints."""
    subject = get_normalized_subject(user)
    if not subject:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    return subject, email


@router.post("/companies", response_model=AddCompanyResponse)
async def add_company(
    body: AddCompanyRequest,
    response: Response,
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> AddCompanyResponse:
    """Add a company to track by careers-page URL.

    Synchronous (Tier 1) when the URL is a known ATS board → 200 with the
    company. When it's a custom site → 202 with a ``submissionId`` and an async
    onboarding job (Playwright capture + Haiku recipe) is enqueued; the client
    polls ``GET /companies/submissions/{id}``.
    """
    subject, email = _require_identity(user)

    retry_after = _add_company_rate_limiter.check(subject)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many add-company requests; please slow down.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    try:
        urow = get_or_create_user(conn, auth0_id=subject, email=email)
    except psycopg2.Error:
        logger.exception("add_company: failed to get/create user for sub=%s", subject)
        raise HTTPException(status_code=500, detail="Failed to load user")
    user_id = urow["id"]
    url = body.url.strip()

    try:
        async with httpx.AsyncClient() as http:
            outcome = await company_add_service.try_add_by_url(
                conn, user_id, url, http
            )
    except BlockedURLError as exc:
        # SSRF / bad scheme / unresolvable host — a client error, not a 500.
        logger.info("add_company rejected url for user=%s: %s", user_id, exc)
        raise HTTPException(
            status_code=422,
            detail="That URL can't be added. Enter a public careers-page URL.",
        )
    except psycopg2.Error:
        logger.exception("add_company DB error for user=%s", user_id)
        raise HTTPException(status_code=500, detail="Failed to add company")

    if outcome.status == "needs_onboarding":
        submission_id = company_submissions.new_submission_id()
        try:
            company_submissions.create_submission(conn, submission_id, user_id, url)
        except psycopg2.Error:
            logger.exception("add_company: failed to create submission for %s", user_id)
            raise HTTPException(status_code=500, detail="Failed to add company")
        # Defer the async onboarding task. Local import avoids importing the
        # Procrastinate task graph at module load (and any import cycle).
        from ..tasks.onboard_custom_company import onboard_custom_company

        try:
            await onboard_custom_company.defer_async(
                submission_id=submission_id, user_id=user_id, url=url
            )
        except Exception:
            logger.exception(
                "add_company: failed to enqueue onboarding for submission %s",
                submission_id,
            )
            # The submission would otherwise hang 'pending' forever — fail it.
            try:
                company_submissions.finish_submission(
                    conn, submission_id, status="failed",
                    error="Could not start site analysis. Please try again.",
                )
            except psycopg2.Error:
                logger.exception("failed to fail submission %s", submission_id)
            raise HTTPException(status_code=500, detail="Failed to add company")
        response.status_code = 202
        return AddCompanyResponse(status="pending", submission_id=submission_id)

    dto = UserCompanyDTO(**company_to_dto(outcome.company or {}))
    return AddCompanyResponse(status=_ADD_STATUS_WIRE[outcome.status], company=dto)


@router.get(
    "/companies/submissions/{submission_id}",
    response_model=SubmissionStatusResponse,
)
async def get_submission_status(
    submission_id: str,
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> SubmissionStatusResponse:
    """Poll the status of an async add-company submission (owner-scoped)."""
    _subject, email = _require_identity(user)
    urow = get_user_by_email(conn, email)
    if urow is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    try:
        row = company_submissions.get_submission(conn, submission_id, urow["id"])
    except psycopg2.Error:
        logger.exception("get_submission_status DB error for %s", submission_id)
        raise HTTPException(status_code=500, detail="Failed to load submission")
    if row is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    company_dto = None
    if row.get("company_id"):
        company_row = company_add_service.db.get_company_by_id(conn, row["company_id"])
        if company_row is not None:
            company_dto = UserCompanyDTO(**company_to_dto(company_row))
    return SubmissionStatusResponse(
        id=row["id"],
        status=row["status"],
        company=company_dto,
        error=row.get("error"),
    )


@router.get("/companies", response_model=UserCompaniesResponse)
async def get_user_companies(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> UserCompaniesResponse:
    """Return the user's runtime-added (custom, unlisted) tracked companies.

    Curated companies already ship in the frontend's static list; the client
    merges these dynamic ones into its company registry.
    """
    _subject, email = _require_identity(user)
    urow = get_user_by_email(conn, email)
    if urow is None:
        return UserCompaniesResponse(companies=[])
    try:
        dtos = company_add_service.list_user_custom_companies(conn, urow["id"])
    except psycopg2.Error:
        logger.exception("get_user_companies DB error for user=%s", urow["id"])
        raise HTTPException(status_code=500, detail="Failed to load companies")
    return UserCompaniesResponse(
        companies=[UserCompanyDTO(**dto) for dto in dtos]
    )
