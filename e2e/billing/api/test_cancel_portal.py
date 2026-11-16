"""BL-10, BL-12 — the billing portal, and cancelling at the end of the period."""

from __future__ import annotations

from typing import Any

import stripe

from conftest import (
    PORTAL,
    BillingUser,
    sub_row,
    subscription_api,
    wait_for_row,
)
from e2e.billing import stripe_env

PAST_END_S = 2 * 3600


def test_bl10_the_portal_opens_for_a_customer(new_user: Any, clocked: Any, conn: Any) -> None:
    user: BillingUser = new_user()
    clocked(user)
    wait_for_row(conn, user.user_id, lambda r: r["status"] == "active", "the subscription row")
    with user.client() as c:
        resp = c.post(PORTAL)
    assert resp.status_code == 200, f"POST {PORTAL}: {resp.status_code} {resp.text[:300]}"
    assert resp.json()["url"].startswith("https://billing.stripe.com/"), resp.json()


def test_bl10_the_portal_refuses_a_user_who_never_checked_out(new_user: Any) -> None:
    user: BillingUser = new_user()
    with user.client() as c:
        resp = c.post(PORTAL)
    assert resp.status_code == 404, f"no Stripe customer, so no portal: {resp.status_code} {resp.text[:200]}"


def _cancel_then_expire(sc: stripe.StripeClient, conn: Any, user: BillingUser, s: stripe_env.ClockedSubscription, params: dict[str, Any]) -> None:
    wait_for_row(conn, user.user_id, lambda r: r["status"] == "active", "the subscription row")
    sc.v1.subscriptions.update(s.subscription_id, params=params)
    wait_for_row(conn, user.user_id, lambda r: r["cancel_at_period_end"] is True,
                 "the update webhook to record the scheduled cancel")

    body = subscription_api(user)
    assert body["isPro"] is True, f"a cancel takes effect at the END of the paid month: {body}"
    assert body["cancelAtPeriodEnd"] is True and body["hasSubscription"] is True, body

    stripe_env.advance_clock(sc, s.clock_id, s.period_end + PAST_END_S)
    row = wait_for_row(conn, user.user_id, lambda r: r["status"] == "canceled",
                       "the period to end and the subscription to be deleted")
    assert row["plan"] == "free", row
    body = subscription_api(user)
    assert body["isPro"] is False and body["hasSubscription"] is False, body
    assert sub_row(conn, user.user_id) is not None, "the row (and its Stripe customer) must be kept for a re-subscribe"


def test_bl12_cancel_at_period_end_keeps_pro_until_the_end(new_user: Any, clocked: Any, sc: stripe.StripeClient, conn: Any) -> None:
    user: BillingUser = new_user()
    s = clocked(user)
    _cancel_then_expire(sc, conn, user, s, {"cancel_at_period_end": True})


def test_bl12_a_cancel_at_date_counts_as_a_scheduled_cancel(new_user: Any, clocked: Any, sc: stripe.StripeClient, conn: Any) -> None:
    """The Portal can schedule a cancel either way — the legacy flag or a
    `cancel_at` timestamp. Both must read as "Pro until then, then Free"."""
    user: BillingUser = new_user()
    s = clocked(user)
    _cancel_then_expire(sc, conn, user, s, {"cancel_at": s.period_end})
