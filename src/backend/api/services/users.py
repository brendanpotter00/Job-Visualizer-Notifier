"""User database functions.

Manages the users table for OAuth authentication.
Uses generic provider/provider_id columns to support multiple OAuth providers.
"""

import logging

from scripts.shared.database import Connection

logger = logging.getLogger(__name__)


def init_users_schema(conn: Connection) -> None:
    """Create the users table and indexes if they don't exist."""
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                provider TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                picture TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(provider, provider_id)
            );
            CREATE INDEX IF NOT EXISTS idx_users_provider_id ON users(provider, provider_id);
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        """)
    conn.commit()
    logger.info("Users schema initialized")


def find_or_create_user(
    conn: Connection,
    provider: str,
    provider_id: str,
    email: str,
    name: str,
    picture: str | None,
) -> dict:
    """Find a user by provider/provider_id, or create one. Updates profile on re-login."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM users WHERE provider = %s AND provider_id = %s",
            (provider, provider_id),
        )
        row = cursor.fetchone()

        if row:
            cursor.execute(
                """UPDATE users SET name = %s, picture = %s, updated_at = NOW()
                   WHERE id = %s RETURNING *""",
                (name, picture, row["id"]),
            )
            row = cursor.fetchone()
        else:
            cursor.execute(
                """INSERT INTO users (provider, provider_id, email, name, picture)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (provider, provider_id, email, name, picture),
            )
            row = cursor.fetchone()

    conn.commit()
    return dict(row)


def get_user_by_id(conn: Connection, user_id: int) -> dict | None:
    """Get a user by ID."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
