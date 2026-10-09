"""Internal Launch Radar endpoints: the loop's API.

Mounted at /api/internal/launch-radar and protected ONLY by the global
require_internal_key middleware (X-Internal-Key), like internal_enrichment, so
there is no per-route auth here. The loop (``scripts/launch_radar/``) calls the
backend directly with ``BACKEND_URL``; these routes are never proxied through a
Vercel function (``api/tests/test_proxy_path_allowlists.py`` pins that no
allowlist entry can reach ``internal``).

Requests and responses are snake_case. Status codes the loop relies on:

    POST  /runs                     201, idempotent on run_uuid
    POST  /runs/{run_uuid}/reserve  200 | 402 budget (detail object) | 404 | 409
    POST  /runs/{run_uuid}/finish   200 | 404 | 409 already finished
    GET   /monitors                 200
    PUT   /monitors/{slot}          200 upsert | 422 bad slot
    PATCH /monitors/{slot}          200 | 404 | 422
    GET   /seen                     200 | 422 when more than 100 values
    GET   /cards                    200 | 422 no filter / all=true with a filter / more than 100 domains
                                    (refresh's and rescore's lookup; keyset-paged)
    POST  /cards                    201 | 404 | 409 run not running / domain already posted | 422
    PUT   /cards/{card_id}/payload  200 | 404 missing or deleted | 422 invalid or other domain

The add-company PR queue (docs/implementations/launch-radar/saved-pr/PLAN.md §3.3;
one request per card, created by Save on the admin page):

    POST  /pr-requests/next               200 claim | 204 nothing claimable
    GET   /pr-requests/{card_id}          200 row + card_status | 404 none or card deleted
    POST  /pr-requests/{card_id}/result   200 | 404 | 409 not in_progress, other URL on
                                          an open row, PR on another card, cancelled
                                          while still saved | 422 outcome/url/reason shape
    POST  /pr-requests/{card_id}/requeue  200 | 404 | 409 queued/in_progress/open or card
                                          not saved
    GET   /pr-requests                    200 (status repeatable, limit 1..500) | 422

Every psycopg2 error rolls back and becomes a 500 with a generic detail.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from psycopg2.extensions import connection as Connection

from ..dependencies import get_db
from ..models import (
    LaunchRadarCardCreate,
    LaunchRadarCardCreated,
    LaunchRadarCardStatus,
    LaunchRadarMonitorPatch,
    LaunchRadarMonitorPut,
    LaunchRadarMonitorRow,
    LaunchRadarMonitorSlot,
    LaunchRadarMonitorsOut,
    LaunchRadarPayloadReplace,
    LaunchRadarPayloadReplaced,
    LaunchRadarPrClaim,
    LaunchRadarPrNext,
    LaunchRadarPrRequestListed,
    LaunchRadarPrRequestOut,
    LaunchRadarPrRequestsOut,
    LaunchRadarPrRequestState,
    LaunchRadarPrResult,
    LaunchRadarPrStatus,
    LaunchRadarReserve,
    LaunchRadarReserved,
    LaunchRadarRunFinish,
    LaunchRadarRunFinished,
    LaunchRadarRunStart,
    LaunchRadarRunStarted,
    LaunchRadarSeenOut,
    LaunchRadarStoredCard,
    LaunchRadarStoredCardsOut,
)
from ..services import launch_radar as svc

logger = logging.getLogger(__name__)

router = APIRouter()

# Most values one GET /seen may carry per parameter.
SEEN_MAX_VALUES = 100

_RUN_UUID_PATH = Path(pattern=r"^[A-Za-z0-9-]{8,64}$")
# A card id is an INTEGER column: a bigger value would be a 500, not a 404.
_CARD_ID_PATH = Path(ge=1, le=2_147_483_647)

T = TypeVar("T")


def _call(conn: Connection, what: str, fn: Callable[[], T]) -> T:
    """Run a service call, mapping its domain errors to status codes and any
    psycopg2 error to a rolled-back generic 500."""
    try:
        return fn()
    except svc.BudgetExceeded as exc:
        raise HTTPException(status_code=402, detail=exc.detail())
    except svc.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except svc.Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except svc.InvalidDomain as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        logger.warning("launch radar %s hit a unique constraint", what)
        raise HTTPException(status_code=409, detail="conflicts with an existing row")
    except psycopg2.Error:
        conn.rollback()
        logger.exception("launch radar %s failed", what)
        raise HTTPException(status_code=500, detail=f"Failed to {what}")


@router.post("/runs", status_code=201, response_model=LaunchRadarRunStarted)
def start_run(
    body: LaunchRadarRunStart,
    conn: Connection = Depends(get_db),
) -> LaunchRadarRunStarted:
    result = _call(
        conn,
        "start run",
        lambda: svc.start_run(conn, body.run_uuid, body.host, body.budget_usd),
    )
    return LaunchRadarRunStarted.model_validate(result)


@router.post("/runs/{run_uuid}/reserve", response_model=LaunchRadarReserved)
def reserve(
    body: LaunchRadarReserve,
    run_uuid: str = _RUN_UUID_PATH,
    conn: Connection = Depends(get_db),
) -> LaunchRadarReserved:
    result = _call(
        conn,
        "reserve spend",
        lambda: svc.reserve_spend(
            conn, run_uuid, body.step, body.est_usd, body.domain, body.accrued
        ),
    )
    return LaunchRadarReserved.model_validate(result)


@router.post("/runs/{run_uuid}/finish", response_model=LaunchRadarRunFinished)
def finish_run(
    body: LaunchRadarRunFinish,
    run_uuid: str = _RUN_UUID_PATH,
    conn: Connection = Depends(get_db),
) -> LaunchRadarRunFinished:
    result = _call(
        conn,
        "finish run",
        lambda: svc.finish_run(
            conn, run_uuid, body.status, body.events_read, body.cards_posted, body.notes
        ),
    )
    return LaunchRadarRunFinished.model_validate(result)


@router.get("/monitors", response_model=LaunchRadarMonitorsOut)
def list_monitors(conn: Connection = Depends(get_db)) -> LaunchRadarMonitorsOut:
    rows = _call(conn, "list monitors", lambda: svc.list_monitors(conn))
    return LaunchRadarMonitorsOut(
        monitors=[LaunchRadarMonitorRow.model_validate(r) for r in rows]
    )


@router.put("/monitors/{slot}", response_model=LaunchRadarMonitorRow)
def put_monitor(
    slot: LaunchRadarMonitorSlot,
    body: LaunchRadarMonitorPut,
    conn: Connection = Depends(get_db),
) -> LaunchRadarMonitorRow:
    row = _call(
        conn,
        "save monitor",
        lambda: svc.put_monitor(
            conn,
            slot,
            body.monitor_id,
            body.query,
            body.processor,
            body.frequency,
            body.status,
            body.charged_through,
        ),
    )
    return LaunchRadarMonitorRow.model_validate(row)


@router.patch("/monitors/{slot}", response_model=LaunchRadarMonitorRow)
def patch_monitor(
    slot: LaunchRadarMonitorSlot,
    body: LaunchRadarMonitorPatch,
    conn: Connection = Depends(get_db),
) -> LaunchRadarMonitorRow:
    changes = body.model_dump(include=body.model_fields_set)
    row = _call(conn, "update monitor", lambda: svc.patch_monitor(conn, slot, changes))
    return LaunchRadarMonitorRow.model_validate(row)


@router.get("/seen", response_model=LaunchRadarSeenOut)
def seen(
    domain: list[str] = Query(default_factory=list),
    name: list[str] = Query(default_factory=list),
    conn: Connection = Depends(get_db),
) -> LaunchRadarSeenOut:
    """Dedupe before spend: which domains already have a card (ANY status,
    tombstones included) and which names are already-tracked companies."""
    for param, values in (("domain", domain), ("name", name)):
        if len(values) > SEEN_MAX_VALUES:
            raise HTTPException(
                status_code=422,
                detail=f"at most {SEEN_MAX_VALUES} '{param}' values per request",
            )
    result = _call(conn, "check seen", lambda: svc.seen(conn, domain, name))
    return LaunchRadarSeenOut.model_validate(result)


@router.get("/cards", response_model=LaunchRadarStoredCardsOut)
def stored_cards(
    domain: list[str] = Query(default_factory=list),
    missing_talent: bool = False,
    all_cards: bool = Query(default=False, alias="all"),
    status: list[LaunchRadarCardStatus] = Query(default_factory=list),
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    conn: Connection = Depends(get_db),
) -> LaunchRadarStoredCardsOut:
    """Live cards with their stored payload, for ``radar.py refresh`` and
    ``radar.py rescore``: by domain (repeatable, normalized server-side) and/or
    every card with no leaders' part of Talent (``missing_talent``), or every live
    card behind the explicit ``all=true`` (``rescore --all``), which takes no other
    filter. One of those is required, so the whole table is never dumped by
    accident. ``status`` (repeatable; none = every live status) narrows it.
    Keyset-paged by id: a page holds the cards with ``id > after_id``, at most
    ``limit``, and the caller asks again from the last id until a page comes back
    short."""
    if len(domain) > SEEN_MAX_VALUES:
        raise HTTPException(
            status_code=422, detail=f"at most {SEEN_MAX_VALUES} 'domain' values per request"
        )
    if all_cards and (domain or missing_talent):
        raise HTTPException(status_code=422, detail="all=true takes no domain or missing_talent")
    if not domain and not missing_talent and not all_cards:
        raise HTTPException(
            status_code=422, detail="give at least one domain, missing_talent=true or all=true"
        )
    rows = _call(
        conn,
        "list cards",
        lambda: svc.find_cards(conn, domain, missing_talent, limit, status, after_id),
    )
    return LaunchRadarStoredCardsOut(
        cards=[LaunchRadarStoredCard.model_validate(r) for r in rows]
    )


@router.post("/cards", status_code=201, response_model=LaunchRadarCardCreated)
def post_card(
    body: LaunchRadarCardCreate,
    conn: Connection = Depends(get_db),
) -> LaunchRadarCardCreated:
    payload = body.payload.model_dump(mode="json")
    result = _call(
        conn, "post card", lambda: svc.insert_card(conn, body.run_uuid, payload)
    )
    return LaunchRadarCardCreated.model_validate(result)


@router.put("/cards/{card_id}/payload", response_model=LaunchRadarPayloadReplaced)
def replace_payload(
    body: LaunchRadarPayloadReplace,
    card_id: int = Path(ge=1),
    conn: Connection = Depends(get_db),
) -> LaunchRadarPayloadReplaced:
    """``radar.py refresh``: replace a new/saved/archived card's payload, validated
    like POST /cards. The card keeps its status and ``posted_at``."""
    payload = body.payload.model_dump(mode="json")
    result = _call(
        conn, "replace card payload", lambda: svc.replace_payload(conn, card_id, payload)
    )
    return LaunchRadarPayloadReplaced.model_validate(result)


# ---------------------------------------------------------------------------
# Add-company PR requests (PLAN §3.3)
# ---------------------------------------------------------------------------


@router.post(
    "/pr-requests/next",
    response_model=LaunchRadarPrClaim,
    responses={204: {"description": "Nothing is claimable"}},
)
def claim_next_pr(
    body: LaunchRadarPrNext,
    conn: Connection = Depends(get_db),
) -> LaunchRadarPrClaim | Response:
    """``radar.sh pr-next``: claim the oldest queued request of a saved card
    (it becomes ``in_progress``, one more attempt), or 204 when none is
    claimable. Stale claims are recovered first."""
    claim = _call(conn, "claim PR request", lambda: svc.claim_next_pr(conn))
    if claim is None:
        return Response(status_code=204)
    return LaunchRadarPrClaim.model_validate(claim)


@router.get("/pr-requests/{card_id}", response_model=LaunchRadarPrRequestState)
def get_pr_request(
    card_id: int = _CARD_ID_PATH,
    conn: Connection = Depends(get_db),
) -> LaunchRadarPrRequestState:
    """``radar.sh pr-check``: the card's request and the card's status."""
    row = _call(conn, "read PR request", lambda: svc.get_pr_request(conn, card_id))
    return LaunchRadarPrRequestState.model_validate(row)


@router.post("/pr-requests/{card_id}/result", response_model=LaunchRadarPrRequestOut)
def report_pr(
    body: LaunchRadarPrResult,
    card_id: int = _CARD_ID_PATH,
    conn: Connection = Depends(get_db),
) -> LaunchRadarPrRequestOut:
    """``radar.sh pr-check`` / ``pr-report``: record the outcome of a claimed
    request. The body's shape is checked by ``LaunchRadarPrResult``."""
    row = _call(
        conn,
        "report PR request",
        lambda: svc.report_pr(conn, card_id, body.outcome, body.pr_url, body.reason),
    )
    return LaunchRadarPrRequestOut.model_validate(row)


