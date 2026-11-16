"""BL-06..BL-09 — the monthly renewal, a declined card, the 3-day grace, recovery.

Time is moved with Stripe TEST CLOCKS: one clock per case, advanced to two
hours past the period end (Stripe finalizes the renewal invoice about an hour
after the period turns over, then charges it).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import stripe

from conftest import (
    BillingUser,
    parse_ts,
    subscription_api,
    wait_for_row,
)
from e2e.billing import stripe_env

PAST_RENEWAL_S = 2 * 3600


def _active(conn: Any, user: BillingUser) -> dict[str, Any]:
    return wait_for_row(conn, user.user_id, lambda r: r["status"] == "active" and r["plan"] == "pro",
                        "the webhook to record the new subscription as pro/active")


def _make_past_due(sc: stripe.StripeClient, conn: Any, user: BillingUser, clocked: Any) -> tuple[stripe_env.ClockedSubscription, dict[str, Any]]:
    s = clocked(user)
    _active(conn, user)
    stripe_env.attach_card(sc, s.customer_id, stripe_env.DECLINING_CARD)
    stripe_env.advance_clock(sc, s.clock_id, s.period_end + PAST_RENEWAL_S)
    row = wait_for_row(conn, user.user_id, lambda r: r["status"] == "past_due",
                       "the declined renewal to mark the subscription past_due")
    return s, row


def test_bl06_renewal_charges_again_and_extends_the_period(new_user: Any, clocked: Any, sc: stripe.StripeClient, conn: Any) -> None:
    user: BillingUser = new_user()
    s = clocked(user)
    first = _active(conn, user)
    first_end = first["current_period_end"]

    stripe_env.advance_clock(sc, s.clock_id, s.period_end + PAST_RENEWAL_S)

    renewed = wait_for_row(conn, user.user_id, lambda r: r["current_period_end"] > first_end,
                           "the renewal webhook to move current_period_end forward")
    assert renewed["status"] == "active" and renewed["plan"] == "pro", renewed
    gained = renewed["current_period_end"] - first_end
    assert timedelta(days=27) < gained < timedelta(days=32), f"the period moved by {gained}, not one month"
    assert renewed["past_due_since"] is None, renewed

    invoices = sc.v1.invoices.list(params={"customer": s.customer_id, "limit": 5}).data
    cycle = [i for i in invoices if i.billing_reason == "subscription_cycle"]
    assert cycle, f"no renewal invoice; reasons: {[i.billing_reason for i in invoices]}"
    assert cycle[0].status == "paid" and cycle[0].amount_paid == stripe_env.PRO_AMOUNT_CENTS, (cycle[0].status, cycle[0].amount_paid)
    assert subscription_api(user)["isPro"] is True


def test_bl07_a_declined_renewal_is_past_due_and_keeps_pro_for_three_days(new_user: Any, clocked: Any, sc: stripe.StripeClient, conn: Any) -> None:
    user: BillingUser = new_user()
    s, row = _make_past_due(sc, conn, user, clocked)
    assert row["plan"] == "pro", "a declined card must not drop the plan before the grace runs out"
    assert row["past_due_since"] is not None, "past_due without past_due_since means no grace clock at all"

    body = subscription_api(user)
    assert body["status"] == "past_due", body
    assert body["isPro"] is True, f"inside the grace window the user keeps Pro: {body}"
    assert body["hasSubscription"] is True, body
    grace = parse_ts(body["graceEndsAt"])
    since = parse_ts(body["pastDueSince"])
    assert grace is not None and since is not None, body
    assert grace - since == timedelta(days=3), f"grace is {grace - since}, not 3 days"

    invoice = sc.v1.invoices.list(params={"customer": s.customer_id, "status": "open", "limit": 1}).data
    assert invoice and invoice[0].attempt_count >= 1, "Stripe never tried to charge the declining card"


def test_bl08_after_the_grace_the_user_is_free_until_the_card_works(new_user: Any, clocked: Any, sc: stripe.StripeClient, conn: Any) -> None:
    """The grace clock is wall-clock time in the backend, which a test clock
    cannot move. So the case moves `past_due_since` itself — the one column
    the rule reads — to either side of the 3-day line."""
    user: BillingUser = new_user()
    _make_past_due(sc, conn, user, clocked)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE user_subscriptions SET past_due_since = now() - interval '2 days 23 hours' WHERE user_id = %s",
            (user.user_id,),
        )
    assert subscription_api(user)["isPro"] is True, "one hour before the grace ends the user must still be Pro"
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE user_subscriptions SET past_due_since = now() - interval '3 days 1 minute' WHERE user_id = %s",
            (user.user_id,),
        )
    body = subscription_api(user)
    assert body["isPro"] is False, f"past the 3-day grace the user must be Free: {body}"
    assert body["status"] == "past_due" and body["hasSubscription"] is True, (
        f"lapsed, not cancelled — Stripe is still retrying the card: {body}"
    )


def test_bl09_fixing_the_card_restores_pro(new_user: Any, clocked: Any, sc: stripe.StripeClient, conn: Any) -> None:
    user: BillingUser = new_user()
    s, _ = _make_past_due(sc, conn, user, clocked)
    with conn.cursor() as cur:  # lapsed: past the grace, so recovery is visible
        cur.execute(
            "UPDATE user_subscriptions SET past_due_since = now() - interval '4 days' WHERE user_id = %s",
            (user.user_id,),
        )
    assert subscription_api(user)["isPro"] is False

    stripe_env.attach_card(sc, s.customer_id, stripe_env.GOOD_CARD)
    open_invoices = sc.v1.invoices.list(params={"customer": s.customer_id, "status": "open", "limit": 1}).data
    assert open_invoices, "no open invoice to retry"
    sc.v1.invoices.pay(open_invoices[0].id)

    row = wait_for_row(conn, user.user_id, lambda r: r["status"] == "active",
                       "the paid retry to bring the subscription back to active")
    assert row["plan"] == "pro" and row["past_due_since"] is None, row
    assert subscription_api(user)["isPro"] is True, "a working card must restore Pro at once"
