"""BL-13..BL-15 — the webhook's guardrails, against real Stripe events.

BL-14 and BL-15 replay events Stripe REALLY sent (fetched from the event log),
signed with the real webhook secret. Nothing here hand-writes an event shape.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import stripe

from conftest import (
    BillingUser,
    event_payload,
    find_event,
    post_webhook,
    sign,
    sub_row,
    wait_for_row,
)


def _event_recorded(conn: Any, event_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM stripe_events WHERE event_id = %s", (event_id,))
        return int(cur.fetchone()["n"])


def _fake_subscription_event(sub_id: str = "sub_e2e_none") -> tuple[str, bytes]:
    event_id = f"evt_e2e_{uuid.uuid4().hex}"
    body = {
        "id": event_id,
        "object": "event",
        "type": "customer.subscription.updated",
        "created": int(time.time()),
        "data": {"object": {"id": sub_id, "object": "subscription", "customer": "cus_e2e_none"}},
    }
    return event_id, json.dumps(body).encode()


def test_bl13_a_bad_or_missing_signature_is_rejected_and_writes_nothing(conn: Any) -> None:
    event_id, payload = _fake_subscription_event()
    wrong = post_webhook(payload, sign(payload, secret="whsec_not_the_real_secret"))
    assert wrong.status_code == 400, f"a forged signature was accepted: {wrong.status_code} {wrong.text[:200]}"
    missing = post_webhook(payload, None)
    assert missing.status_code == 400, f"an unsigned body was accepted: {missing.status_code}"
    stale = post_webhook(payload, sign(payload, timestamp=int(time.time()) - 3600))
    assert stale.status_code == 400, f"an hour-old signature was accepted (replay window): {stale.status_code}"
    assert _event_recorded(conn, event_id) == 0, "a rejected event must leave no trace"


def test_bl13_an_unhandled_event_type_is_acknowledged_and_ignored(conn: Any) -> None:
    event_id = f"evt_e2e_{uuid.uuid4().hex}"
    payload = json.dumps(
        {"id": event_id, "object": "event", "type": "customer.created", "created": int(time.time()),
         "data": {"object": {"id": "cus_e2e_none", "object": "customer"}}}
    ).encode()
    resp = post_webhook(payload, sign(payload))
    assert resp.status_code == 200, f"Stripe would retry an unhandled type for days: {resp.status_code}"
    assert _event_recorded(conn, event_id) == 0


def test_bl14_replaying_a_delivered_event_changes_nothing(new_user: Any, clocked: Any, sc: stripe.StripeClient, conn: Any) -> None:
    user: BillingUser = new_user()
    s = clocked(user)
    before = wait_for_row(conn, user.user_id, lambda r: r["status"] == "active", "the subscription row")
    event_id = find_event(sc, "customer.subscription.created", s.subscription_id)
    assert _event_recorded(conn, event_id) == 1, "the forwarded delivery was never recorded"

    payload = json.dumps(event_payload(sc, event_id)).encode()
    for _ in range(2):
        resp = post_webhook(payload, sign(payload))
        assert resp.status_code == 200, f"a replay must still answer 200: {resp.status_code} {resp.text[:200]}"
    assert _event_recorded(conn, event_id) == 1, "a replay was recorded twice"
    after = sub_row(conn, user.user_id)
    assert after is not None and after["updated_at"] == before["updated_at"], "a replay rewrote the row"


def test_bl15_a_stale_event_cannot_undo_newer_state(new_user: Any, clocked: Any, sc: stripe.StripeClient, conn: Any) -> None:
    """Out-of-order delivery: the `created` event (cancel flag OFF) arrives
    after a cancel was scheduled. The handler treats every event as a nudge to
    re-read the subscription from Stripe, so the row must stay cancelled."""
    user: BillingUser = new_user()
    s = clocked(user)
    wait_for_row(conn, user.user_id, lambda r: r["status"] == "active", "the subscription row")
    created_id = find_event(sc, "customer.subscription.created", s.subscription_id)

    sc.v1.subscriptions.update(s.subscription_id, params={"cancel_at_period_end": True})
    wait_for_row(conn, user.user_id, lambda r: r["cancel_at_period_end"] is True, "the scheduled cancel")

    stale = event_payload(sc, created_id)
    assert stale["data"]["object"]["cancel_at_period_end"] is False, "fixture: the old event should predate the cancel"
    stale["id"] = f"evt_e2e_{uuid.uuid4().hex}"  # a new id, so dedupe cannot be what saves us
    payload = json.dumps(stale).encode()
    resp = post_webhook(payload, sign(payload))
    assert resp.status_code == 200, f"{resp.status_code} {resp.text[:200]}"

    row = sub_row(conn, user.user_id)
    assert row is not None and row["cancel_at_period_end"] is True, (
        f"a stale event regressed the row to its old payload: {row}"
    )
    assert _event_recorded(conn, stale["id"]) == 1, "the stale event should still be recorded as handled"
