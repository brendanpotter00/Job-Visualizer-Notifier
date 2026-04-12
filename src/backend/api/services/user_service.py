"""User CRUD operations."""

import uuid
from datetime import datetime, timezone

from psycopg2 import sql
from psycopg2.extensions import connection as Connection

from scripts.shared.database import _get_table_name


def get_or_create_user(
    conn: Connection,
    env: str,
    auth0_id: str,
    email: str,
    given_name: str | None = None,
    family_name: str | None = None,
    picture_url: str | None = None,
) -> dict:
    """Insert a new user or update token-sourced fields on conflict."""
    table = sql.Identifier(_get_table_name(env, "users"))
    now = datetime.now(timezone.utc).isoformat()
    user_id = uuid.uuid4().hex
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, given_name, family_name, picture_url, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (auth0_id) DO UPDATE SET"
            "   email = EXCLUDED.email, given_name = EXCLUDED.given_name,"
            "   family_name = EXCLUDED.family_name, picture_url = EXCLUDED.picture_url,"
            "   updated_at = EXCLUDED.updated_at"
            " RETURNING *"
        ).format(table),
        (user_id, auth0_id, email, given_name, family_name, picture_url, now, now),
    )
    conn.commit()
    return dict(cursor.fetchone())


def get_user_by_auth0_id(conn: Connection, env: str, auth0_id: str) -> dict | None:
    """Look up a user by their Auth0 ID."""
    table = sql.Identifier(_get_table_name(env, "users"))
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL("SELECT * FROM {} WHERE auth0_id = %s").format(table), (auth0_id,)
    )
    row = cursor.fetchone()
    return dict(row) if row else None


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
    cursor.execute(
        sql.SQL(
            "UPDATE {} SET display_name = %s, updated_at = %s WHERE auth0_id = %s RETURNING *"
        ).format(table),
        (display_name, now, auth0_id),
    )
    conn.commit()
    row = cursor.fetchone()
    return dict(row) if row else None
