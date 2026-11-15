"""Billing endpoints (``/api/billing``): Stripe Checkout, Portal, status, webhook.

The first three are user-facing (Bearer token, reached through the Vercel
``api/billing.ts`` proxy). The webhook is called by Stripe itself, DIRECTLY on
the Railway origin: it is exempt from the X-Internal-Key middleware
(``auth/internal_key._EXEMPT_PATHS``) because Stripe cannot send that header,
and it is deliberately NOT in the Vercel proxy's allowlist — the Stripe
signature over the raw body is its only authentication, and a proxy hop that
re-serializes the body would break it.
"""

from __future__ import annotations

import logging

import psycopg2
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extensions import connection as Connection
from starlette.concurrency import run_in_threadpool

from ..auth.dependencies import TokenClaims, get_current_user
from ..auth.jwt import get_normalized_subject
from ..dependencies import get_db
from ..models import BillingRedirectResponse, SubscriptionResponse
from ..services import billing_service
from ..services.billing_service import (
    AlreadySubscribedError,
    BillingNotConfiguredError,
    NoBillingAccountError,
)
from ..services.entitlements import grace_ends_at, is_pro
from ..services.user_service import UserRow, get_or_create_user

logger = logging.getLogger(__name__)

router = APIRouter()

_NOT_CONFIGURED = "Billing is not configured on this server."

# The webhook is the one public, body-reading POST (everything else sits behind
# X-Internal-Key), and the body must be read before the signature can be checked.
# Real Stripe events are a few KB; refuse anything near this before buffering it.
MAX_WEBHOOK_BODY_BYTES = 1_000_000

# Every handler below that calls Stripe or psycopg2 is a plain ``def``: FastAPI
# runs those in its threadpool. As ``async def`` they would block the one event
# loop the Procrastinate worker lanes and the auto-scraper also run on.


def _resolve_user(conn: Connection, user: TokenClaims) -> UserRow:
    """Upsert and return the caller's users row (same rules as GET /api/users)."""
    auth0_id = get_normalized_subject(user)
    if not auth0_id:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    try:
        return get_or_create_user(
            conn,
            auth0_id=auth0_id,
            email=email,
            given_name=user.get("given_name"),
            family_name=user.get("family_name"),
            picture_url=user.get("picture"),
        )
    except psycopg2.Error:
        logger.exception("Failed to get/create user for billing, sub=%s", auth0_id)
        raise HTTPException(status_code=500, detail="Failed to load user profile")


@router.get("/subscription", response_model=SubscriptionResponse)
def get_subscription(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> SubscriptionResponse:
    """The caller's plan. Reads the DB only — never calls Stripe."""
    me = _resolve_user(conn, user)
    row = billing_service.get_subscription(conn, me["id"])
    return SubscriptionResponse(
        plan="pro" if row and row["plan"] == "pro" else "free",
        status=row["status"] if row else None,
        is_pro=is_pro(conn, me["id"], me["email"]),
        has_subscription=billing_service.is_live(row),
        current_period_end=row["current_period_end"] if row else None,
        cancel_at_period_end=bool(row and row["cancel_at_period_end"]),
        past_due_since=row["past_due_since"] if row else None,
        grace_ends_at=grace_ends_at(row),
        billing_enabled=billing_service.billing_configured(),
    )


@router.post("/checkout-session", response_model=BillingRedirectResponse)
def create_checkout_session(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> BillingRedirectResponse:
    """Start hosted Checkout for Pro. 409 if the caller already has a live subscription."""
    me = _resolve_user(conn, user)
    try:
        url = billing_service.create_checkout_session(conn, me["id"], me["email"])
    except BillingNotConfiguredError:
        raise HTTPException(status_code=503, detail=_NOT_CONFIGURED)
    except AlreadySubscribedError:
        raise HTTPException(
            status_code=409,
            detail="You already have a Pro subscription. Use Manage billing to change it.",
        )
    except stripe.StripeError:
        logger.exception("Stripe Checkout session failed for user=%s", me["id"])
        raise HTTPException(status_code=502, detail="Stripe could not start checkout. Try again.")
    return BillingRedirectResponse(url=url)


@router.post("/portal-session", response_model=BillingRedirectResponse)
def create_portal_session(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> BillingRedirectResponse:
    """Open the Stripe Customer Portal. 404 if the caller never started Checkout."""
    me = _resolve_user(conn, user)
    try:
        url = billing_service.create_portal_session(conn, me["id"])
    except BillingNotConfiguredError:
        raise HTTPException(status_code=503, detail=_NOT_CONFIGURED)
    except NoBillingAccountError:
        raise HTTPException(status_code=404, detail="No billing account yet.")
    except stripe.StripeError:
        logger.exception("Stripe Portal session failed for user=%s", me["id"])
        raise HTTPException(status_code=502, detail="Stripe could not open billing. Try again.")
    return BillingRedirectResponse(url=url)


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    conn: Connection = Depends(get_db),
) -> dict[str, bool]:
    """Stripe → us. 400 on a bad signature, 500 (Stripe retries) on a failed sync.

    Every 2xx tells Stripe "done": unknown event types and replays get a 200 so
    they are not retried for days.
    """
    if not billing_service.billing_configured():
        raise HTTPException(status_code=503, detail=_NOT_CONFIGURED)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_WEBHOOK_BODY_BYTES:  # chunked, or a lying Content-Length
            raise HTTPException(status_code=413, detail="Payload too large")
    payload = bytes(body)
    try:
        event = billing_service.construct_event(payload, request.headers.get("stripe-signature"))
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    try:
        # Stripe + psycopg2 are blocking: off the event loop (see module note).
        await run_in_threadpool(billing_service.process_event, conn, event)
    except Exception:
        logger.exception("Stripe webhook %s (%s) failed; Stripe will retry", event.get("id"), event.get("type"))
        raise HTTPException(status_code=500, detail="Webhook processing failed")
    return {"received": True}
