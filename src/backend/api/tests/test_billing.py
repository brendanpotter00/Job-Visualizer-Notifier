"""Billing: /api/billing routes, the Stripe webhook, entitlements, and the schema.

Stripe is never called: ``billing_service._client`` is monkeypatched with a fake
that records what it was asked and returns canned objects. Webhook signatures
are real HMACs over the raw body, verified by the real ``stripe`` parser.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth.dependencies import get_current_user
from api.config import settings
from api.services import billing_service, entitlements

from .conftest import _insert_admin, _insert_user, _make_user

WEBHOOK_SECRET = "whsec_test_secret"
PRICE_PRO = "price_test_pro"
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def no_stripe_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test unconfigured, whatever the machine's .env says."""
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    monkeypatch.setattr(settings, "stripe_webhook_secret", None)
    monkeypatch.setattr(settings, "stripe_price_id_pro", None)


@pytest.fixture
def stripe_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "stripe_price_id_pro", PRICE_PRO)
    monkeypatch.setattr(settings, "public_app_url", "https://app.example")


class FakeStripe:
    """Stands in for ``stripe.StripeClient``; only the four calls we make."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.fail_retrieve = False
        outer = self

        def create_customer(params: dict, options: dict | None = None) -> Any:
            outer.calls.append(("customers.create", params))
            return SimpleNamespace(id="cus_test_1")

        def create_checkout(params: dict) -> Any:
            outer.calls.append(("checkout.create", params))
            return SimpleNamespace(url="https://checkout.stripe.test/cs_1")

        def create_portal(params: dict) -> Any:
            outer.calls.append(("portal.create", params))
            return SimpleNamespace(url="https://billing.stripe.test/p_1")

        def retrieve(sub_id: str) -> Any:
            outer.calls.append(("subscriptions.retrieve", sub_id))
            if outer.fail_retrieve:
                raise RuntimeError("stripe down")
            data = outer.subscriptions[sub_id]
            return SimpleNamespace(to_dict=lambda: data)

        self.v1 = SimpleNamespace(
            customers=SimpleNamespace(create=create_customer),
            checkout=SimpleNamespace(sessions=SimpleNamespace(create=create_checkout)),
            billing_portal=SimpleNamespace(sessions=SimpleNamespace(create=create_portal)),
            subscriptions=SimpleNamespace(retrieve=retrieve),
        )


@pytest.fixture
def fake_stripe(monkeypatch: pytest.MonkeyPatch, stripe_settings: None) -> FakeStripe:
    fake = FakeStripe()
    monkeypatch.setattr(billing_service, "_client", lambda: fake)
    return fake


def _sub(
    sub_id: str = "sub_1",
    *,
    customer: str = "cus_test_1",
    status: str = "active",
    price: str = PRICE_PRO,
    period_end: int = 1_800_000_000,
    cancel_at_period_end: bool = False,
    user_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": sub_id,
        "object": "subscription",
        "customer": customer,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "cancel_at": None,
        "metadata": {"user_id": user_id} if user_id else {},
        "items": {"data": [{"price": {"id": price}, "current_period_end": period_end}]},
    }


def _signed(payload: bytes, secret: str = WEBHOOK_SECRET) -> str:
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _event(
    event_type: str,
    obj: dict[str, Any],
    *,
    event_id: str = "evt_1",
    created: datetime = NOW,
) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": event_type,
            "created": int(created.timestamp()),
            "data": {"object": obj},
        }
    ).encode()


def _post_webhook(client: TestClient, payload: bytes, sig: str | None = None) -> Any:
    return client.post(
        "/api/billing/webhook",
        content=payload,
        headers={"Stripe-Signature": sig if sig is not None else _signed(payload)},
    )


def _user_id(db_conn) -> str:
    """The users.id the test token resolves to (created via GET /subscription)."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", ("test@example.com",))
        return str(cur.fetchone()["id"])


