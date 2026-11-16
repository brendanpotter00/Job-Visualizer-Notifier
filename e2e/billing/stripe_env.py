"""Stripe sandbox helpers for the billing gate: preflight, test clocks, cleanup.

Cleanup finds what a run created by two tags: test clocks named `e2e-billing-*`
(deleting a clock deletes its customers and subscriptions) and the customers
this section's own database links to (Checkout-created, so not on a clock).

  python -m e2e.billing.stripe_env preflight  # prints STRIPE_PRICE_ID_PRO=…; exit 3 = BLOCKED
  python -m e2e.billing.stripe_env cleanup
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import stripe

PRICE_LOOKUP_KEY = "pro_monthly"
PRO_AMOUNT_CENTS = 600
CLOCK_PREFIX = "e2e-billing"

# Stripe test payment methods; the second attaches, then declines every charge.
GOOD_CARD = "pm_card_visa"
DECLINING_CARD = "pm_card_chargeCustomerFail"


def secret_key() -> str:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key.startswith(("sk_test_", "rk_test_")):
        raise SystemExit(
            "billing e2e refuses to run: STRIPE_SECRET_KEY is not a sandbox/test key "
            "(sk_test_… / rk_test_…). Never point this gate at a live account."
        )
    return key


def client() -> stripe.StripeClient:
    return stripe.StripeClient(secret_key(), max_network_retries=2)


def ensure_price(c: stripe.StripeClient) -> str:
    """The sandbox's $6/month Pro price by lookup_key, created if missing; wrong terms are refused."""
    prices = c.v1.prices.list(params={"lookup_keys": [PRICE_LOOKUP_KEY], "active": True, "limit": 1})
    if prices.data:
        p = prices.data[0]
        recurring = p.recurring
        if p.unit_amount != PRO_AMOUNT_CENTS or p.currency != "usd" or not recurring or recurring.interval != "month":
            raise SystemExit(
                f"billing e2e: price {p.id} (lookup_key {PRICE_LOOKUP_KEY}) is not $6/month USD — "
                "fix or archive it in the sandbox."
            )
        return p.id
    product = c.v1.products.create(params={"name": "Pro", "description": "Unlimited MCP access"})
    price = c.v1.prices.create(
        params={
            "product": product.id,
            "unit_amount": PRO_AMOUNT_CENTS,
            "currency": "usd",
            "recurring": {"interval": "month"},
            "lookup_key": PRICE_LOOKUP_KEY,
        }
    )
    return price.id


def check_portal_configuration(c: stripe.StripeClient) -> str:
    """Refuse a default Portal config that cannot cancel or update the card.
    None saved yet is fine: Stripe's default has both on."""
    configs = c.v1.billing_portal.configurations.list(params={"is_default": True, "limit": 1})
    if not configs.data:
        return "none yet (Stripe creates the default on first use)"
    cfg = configs.data[0]
    f = cfg.features
    if not (f.subscription_cancel.enabled and f.payment_method_update.enabled):
        raise SystemExit(
            f"billing e2e: the sandbox's default portal configuration {cfg.id} has "
            "cancel or payment-method update turned off. Turn both on in "
            "Settings → Billing → Customer portal."
        )
    return f"{cfg.id} (cancel={f.subscription_cancel.mode}, card update on)"


def preflight() -> int:
    try:
        c = client()
        c.v1.balance.retrieve()
    except stripe.AuthenticationError as e:
        print(f"PREFLIGHT_ERROR=Stripe rejected the key: {e}", file=sys.stderr)
        return 1
    except stripe.StripeError as e:
        print(f"PREFLIGHT_BLOCKED=Stripe sandbox unreachable: {e}", file=sys.stderr)
        return 3
    price = ensure_price(c)
    portal = check_portal_configuration(c)
    print(f"STRIPE_PRICE_ID_PRO={price}")
    print(f"# portal configuration: {portal}", file=sys.stderr)
    return 0


# --- Test clocks -----------------------------------------------------------


@dataclass
class ClockedSubscription:
    clock_id: str
    customer_id: str
    subscription_id: str
    period_end: int


