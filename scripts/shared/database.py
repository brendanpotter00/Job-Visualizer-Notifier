"""
Database abstraction layer for job scrapers

Supports both SQLite (local development) and PostgreSQL (production).
Uses environment-based table naming (e.g., job_listings_local, job_listings_prod).
"""

import logging
import sqlite3
from typing import Set, List, Optional, Dict, Any, Union
from urllib.parse import urlparse
from datetime import datetime

from .models import JobListing, ScrapeRun

logger = logging.getLogger(__name__)

# Type alias for database connections
Connection = Union[sqlite3.Connection, Any]  # Any for psycopg2 connection


def get_connection(db_url: str, env: str = "local") -> Connection:
    """
    Create a database connection from a URL

    Args:
        db_url: Database URL (sqlite:///path/to/db.db or postgresql://user:pass@host:port/dbname)
        env: Environment name (local, qa, prod) - used for table naming

    Returns:
        Database connection object
    """
    parsed = urlparse(db_url)

    if parsed.scheme == "sqlite":
        # Extract path from URL (remove leading slashes for relative paths)
        db_path = db_url.replace("sqlite:///", "")
        logger.info(f"Connecting to SQLite database: {db_path}")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        return conn

    elif parsed.scheme == "postgresql":
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError:
            raise ImportError(
                "psycopg2 not installed. Install with: pip install psycopg2-binary"
            )

        logger.info(f"Connecting to PostgreSQL database: {parsed.hostname}")
        conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
        return conn

    else:
        raise ValueError(
            f"Unsupported database scheme: {parsed.scheme}. "
            "Use 'sqlite' or 'postgresql'"
        )


