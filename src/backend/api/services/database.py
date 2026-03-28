"""Database query functions for the API layer.

Reuses connection management and table naming from scripts/shared/database.py.
Adds read-only query functions needed by the API endpoints.
"""

import json
import logging

from psycopg2 import sql

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
    return json.dumps(value)


def _row_to_job_dict(row: dict) -> dict:
    """Convert a database row to a dict with JSON string fields."""
    d = dict(row)
    d["details"] = _ensure_json_string(d.get("details"))
    d["ai_metadata"] = _ensure_json_string(d.get("ai_metadata"))
    return d


def _table_id(env: str, table_type: str = "jobs") -> sql.Identifier:
    """Get a safe SQL identifier for the environment-specific table."""
    return sql.Identifier(_get_table_name(env, table_type))


def get_jobs(
    conn: Connection,
    env: str,
    company: str | None = None,
    status: str | None = None,
    limit: int = 5000,
    offset: int = 0,
) -> list[dict]:
    """List jobs with optional filters, ordered by last_seen_at DESC."""
    with conn.cursor() as cursor:
        table = _table_id(env)

        conditions: list[sql.Composable] = []
        params: list = []
        if company:
            conditions.append(sql.SQL("company = %s"))
            params.append(company)
        if status:
            conditions.append(sql.SQL("status = %s"))
            params.append(status)

        where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
        query = sql.SQL("SELECT * FROM {} {} ORDER BY last_seen_at DESC LIMIT %s OFFSET %s").format(
            table, where
        )
        params.extend([limit, offset])
        cursor.execute(query, params)

        return [_row_to_job_dict(row) for row in cursor.fetchall()]


def get_job_by_id(conn: Connection, env: str, job_id: str) -> dict | None:
    """Get a single job by ID."""
    with conn.cursor() as cursor:
        table = _table_id(env)

        cursor.execute(
            sql.SQL("SELECT * FROM {} WHERE id = %s").format(table),
            (job_id,),
        )
        row = cursor.fetchone()

        if row:
            return _row_to_job_dict(row)
        return None


def get_stats(conn: Connection, env: str, company: str | None = None) -> dict:
    """Get job statistics with optional company filter."""
    with conn.cursor() as cursor:
        table = _table_id(env)

        if company:
            cursor.execute(
                sql.SQL("""
                SELECT
                    COUNT(*) AS total_jobs,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_jobs,
                    COUNT(*) FILTER (WHERE status = 'CLOSED') AS closed_jobs
                FROM {}
                WHERE company = %s
                """).format(table),
                (company,),
            )
        else:
            cursor.execute(
                sql.SQL("""
                SELECT
                    COUNT(*) AS total_jobs,
                    COUNT(*) FILTER (WHERE status = 'OPEN') AS open_jobs,
                    COUNT(*) FILTER (WHERE status = 'CLOSED') AS closed_jobs
                FROM {}
                """).format(table),
            )

        stats_row = cursor.fetchone()

        # Get per-company counts
        if company:
            cursor.execute(
                sql.SQL("SELECT company, COUNT(*) AS count FROM {} WHERE company = %s GROUP BY company ORDER BY company").format(table),
                (company,),
            )
        else:
            cursor.execute(
                sql.SQL("SELECT company, COUNT(*) AS count FROM {} GROUP BY company ORDER BY company").format(table),
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
    company: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Get scrape run history, ordered by started_at DESC."""
    with conn.cursor() as cursor:
        table = _table_id(env, "runs")

        if company:
            cursor.execute(
                sql.SQL("SELECT * FROM {} WHERE company = %s ORDER BY started_at DESC LIMIT %s").format(table),
                (company, limit),
            )
        else:
            cursor.execute(
                sql.SQL("SELECT * FROM {} ORDER BY started_at DESC LIMIT %s").format(table),
                (limit,),
            )

        return [dict(row) for row in cursor.fetchall()]
