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


class LastAdminError(Exception):
    """Raised when revoking would leave the platform with zero admins.

    The router translates this to a 409 — distinct from a 400 self-revoke,
    because two admins acting concurrently could each pass the self-check
    and try to revoke the other, leaving zero admins with no API-level
    recovery path. The ``FOR UPDATE`` lock in ``revoke_admin`` serializes
    these and lets exactly one win.
    """


def is_admin_by_email(conn: Connection, email: str) -> bool:
    """Return True iff a user with this email has an admin grant.

    ``SELECT EXISTS (...)`` always returns exactly one row containing a single
    boolean. A ``None`` result would mean the cursor itself misbehaved, which
    is a driver bug — not a "user is not an admin." We deliberately let that
    raise rather than silently denying admin to a legitimate caller (per the
    "correctness over don't crash" rule in the project memory).
    """
    with conn.cursor() as cursor:
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
        # RealDictCursor (configured in dependencies.init_pool) returns a
        # ``RealDictRow`` keyed by the column name. The unaliased EXISTS column
        # is named ``exists`` by Postgres.
        row = cursor.fetchone()
    return bool(row["exists"])


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
    with conn.cursor() as cursor:
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


def grant_admin(conn: Connection, user_id: str, granted_by_id: str | None) -> bool:
    """Insert an admin grant for ``user_id``.

    Idempotent — ``ON CONFLICT DO NOTHING`` so a re-grant is a no-op. Returns
    True if a row was inserted, False if the user already had a grant.
    Raises ``psycopg2.errors.ForeignKeyViolation`` if ``user_id`` does not
    exist in ``users`` — callers translate that to a 404 at the HTTP layer.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "INSERT INTO {admins} (user_id, granted_by)"
                " VALUES (%s, %s)"
                " ON CONFLICT (user_id) DO NOTHING"
            ).format(admins=_ADMINS),
            (user_id, granted_by_id),
        )
        inserted = cursor.rowcount == 1
    conn.commit()
    return inserted


def revoke_admin(conn: Connection, user_id: str) -> bool:
    """Delete an admin grant for ``user_id``.

    Idempotent — returns False if the user wasn't an admin, True if a row
    was deleted.

    Last-admin guardrail: runs inside an explicit transaction with a
    ``SELECT ... FOR UPDATE`` lock over ``admins``. If the table holds
    exactly one row AND that row is the target, raises ``LastAdminError``
    rather than DELETE — two admins racing to revoke each other would
    otherwise both pass the router-level self-revoke check and leave zero
    admins. Idempotent revoke of a non-admin still returns False (the row
    doesn't exist; nothing to lock against).
    """
    try:
        with conn.cursor() as cursor:
            # Lock the entire ``admins`` table for the duration of this
            # transaction. ``FOR UPDATE`` on the selected rows blocks any
            # concurrent revoke from seeing a stale count.
            cursor.execute(
                sql.SQL(
                    "SELECT user_id FROM {admins} FOR UPDATE"
                ).format(admins=_ADMINS),
            )
            rows = cursor.fetchall()
            admin_ids = [r["user_id"] for r in rows]

            if user_id in admin_ids and len(admin_ids) == 1:
                # Target IS the last admin — bail out before the DELETE.
                # The router translates this to a 409.
                raise LastAdminError(
                    "Cannot revoke the last admin grant"
                )

            cursor.execute(
                sql.SQL("DELETE FROM {admins} WHERE user_id = %s").format(
                    admins=_ADMINS
                ),
                (user_id,),
            )
            deleted = cursor.rowcount == 1
        conn.commit()
        return deleted
    except LastAdminError:
        # Release the row locks; the transaction holds no other writes.
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise


def get_users_stats(conn: Connection) -> dict:
    """Aggregate stats for the admin dashboard.

    Returns total user count, earliest and latest ``created_at`` strings, and
    per-provider counts. ``created_at`` is stored as ISO-8601 ``Text`` so the
    MIN/MAX comparison is lexicographic — safe because ISO-8601 sorts
    chronologically.

    ``COUNT(*)`` and ``MIN``/``MAX`` always return exactly one aggregate row,
    so the ``fetchone()`` result is never ``None``. We index directly into it
    rather than guarding with ``if agg else 0`` — that branch would swallow a
    driver-state bug as "zero users" and quietly break the admin dashboard.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "SELECT COUNT(*) AS total,"
                " MIN(created_at) AS first_signup,"
                " MAX(created_at) AS latest_signup"
                " FROM {users}"
            ).format(users=_USERS),
        )
        agg = cursor.fetchone()
        # Per-provider counts pulled in a separate query because the provider
        # mapping (auth0|… → "email", google[-oauth2]|… → "google") lives in
        # ``_signup_provider_from_auth0_id`` and is exercised by tests there.
        # Pushing it into SQL would duplicate the mapping in two places.
        cursor.execute(
            sql.SQL("SELECT auth0_id FROM {users}").format(users=_USERS),
        )
        provider_rows = cursor.fetchall()

    total = int(agg["total"])
    first_signup = agg["first_signup"]
    latest_signup = agg["latest_signup"]

    by_provider: dict[str, int] = {}
    for row in provider_rows:
        provider = _signup_provider_from_auth0_id(row["auth0_id"])
        by_provider[provider] = by_provider.get(provider, 0) + 1

    return {
        "total_users": total,
        "first_signup_at": first_signup,
        "latest_signup_at": latest_signup,
        "by_provider": by_provider,
    }
