"""Stripe billing: Checkout, the Customer Portal, and webhook → ``user_subscriptions``.

- Only the webhook grants Pro; Checkout's ``success_url`` proves nothing.
- Every webhook re-reads the subscription from Stripe, so delivery order does not matter.
- The ``stripe_events`` dedupe INSERT commits with the sync: a replay is a no-op,
  and a failed sync rolls it back so Stripe's retry runs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, TypedDict, cast

import stripe
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

from ..config import settings

logger = logging.getLogger(__name__)

_SUBS = sql.Identifier("user_subscriptions")
_EVENTS = sql.Identifier("stripe_events")
_USERS = sql.Identifier("users")

# Over: neither grants Pro nor blocks a new Checkout. Any other status is live.
TERMINAL_STATUSES = frozenset({"canceled", "incomplete_expired"})

# Everything else is acknowledged with a 200 so Stripe does not retry it.
HANDLED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_failed",
        "invoice.paid",
    }
)

STRIPE_TIMEOUT_SECONDS = 10
STRIPE_MAX_NETWORK_RETRIES = 1


class BillingNotConfiguredError(Exception):
    """A Stripe setting this call needs is unset (503)."""


class AlreadySubscribedError(Exception):
    """The user already has a live subscription (409)."""


class NoBillingAccountError(Exception):
    """The user has no Stripe customer yet (404)."""


class SubscriptionRow(TypedDict):
    user_id: str
    stripe_customer_id: str
    stripe_subscription_id: str | None
    plan: str
    status: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    past_due_since: datetime | None
    created_at: datetime
    updated_at: datetime


def billing_configured() -> bool:
    """True iff every Stripe setting and the return origin are set."""
    return bool(
        settings.stripe_secret_key
        and settings.stripe_webhook_secret
        and settings.stripe_price_id_pro
        and settings.public_app_url
    )


@lru_cache(maxsize=1)
def _client_for(api_key: str) -> stripe.StripeClient:
    return stripe.StripeClient(
        api_key,
        http_client=stripe.HTTPXClient(timeout=STRIPE_TIMEOUT_SECONDS, allow_sync_methods=True),
        max_network_retries=STRIPE_MAX_NETWORK_RETRIES,
    )


def _client() -> stripe.StripeClient:
    if not settings.stripe_secret_key:
        raise BillingNotConfiguredError("STRIPE_SECRET_KEY is not set")
    return _client_for(settings.stripe_secret_key)


def _app_url(path: str) -> str:
    if not settings.public_app_url:
        raise BillingNotConfiguredError("PUBLIC_APP_URL is not set")
    return f"{settings.public_app_url.rstrip('/')}{path}"


def _epoch(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _id_of(value: Any) -> str | None:
    """A Stripe reference is an id string, or the object itself when expanded."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        ref = value.get("id")
        return ref if isinstance(ref, str) else None
    return None


def _xact_lock(conn: Connection, key: str) -> None:
    """Serialize on ``key`` until the current transaction ends."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


def is_live(row: SubscriptionRow | None) -> bool:
    """True iff the row holds a subscription that is not over."""
    return bool(
        row
        and row["stripe_subscription_id"]
        and (row["status"] or "") not in TERMINAL_STATUSES
    )


def get_subscription(conn: Connection, user_id: str) -> SubscriptionRow | None:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT * FROM {} WHERE user_id = %s").format(_SUBS), (user_id,)
        )
        row = cur.fetchone()
    return cast(SubscriptionRow, dict(row)) if row else None


def ensure_stripe_customer(conn: Connection, user_id: str, email: str) -> str:
    """The user's one Stripe customer id, created (with its row) on first use."""
    existing = get_subscription(conn, user_id)
    if existing:
        return existing["stripe_customer_id"]
    # The idempotency key makes two concurrent first clicks create one customer.
    customer = _client().v1.customers.create(
        params={"email": email, "metadata": {"user_id": user_id}},
        options={"idempotency_key": f"jvn-customer-{user_id}"},
    )
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (user_id, stripe_customer_id) VALUES (%s, %s)"
                " ON CONFLICT (user_id) DO NOTHING"
            ).format(_SUBS),
            (user_id, customer.id),
        )
    conn.commit()
    row = get_subscription(conn, user_id)
    if row is None:  # pragma: no cover - the INSERT above or a racer wrote it
        raise RuntimeError(f"user_subscriptions row missing after insert for {user_id}")
    return row["stripe_customer_id"]


