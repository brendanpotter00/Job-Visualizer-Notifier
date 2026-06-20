"""User CRUD operations.

Identity model: ``auth0_id`` and ``email`` are both UNIQUE. The upsert uses a
two-key SELECT lookup (match by either) so that:

* Cross-provider merge (same email, different auth0_id) → matches by email →
  UPDATE sets new auth0_id.
* IdP email change (same auth0_id, different email) → matches by auth0_id →
  UPDATE sets new email.
* Brand-new user → no match → INSERT.

If both keys match different rows, the identity model is corrupted; we raise
``RuntimeError`` rather than silently merging two humans into one row.

See ``docs/implementations/auth0/REVIEW_AUDIT.md`` "2026-04-14 — Design reversal".
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import TypedDict, cast

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)

_USERS_TABLE = sql.Identifier("users")


class UserRow(TypedDict):
    """Shape of a ``users`` row as returned by the service layer.

    Mirrors the columns declared in ``db_models.User``. The ``auth0_id``
    column name is historical — it tracks the most recent identity
    provider's subject (Auth0 ``sub`` or Google-prefixed One Tap ``sub``),
    not just Auth0 specifically. See ``models.UserResponse`` for the
    API-boundary rename to ``provider_subject``.

    Threaded through ``_row_to_user_response`` in ``routers/users.py`` so
    a column rename in ``db_models`` becomes a mypy/pyright error at the
    router's row-key reads rather than a runtime ``KeyError`` on the
    next request.
    """

    id: str
    auth0_id: str
    email: str
    display_name: str | None
    given_name: str | None
    family_name: str | None
    picture_url: str | None
    created_at: str
    updated_at: str
    company_enroll_watermark: datetime
    auto_enroll_new_companies: bool


def get_or_create_user(
    conn: Connection,
    auth0_id: str,
    email: str,
    given_name: str | None = None,
    family_name: str | None = None,
    picture_url: str | None = None,
) -> UserRow:
    """Upsert a user via a two-key identity lookup.

    Looks up by ``auth0_id OR email``, then UPDATE or INSERT. ``display_name``
    is never overwritten — user customizations persist across provider switches.

    Raises ``RuntimeError`` if the lookup matches more than one row (ambiguous
    identity). Retries once on ``UniqueViolation`` to tolerate concurrent
    first-login races.
    """
    table = _USERS_TABLE

    for attempt in range(2):
        try:
            return _lookup_and_upsert(
                conn, table, auth0_id, email, given_name, family_name, picture_url
            )
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            if attempt == 0:
                # Concurrent first-login race: another transaction inserted the
                # row between our SELECT and INSERT. Retry the SELECT to match it.
                logger.info(
                    "UniqueViolation on user upsert for auth0_id=%s; retrying "
                    "(concurrent first-login race)",
                    auth0_id,
                )
                continue
            logger.error(
                "UniqueViolation on user upsert for auth0_id=%s persisted after retry",
                auth0_id,
            )
            raise
        except psycopg2.Error as exc:
            conn.rollback()
            logger.error(
                "Database error in get_or_create_user for auth0_id=%s: %s",
                auth0_id,
                exc,
                exc_info=True,
            )
            raise

    # Unreachable: the loop either returns or raises on every iteration.
    raise RuntimeError("get_or_create_user retry loop exhausted without result")


def _lookup_and_upsert(
    conn: Connection,
    table: sql.Identifier,
    auth0_id: str,
    email: str,
    given_name: str | None,
    family_name: str | None,
    picture_url: str | None,
) -> UserRow:
    """SELECT by either key, then UPDATE or INSERT. Raises on ambiguous match."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()

    cursor.execute(
        sql.SQL("SELECT id FROM {} WHERE auth0_id = %s OR email = %s").format(table),
        (auth0_id, email),
    )
    matches = cursor.fetchall()

    if len(matches) > 1:
        raise RuntimeError(
            f"Ambiguous identity: auth0_id={auth0_id!r} and email={email!r} "
            f"map to {len(matches)} different rows. Identity model corrupted."
        )

    if matches:
        row_id = matches[0]["id"]
        cursor.execute(
            sql.SQL(
                "UPDATE {} SET auth0_id = %s, email = %s, given_name = %s,"
                " family_name = %s, picture_url = %s, updated_at = %s"
                " WHERE id = %s RETURNING *"
            ).format(table),
            (auth0_id, email, given_name, family_name, picture_url, now, row_id),
        )
    else:
        user_id = uuid.uuid4().hex
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (id, auth0_id, email, given_name, family_name,"
                " picture_url, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *"
            ).format(table),
            (
                user_id,
                auth0_id,
                email,
                given_name,
                family_name,
                picture_url,
                now,
                now,
            ),
        )

    conn.commit()
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(
            f"User upsert returned no rows for auth0_id={auth0_id}"
        )
    return cast(UserRow, dict(row))


def update_user(
    conn: Connection,
    email: str,
    display_name: str | None = None,
) -> UserRow | None:
    """Update a user's display name, keyed by email (the stable identifier).

    Returns ``None`` if no user matches the email.
    """
    table = _USERS_TABLE
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()
    try:
        cursor.execute(
            sql.SQL(
                "UPDATE {} SET display_name = %s, updated_at = %s"
                " WHERE email = %s RETURNING *"
            ).format(table),
            (display_name, now, email),
        )
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in update_user for email=%s: %s",
            email,
            exc,
            exc_info=True,
        )
        raise
    row = cursor.fetchone()
    return cast(UserRow, dict(row)) if row else None


def get_user_by_email(
    conn: Connection,
    email: str,
) -> UserRow | None:
    """Fetch a user row by email. Returns ``None`` if not found.

    Return type is the typed ``UserRow`` (not raw ``dict``) so callers
    that read ``row["id"]`` / etc. surface a column rename in
    ``db_models.User`` as a mypy/pyright error at the read site instead
    of a runtime ``KeyError`` on the next request. Matches the threading
    done for ``get_or_create_user`` / ``update_user`` in pass 2.
    """
    table = _USERS_TABLE
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL("SELECT * FROM {} WHERE email = %s").format(table),
        (email,),
    )
    row = cursor.fetchone()
    return cast(UserRow, dict(row)) if row else None
