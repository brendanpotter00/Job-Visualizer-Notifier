"""Database query functions for the API layer.

Reuses connection management and table naming from scripts/shared/database.py.
Adds read-only query functions needed by the API endpoints.
"""

import json
import logging
from typing import Optional

from scripts.shared.database import (
    _get_table_name,
    Connection,
)

logger = logging.getLogger(__name__)


def _ensure_json_string(value) -> str:
    """Ensure a value is a JSON string (not a parsed dict/list).

    psycopg2 with RealDictCursor auto-parses JSONB columns into Python dicts.
    The frontend expects these as JSON strings, not parsed objects.
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    logger.warning(
        "Unexpected type %s in _ensure_json_string, falling back to str()",
        type(value).__name__,
    )
    return str(value)


def _row_to_job_dict(row: dict) -> dict:
    """Convert a database row to a dict with JSON string fields."""
    d = dict(row)
    d["details"] = _ensure_json_string(d.get("details"))
    d["ai_metadata"] = _ensure_json_string(d.get("ai_metadata"))
    return d


def get_jobs(
    conn: Connection,
    env: str,
    company: Optional[str] = None,
    limit: int = 5000,
    offset: int = 0,
) -> list[dict]:
    """List jobs with optional company filter, ordered by last_seen_at DESC."""
    cursor = conn.cursor()
    table = _get_table_name(env, "jobs")

    if company:
        cursor.execute(
            f"SELECT * FROM {table} WHERE company = %s ORDER BY last_seen_at DESC LIMIT %s OFFSET %s",
            (company, limit, offset),
        )
    else:
        cursor.execute(
            f"SELECT * FROM {table} ORDER BY last_seen_at DESC LIMIT %s OFFSET %s",
            (limit, offset),
        )

    return [_row_to_job_dict(row) for row in cursor.fetchall()]


def get_job_by_id(conn: Connection, env: str, job_id: str) -> Optional[dict]:
    """Get a single job by ID."""
    cursor = conn.cursor()
    table = _get_table_name(env, "jobs")

    cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (job_id,))
    row = cursor.fetchone()

    if row:
        return _row_to_job_dict(row)
    return None


def get_stats(conn: Connection, env: str, company: Optional[str] = None) -> dict:
    """Get job statistics with optional company filter."""
    cursor = conn.cursor()
    table = _get_table_name(env, "jobs")

    if company:
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total_jobs,
                COUNT(*) FILTER (WHERE status = 'OPEN') AS open_jobs,
                COUNT(*) FILTER (WHERE status = 'CLOSED') AS closed_jobs
            FROM {table}
            WHERE company = %s
            """,
            (company,),
        )
    else:
        cursor.execute(
            f"""
            SELECT
                COUNT(*) AS total_jobs,
                COUNT(*) FILTER (WHERE status = 'OPEN') AS open_jobs,
                COUNT(*) FILTER (WHERE status = 'CLOSED') AS closed_jobs
            FROM {table}
            """
        )

    stats_row = cursor.fetchone()

    # Get per-company counts
    if company:
        cursor.execute(
            f"SELECT company, COUNT(*) AS count FROM {table} WHERE company = %s GROUP BY company ORDER BY company",
            (company,),
        )
    else:
        cursor.execute(
            f"SELECT company, COUNT(*) AS count FROM {table} GROUP BY company ORDER BY company"
        )

    company_counts = [dict(row) for row in cursor.fetchall()]

    return {
        "total_jobs": stats_row["total_jobs"],
        "open_jobs": stats_row["open_jobs"],
        "closed_jobs": stats_row["closed_jobs"],
        "company_counts": company_counts,
    }


def get_scrape_runs(
    conn: Connection,
    env: str,
    company: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """Get scrape run history, ordered by started_at DESC."""
    cursor = conn.cursor()
    table = _get_table_name(env, "runs")

    if company:
        cursor.execute(
            f"SELECT * FROM {table} WHERE company = %s ORDER BY started_at DESC LIMIT %s",
            (company, limit),
        )
    else:
        cursor.execute(
            f"SELECT * FROM {table} ORDER BY started_at DESC LIMIT %s",
            (limit,),
        )

    return [dict(row) for row in cursor.fetchall()]