def create_checkout_session(conn: Connection, user_id: str, email: str) -> str:
    """Start a hosted Checkout for the Pro Price; return its URL."""
    if not settings.stripe_price_id_pro:
        raise BillingNotConfiguredError("STRIPE_PRICE_ID_PRO is not set")
    if is_live(get_subscription(conn, user_id)):
        raise AlreadySubscribedError(user_id)
    customer_id = ensure_stripe_customer(conn, user_id, email)
    client = _client()
    # Two concurrent requests would each find no open session and leave two payable.
    _xact_lock(conn, customer_id)
    try:
        # The row learns of a payment only when its webhook lands, so ask Stripe.
        for sub in client.v1.subscriptions.list(
            params={"customer": customer_id, "status": "all", "limit": 100}
        ).auto_paging_iter():
            if sub.status not in TERMINAL_STATUSES:
                raise AlreadySubscribedError(user_id)
        # An earlier session (another tab) could otherwise become a second subscription.
        for open_session in client.v1.checkout.sessions.list(
            params={"customer": customer_id, "status": "open", "limit": 100}
        ).auto_paging_iter():
            client.v1.checkout.sessions.expire(open_session.id)
        session = client.v1.checkout.sessions.create(
            params={
                "mode": "subscription",
                "customer": customer_id,
                "client_reference_id": user_id,
                "line_items": [{"price": settings.stripe_price_id_pro, "quantity": 1}],
                "subscription_data": {"metadata": {"user_id": user_id}},
                "success_url": _app_url("/pricing?checkout=success"),
                "cancel_url": _app_url("/pricing?checkout=cancel"),
            }
        )
    finally:
        conn.rollback()  # nothing to write; releases the lock
    if not session.url:  # pragma: no cover - hosted Checkout always has a URL
        raise RuntimeError("Stripe returned a Checkout session without a URL")
    return session.url


def create_portal_session(conn: Connection, user_id: str) -> str:
    """Open the Stripe Customer Portal (card, invoices, cancel) for this user."""
    row = get_subscription(conn, user_id)
    if row is None:
        raise NoBillingAccountError(user_id)
    session = _client().v1.billing_portal.sessions.create(
        params={
            "customer": row["stripe_customer_id"],
            "return_url": _app_url("/pricing"),
        }
    )
    return session.url


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------


def construct_event(payload: bytes, sig_header: str | None) -> dict[str, Any]:
    """Verify the signature and parse the event.

    Raises ``ValueError`` (bad JSON) or ``stripe.SignatureVerificationError``.
    """
    if not settings.stripe_webhook_secret:
        raise BillingNotConfiguredError("STRIPE_WEBHOOK_SECRET is not set")
    event = stripe.Webhook.construct_event(
        payload, sig_header or "", settings.stripe_webhook_secret
    )
    return cast(dict[str, Any], event.to_dict())


def subscription_id_of(event: dict[str, Any]) -> str | None:
    """The subscription an event is about, across the event shapes we handle."""
    obj = event.get("data", {}).get("object", {}) or {}
    event_type = event.get("type", "")
    if event_type.startswith("customer.subscription."):
        return _id_of(obj.get("id"))
    if event_type == "checkout.session.completed":
        return _id_of(obj.get("subscription"))
    if event_type.startswith("invoice."):
        # API 2025-03-31 moved it under parent.subscription_details.
        direct = _id_of(obj.get("subscription"))
        if direct:
            return direct
        details = (obj.get("parent") or {}).get("subscription_details") or {}
        return _id_of(details.get("subscription"))
    return None


def _record_event_once(conn: Connection, event_id: str, event_type: str) -> bool:
    """INSERT the event id; False if it was already processed (a replay)."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (event_id, type) VALUES (%s, %s)"
                " ON CONFLICT (event_id) DO NOTHING RETURNING id"
            ).format(_EVENTS),
            (event_id, event_type),
        )
        return cur.fetchone() is not None


def process_event(conn: Connection, event: dict[str, Any]) -> bool:
    """Apply one verified webhook event. Returns True if it changed anything.

    Commits on success; on any exception rolls back (the dedupe row included)
    and re-raises so the router answers 500 and Stripe retries.
    """
    event_type = str(event.get("type", ""))
    if event_type not in HANDLED_EVENT_TYPES:
        return False
    try:
        if not _record_event_once(conn, str(event["id"]), event_type):
            conn.rollback()
            logger.info("Stripe event %s already processed; ignoring replay", event["id"])
            return False
        sub_id = subscription_id_of(event)
        if sub_id:
            # Without it, a handler that read older state could commit after a newer one.
            _xact_lock(conn, sub_id)
            obj = event.get("data", {}).get("object", {}) or {}
            fallback_user_id = (
                obj.get("client_reference_id")
                if event_type == "checkout.session.completed"
                else None
            )
            sync_subscription(
                conn,
                sub_id,
                event_created=_epoch(event.get("created")) or datetime.now(timezone.utc),
                fallback_user_id=fallback_user_id,
                marks_failure=_marks_payment_failure(event),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def _marks_payment_failure(event: dict[str, Any]) -> bool:
    """True iff this event IS the renewal failing, so its time starts the grace."""
    if event.get("type") == "invoice.payment_failed":
        return True
    if event.get("type") == "customer.subscription.updated":
        previous = (event.get("data") or {}).get("previous_attributes") or {}
        return "status" in previous and previous.get("status") != "past_due"
    return False


def _period_end(sub: dict[str, Any]) -> datetime | None:
    """API 2025-03-31 moved current_period_end onto the subscription items."""
    items = (sub.get("items") or {}).get("data") or []
    ends = [i.get("current_period_end") for i in items if i.get("current_period_end")]
    if ends:
        return _epoch(max(ends))
    return _epoch(sub.get("current_period_end"))


def _price_ids(sub: dict[str, Any]) -> list[str]:
    items = (sub.get("items") or {}).get("data") or []
    return [p for p in (_id_of(item.get("price")) for item in items) if p]


def _user_exists(conn: Connection, user_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT EXISTS (SELECT 1 FROM {} WHERE id = %s)").format(_USERS),
            (user_id,),
        )
        row = cur.fetchone()
    return bool(row["exists"])


def sync_subscription(
    conn: Connection,
    subscription_id: str,
    *,
    event_created: datetime,
    fallback_user_id: str | None = None,
    marks_failure: bool = False,
) -> None:
    """Re-read one subscription from Stripe and write it to its user's row. No commit."""
    sub = _client().v1.subscriptions.retrieve(subscription_id).to_dict()
    apply_subscription(
        conn,
        sub,
        event_created=event_created,
        fallback_user_id=fallback_user_id,
        marks_failure=marks_failure,
    )


