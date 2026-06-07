"""Per-user company selection preferences."""

import logging

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)

_TABLE = sql.Identifier("user_enabled_companies")


def list_enabled_companies(conn: Connection, user_id: str) -> list[str]:
    """Return the company IDs this user effectively has enabled, sorted.

    The result merges the user's explicitly-stored rows with companies added
    *after* the user's ``company_enroll_watermark`` (auto-enroll), so a curated
    user automatically picks up newly-added companies. The auto-enroll branch is
    gated on:

    * the user having at least one stored row — a user with zero rows is still
      "see all" and must resolve to ``[]`` (the merge would otherwise convert a
      brand-new signup into an explicit list), and
    * ``users.auto_enroll_new_companies`` being true — the global opt-out toggle.

    Single round-trip: the auto-enrolled IDs are computed in-query against the
    ``companies`` table, so the caller does not need to fetch the watermark or
    flag separately. The second UNION branch aliases ``c.id AS company_id`` so
    both branches share the ``company_id`` dict key under ``RealDictCursor``.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT e.company_id
        FROM user_enabled_companies e
        WHERE e.user_id = %(uid)s
        UNION
        SELECT c.id AS company_id
        FROM companies c, users u
        WHERE u.id = %(uid)s
          AND u.auto_enroll_new_companies
          AND c.enabled
          AND c.created_at > u.company_enroll_watermark
          AND EXISTS (
            SELECT 1 FROM user_enabled_companies x WHERE x.user_id = %(uid)s
          )
        ORDER BY company_id
        """,
        {"uid": user_id},
    )
    return [row["company_id"] for row in cursor.fetchall()]


def set_enabled_companies(
    conn: Connection,
    user_id: str,
    company_ids: list[str],
    auto_enroll_new_companies: bool = True,
) -> list[str]:
    """Replace a user's enabled-companies set and auto-enroll preference.

    Returns the canonicalized (deduped + sorted) company-id list. The caller
    echoes ``auto_enroll_new_companies`` back from the request, so it is not
    returned here.

    DELETE-then-INSERT in a single transaction; rolls back on any DB error.
    Canonicalizes input by deduping and sorting so the round-trip is stable.

    Also bumps ``company_enroll_watermark`` to ``now()`` and persists the toggle.
    The watermark bump is load-bearing: it records that the user has now decided
    about every company that exists as of this save, so a company they just saw
    (and chose to keep or drop) is no longer "newer than the watermark" and will
    not be auto-re-added on the next read — i.e. opt-outs stick.
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
        cursor.execute(
            "UPDATE users "
            "SET company_enroll_watermark = now(), auto_enroll_new_companies = %s "
            "WHERE id = %s",
            (auto_enroll_new_companies, user_id),
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