def _sub_row(db_conn, user_id: str) -> dict[str, Any] | None:
    with db_conn.cursor() as cur:
        cur.execute("SELECT * FROM user_subscriptions WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    db_conn.commit()
    return dict(row) if row else None


def _seed_customer(db_conn, client: TestClient) -> str:
    """Resolve the test user and give them a Stripe customer row."""
    client.get("/api/billing/subscription")
    uid = _user_id(db_conn)
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO user_subscriptions (user_id, stripe_customer_id) VALUES (%s, %s)",
            (uid, "cus_test_1"),
        )
    db_conn.commit()
    return uid


# ------------------------------------------------------------------ status


class TestGetSubscription:
    def test_free_by_default_and_billing_disabled_without_keys(self, client, db_conn):
        body = client.get("/api/billing/subscription").json()
        assert body == {
            "plan": "free",
            "status": None,
            "isPro": False,
            "hasSubscription": False,
            "currentPeriodEnd": None,
            "cancelAtPeriodEnd": False,
            "pastDueSince": None,
            "graceEndsAt": None,
            "billingEnabled": False,
        }

    def test_admin_is_pro_without_a_subscription(self, client, db_conn, stripe_settings):
        client.get("/api/billing/subscription")
        _insert_admin(db_conn, _user_id(db_conn))
        body = client.get("/api/billing/subscription").json()
        assert body["isPro"] is True
        assert body["hasSubscription"] is False  # nothing to manage
        assert body["billingEnabled"] is True


# ---------------------------------------------------------------- checkout


class TestCheckout:
    def test_503_when_not_configured(self, client, db_conn):
        assert client.post("/api/billing/checkout-session").status_code == 503

    def test_creates_customer_row_and_returns_checkout_url(self, client, db_conn, fake_stripe):
        resp = client.post("/api/billing/checkout-session")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"url": "https://checkout.stripe.test/cs_1"}
        uid = _user_id(db_conn)
        row = _sub_row(db_conn, uid)
        assert row is not None and row["stripe_customer_id"] == "cus_test_1"
        assert row["plan"] == "free"  # Checkout alone never grants Pro
        (_, params) = [c for c in fake_stripe.calls if c[0] == "checkout.create"][0]
        assert params["mode"] == "subscription"
        assert params["customer"] == "cus_test_1"
        assert params["client_reference_id"] == uid
        assert params["line_items"] == [{"price": PRICE_PRO, "quantity": 1}]
        assert params["success_url"] == "https://app.example/pricing?checkout=success"
        assert params["cancel_url"] == "https://app.example/pricing?checkout=cancel"

    def test_reuses_the_customer_on_a_second_checkout(self, client, db_conn, fake_stripe):
        client.post("/api/billing/checkout-session")
        client.post("/api/billing/checkout-session")
        assert [c[0] for c in fake_stripe.calls].count("customers.create") == 1

    def test_409_when_a_live_subscription_exists(self, client, db_conn, fake_stripe):
        uid = _seed_customer(db_conn, client)
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE user_subscriptions SET stripe_subscription_id='sub_1',"
                " plan='pro', status='past_due' WHERE user_id=%s",
                (uid,),
            )
        db_conn.commit()
        assert client.post("/api/billing/checkout-session").status_code == 409

    def test_a_canceled_subscription_can_check_out_again(self, client, db_conn, fake_stripe):
        uid = _seed_customer(db_conn, client)
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE user_subscriptions SET stripe_subscription_id='sub_old',"
                " status='canceled' WHERE user_id=%s",
                (uid,),
            )
        db_conn.commit()
        assert client.post("/api/billing/checkout-session").status_code == 200


class TestPortal:
    def test_404_without_a_billing_account(self, client, db_conn, fake_stripe):
        assert client.post("/api/billing/portal-session").status_code == 404

    def test_returns_portal_url_for_the_users_customer(self, client, db_conn, fake_stripe):
        _seed_customer(db_conn, client)
        resp = client.post("/api/billing/portal-session")
        assert resp.status_code == 200
        assert resp.json() == {"url": "https://billing.stripe.test/p_1"}
        (_, params) = [c for c in fake_stripe.calls if c[0] == "portal.create"][0]
        assert params == {"customer": "cus_test_1", "return_url": "https://app.example/pricing"}


