"""Per-user company selection preferences."""

import logging

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)

_TABLE = sql.Identifier("user_enabled_companies")


def list_enabled_companies(conn: Connection, user_id: str) -> list[str]:
    """Return the company IDs this user has enabled, sorted alphabetically."""
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL("SELECT company_id FROM {} WHERE user_id = %s ORDER BY company_id").format(
            _TABLE
        ),
        (user_id,),
    )
    return [row["company_id"] for row in cursor.fetchall()]


def set_enabled_companies(
    conn: Connection, user_id: str, company_ids: list[str]
) -> list[str]:
    """Replace a user's enabled-companies set. Returns the canonicalized list.

    DELETE-then-INSERT in a single transaction; rolls back on any DB error.
    Canonicalizes input by deduping and sorting so the round-trip is stable.
    """
    canonical = sorted(set(company_ids))
    cursor = conn.cursor()
    table = _TABLE
    try:
        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE user_id = %s").format(table),
            (user_id,),
        )
        if canonical:
            cursor.executemany(
                sql.SQL("INSERT INTO {} (user_id, company_id) VALUES (%s, %s)").format(table),
                [(user_id, cid) for cid in canonical],
            )
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in set_enabled_companies for user_id=%s: %s",
            user_id,
            exc,
            exc_info=True,
        )
        raise
    return canonical
