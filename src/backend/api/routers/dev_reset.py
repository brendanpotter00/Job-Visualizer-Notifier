"""LOCAL-DEVELOPMENT-ONLY custom-company reset — ``/api/users/dev-reset``.

A SEPARATE router module, not two more decorators on ``user_companies``, and that
is the whole reason it is a file: ``main.py`` can skip ``include_router`` entirely
when ``settings.dev_reset_enabled`` is off, so with the flag off the path is not in
the route table and answers a plain 404. A route that 403s instead would tell an
anonymous prober that a "delete everything a user added" endpoint exists here.

WHY ``/api/users/dev-reset`` AND NOT ``/api/users/companies/dev-reset``. The
``api/users.ts`` proxy allowlists ``companies/:id``, and ``:id`` matches ANY single
segment (``api/utils/proxyPath.ts`` — the name is documentation only). So a route at
``companies/dev-reset`` would be reachable from the public internet as
``GET /api/users?path=companies/dev-reset`` the moment the flag was ever on in a
deployed environment. One segment up, nothing in that allowlist matches
``dev-reset`` — and ``api/tests/test_proxy_path_allowlists.py`` now asserts that no
allowlist entry, literal or wildcard, can ever reach a ``NOT_PROXIED`` path.

The guards, in the order a request meets them:

1. the router is registered at all (``settings.dev_reset_enabled``);
2. :func:`api.services.dev_reset.assert_local_database` — parsed, fail-closed, and
   re-derived on every call INDEPENDENTLY of the flag;
3. a Bearer token, and by default the reset is scoped to that caller's own boards;
4. every delete is scoped to ``visibility='user'``.
"""

from __future__ import annotations

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as Connection
from pydantic import BaseModel, Field

from ..auth.claims import TokenClaims
from ..auth.dependencies import get_current_user
from ..config import settings
from ..dependencies import get_db
from ..services import dev_reset as svc
from ..services.user_service import get_user_by_email

logger = logging.getLogger(__name__)

router = APIRouter()


# Response models live HERE rather than in the shared ``api/models.py`` on purpose:
# every symbol in this file disappears from the running app when the flag is off,
# and a dev-only shape in the shared module is a dev-only shape that outlives it.
#
# They are also plain ``BaseModel``s, so the field names go out as snake_case rather
# than the camelCase the rest of the API emits via ``models.py``'s ``to_camel``
# alias generator. Deliberate: half of what this returns is TABLE NAMES
# (``job_listings``, ``company_add_attempts``), which are snake_case and cannot be
# anything else, and a camelCase wrapper around snake_case payload keys reads worse
# than one consistent convention. Only one dev-only component consumes it.
class DevResetStatusResponse(BaseModel):
    """What the QA page needs to decide whether to render the button at all."""

    enabled: bool = Field(
        description="Always true — reaching this route means the flag is on and the "
        "router was registered. The 'off' answer is a 404, not a false."
    )
    database_host: str = Field(
        description="The loopback host the reset would run against, echoed back so "
        "the button can name the database it is about to clear."
    )


class DevResetResponse(BaseModel):
    scope: str
    company_ids: list[str]
    deleted: dict[str, int]
    published_companies_kept: int
    published_jobs_kept: int


def _guard_local_database() -> str:
    """The guard that does not depend on the flag. 403 on anything unproven."""
    try:
        return svc.assert_local_database(settings.database_url)
    except svc.NonLocalDatabaseError as exc:
        logger.error("dev_reset refused: %s", exc)
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _caller_user_id(conn: Connection, user: TokenClaims) -> str:
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    row = get_user_by_email(conn, email)
    if row is None:
        # Nothing to reset — but answering 404 keeps "you have no rows" distinct
        # from "the reset ran and deleted nothing", which is the difference between
        # a mis-typed login and a working reset.
        raise HTTPException(status_code=404, detail="No user row for this token")
    return str(row["id"])


@router.get("", response_model=DevResetStatusResponse)
async def dev_reset_status(
    user: TokenClaims = Depends(get_current_user),
) -> DevResetStatusResponse:
    """Is the reset available, and against which database?

    The QA page calls this on mount and renders the button only on a 200. A 404 here
    is the normal answer everywhere except a developer's laptop.
    """
    return DevResetStatusResponse(enabled=True, database_host=_guard_local_database())


@router.post("", response_model=DevResetResponse)
async def dev_reset_custom_companies(
    scope: str = Query(
        default=svc.SCOPE_MINE,
        pattern=f"^({svc.SCOPE_MINE}|{svc.SCOPE_ALL})$",
        description=(
            "'mine' (default) clears only the calling user's custom companies; "
            "'all' clears every user's. 'mine' is the default because it is the "
            "smallest thing that makes the add flow re-testable."
        ),
    ),
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> DevResetResponse:
    """Delete the caller's user-added companies and everything hanging off them.

    Clears: their ``companies`` rows (``visibility='user'`` only), their
    ``user_companies`` ownership rows, their ``company_add_attempts`` audit — which
    is the monthly-quota counter, so the adds come back — their ``company_scripts``
    recipes and ``provider_config`` discovery progress (that blob lives on the
    company row), their ``company_harvests`` and ``scrape_runs``, and every
    ``custom:<id>`` job row with its freshness / location / tag / enrichment
    sidecars.

    Spares, structurally rather than by convention: every ``visibility='public'``
    company and every job under a published source_id. No statement in the purge can
    name one.
    """
    host = _guard_local_database()
    user_id = None if scope == svc.SCOPE_ALL else _caller_user_id(conn, user)
    logger.warning(
        "DEV RESET requested: scope=%s database_host=%s caller=%s",
        scope, host, user.get("email"),
    )
    try:
        outcome = svc.reset_custom_companies(conn, user_id=user_id)
    except psycopg2.Error as exc:
        logger.exception("dev_reset failed (scope=%s)", scope)
        raise HTTPException(status_code=500, detail="Dev reset failed") from exc
    return DevResetResponse(
        scope=outcome.scope,
        company_ids=outcome.company_ids,
        deleted=outcome.deleted,
        published_companies_kept=outcome.published_companies_kept,
        published_jobs_kept=outcome.published_jobs_kept,
    )
