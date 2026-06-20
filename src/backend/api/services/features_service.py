"""Feature voting service backed by the bare-named ``features`` and
``feature_upvotes`` tables.

Idempotency:
- ``add_upvote`` uses ``INSERT ... ON CONFLICT DO NOTHING`` on the composite
  PK, so double-POST is a no-op.
- ``remove_upvote`` uses ``DELETE``, naturally idempotent.

Both mutations raise ``FeatureNotFound`` when the given ``feature_id`` does
not exist, before touching the upvote table.
"""

import logging
from typing import Any

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)


class FeatureNotFound(Exception):
    """Raised when an upvote mutation targets a feature_id that doesn't exist."""


_FEATURES = sql.Identifier("features")
_UPVOTES = sql.Identifier("feature_upvotes")


def list_features_with_upvotes(
    conn: Connection, user_id: str | None
) -> list[dict]:
    cursor = conn.cursor()

    if user_id is None:
        cursor.execute(
            sql.SQL(
                "SELECT f.id, f.title, f.description, f.created_at,"
                "       COUNT(u.user_id) AS upvote_count,"
                "       FALSE AS has_upvoted"
                " FROM {features} AS f"
                " LEFT JOIN {upvotes} AS u ON u.feature_id = f.id"
                " GROUP BY f.id"
                " ORDER BY f.created_at ASC, f.id ASC"
            ).format(features=_FEATURES, upvotes=_UPVOTES)
        )
    else:
        cursor.execute(
            sql.SQL(
                "SELECT f.id, f.title, f.description, f.created_at,"
                "       COUNT(u.user_id) AS upvote_count,"
                "       BOOL_OR(u.user_id = %s) AS has_upvoted"
                " FROM {features} AS f"
                " LEFT JOIN {upvotes} AS u ON u.feature_id = f.id"
                " GROUP BY f.id"
                " ORDER BY f.created_at ASC, f.id ASC"
            ).format(features=_FEATURES, upvotes=_UPVOTES),
            (user_id,),
        )
    rows = cursor.fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"],
            "created_at": row["created_at"],
            "upvote_count": int(row["upvote_count"]),
            "has_upvoted": bool(row["has_upvoted"]) if row["has_upvoted"] is not None else False,
        }
        for row in rows
    ]


def _feature_exists(cursor: Any, feature_id: str) -> bool:
    cursor.execute(
        sql.SQL("SELECT 1 FROM {} WHERE id = %s").format(_FEATURES),
        (feature_id,),
    )
    return cursor.fetchone() is not None


def _count_upvotes(cursor: Any, feature_id: str) -> int:
    cursor.execute(
        sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE feature_id = %s").format(_UPVOTES),
        (feature_id,),
    )
    return int(cursor.fetchone()["n"])


def add_upvote(conn: Connection, feature_id: str, user_id: str) -> dict:
    cursor = conn.cursor()
    try:
        if not _feature_exists(cursor, feature_id):
            raise FeatureNotFound(feature_id)
        cursor.execute(
            sql.SQL(
                "INSERT INTO {} (feature_id, user_id)"
                " VALUES (%s, %s)"
                " ON CONFLICT (feature_id, user_id) DO NOTHING"
            ).format(_UPVOTES),
            (feature_id, user_id),
        )
        count = _count_upvotes(cursor, feature_id)
        conn.commit()
    except FeatureNotFound:
        conn.rollback()
        raise
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in add_upvote for feature_id=%s user_id=%s: %s",
            feature_id, user_id, exc, exc_info=True,
        )
        raise
    return {"feature_id": feature_id, "upvote_count": count, "has_upvoted": True}


def remove_upvote(conn: Connection, feature_id: str, user_id: str) -> dict:
    cursor = conn.cursor()
    try:
        if not _feature_exists(cursor, feature_id):
            raise FeatureNotFound(feature_id)
        cursor.execute(
            sql.SQL(
                "DELETE FROM {} WHERE feature_id = %s AND user_id = %s"
            ).format(_UPVOTES),
            (feature_id, user_id),
        )
        count = _count_upvotes(cursor, feature_id)
        conn.commit()
    except FeatureNotFound:
        conn.rollback()
        raise
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error in remove_upvote for feature_id=%s user_id=%s: %s",
            feature_id, user_id, exc, exc_info=True,
        )
        raise
    return {"feature_id": feature_id, "upvote_count": count, "has_upvoted": False}
