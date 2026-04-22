"""Idempotent seed of starter candidate features.

Called from FastAPI lifespan on every boot. Uses ``INSERT ... ON CONFLICT
(id) DO NOTHING`` so re-runs are harmless. IDs are intentionally stable —
downstream upvote rows reference them via FK.
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
)


def _features_table(env: str) -> str:
    return f"features_{env}"


def seed_starter_features(conn: Connection, env: str) -> int:
    """Insert starter features if not already present. Returns rows inserted.

    Idempotent; commits on success. Rolls back + re-raises on database error.
    """
    table = sql.Identifier(_features_table(env))
    cursor = conn.cursor()
    inserted = 0
    try:
        for feature_id, title, description in STARTER_FEATURES:
            cursor.execute(
                sql.SQL(
                    "INSERT INTO {} (id, title, description)"
                    " VALUES (%s, %s, %s)"
                    " ON CONFLICT (id) DO NOTHING"
                ).format(table),
                (feature_id, title, description),
            )
            if cursor.rowcount == 1:
                inserted += 1
        conn.commit()
    except psycopg2.Error as exc:
        conn.rollback()
        logger.error(
            "Database error during seed_starter_features (env=%s): %s",
            env, exc, exc_info=True,
        )
        raise
    # Emit unconditionally so cold-start logs always show the seed ran, even
    # when every feature already existed. A conditional log was silent after
    # the first successful boot, indistinguishable in Railway logs from a
    # silent crash of the seed routine (see 2026-04-18 review pass 2).
    logger.info(
        "seed_starter_features completed (env=%s, inserted=%d)", env, inserted
    )
    return inserted