def init_schema(conn: Connection, env: str = "local") -> None:
    """
    Initialize database schema with environment-specific table names

    Args:
        conn: Database connection
        env: Environment name (used for table suffix)
    """
    cursor = conn.cursor()

    jobs_table = f"job_listings_{env}"
    runs_table = f"scrape_runs_{env}"

    # Create job_listings table
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {jobs_table} (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            url TEXT NOT NULL,
            source_id TEXT NOT NULL,
            details TEXT DEFAULT '{{}}',
            posted_on TEXT,
            created_at TEXT NOT NULL,
            closed_on TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN',
            has_matched INTEGER DEFAULT 0,
            ai_metadata TEXT DEFAULT '{{}}',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            consecutive_misses INTEGER DEFAULT 0,
            details_scraped INTEGER DEFAULT 0
        )
    """)

    # Create indexes for job_listings
    cursor.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{jobs_table}_status
        ON {jobs_table}(status)
    """)
    cursor.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{jobs_table}_company
        ON {jobs_table}(company)
    """)
    cursor.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{jobs_table}_last_seen
        ON {jobs_table}(last_seen_at)
    """)

    # Create scrape_runs table
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {runs_table} (
            run_id TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            mode TEXT NOT NULL,
            jobs_seen INTEGER DEFAULT 0,
            new_jobs INTEGER DEFAULT 0,
            closed_jobs INTEGER DEFAULT 0,
            details_fetched INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    logger.info(f"Database schema initialized for environment: {env}")


def get_active_job_ids(conn: Connection, company: str, env: str = "local") -> Set[str]:
    """
    Get set of all active (OPEN) job IDs for a company

    Args:
        conn: Database connection
        company: Company name (e.g., "google")
        env: Environment name

    Returns:
        Set of job IDs that are currently marked as OPEN
    """
    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    cursor.execute(
        f"SELECT id FROM {jobs_table} WHERE company = ? AND status = 'OPEN'",
        (company,)
    )

    rows = cursor.fetchall()
    return {row[0] if isinstance(row, tuple) else row['id'] for row in rows}


def get_job_by_id(conn: Connection, job_id: str, env: str = "local") -> Optional[Dict[str, Any]]:
    """
    Retrieve a job by ID

    Args:
        conn: Database connection
        job_id: Job ID
        env: Environment name

    Returns:
        Job data as dict, or None if not found
    """
    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    cursor.execute(f"SELECT * FROM {jobs_table} WHERE id = ?", (job_id,))
    row = cursor.fetchone()

    if row:
        return dict(row) if hasattr(row, 'keys') else row
    return None


def insert_job(conn: Connection, job: JobListing, env: str = "local") -> None:
    """
    Insert a new job into the database

    Args:
        conn: Database connection
        job: JobListing model
        env: Environment name
    """
    import json

    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    cursor.execute(f"""
        INSERT INTO {jobs_table} (
            id, title, company, location, url, source_id,
            details, posted_on, created_at, closed_on, status,
            has_matched, ai_metadata,
            first_seen_at, last_seen_at, consecutive_misses, details_scraped
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job.id, job.title, job.company, job.location, job.url, job.source_id,
        json.dumps(job.details), job.posted_on, job.created_at, job.closed_on, job.status,
        1 if job.has_matched else 0, json.dumps(job.ai_metadata),
        job.first_seen_at, job.last_seen_at, job.consecutive_misses,
        1 if job.details_scraped else 0
    ))

    conn.commit()
    logger.debug(f"Inserted job: {job.id} - {job.title}")


def update_last_seen(conn: Connection, job_ids: List[str], timestamp: str, env: str = "local") -> None:
    """
    Update last_seen_at timestamp for jobs and reset consecutive_misses to 0

    Args:
        conn: Database connection
        job_ids: List of job IDs to update
        timestamp: ISO 8601 timestamp
        env: Environment name
    """
    if not job_ids:
        return

    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    # SQLite uses ? placeholders
    placeholders = ','.join(['?' for _ in job_ids])

    cursor.execute(f"""
        UPDATE {jobs_table}
        SET last_seen_at = ?, consecutive_misses = 0
        WHERE id IN ({placeholders})
    """, [timestamp] + job_ids)

    conn.commit()
    logger.info(f"Updated last_seen for {len(job_ids)} jobs")


def increment_consecutive_misses(conn: Connection, job_ids: List[str], env: str = "local") -> None:
    """
    Increment consecutive_misses counter for jobs

    Args:
        conn: Database connection
        job_ids: List of job IDs to update
        env: Environment name
    """
    if not job_ids:
        return

    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    placeholders = ','.join(['?' for _ in job_ids])

    cursor.execute(f"""
        UPDATE {jobs_table}
        SET consecutive_misses = consecutive_misses + 1
        WHERE id IN ({placeholders})
    """, job_ids)

    conn.commit()
    logger.info(f"Incremented misses for {len(job_ids)} jobs")


def mark_jobs_closed(conn: Connection, job_ids: List[str], timestamp: str, env: str = "local") -> None:
    """
    Mark jobs as CLOSED with closed_on timestamp

    Args:
        conn: Database connection
        job_ids: List of job IDs to mark as closed
        timestamp: ISO 8601 timestamp
        env: Environment name
    """
    if not job_ids:
        return

    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    placeholders = ','.join(['?' for _ in job_ids])

    cursor.execute(f"""
        UPDATE {jobs_table}
        SET status = 'CLOSED', closed_on = ?
        WHERE id IN ({placeholders})
    """, [timestamp] + job_ids)

    conn.commit()
    logger.info(f"Marked {len(job_ids)} jobs as CLOSED")


def reactivate_job(conn: Connection, job_id: str, timestamp: str, env: str = "local") -> None:
    """
    Reactivate a closed job (if it reappears in search results)

    Args:
        conn: Database connection
        job_id: Job ID to reactivate
        timestamp: ISO 8601 timestamp
        env: Environment name
    """
    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    cursor.execute(f"""
        UPDATE {jobs_table}
        SET status = 'OPEN', closed_on = NULL, last_seen_at = ?, consecutive_misses = 0
        WHERE id = ?
    """, (timestamp, job_id))

    conn.commit()
    logger.info(f"Reactivated job: {job_id}")


def record_scrape_run(conn: Connection, run_data: ScrapeRun, env: str = "local") -> None:
    """
    Record metadata about a scrape run

    Args:
        conn: Database connection
        run_data: ScrapeRun model
        env: Environment name
    """
    cursor = conn.cursor()
    runs_table = f"scrape_runs_{env}"

    cursor.execute(f"""
        INSERT INTO {runs_table} (
            run_id, company, started_at, completed_at, mode,
            jobs_seen, new_jobs, closed_jobs, details_fetched, error_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_data.run_id, run_data.company, run_data.started_at, run_data.completed_at,
        run_data.mode, run_data.jobs_seen, run_data.new_jobs, run_data.closed_jobs,
        run_data.details_fetched, run_data.error_count
    ))

    conn.commit()
    logger.info(f"Recorded scrape run: {run_data.run_id}")


def get_all_active_jobs(conn: Connection, company: str, env: str = "local") -> List[JobListing]:
    """
    Get all active jobs for a company

    Args:
        conn: Database connection
        company: Company name
        env: Environment name

    Returns:
        List of JobListing objects
    """
    import json

    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    cursor.execute(
        f"SELECT * FROM {jobs_table} WHERE company = ? AND status = 'OPEN'",
        (company,)
    )

    rows = cursor.fetchall()
    jobs = []

    for row in rows:
        row_dict = dict(row) if hasattr(row, 'keys') else row
        # Convert JSON strings back to dicts
        row_dict['details'] = json.loads(row_dict['details']) if isinstance(row_dict['details'], str) else row_dict['details']
        row_dict['ai_metadata'] = json.loads(row_dict['ai_metadata']) if isinstance(row_dict['ai_metadata'], str) else row_dict['ai_metadata']
        # Convert integers back to booleans
        row_dict['has_matched'] = bool(row_dict['has_matched'])
        row_dict['details_scraped'] = bool(row_dict['details_scraped'])

        jobs.append(JobListing(**row_dict))

    return jobs