@router.post("/pr-requests/{card_id}/requeue", response_model=LaunchRadarPrRequestOut)
def requeue_pr(
    body: LaunchRadarPrNext,
    card_id: int = _CARD_ID_PATH,
    conn: Connection = Depends(get_db),
) -> LaunchRadarPrRequestOut:
    """``radar.sh pr-requeue`` (interactive only): put a finished request of a
    saved card back in the queue with its attempts reset."""
    row = _call(conn, "re-queue PR request", lambda: svc.requeue_pr(conn, card_id))
    return LaunchRadarPrRequestOut.model_validate(row)


@router.get("/pr-requests", response_model=LaunchRadarPrRequestsOut)
def list_pr_requests(
    status: list[LaunchRadarPrStatus] = Query(default_factory=list),
    limit: int = Query(default=100, ge=1, le=500),
    conn: Connection = Depends(get_db),
) -> LaunchRadarPrRequestsOut:
    """``radar.sh pr-status`` / ``pr-refresh``: requests in ``status``
    (repeatable; none = every status), oldest first, with domain and company."""
    rows = _call(conn, "list PR requests", lambda: svc.list_pr_requests(conn, status, limit))
    return LaunchRadarPrRequestsOut(
        requests=[LaunchRadarPrRequestListed.model_validate(r) for r in rows]
    )
