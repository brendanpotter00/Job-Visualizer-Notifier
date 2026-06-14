"""User-feedback service backed by the bare-named ``feedback`` table.

``submit_feedback`` INSERTs one row (anonymous when ``user_id`` is None) and
returns it. ``list_feedback`` returns rows newest-first for the admin surface.
Mirrors the psycopg2 + ``sql.Identifier`` style of ``features_service.py``.
"""

import logging
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)

_FEEDBACK = sql.Identifier("feedback")


def submit_feedback(
    conn: Connection,
    message: str,
    user_id: str | None,
    user_email: str | None,
    display_name: str | None,
) -> dict:
    """Insert one feedback row and return it.

    ``user_id``/``user_email``/``display_name`` are all None for anonymous
    submissions. When set, they are a point-in-time snapshot of the submitter
    (resolved by the router via ``get_or_create_user``). ``id`` is a uuid hex and
    ``created_at`` comes from the server default — both come back via RETURNING.
    """
    feedback_id = uuid.uuid4().hex
    cursor = conn.cursor()
    try:
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (id, message, user_id, user_email, display_name)"
                " VALUES (%s, %s, %s, %s, %s)"
                " RETURNING id, message, user_id, user_email, display_name,"
                "           created_at"
            ).format(_FEEDBACK),
            (feedback_id, message, user_id, user_email, display_name),
        )
        row = cursor.fetchone()
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in submit_feedback (user_id=%s): %s",
            user_id, exc, exc_info=True,
        )
        raise
    return dict(row)


# Allowlisted sort directions composed straight into the ORDER BY. The raw
# ``sort_dir`` string is NEVER interpolated — it only selects a fixed keyword,
# so there's no SQL-injection surface even though the value originates from a
# query param.
_SORT_DIRECTIONS = {"asc": sql.SQL("ASC"), "desc": sql.SQL("DESC")}


def list_feedback(
    conn: Connection, limit: int, offset: int, sort_dir: str = "desc"
) -> list[dict]:
    """Return feedback rows ordered by ``created_at`` (``sort_dir``), paginated.

    Read-only: no commit. The secondary ``id`` tiebreaker (same direction) is
    stable for rows sharing a ``created_at`` (same-transaction inserts). An
    unrecognized ``sort_dir`` falls back to newest-first.
    """
    direction = _SORT_DIRECTIONS.get(sort_dir, _SORT_DIRECTIONS["desc"])
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "SELECT id, message, user_id, user_email, display_name, created_at"
            " FROM {table}"
            " ORDER BY created_at {dir}, id {dir}"
            " LIMIT %s OFFSET %s"
        ).format(table=_FEEDBACK, dir=direction),
        (limit, offset),
    )
    rows = cursor.fetchall()
    return [dict(r) for r in rows]


def count_feedback(conn: Connection) -> int:
    """Return the total number of feedback rows (read-only, no commit).

    Used by the admin list endpoint to drive server-side pagination — the page
    of rows from ``list_feedback`` plus this total lets the UI page through
    everything instead of being capped at a single fetched slice.
    """
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL("SELECT COUNT(*) AS total FROM {}").format(_FEEDBACK)
    )
    row = cursor.fetchone()
    return int(row["total"])
