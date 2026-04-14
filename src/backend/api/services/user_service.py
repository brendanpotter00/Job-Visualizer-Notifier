"""User CRUD operations."""

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
    """Insert a new user or update token-sourced fields on email conflict.

    Email (verified by the identity provider) is the stable human identifier;
    ``auth0_id`` tracks the most recent login provider's subject. This lets a
    single human log in via Auth0 and Google One Tap without creating duplicate
    rows. ``display_name`` is intentionally excluded from the SET clause so
    user customizations persist across provider switches.
    """
    table = sql.Identifier(_get_table_name(env, "users"))
    now = datetime.now(timezone.utc).isoformat()
    user_id = uuid.uuid4().hex
    cursor = conn.cursor()
    try:
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (id, auth0_id, email, given_name, family_name, picture_url, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (email) DO UPDATE SET"
                "   auth0_id = EXCLUDED.auth0_id, given_name = EXCLUDED.given_name,"
                "   family_name = EXCLUDED.family_name, picture_url = EXCLUDED.picture_url,"
                "   updated_at = EXCLUDED.updated_at"
                " RETURNING *"
            ).format(table),
            (user_id, auth0_id, email, given_name, family_name, picture_url, now, now),
        )
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in get_or_create_user for auth0_id=%s: %s",
            auth0_id,
            exc,
            exc_info=True,
        )
        raise
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"User upsert returned no rows for auth0_id={auth0_id}")
    return dict(row)


def update_user(
    conn: Connection,
    env: str,
    auth0_id: str,
    display_name: str | None = None,
) -> dict | None:
    """Update a user's display name."""
    table = sql.Identifier(_get_table_name(env, "users"))
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()
    try:
        cursor.execute(
            sql.SQL(
                "UPDATE {} SET display_name = %s, updated_at = %s WHERE auth0_id = %s RETURNING *"
            ).format(table),
            (display_name, now, auth0_id),
        )
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in update_user for auth0_id=%s: %s",
            auth0_id,
            exc,
            exc_info=True,
        )
        raise
    row = cursor.fetchone()
    return dict(row) if row else None
