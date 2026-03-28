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


def _build_where(
    company: str | None = None, status: str | None = None,
) -> tuple[sql.Composable, list]:
    """Build a WHERE clause and parameter list from optional filters."""
    conditions: list[sql.Composable] = []
    params: list = []
    if company:
        conditions.append(sql.SQL("company = %s"))
        params.append(company)
    if status:
        conditions.append(sql.SQL("status = %s"))
        params.append(status)
    where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("")
    return where, params


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
        where, params = _build_where(company=company, status=status)

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
        where, params = _build_where(company=company)

        # Single query: per-company counts plus totals via window functions
        cursor.execute(
            sql.SQL("""
            SELECT
                company,
                COUNT(*) AS count,
                SUM(COUNT(*)) OVER () AS total_jobs,
                SUM(COUNT(*) FILTER (WHERE status = 'OPEN')) OVER () AS open_jobs,
                SUM(COUNT(*) FILTER (WHERE status = 'CLOSED')) OVER () AS closed_jobs
            FROM {} {}
            GROUP BY company
            ORDER BY company
            """).format(table, where),
            params if params else None,
        )
        rows = cursor.fetchall()

        if rows:
            first = rows[0]
            total_jobs = first["total_jobs"]
            open_jobs = first["open_jobs"]
            closed_jobs = first["closed_jobs"]
        else:
            total_jobs = open_jobs = closed_jobs = 0

        return {
            "total_jobs": total_jobs,
            "open_jobs": open_jobs,
            "closed_jobs": closed_jobs,
            "company_counts": [{"company": r["company"], "count": r["count"]} for r in rows],
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
        where, params = _build_where(company=company)

        params.append(limit)
        cursor.execute(
            sql.SQL("SELECT * FROM {} {} ORDER BY started_at DESC LIMIT %s").format(table, where),
            params,
        )

        return [dict(row) for row in cursor.fetchall()]