# ----------------------------------------------------------------- webhook


class TestWebhook:
    def test_503_when_not_configured(self, client, db_conn):
        payload = _event("customer.subscription.updated", _sub())
        assert _post_webhook(client, payload).status_code == 503

    def test_400_on_a_bad_signature(self, client, db_conn, fake_stripe):
        payload = _event("customer.subscription.updated", _sub())
        assert _post_webhook(client, payload, sig=_signed(payload, "whsec_wrong")).status_code == 400
        assert _post_webhook(client, payload, sig="").status_code == 400
        assert fake_stripe.calls == []

    def test_checkout_completed_makes_the_user_pro(self, client, db_conn, fake_stripe):
        uid = _seed_customer(db_conn, client)
        fake_stripe.subscriptions["sub_1"] = _sub()
        obj = {"object": "checkout.session", "subscription": "sub_1", "client_reference_id": uid}
        assert _post_webhook(client, _event("checkout.session.completed", obj)).status_code == 200
        row = _sub_row(db_conn, uid)
        assert row["plan"] == "pro" and row["status"] == "active"
        assert row["stripe_subscription_id"] == "sub_1"
        assert row["current_period_end"] == datetime.fromtimestamp(1_800_000_000, tz=timezone.utc)
        assert client.get("/api/billing/subscription").json()["isPro"] is True

    def test_a_replay_is_a_200_no_op(self, client, db_conn, fake_stripe):
        _seed_customer(db_conn, client)
        fake_stripe.subscriptions["sub_1"] = _sub()
        payload = _event("customer.subscription.updated", _sub(), event_id="evt_same")
        assert _post_webhook(client, payload).status_code == 200
        assert _post_webhook(client, payload).status_code == 200
        retrieves = [c for c in fake_stripe.calls if c[0] == "subscriptions.retrieve"]
        assert len(retrieves) == 1

    def test_a_failed_sync_is_500_and_not_recorded_so_the_retry_runs(
        self, client, db_conn, fake_stripe
    ):
        uid = _seed_customer(db_conn, client)
        fake_stripe.subscriptions["sub_1"] = _sub()
        payload = _event("customer.subscription.updated", _sub(), event_id="evt_retry")
        fake_stripe.fail_retrieve = True
        assert _post_webhook(client, payload).status_code == 500
        fake_stripe.fail_retrieve = False
        assert _post_webhook(client, payload).status_code == 200
        assert _sub_row(db_conn, uid)["plan"] == "pro"

    def test_unknown_event_types_are_acknowledged_and_ignored(self, client, db_conn, fake_stripe):
        payload = _event("customer.created", {"id": "cus_x"})
        assert _post_webhook(client, payload).status_code == 200
        assert fake_stripe.calls == []

    def test_an_unknown_customer_is_ignored_not_retried(self, client, db_conn, fake_stripe):
        fake_stripe.subscriptions["sub_9"] = _sub("sub_9", customer="cus_elsewhere", user_id="nope")
        payload = _event("customer.subscription.updated", {"id": "sub_9"})
        assert _post_webhook(client, payload).status_code == 200

    def test_links_by_metadata_when_the_row_is_missing(self, client, db_conn, fake_stripe):
        client.get("/api/billing/subscription")
        uid = _user_id(db_conn)
        fake_stripe.subscriptions["sub_1"] = _sub(customer="cus_dash", user_id=uid)
        assert _post_webhook(client, _event("customer.subscription.created", {"id": "sub_1"})).status_code == 200
        row = _sub_row(db_conn, uid)
        assert row["stripe_customer_id"] == "cus_dash" and row["plan"] == "pro"

    def test_past_due_since_is_stripes_event_time_and_keeps_the_earliest(
        self, client, db_conn, fake_stripe
    ):
        uid = _seed_customer(db_conn, client)
        fake_stripe.subscriptions["sub_1"] = _sub(status="past_due")
        later = NOW + timedelta(hours=5)
        _post_webhook(client, _event("invoice.payment_failed", {"subscription": "sub_1"}, event_id="e1", created=later))
        _post_webhook(client, _event("customer.subscription.updated", {"id": "sub_1"}, event_id="e2", created=NOW))
        assert _sub_row(db_conn, uid)["past_due_since"] == NOW
        fake_stripe.subscriptions["sub_1"] = _sub(status="active")
        _post_webhook(client, _event("invoice.paid", {"parent": {"subscription_details": {"subscription": "sub_1"}}}, event_id="e3"))
        row = _sub_row(db_conn, uid)
        assert row["status"] == "active" and row["past_due_since"] is None

    def test_deleted_subscription_drops_to_free_and_keeps_the_row(self, client, db_conn, fake_stripe):
        uid = _seed_customer(db_conn, client)
        fake_stripe.subscriptions["sub_1"] = _sub()
        _post_webhook(client, _event("customer.subscription.created", {"id": "sub_1"}, event_id="a"))
        fake_stripe.subscriptions["sub_1"] = _sub(status="canceled")
        _post_webhook(client, _event("customer.subscription.deleted", {"id": "sub_1"}, event_id="b"))
        row = _sub_row(db_conn, uid)
        assert row["plan"] == "free" and row["status"] == "canceled"
        assert row["stripe_customer_id"] == "cus_test_1"

    def test_a_late_event_for_an_old_subscription_does_not_clobber_the_new_one(
        self, client, db_conn, fake_stripe
    ):
        uid = _seed_customer(db_conn, client)
        fake_stripe.subscriptions["sub_new"] = _sub("sub_new")
        _post_webhook(client, _event("customer.subscription.created", {"id": "sub_new"}, event_id="a"))
        fake_stripe.subscriptions["sub_old"] = _sub("sub_old", status="canceled")
        _post_webhook(client, _event("customer.subscription.deleted", {"id": "sub_old"}, event_id="b"))
        row = _sub_row(db_conn, uid)
        assert row["stripe_subscription_id"] == "sub_new" and row["plan"] == "pro"

    def test_a_subscription_on_another_price_is_recorded_free(self, client, db_conn, fake_stripe):
        uid = _seed_customer(db_conn, client)
        fake_stripe.subscriptions["sub_1"] = _sub(price="price_other")
        _post_webhook(client, _event("customer.subscription.created", {"id": "sub_1"}))
        assert _sub_row(db_conn, uid)["plan"] == "free"

    def test_the_webhook_is_exempt_from_the_internal_key(self):
        from api.auth.internal_key import _EXEMPT_PATHS

        assert "/api/billing/webhook" in _EXEMPT_PATHS


