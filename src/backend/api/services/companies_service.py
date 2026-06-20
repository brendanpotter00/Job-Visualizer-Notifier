"""Read-only query backing the public Curated Companies directory.

Distinct from ``scripts.shared.database.list_enabled_companies`` (which is
ats-scoped for the worker fan-out) — this returns EVERY enabled company with its
directory content, alphabetically by display name.
"""

import logging

from psycopg2 import sql
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)

_COMPANIES_TABLE = sql.Identifier("companies")


def list_enabled_companies_with_profiles(conn: Connection) -> list[dict]:
    """All enabled companies + directory content, sorted by display name.

    Ordered case-insensitively (``lower(display_name)``) with ``id`` as a stable
    tiebreaker so the alphabetical listing is deterministic.
    """
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL(
            "SELECT id, display_name, ats, blurb, accomplishment"
            " FROM {}"
            " WHERE enabled = TRUE"
            " ORDER BY lower(display_name) ASC, id ASC"
        ).format(_COMPANIES_TABLE)
    )
    rows = cursor.fetchall()
    return [
        {
            "id": row["id"],
            "display_name": row["display_name"],
            "ats": row["ats"],
            "blurb": row["blurb"],
            "accomplishment": row["accomplishment"],
        }
        for row in rows
    ]