def apply_subscription(
    conn: Connection,
    sub: dict[str, Any],
    *,
    event_created: datetime,
    fallback_user_id: str | None = None,
    marks_failure: bool = False,
) -> None:
    """Write a Stripe subscription object to ``user_subscriptions``. No commit."""
    customer_id = _id_of(sub.get("customer"))
    if not customer_id:
        logger.warning("Stripe subscription %s has no customer; ignoring", sub.get("id"))
        return
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT * FROM {} WHERE stripe_customer_id = %s FOR UPDATE").format(_SUBS),
            (customer_id,),
        )
        found = cur.fetchone()
    row = cast(SubscriptionRow, dict(found)) if found else None

    if row is None:
        # No row (a Dashboard-made customer): link via the user id stamped on the
        # subscription, but only to a user that exists here, so an event from
        # another environment is ignored instead of failing the FK forever.
        metadata = sub.get("metadata") or {}
        user_id = metadata.get("user_id") or fallback_user_id
        if not user_id or not _user_exists(conn, str(user_id)):
            logger.warning(
                "Stripe customer %s matches no user here; ignoring subscription %s",
                customer_id,
                sub.get("id"),
            )
            return
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "INSERT INTO {} (user_id, stripe_customer_id) VALUES (%s, %s)"
                    " ON CONFLICT (user_id) DO NOTHING RETURNING *"
                ).format(_SUBS),
                (str(user_id), customer_id),
            )
            inserted = cur.fetchone()
        if inserted is None:
            logger.error(
                "User %s already has a different Stripe customer; not linking %s",
                user_id,
                customer_id,
            )
            return
        row = cast(SubscriptionRow, dict(inserted))

    sub_id = str(sub.get("id"))
    status = str(sub.get("status") or "")
    # A late event about an old, finished subscription must not overwrite a newer live one.
    if (
        row["stripe_subscription_id"]
        and row["stripe_subscription_id"] != sub_id
        and status in TERMINAL_STATUSES
        and is_live(row)
    ):
        logger.info(
            "Ignoring %s for old subscription %s; %s is current",
            status,
            sub_id,
            row["stripe_subscription_id"],
        )
        return

    on_pro_price = bool(settings.stripe_price_id_pro) and (
        settings.stripe_price_id_pro in _price_ids(sub)
    )
    if status not in TERMINAL_STATUSES and not on_pro_price:
        logger.warning(
            "Live subscription %s is not on STRIPE_PRICE_ID_PRO (%s); recording it as free",
            sub_id,
            _price_ids(sub),
        )
    plan = "pro" if on_pro_price and status not in TERMINAL_STATUSES else "free"

    past_due_since: datetime | None = None
    if status == "past_due":
        previous = row["past_due_since"] if row["stripe_subscription_id"] == sub_id else None
        if marks_failure:
            # Stripe's time for the failure; the earlier of two failure signals wins.
            past_due_since = event_created if previous is None else min(previous, event_created)
        else:
            # Any other event only shows it is past_due by now; a failure event replaces this.
            past_due_since = previous or datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "UPDATE {} SET stripe_subscription_id = %s, plan = %s, status = %s,"
                " current_period_end = %s, cancel_at_period_end = %s,"
                " past_due_since = %s"
                " WHERE stripe_customer_id = %s"
            ).format(_SUBS),
            (
                sub_id,
                plan,
                status,
                _period_end(sub),
                # The Portal schedules a cancel with either the flag or a cancel_at date.
                bool(sub.get("cancel_at_period_end")) or sub.get("cancel_at") is not None,
                past_due_since,
                customer_id,
            ),
        )
