"""Stripe billing: Checkout, the Customer Portal, and webhook → ``user_subscriptions``.

Three rules shape this module:

1. **Only the webhook grants Pro.** Checkout's ``success_url`` is a page the user
   can type into the address bar; it proves nothing. The page polls
   ``GET /api/billing/subscription`` and waits for the webhook to land.
2. **Every webhook re-reads the subscription FROM Stripe** (``sync_subscription``)
   instead of trusting the event payload. Stripe does not guarantee delivery
   order, so applying payloads in arrival order could write an old state over a
   new one; the live object is always the newest state.
3. **Replays are no-ops, failures are retried.** The ``stripe_events`` INSERT and
   the sync commit in ONE transaction: a duplicate ``event_id`` short-circuits,
   and a sync that raises rolls the INSERT back so Stripe's retry (it retries any
   non-2xx for up to three days) is processed rather than mistaken for a replay.

The Stripe SDK is reached only through ``_client()``, which tests monkeypatch —
no test needs network access or a key.
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

# A subscription in one of these is over: it neither grants Pro nor blocks a new
# Checkout. Everything else (active, trialing, past_due, unpaid, incomplete,
# paused) is a LIVE subscription — starting a second Checkout on top of one
# would bill the user twice, so Checkout is refused and the user is sent to the
# Customer Portal instead.
TERMINAL_STATUSES = frozenset({"canceled", "incomplete_expired"})

# The webhook acts on these and acknowledges everything else with a 200 (a
# non-2xx for an event we do not care about would make Stripe retry it for days).
HANDLED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",  # first payment: links customer → subscription
        "customer.subscription.created",
        "customer.subscription.updated",  # renewal, past_due, cancel_at_period_end, resume
        "customer.subscription.deleted",  # ended → plan 'free'
        "invoice.payment_failed",  # backstop for the past_due flip
        "invoice.paid",  # backstop for leaving past_due
    }
)


class BillingNotConfiguredError(Exception):
    """A Stripe secret this call needs is unset. The router answers 503."""


class AlreadySubscribedError(Exception):
    """The user already has a live subscription. The router answers 409."""


class NoBillingAccountError(Exception):
    """The user has never started Checkout, so has no Stripe customer (404)."""


class SubscriptionRow(TypedDict):
    """One ``user_subscriptions`` row, as ``RealDictCursor`` returns it."""

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
    """True iff the three Stripe secrets AND the return origin are set.

    ``PUBLIC_APP_URL`` is required, not defaulted: a prod deploy with keys but no
    origin would send paying users back to localhost after Checkout.
    """
    return bool(
        settings.stripe_secret_key
        and settings.stripe_webhook_secret
        and settings.stripe_price_id_pro
        and settings.public_app_url
    )


# Stripe calls run in FastAPI's threadpool (the billing routes are plain ``def``),
# but a stuck call still pins a worker thread and a DB connection. Bound it: the
# SDK default is an 80 s timeout with retries. httpx is already a direct
# dependency, so the client is the same in every environment.
STRIPE_TIMEOUT_SECONDS = 10
STRIPE_MAX_NETWORK_RETRIES = 1


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
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        ref = value.get("id")
        return ref if isinstance(ref, str) else None
    return None


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
    """Return the user's Stripe customer id, creating customer + row on first use.

    One Stripe customer per ``users.id``, ever: it is reused for every later
    Checkout and the Portal. The idempotency key makes two concurrent first
    clicks create ONE customer, and ``ON CONFLICT DO NOTHING`` makes them write
    one row.
    """
    existing = get_subscription(conn, user_id)
    if existing:
        return existing["stripe_customer_id"]
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
    """Start a hosted Checkout for the $6/month Pro Price; return its URL."""
    if not settings.stripe_price_id_pro:
        raise BillingNotConfiguredError("STRIPE_PRICE_ID_PRO is not set")
    if is_live(get_subscription(conn, user_id)):
        raise AlreadySubscribedError(user_id)
    customer_id = ensure_stripe_customer(conn, user_id, email)
    client = _client()
    # The row only learns about a subscription when its webhook lands, so between
    # payment and webhook (or forever, if the webhook is misconfigured) the DB
    # check above passes. Ask Stripe — the source of truth — before opening a
    # second Checkout that would bill the user twice.
    for sub in client.v1.subscriptions.list(
        params={"customer": customer_id, "status": "all", "limit": 100}
    ).auto_paging_iter():
        if sub.status not in TERMINAL_STATUSES:
            raise AlreadySubscribedError(user_id)
    # One open Checkout per customer: expire any earlier one (another tab, the
    # browser history) so it can never be completed into a second subscription.
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
            # The success page proves nothing (rule 1 above); it only tells the
            # page to poll until the webhook lands.
            "success_url": _app_url("/pricing?checkout=success"),
            "cancel_url": _app_url("/pricing?checkout=cancel"),
        }
    )
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
    """Verify the signature and parse the event. Raises on a bad signature.

    Raises ``ValueError`` (bad JSON) or ``stripe.SignatureVerificationError``;
    the router turns both into a 400.
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
        # API 2025-03-31 moved invoice.subscription under
        # parent.subscription_details; accept both shapes.
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

    Commits on success. On ANY exception it rolls back (the ``stripe_events``
    INSERT included) and re-raises, so the router can answer 500 and Stripe
    retries the delivery.
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
            # Serialize every event about one subscription BEFORE re-reading it.
            # Without this, handler A can read an older state, handler B read and
            # commit a newer one, and A commit last — writing stale state over
            # fresh (two replicas, or two threadpool workers, make it real).
            # Released at commit/rollback.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (sub_id,)
                )
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
    """True iff this event IS the renewal failing (its time starts the grace).

    Any other event that merely re-reads a past_due subscription — a late or
    retried one created before the failure, say — must not backdate the grace.
    """
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
    out: list[str] = []
    for item in items:
        price_id = _id_of(item.get("price"))
        if price_id:
            out.append(price_id)
    return out


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
    """Re-read one subscription from Stripe and write it to its user's row.

    Does NOT commit — ``process_event`` owns the transaction.
    """
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
        # Normally ensure_stripe_customer wrote the row before Checkout. Without
        # one (a customer made in the Dashboard, a lost write) we link through the
        # user id we stamped on the subscription — but only to a user that exists
        # here, so a test-mode event from another environment can never FK-fail
        # (which would 500 and make Stripe retry it for three days).
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
                    " ON CONFLICT (user_id) DO NOTHING RETURNING user_id"
                ).format(_SUBS),
                (str(user_id), customer_id),
            )
            if cur.fetchone() is None:
                logger.error(
                    "User %s already has a different Stripe customer; not linking %s",
                    user_id,
                    customer_id,
                )
                return
        row = {
            "user_id": str(user_id),
            "stripe_customer_id": customer_id,
            "stripe_subscription_id": None,
            "plan": "free",
            "status": None,
            "current_period_end": None,
            "cancel_at_period_end": False,
            "past_due_since": None,
            "created_at": event_created,
            "updated_at": event_created,
        }

    sub_id = str(sub.get("id"))
    status = str(sub.get("status") or "")
    # A late event about an OLD, finished subscription must not overwrite the
    # user's newer one (a user who cancelled and re-subscribed has two).
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
        # Stripe's event time, never now() (POSTGRES-ANTI-PATTERNS §4): a late
        # delivery must not push the 3-day grace back. Keep the earliest
        # observation while the SAME subscription stays past_due.
        previous = row["past_due_since"] if row["stripe_subscription_id"] == sub_id else None
        if previous is None:
            past_due_since = event_created
        elif marks_failure:
            # Two failure signals for one episode (payment_failed + the status
            # flip) can arrive in either order; the earlier one started it.
            past_due_since = min(previous, event_created)
        else:
            past_due_since = previous

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
                # The Portal can schedule a cancel either way: the legacy
                # cancel_at_period_end flag, or a cancel_at timestamp. Both mean
                # "Pro until the period ends, then Free".
                bool(sub.get("cancel_at_period_end")) or sub.get("cancel_at") is not None,
                past_due_since,
                customer_id,
            ),
        )
