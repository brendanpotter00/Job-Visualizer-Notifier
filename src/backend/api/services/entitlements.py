"""Who is Pro right now, and the responses that send everyone else to /pricing.

``is_pro()`` is the ONE rule. The future MCP rate limiter calls it per request,
so it is a single primary-key read (``user_subscriptions.user_id``) plus the
admin lookup the add quota already does. ``rate_limited_response()`` is the 429
that limiter will return; it exists now so its shape is pinned by a test before
anything depends on it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, get_current_user
from ..config import settings
from ..dependencies import get_db
from .admin_service import is_admin_by_email
from .billing_service import SubscriptionRow, get_subscription
from .user_service import get_user_by_email

# How long a user whose renewal failed keeps Pro while Stripe retries the card.
# After this they are Free ("lapsed") until a payment goes through; Stripe keeps
# retrying in the background, and a successful retry restores Pro at once.
PAST_DUE_GRACE = timedelta(days=3)

_PAID_STATUSES = frozenset({"active", "trialing"})


def grace_ends_at(row: SubscriptionRow | None) -> datetime | None:
    if not row or row["status"] != "past_due" or not row["past_due_since"]:
        return None
    return row["past_due_since"] + PAST_DUE_GRACE


def is_pro_row(row: SubscriptionRow | None, *, now: datetime | None = None) -> bool:
    """The entitlement rule on a row alone (no admin exemption)."""
    if not row or row["plan"] != "pro":
        return False
    if row["status"] in _PAID_STATUSES:
        return True
    ends = grace_ends_at(row)
    if ends is None:
        return False
    return (now or datetime.now(timezone.utc)) < ends


def is_pro(
    conn: Connection,
    user_id: str,
    email: str | None = None,
    *,
    now: datetime | None = None,
) -> bool:
    """True iff this user gets Pro features right now.

    Admins always do — the same exemption ``add_quota`` gives them. The admin
    lookup raises on a driver error rather than silently denying (see
    ``is_admin_by_email``).
    """
    if email and is_admin_by_email(conn, email):
        return True
    return is_pro_row(get_subscription(conn, user_id), now=now)


def upgrade_url(reason: str | None = None) -> str:
    # Relative when the origin is unset (local dev without billing): still a
    # usable link for a browser, and never a wrong absolute host.
    base = f"{(settings.public_app_url or '').rstrip('/')}/pricing"
    return f"{base}?reason={reason}" if reason else base


async def require_pro(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> TokenClaims:
    """Route dependency: 402 with the pricing link unless the caller is Pro."""
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    row = get_user_by_email(conn, email)
    if row is None or not is_pro(conn, row["id"], email):
        raise HTTPException(
            status_code=402,
            detail={"error": "pro_required", "upgradeUrl": upgrade_url("pro_required")},
        )
    return user


def rate_limited_response(*, limit: int, window: str, resets_at: datetime) -> JSONResponse:
    """The 429 a free user gets past the MCP limit. Links to /pricing three ways.

    ``upgradeUrl`` in the body (for an agent reading JSON), a ``Link`` header with
    ``rel="payment"`` (for a client that follows links), and ``Retry-After`` so a
    well-behaved client backs off until the window resets.
    """
    url = upgrade_url("mcp_limit")
    resets_at = resets_at.astimezone(timezone.utc)
    retry_after = max(0, int((resets_at - datetime.now(timezone.utc)).total_seconds()))
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limited",
            "plan": "free",
            "limit": limit,
            "window": window,
            "resetsAt": resets_at.isoformat().replace("+00:00", "Z"),
            "upgradeUrl": url,
        },
        headers={
            "Retry-After": str(retry_after),
            "Link": f'<{url}>; rel="payment"',
        },
    )
