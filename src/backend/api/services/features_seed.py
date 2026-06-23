"""Idempotent seed + completion reconcile for candidate features.

Called from FastAPI lifespan on every boot. ``seed_starter_features`` uses
``INSERT ... ON CONFLICT (id) DO NOTHING`` to add new candidates, then
``reconcile_completed_features`` stamps ``completed_at`` on features we've since
shipped. Both are idempotent so re-runs are harmless. IDs are intentionally
stable — downstream upvote rows reference them via FK.
"""

import logging

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)


STARTER_FEATURES: tuple[tuple[str, str, str], ...] = (
    (
        "resume-match-ai",
        "AI resume matching notifications",
        "Upload your resume and get notifications when recently posted jobs match your background.",
    ),
    (
        "location-normalization",
        "Location normalization",
        "Normalize job-posting locations so 'SF / Bay Area / San Francisco, CA' collapses into one filter value.",
    ),
    (
        "mcp-server",
        "Hosted MCP server",
        "A deployed MCP server so Claude, Codex, and other agents can query job-posting data as a tool.",
    ),
    (
        "custom-dashboards",
        "Custom Dashboards",
        "Describe a dashboard in plain language and AI lays out live charts, ranked lists, and graphs from your job data — placing each component where you ask.",
    ),
)


# Features that have shipped. Their rows already exist in prod (seeded as
# candidates), so completion is applied via an idempotent UPDATE rather than the
# INSERT path. Add an id here when its feature goes live.
COMPLETED_FEATURE_IDS: tuple[str, ...] = ("location-normalization",)


_FEATURES_TABLE = sql.Identifier("features")


def seed_starter_features(conn: Connection) -> int:
    """Insert starter features if not already present. Returns rows inserted.

    Idempotent; commits on success. Rolls back + re-raises on database error.
    After seeding, reconciles the completed status of already-shipped features.
    """
    cursor = conn.cursor()
    inserted = 0
    try:
        for feature_id, title, description in STARTER_FEATURES:
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {} (id, title, description)"
                    " VALUES (%s, %s, %s)"
                    " ON CONFLICT (id) DO NOTHING"
                ).format(_FEATURES_TABLE),
                (feature_id, title, description),
            )
            if cursor.rowcount == 1:
                inserted += 1
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error during seed_starter_features: %s", exc, exc_info=True,
        )
        raise
    # Emit unconditionally so cold-start logs always show the seed ran, even
    # when every feature already existed. A conditional log was silent after
    # the first successful boot, indistinguishable in Railway logs from a
    # silent crash of the seed routine (see 2026-04-18 review pass 2).
    logger.info("seed_starter_features completed (inserted=%d)", inserted)
    reconcile_completed_features(conn)
    return inserted


def reconcile_completed_features(conn: Connection) -> int:
    """Stamp ``completed_at`` on shipped features that aren't marked yet.

    Returns the number of rows newly marked completed. Idempotent: the
    ``completed_at IS NULL`` guard means re-runs are no-ops and never re-stamp
    (so the recorded ship date stays put). Commits on success; rolls back +
    re-raises on database error. Unknown ids in ``COMPLETED_FEATURE_IDS`` simply
    match nothing.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            sql.SQL(
                "UPDATE {} SET completed_at = now()"
                " WHERE id = ANY(%s) AND completed_at IS NULL"
            ).format(_FEATURES_TABLE),
            (list(COMPLETED_FEATURE_IDS),),
        )
        marked = int(cursor.rowcount)
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error during reconcile_completed_features: %s",
            exc,
            exc_info=True,
        )
        raise
    logger.info("reconcile_completed_features completed (marked=%d)", marked)
    return marked
