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
2. :func:`api.services.dev_reset.assert_local_database` — parsed with libpq's own
   ``parse_dsn`` (a ``?host=``/``?hostaddr=`` parameter overrides the URL authority
   and would otherwise read as "localhost" while connecting to production),
   fail-closed, and re-derived on every call INDEPENDENTLY of the flag;
3. :func:`api.services.dev_reset.assert_local_connection` — the same question put to
   the SERVER (``SELECT inet_server_addr()``), which no DSN spelling can answer for it;
4. a Bearer token, and by default the reset is scoped to that caller's own boards;
5. ``?scope=all`` — the one that clears EVERY user — additionally requires an
   ``admins`` grant, the same one ``require_admin`` reads;
6. every delete is scoped to ``visibility='user'``.
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
from ..services.admin_service import is_admin_by_email
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


def _guard_local_database(conn: Connection) -> str:
    """The guard that does not depend on the flag. 403 on anything unproven.

    TWO QUESTIONS, ASKED OF TWO DIFFERENT THINGS. The DSN is parsed with libpq's own
    parser (so a ``?host=`` / ``?hostaddr=`` parameter cannot hide a production host
    behind a ``localhost`` authority), and then the SERVER on the other end is asked
    where it is. A string can be spelled to look local; the connection cannot.
    """
    try:
        host = svc.assert_local_database(settings.database_url)
        svc.assert_local_connection(conn)
    except svc.NonLocalDatabaseError as exc:
        logger.error("dev_reset refused: %s", exc)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return host


def _guard_admin_for_scope_all(conn: Connection, user: TokenClaims) -> None:
    """``?scope=all`` deletes EVERY user's rows, so it needs the admin grant.

    NOT a ``Depends(require_admin)`` on the route, because the gate is conditional on
    a query parameter and a route-level dependency cannot see one: hanging
    ``require_admin`` on the whole endpoint would demand an ``admins`` row for the
    ordinary ``scope=mine`` reset, which is the thing a developer runs twenty times an
    evening and the reason this endpoint exists. So it reads the same grant
    ``require_admin`` reads, at the point where the scope is known.

    Why it needs one at all: ``scope=all`` issues ``DELETE FROM user_companies`` and
    ``DELETE FROM company_add_attempts`` with no WHERE clause. On one laptop that is
    the point; behind a token it is "any authenticated user wipes everybody's data",
    and it compounds every other layer — the flag being on where it should not be,
    or a DSN that is not as local as it looks.
    """
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    if not is_admin_by_email(conn, email):
        logger.warning(
            "dev_reset refused scope=all for non-admin caller %s", email
        )
        raise HTTPException(
            status_code=403,
            detail="scope=all clears every user's custom companies and requires an "
                   "admin grant. Use scope=mine to clear your own.",
        )


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
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> DevResetStatusResponse:
    """Is the reset available, and against which database?

    The QA page calls this on mount and renders the button only on a 200. A 404 here
    is the normal answer everywhere except a developer's laptop.

    IT TAKES A CONNECTION so that the host it prints under the button is one the
    server confirmed, not one a DSN claimed. "Database: localhost" rendered as
    reassurance next to a destructive button has to be worth reading.
    """
    return DevResetStatusResponse(
        enabled=True, database_host=_guard_local_database(conn)
    )


@router.post("", response_model=DevResetResponse)
async def dev_reset_custom_companies(
    scope: str = Query(
        default=svc.SCOPE_MINE,
        pattern=f"^({svc.SCOPE_MINE}|{svc.SCOPE_ALL})$",
        description=(
            "'mine' (default) clears only the calling user's custom companies; "
            "'all' clears every user's and REQUIRES AN ADMIN GRANT. 'mine' is the "
            "default because it is the smallest thing that makes the add flow "
            "re-testable."
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

    ``?scope=all`` REQUIRES AN ADMIN GRANT. It clears every user's rows — two of its
    statements are unqualified DELETEs — so it is not something an ordinary
    authenticated caller may do to everybody else. ``scope=mine`` (the default, and
    the one the button sends) needs no grant.
    """
    host = _guard_local_database(conn)
    user_id: str | None = None
    if scope == svc.SCOPE_ALL:
        _guard_admin_for_scope_all(conn, user)
    else:
        user_id = _caller_user_id(conn, user)
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
