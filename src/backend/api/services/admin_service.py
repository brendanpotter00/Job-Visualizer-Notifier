"""Admin grant + admin-scoped query helpers.

Admin status is a relationship row in the ``admins`` table (FK to ``users.id``),
not a column on ``users``. This keeps the user identity model lean and lets
admin grants grow audit metadata or scoped capability columns over time
without a re-migration of every user row.
"""

import logging

from psycopg2 import sql
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)

_ADMINS = sql.Identifier("admins")
_USERS = sql.Identifier("users")


def is_admin_by_email(conn: Connection, email: str) -> bool:
    """Return True iff a user with this email has an admin grant."""
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "SELECT EXISTS ("
            "  SELECT 1 FROM {admins} a"
            "  JOIN {users} u ON u.id = a.user_id"
            "  WHERE u.email = %s"
            ")"
        ).format(admins=_ADMINS, users=_USERS),
        (email,),
    )
    row = cursor.fetchone()
    if row is None:
        return False
    value = row[0] if not isinstance(row, dict) else next(iter(row.values()))
    return bool(value)


def _signup_provider_from_auth0_id(auth0_id: str) -> str:
    """Derive the human-readable signup provider from the auth0_id prefix.

    Mapping is driven by the JWT issuer routing in ``api/auth/jwt.py``:
    Google One Tap tokens are stored as ``google|*``, Auth0-federated Google
    OAuth tokens as ``google-oauth2|*``, and Auth0 email/password users as
    ``auth0|*``.
    """
    prefix = auth0_id.split("|", 1)[0] if "|" in auth0_id else auth0_id
    if prefix in ("google", "google-oauth2"):
        return "google"
    if prefix == "auth0":
        return "email"
    return "other"


def list_users_with_admin_flag(conn: Connection) -> list[dict]:
    """Return every user with a derived signup_provider and is_admin flag."""
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "SELECT u.id, u.email, u.display_name, u.auth0_id, u.created_at,"
            " (a.user_id IS NOT NULL) AS is_admin"
            " FROM {users} u"
            " LEFT JOIN {admins} a ON a.user_id = u.id"
            " ORDER BY u.created_at DESC"
        ).format(users=_USERS, admins=_ADMINS),
    )
    rows = cursor.fetchall()
    return [
        {
            "id": r["id"],
            "email": r["email"],
            "display_name": r.get("display_name"),
            "signup_provider": _signup_provider_from_auth0_id(r["auth0_id"]),
            "created_at": r["created_at"],
            "is_admin": bool(r["is_admin"]),
        }
        for r in rows
    ]


def get_users_stats(conn: Connection) -> dict:
    """Aggregate stats for the admin dashboard.

    Returns total user count, earliest and latest ``created_at`` strings, and
    per-provider counts. ``created_at`` is stored as ISO-8601 ``Text`` so the
    MIN/MAX comparison is lexicographic — safe because ISO-8601 sorts
    chronologically.
    """
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "SELECT COUNT(*) AS total,"
            " MIN(created_at) AS first_signup,"
            " MAX(created_at) AS latest_signup"
            " FROM {users}"
        ).format(users=_USERS),
    )
    agg = cursor.fetchone()
    total = int(agg["total"]) if agg else 0
    first_signup = agg["first_signup"] if agg else None
    latest_signup = agg["latest_signup"] if agg else None

    cursor.execute(
        sql.SQL("SELECT auth0_id FROM {users}").format(users=_USERS),
    )
    by_provider: dict[str, int] = {}
    for row in cursor.fetchall():
        provider = _signup_provider_from_auth0_id(row["auth0_id"])
        by_provider[provider] = by_provider.get(provider, 0) + 1

    return {
        "total_users": total,
        "first_signup_at": first_signup,
        "latest_signup_at": latest_signup,
        "by_provider": by_provider,
    }