def new_clock(c: stripe.StripeClient, label: str) -> str:
    clock = c.v1.test_helpers.test_clocks.create(
        params={"frozen_time": int(time.time()), "name": f"{CLOCK_PREFIX}-{label}"[:60]}
    )
    return clock.id


def advance_clock(c: stripe.StripeClient, clock_id: str, to: int, *, timeout: float = 180.0) -> None:
    """Move the clock and wait until Stripe has finished every billing step it
    triggered. `status` stays `advancing` while invoices finalize and charge."""
    c.v1.test_helpers.test_clocks.advance(clock_id, params={"frozen_time": to})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        clock = c.v1.test_helpers.test_clocks.retrieve(clock_id)
        if clock.status == "ready":
            return
        if clock.status == "internal_failure":
            raise AssertionError(f"test clock {clock_id} hit internal_failure while advancing")
        time.sleep(2)
    raise AssertionError(f"test clock {clock_id} still advancing after {timeout}s")


def attach_card(c: stripe.StripeClient, customer_id: str, test_pm: str) -> str:
    """Attach a Stripe test payment method and make it the invoice default."""
    pm = c.v1.payment_methods.attach(test_pm, params={"customer": customer_id})
    c.v1.customers.update(customer_id, params={"invoice_settings": {"default_payment_method": pm.id}})
    return pm.id


def subscribe_on_clock(c: stripe.StripeClient, *, user_id: str, email: str, label: str) -> ClockedSubscription:
    """A paid $6/month subscription for `user_id` on its own test clock, linked
    by `metadata.user_id` (the webhook's link when no row exists yet)."""
    clock_id = new_clock(c, label)
    customer = c.v1.customers.create(
        params={"email": email, "test_clock": clock_id, "metadata": {"user_id": user_id}}
    )
    attach_card(c, customer.id, GOOD_CARD)
    sub = c.v1.subscriptions.create(
        params={
            "customer": customer.id,
            "items": [{"price": os.environ["STRIPE_PRICE_ID_PRO"]}],
            "metadata": {"user_id": user_id},
        }
    )
    return ClockedSubscription(
        clock_id=clock_id,
        customer_id=customer.id,
        subscription_id=sub.id,
        period_end=int(sub["items"]["data"][0]["current_period_end"]),
    )


# --- Cleanup -----------------------------------------------------------------


def _delete_quietly(fn: Any, obj_id: str) -> bool:
    try:
        fn(obj_id)
        return True
    except stripe.InvalidRequestError:
        return False  # already gone (deleted with its clock, or by a prior cleanup)


def cleanup(dsn: str) -> None:
    """Delete every Stripe object and DB row this section created. Idempotent,
    so it runs both before a run (a prior run may have been aborted) and after."""
    c = client()
    clocks = 0
    for clock in c.v1.test_helpers.test_clocks.list(params={"limit": 100}).auto_paging_iter():
        if (clock.name or "").startswith(CLOCK_PREFIX):
            clocks += _delete_quietly(c.v1.test_helpers.test_clocks.delete, clock.id)

    # Through the shared fence: refuses any database but this section's own.
    from e2e.shared.db import assertions as db

    customers = 0
    conn = db.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT stripe_customer_id FROM user_subscriptions")
            for row in cur.fetchall():
                customers += _delete_quietly(c.v1.customers.delete, row["stripe_customer_id"])
            cur.execute("DELETE FROM user_subscriptions")
            cur.execute("DELETE FROM stripe_events")
            cur.execute(
                "DELETE FROM admins WHERE user_id IN (SELECT id FROM users WHERE email LIKE %s)",
                ("e2e+billing-%",),
            )
            cur.execute("DELETE FROM users WHERE email LIKE %s", ("e2e+billing-%",))
        conn.commit()
    finally:
        conn.close()
    print(f"billing cleanup: deleted {clocks} test clock(s), {customers} product-created customer(s)")


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "preflight":
        return preflight()
    if cmd == "cleanup":
        cleanup(os.environ["E2E_DATABASE_URL"])
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
