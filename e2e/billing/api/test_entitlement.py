"""BL-01, BL-04, BL-05 — who is Pro, and what Checkout may and may not do."""

from __future__ import annotations

import os
from typing import Any

import stripe

from conftest import (
    CHECKOUT,
    BillingUser,
    sub_row,
    subscription_api,
    wait_for_row,
)


def test_bl01_a_new_user_is_free_with_billing_open(new_user: Any) -> None:
    user: BillingUser = new_user()
    body = subscription_api(user)
    assert body["plan"] == "free", body
    assert body["isPro"] is False, body
    assert body["hasSubscription"] is False, body
    assert body["billingEnabled"] is True, (
        "billingEnabled is false: the stack booted without a full Stripe config, so the "
        f"pricing page would show 'Checkout is not open yet'. Body: {body}"
    )


def test_bl01_an_admin_is_pro_without_paying(new_user: Any, conn: Any) -> None:
    admin: BillingUser = new_user(admin=True)
    body = subscription_api(admin)
    assert body["isPro"] is True, f"admins get Pro free (the add-quota exemption); got {body}"
    assert body["hasSubscription"] is False, body
    assert sub_row(conn, admin.user_id) is None, "an admin's free Pro must not invent a subscription row"


def test_bl04_starting_checkout_does_not_grant_pro(new_user: Any, sc: stripe.StripeClient, conn: Any) -> None:
    """Only the webhook grants Pro. A Checkout Session that was opened and never
    paid leaves the user Free — the success_url is just a page."""
    user: BillingUser = new_user()
    with user.client() as c:
        resp = c.post(CHECKOUT)
    assert resp.status_code == 200, f"POST {CHECKOUT}: {resp.status_code} {resp.text[:300]}"
    url = resp.json()["url"]
    assert url.startswith("https://checkout.stripe.com/"), url

    session_id = url.split("/pay/", 1)[1].split("#", 1)[0]
    session = sc.v1.checkout.sessions.retrieve(session_id)
    assert session.mode == "subscription", session.mode
    assert session.status == "open", session.status
    assert session.client_reference_id == user.user_id, "the webhook's fallback link to the user is missing"
    assert session.success_url == "http://127.0.0.1:3204/pricing?checkout=success", session.success_url
    assert session.cancel_url == "http://127.0.0.1:3204/pricing?checkout=cancel", session.cancel_url
    items = sc.v1.checkout.sessions.line_items.list(session_id)
    assert [li.price.id for li in items.data] == [os.environ["STRIPE_PRICE_ID_PRO"]], "Checkout is not selling the Pro price"

    row = sub_row(conn, user.user_id)
    assert row is not None, "Checkout must create (and remember) the Stripe customer"
    assert row["stripe_customer_id"] == session.customer, (row, session.customer)
    assert row["plan"] == "free" and row["status"] is None, row
    body = subscription_api(user)
    assert body["isPro"] is False and body["hasSubscription"] is False, body


def test_bl05_a_second_checkout_expires_the_first(new_user: Any, sc: stripe.StripeClient) -> None:
    """Two tabs, two Checkout pages: only the newest may be paid, or a user who
    finishes both is billed twice."""
    user: BillingUser = new_user()
    with user.client() as c:
        first = c.post(CHECKOUT)
        second = c.post(CHECKOUT)
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    first_id = first.json()["url"].split("/pay/", 1)[1].split("#", 1)[0]
    second_id = second.json()["url"].split("/pay/", 1)[1].split("#", 1)[0]
    assert first_id != second_id
    assert sc.v1.checkout.sessions.retrieve(first_id).status == "expired", "the first Checkout is still payable"
    assert sc.v1.checkout.sessions.retrieve(second_id).status == "open"


def test_bl05_a_live_subscriber_cannot_check_out_again(new_user: Any, clocked: Any, conn: Any) -> None:
    user: BillingUser = new_user()
    clocked(user)
    wait_for_row(conn, user.user_id, lambda r: r["status"] == "active" and r["plan"] == "pro",
                 "the webhook to record the new subscription as pro/active")
    with user.client() as c:
        resp = c.post(CHECKOUT)
    assert resp.status_code == 409, f"a live subscriber was offered a second subscription: {resp.status_code} {resp.text[:200]}"