# ------------------------------------------------------------ entitlements


def _row(**overrides: Any) -> billing_service.SubscriptionRow:
    base: dict[str, Any] = {
        "user_id": "u",
        "stripe_customer_id": "cus",
        "stripe_subscription_id": "sub",
        "plan": "pro",
        "status": "active",
        "current_period_end": None,
        "cancel_at_period_end": False,
        "past_due_since": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


class TestIsPro:
    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({}, True),
            ({"status": "trialing"}, True),
            ({"plan": "free", "status": "active"}, False),
            ({"status": "canceled", "plan": "free"}, False),
            ({"status": "unpaid"}, False),
            ({"status": "incomplete"}, False),
            # The 3-day grace: Pro just inside it, Free at and past its end.
            ({"status": "past_due", "past_due_since": NOW - timedelta(days=2, hours=23)}, True),
            ({"status": "past_due", "past_due_since": NOW - timedelta(days=3)}, False),
            ({"status": "past_due", "past_due_since": NOW - timedelta(days=5)}, False),
            ({"status": "past_due", "past_due_since": None}, False),
        ],
    )
    def test_rule(self, overrides: dict[str, Any], expected: bool) -> None:
        assert entitlements.is_pro_row(_row(**overrides), now=NOW) is expected

    def test_no_row_is_free(self) -> None:
        assert entitlements.is_pro_row(None, now=NOW) is False

    def test_grace_ends_three_days_after_past_due_since(self) -> None:
        row = _row(status="past_due", past_due_since=NOW)
        assert entitlements.grace_ends_at(row) == NOW + timedelta(days=3)
        assert entitlements.grace_ends_at(_row()) is None

    def test_admins_are_pro(self, db_conn) -> None:
        user = _make_user({"email": "admin@example.com"})
        _insert_user(db_conn, user)
        _insert_admin(db_conn, user["id"])
        assert entitlements.is_pro(db_conn, user["id"], "admin@example.com") is True
        assert entitlements.is_pro(db_conn, user["id"]) is False


