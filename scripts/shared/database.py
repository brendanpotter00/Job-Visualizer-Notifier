"""
Database abstraction layer for job scrapers

PostgreSQL only. Uses environment-based table naming (e.g., job_listings_local, job_listings_prod).
"""

import json
import logging
from typing import Set, List, Optional, Dict, Any
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor

from .models import JobListing, ScrapeRun

logger = logging.getLogger(__name__)

# Type alias for database connections
Connection = psycopg2.extensions.connection


def get_connection(db_url: str, env: str = "local") -> Connection:
    """
    Create a PostgreSQL database connection from a URL

    Args:
        db_url: Database URL (postgresql://user:pass@host:port/dbname)
        env: Environment name (local, qa, prod) - used for table naming

    Returns:
        PostgreSQL connection object
    """
    parsed = urlparse(db_url)

    if parsed.scheme != "postgresql":
        raise ValueError(
            f"Unsupported database scheme: {parsed.scheme}. "
            "Only 'postgresql' is supported."
        )

    logger.info(f"Connecting to PostgreSQL database: {parsed.hostname}")
    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    return conn


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
            details JSONB DEFAULT '{{}}'::jsonb,
            posted_on TEXT,
            created_at TEXT NOT NULL,
            closed_on TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN',
            has_matched BOOLEAN DEFAULT FALSE,
            ai_metadata JSONB DEFAULT '{{}}'::jsonb,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            consecutive_misses INTEGER DEFAULT 0,
            details_scraped BOOLEAN DEFAULT FALSE
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
        f"SELECT id FROM {jobs_table} WHERE company = %s AND status = 'OPEN'",
        (company,)
    )

    rows = cursor.fetchall()
    return {row['id'] for row in rows}


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

    cursor.execute(f"SELECT * FROM {jobs_table} WHERE id = %s", (job_id,))
    row = cursor.fetchone()

    if row:
        return dict(row)
    return None


def insert_job(conn: Connection, job: JobListing, env: str = "local") -> None:
    """
    Insert a new job into the database

    Args:
        conn: Database connection
        job: JobListing model
        env: Environment name
    """
    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    cursor.execute(f"""
        INSERT INTO {jobs_table} (
            id, title, company, location, url, source_id,
            details, posted_on, created_at, closed_on, status,
            has_matched, ai_metadata,
            first_seen_at, last_seen_at, consecutive_misses, details_scraped
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        job.id, job.title, job.company, job.location, job.url, job.source_id,
        json.dumps(job.details), job.posted_on, job.created_at, job.closed_on, job.status,
        job.has_matched, json.dumps(job.ai_metadata),
        job.first_seen_at, job.last_seen_at, job.consecutive_misses,
        job.details_scraped
    ))

    conn.commit()
    logger.debug(f"Inserted job: {job.id} - {job.title}")


def upsert_job(conn: Connection, job: JobListing, env: str = "local") -> bool:
    """
    Insert a new job or update an existing one (e.g., reactivate a closed job)

    Uses PostgreSQL's ON CONFLICT to atomically handle both cases.
    On conflict: updates mutable fields and reactivates the job (status='OPEN').
    Preserves: first_seen_at, created_at (original discovery metadata).

    Args:
        conn: Database connection
        job: JobListing model
        env: Environment name

    Returns:
        True if a new job was inserted, False if an existing job was updated
    """
    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    cursor.execute(f"""
        INSERT INTO {jobs_table} (
            id, title, company, location, url, source_id,
            details, posted_on, created_at, closed_on, status,
            has_matched, ai_metadata,
            first_seen_at, last_seen_at, consecutive_misses, details_scraped
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title,
            location = EXCLUDED.location,
            url = EXCLUDED.url,
            details = EXCLUDED.details,
            posted_on = EXCLUDED.posted_on,
            status = 'OPEN',
            closed_on = NULL,
            last_seen_at = EXCLUDED.last_seen_at,
            consecutive_misses = 0,
            details_scraped = EXCLUDED.details_scraped
        RETURNING (xmax = 0) AS inserted
    """, (
        job.id, job.title, job.company, job.location, job.url, job.source_id,
        json.dumps(job.details), job.posted_on, job.created_at, job.closed_on, job.status,
        job.has_matched, json.dumps(job.ai_metadata),
        job.first_seen_at, job.last_seen_at, job.consecutive_misses,
        job.details_scraped
    ))

    result = cursor.fetchone()
    was_inserted = result['inserted'] if result else True

    conn.commit()

    if was_inserted:
        logger.debug(f"Inserted new job: {job.id} - {job.title}")
    else:
        logger.info(f"Reactivated job: {job.id} - {job.title}")

    return was_inserted


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

    placeholders = ','.join(['%s' for _ in job_ids])

    cursor.execute(f"""
        UPDATE {jobs_table}
        SET last_seen_at = %s, consecutive_misses = 0
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

    placeholders = ','.join(['%s' for _ in job_ids])

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

    placeholders = ','.join(['%s' for _ in job_ids])

    cursor.execute(f"""
        UPDATE {jobs_table}
        SET status = 'CLOSED', closed_on = %s
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
        SET status = 'OPEN', closed_on = NULL, last_seen_at = %s, consecutive_misses = 0
        WHERE id = %s
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
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
    cursor = conn.cursor()
    jobs_table = f"job_listings_{env}"

    cursor.execute(
        f"SELECT * FROM {jobs_table} WHERE company = %s AND status = 'OPEN'",
        (company,)
    )

    rows = cursor.fetchall()
    jobs = []

    for row in rows:
        row_dict = dict(row)
        # JSONB columns are already parsed by psycopg2
        if isinstance(row_dict['details'], str):
            row_dict['details'] = json.loads(row_dict['details'])
        if isinstance(row_dict['ai_metadata'], str):
            row_dict['ai_metadata'] = json.loads(row_dict['ai_metadata'])

        jobs.append(JobListing(**row_dict))

    return jobs
