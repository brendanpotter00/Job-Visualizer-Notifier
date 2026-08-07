"""DB layer for the add-company flow: ``company_submissions`` + user enablement.

Kept separate from ``user_preferences_service`` (which does full-replace of the
enabled set) because the add-company flow needs an *additive* enable — turning on
one new company without disturbing the user's existing selections — plus CRUD for
the async onboarding submission rows and the per-user rate-limit count.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import psycopg2
from psycopg2.extensions import connection as Connection

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = ("succeeded", "failed")


def new_submission_id() -> str:
    """A fresh submission id (uuid4 hex)."""
    return uuid.uuid4().hex


def create_submission(
    conn: Connection, submission_id: str, user_id: str, url: str
) -> None:
    """Insert a ``pending`` submission row."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO company_submissions (id, user_id, url, status) "
            "VALUES (%s, %s, %s, 'pending')",
            (submission_id, user_id, url),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


def get_submission(
    conn: Connection, submission_id: str, user_id: str
) -> Optional[dict[str, Any]]:
    """Fetch one submission scoped to its owner (None if not owned/absent)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, user_id, url, status, company_id, error, created_at, updated_at "
        "FROM company_submissions WHERE id = %s AND user_id = %s",
        (submission_id, user_id),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def finish_submission(
    conn: Connection,
    submission_id: str,
    *,
    status: str,
    company_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Move a submission to a terminal status (``succeeded`` / ``failed``)."""
    if status not in _TERMINAL_STATUSES:
        raise ValueError(f"finish_submission status must be terminal; got {status!r}")
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE company_submissions "
            "SET status = %s, company_id = %s, error = %s, updated_at = now() "
            "WHERE id = %s",
            (status, company_id, error, submission_id),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise


def count_recent_submissions(conn: Connection, user_id: str, hours: int = 24) -> int:
    """Count a user's submissions in the last ``hours`` (per-user quota source)."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) AS n FROM company_submissions "
        "WHERE user_id = %s AND created_at > now() - make_interval(hours => %s)",
        (user_id, hours),
    )
    row = cursor.fetchone()
    return int(row["n"]) if row else 0


def enable_company_for_user(conn: Connection, user_id: str, company_id: str) -> None:
    """Additively enable one company for a user (idempotent).

    Unlike ``user_preferences_service.set_enabled_companies`` (full replace), this
    inserts a single ``user_enabled_companies`` row and leaves the rest intact —
    the add-company flow should never clear a user's other selections.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO user_enabled_companies (user_id, company_id) "
            "VALUES (%s, %s) ON CONFLICT (user_id, company_id) DO NOTHING",
            (user_id, company_id),
        )
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
