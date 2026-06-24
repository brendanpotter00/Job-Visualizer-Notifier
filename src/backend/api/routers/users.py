"""User profile endpoints."""

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Response
from posthog import identify_context, new_context
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, get_current_user
from ..auth.jwt import get_normalized_subject
from ..dependencies import get_db
from ..models import (
    EnabledCompaniesResponse,
    EnabledCompaniesUpdateRequest,
    UserResponse,
    UserUpdateRequest,
)
from ..services.admin_service import is_admin_by_email
from ..services.posthog_client import get_posthog
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
        with new_context():
            identify_context(auth0_id)
            ph.capture(
                "user_signed_up",
                distinct_id=auth0_id,
                properties={"$set": {"email": email}},
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
