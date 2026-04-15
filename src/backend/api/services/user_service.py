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

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

from scripts.shared.database import _get_table_name

logger = logging.getLogger(__name__)


def get_or_create_user(
    conn: Connection,
    env: str,
    auth0_id: str,
    email: str,
    given_name: str | None = None,
    family_name: str | None = None,
    picture_url: str | None = None,
) -> dict:
    """Upsert a user via a two-key identity lookup.

    Looks up by ``auth0_id OR email``, then UPDATE or INSERT. ``display_name``
    is never overwritten — user customizations persist across provider switches.

    Raises ``RuntimeError`` if the lookup matches more than one row (ambiguous
    identity). Retries once on ``UniqueViolation`` to tolerate concurrent
    first-login races.
    """
    table = sql.Identifier(_get_table_name(env, "users"))

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
) -> dict:
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
    return dict(row)


def update_user(
    conn: Connection,
    env: str,
    email: str,
    display_name: str | None = None,
) -> dict | None:
    """Update a user's display name, keyed by email (the stable identifier).

    Returns ``None`` if no user matches the email.
    """
    table = sql.Identifier(_get_table_name(env, "users"))
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
    return dict(row) if row else None