class TestRequirePro:
    def test_402_with_the_pricing_link_for_a_free_user(self, test_app, db_conn, stripe_settings):
        from fastapi import Depends, FastAPI

        from api.dependencies import get_db

        app = FastAPI()

        @app.get("/pro-only")
        def pro_only(_: dict = Depends(entitlements.require_pro)) -> dict:
            return {"ok": True}

        app.dependency_overrides[get_db] = test_app.dependency_overrides[get_db]
        app.dependency_overrides[get_current_user] = test_app.dependency_overrides[get_current_user]
        _insert_user(db_conn, _make_user())  # test@example.com, no subscription
        resp = TestClient(app).get("/pro-only")
        assert resp.status_code == 402
        assert resp.json()["detail"] == {
            "error": "pro_required",
            "upgradeUrl": "https://app.example/pricing?reason=pro_required",
        }


class TestRateLimitedResponse:
    def test_shape_links_to_pricing_three_ways(self, stripe_settings) -> None:
        resets = datetime.now(timezone.utc) + timedelta(hours=1)
        resp = entitlements.rate_limited_response(limit=100, window="day", resets_at=resets)
        assert resp.status_code == 429
        body = json.loads(resp.body)
        url = "https://app.example/pricing?reason=mcp_limit"
        assert body["error"] == "rate_limited" and body["plan"] == "free"
        assert body["limit"] == 100 and body["window"] == "day"
        assert body["upgradeUrl"] == url
        assert body["resetsAt"].endswith("Z")
        assert resp.headers["Link"] == f'<{url}>; rel="payment"'
        assert 3500 <= int(resp.headers["Retry-After"]) <= 3600


# ------------------------------------------------------------------ schema


class TestSchema:
    def test_a_user_with_billing_state_cannot_be_deleted(self, db_conn) -> None:
        user = _make_user()
        _insert_user(db_conn, user)
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_subscriptions (user_id, stripe_customer_id) VALUES (%s, 'cus_r')",
                (user["id"],),
            )
        db_conn.commit()
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            with db_conn.cursor() as cur:
                cur.execute(sql.SQL("DELETE FROM users WHERE id = %s"), (user["id"],))
        db_conn.rollback()

    def test_the_trigger_stamps_updated_at_on_every_update(self, db_conn) -> None:
        user = _make_user()
        _insert_user(db_conn, user)
        with db_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_subscriptions (user_id, stripe_customer_id, updated_at)"
                " VALUES (%s, 'cus_t', '2020-01-01T00:00:00Z')",
                (user["id"],),
            )
            cur.execute(
                "UPDATE user_subscriptions SET status = 'active' WHERE user_id = %s"
                " RETURNING updated_at",
                (user["id"],),
            )
            stamped = cur.fetchone()["updated_at"]
        db_conn.commit()
        assert stamped > datetime(2025, 1, 1, tzinfo=timezone.utc)

    def test_plan_only_accepts_free_or_pro(self, db_conn) -> None:
        user = _make_user()
        _insert_user(db_conn, user)
        with pytest.raises(psycopg2.errors.CheckViolation):
            with db_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_subscriptions (user_id, stripe_customer_id, plan)"
                    " VALUES (%s, 'cus_c', 'enterprise')",
                    (user["id"],),
                )
        db_conn.rollback()
