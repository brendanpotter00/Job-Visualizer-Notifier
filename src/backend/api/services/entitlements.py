"""Who is Pro right now. ``is_pro()`` is the one rule."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from psycopg2.extensions import connection as Connection

from .admin_service import is_admin_by_email
from .billing_service import SubscriptionRow, get_subscription

# A failed renewal keeps Pro this long while Stripe retries the card.
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


def is_pro(conn: Connection, user_id: str, email: str) -> bool:
    """True iff this user gets Pro features right now. Admins always do."""
    return is_admin_by_email(conn, email) or is_pro_row(get_subscription(conn, user_id))
