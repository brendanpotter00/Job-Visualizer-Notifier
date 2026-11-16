"""pytest fixtures for the billing API tier (CASES.md).

Assumes run.sh has the stack up on :8204 and `stripe listen` forwarding to it,
so a fix loop can point pytest at a `--keep-up` stack. Every case gets a fresh
user and, when time must pass, its own test clock.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

import httpx
import pytest

_HERE = Path(__file__).resolve()
_SECTION_DIR = _HERE.parents[1]
_REPO_ROOT = _HERE.parents[3]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "src" / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import stripe  # noqa: E402

from e2e.billing import stripe_env  # noqa: E402
from e2e.shared.auth.mint import custom_user, mint_token  # noqa: E402
from e2e.shared.db import assertions as db  # noqa: E402

BASE_URL = os.environ.get("E2E_BACKEND_URL", "http://127.0.0.1:8204")
DB_DSN = os.environ.get(
    "E2E_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/jobscraper_e2e_billing"
)
SUBSCRIPTION = "/api/billing/subscription"
CHECKOUT = "/api/billing/checkout-session"
PORTAL = "/api/billing/portal-session"
WEBHOOK = "/api/billing/webhook"

# Webhooks travel Stripe -> `stripe listen` -> backend; seconds, normally.
WEBHOOK_WAIT_S = 45.0

ARTIFACTS_DIR = Path(
    os.environ.get("E2E_ARTIFACTS_DIR", str(_SECTION_DIR / "artifacts" / f"local-{int(time.time())}"))
)
CASES_DIR = ARTIFACTS_DIR / "cases"

T = TypeVar("T")


def _sanitize(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


@pytest.fixture(scope="session", autouse=True)
def _stack_or_blocked() -> None:
    """BLOCKED (skipped), not failed, when run.sh's preflight could not reach
    the sandbox; otherwise fail fast, in words, if this is not the billing stack."""
    blocked = os.environ.get("E2E_STRIPE_BLOCKED")
    if blocked:
        pytest.skip(f"BLOCKED: {blocked}")
    resp = httpx.get(f"{BASE_URL}/health", timeout=10.0)
    resp.raise_for_status()
    db.connect(DB_DSN).close()  # asserts the database name (E2E_EXPECTED_DB)
    for var in ("STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_ID_PRO"):
        assert os.environ.get(var), f"{var} is not exported — run this through e2e/run.sh billing"


@pytest.fixture(scope="session")
def sc() -> stripe.StripeClient:
    return stripe_env.client()


@pytest.fixture()
def conn() -> Iterator[Any]:
    """Autocommit, so every poll sees what the webhook handler just committed."""
    c = db.connect(DB_DSN)
    c.autocommit = True
    try:
        yield c
    finally:
        c.close()


# --- Users -------------------------------------------------------------------


@dataclass
class BillingUser:
    sub: str
    email: str
    token: str
    user_id: str

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url=BASE_URL, timeout=60.0, headers={"Authorization": f"Bearer {self.token}"}
        )


def create_user(conn: Any, *, admin: bool = False) -> BillingUser:
    """A brand-new signed-in user, created the product's own way: the first
    authenticated call upserts the `users` row (get_or_create_user)."""
    tag = uuid.uuid4().hex[:12]
    sub = f"auth0|e2e-billing-{tag}"
    email = f"e2e+billing-{tag}@jvn.test"
    token = mint_token(custom_user(sub, email))
    resp = httpx.get(f"{BASE_URL}{SUBSCRIPTION}", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    assert resp.status_code == 200, f"first sign-in call failed: {resp.status_code} {resp.text[:300]}"
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        assert row, f"GET {SUBSCRIPTION} did not create a users row for {email}"
        user_id = row["id"]
        if admin:
            cur.execute("INSERT INTO admins (user_id) VALUES (%s)", (user_id,))
    return BillingUser(sub=sub, email=email, token=token, user_id=user_id)


@pytest.fixture()
def new_user(conn: Any) -> Callable[..., BillingUser]:
    def make(*, admin: bool = False) -> BillingUser:
        return create_user(conn, admin=admin)

    return make


# --- Test clocks -------------------------------------------------------------


@pytest.fixture()
def clocked(sc: stripe.StripeClient, request: pytest.FixtureRequest) -> Iterator[Callable[[BillingUser], stripe_env.ClockedSubscription]]:
    """`clocked(user)` -> a paid $6/month subscription on its own test clock.
    Every clock made here is deleted at the end of the case, taking its
    customer and subscription with it."""
    made: list[str] = []

    def make(user: BillingUser) -> stripe_env.ClockedSubscription:
        s = stripe_env.subscribe_on_clock(
            sc, user_id=user.user_id, email=user.email, label=_sanitize(request.node.name)[:40]
        )
        made.append(s.clock_id)
        return s

    yield make
    for clock_id in made:
        try:
            sc.v1.test_helpers.test_clocks.delete(clock_id)
        except stripe.StripeError:
            pass  # run.sh's cleanup sweeps anything named e2e-billing-*


# --- Reads + waits ------------------------------------------------------------


def sub_row(conn: Any, user_id: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM user_subscriptions WHERE user_id = %s", (user_id,))
        return cur.fetchone()


def subscription_api(user: BillingUser) -> dict[str, Any]:
    with user.client() as c:
        resp = c.get(SUBSCRIPTION)
    assert resp.status_code == 200, f"GET {SUBSCRIPTION}: {resp.status_code} {resp.text[:300]}"
    return resp.json()


def wait_until(fetch: Callable[[], T], ok: Callable[[T], bool], what: str, timeout: float = WEBHOOK_WAIT_S) -> T:
    """Poll `fetch` until `ok(value)`; on timeout fail naming the step and the
    last value seen (PLAN.md: name the step, not the assertion)."""
    deadline = time.monotonic() + timeout
    value = fetch()
    while not ok(value):
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout:.0f}s waiting for: {what}. Last value: {value!r}")
        time.sleep(1.0)
        value = fetch()
    return value


def wait_for_row(conn: Any, user_id: str, ok: Callable[[dict[str, Any]], bool], what: str, timeout: float = WEBHOOK_WAIT_S) -> dict[str, Any]:
    row = wait_until(lambda: sub_row(conn, user_id), lambda r: r is not None and ok(r), what, timeout)
    assert row is not None
    return row


def parse_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


# --- Webhook signing (BL-13..15) ----------------------------------------------


def sign(payload: bytes, *, secret: str | None = None, timestamp: int | None = None) -> str:
    """A `Stripe-Signature` header exactly as Stripe builds it (v1 = HMAC-SHA256
    of "<t>.<payload>"), with the real secret unless told otherwise."""
    secret = secret if secret is not None else os.environ["STRIPE_WEBHOOK_SECRET"]
    ts = timestamp if timestamp is not None else int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def post_webhook(payload: bytes, signature: str | None) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["Stripe-Signature"] = signature
    return httpx.post(f"{BASE_URL}{WEBHOOK}", content=payload, headers=headers, timeout=30)


def event_payload(sc: stripe.StripeClient, event_id: str) -> dict[str, Any]:
    """A real event's JSON, exactly as Stripe serves it."""
    return json.loads(sc.raw_request("get", f"/v1/events/{event_id}").body)


def find_event(sc: stripe.StripeClient, event_type: str, object_id: str, timeout: float = WEBHOOK_WAIT_S) -> str:
    """The id of the `event_type` event whose data.object is `object_id`."""

    def fetch() -> str | None:
        for ev in sc.v1.events.list(params={"type": event_type, "limit": 50}).data:
            if ev.data.object["id"] == object_id:
                return ev.id
        return None

    found = wait_until(fetch, lambda v: v is not None, f"{event_type} for {object_id} in the event log", timeout)
    assert found is not None
    return found


# --- Artifacts ------------------------------------------------------------------


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    d = CASES_DIR / _sanitize(item.name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "step.txt").write_text(str(report.longrepr), encoding="utf-8")
