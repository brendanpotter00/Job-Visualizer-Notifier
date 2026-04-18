"""
Database abstraction layer for job scrapers

PostgreSQL only. Uses environment-based table naming (e.g., job_listings_local, job_listings_prod).
"""

import json
import logging
import re
from typing import Set, List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from .models import JobListing, ScrapeRun

logger = logging.getLogger(__name__)

# Type alias for database connections
Connection = psycopg2.extensions.connection

# Allowed environment values (prevents SQL injection via table name construction)
ALLOWED_ENVS = frozenset({"local", "qa", "prod"})

# Pattern for test environments (test_<hex_chars> for test isolation)
_TEST_ENV_PATTERN = re.compile(r"^test_[a-f0-9]{8}$")

# Column list for job_listings table (used in INSERT statements)
_JOB_COLUMNS = """
    id, title, company, location, url, source_id,
    details, posted_on, created_at, closed_on, status,
    has_matched, ai_metadata,
    first_seen_at, last_seen_at, consecutive_misses, details_scraped
""".strip()

# ON CONFLICT clause for upsert operations
_UPSERT_ON_CONFLICT = """
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
""".strip()


def _is_valid_env(env: str) -> bool:
    """Check if environment name is valid (prevents SQL injection)."""
    return env in ALLOWED_ENVS or bool(_TEST_ENV_PATTERN.match(env))


def _get_table_name(env: str, table_type: str = "jobs") -> str:
    """
    Get environment-specific table name.

    Args:
        env: Environment name (local, qa, prod, or test_<hex> for tests)
        table_type: Type of table ("jobs", "runs", or "users")

    Returns:
        Full table name with environment suffix

    Raises:
        ValueError: If env is not valid
    """
    if not _is_valid_env(env):
        raise ValueError(f"Invalid environment: {env}. Must be one of {ALLOWED_ENVS} or test_<hex>")
    if table_type == "runs":
        return f"scrape_runs_{env}"
    elif table_type == "users":
        return f"users_{env}"
    return f"job_listings_{env}"


def _build_job_values(job: JobListing) -> Tuple:
    """
    Build a tuple of values from a JobListing for database insertion.

    Args:
        job: JobListing model

    Returns:
        Tuple of values matching _JOB_COLUMNS order
    """
    return (
        job.id, job.title, job.company, job.location, job.url, job.source_id,
        json.dumps(job.details), job.posted_on, job.created_at, job.closed_on, job.status,
        job.has_matched, json.dumps(job.ai_metadata),
        job.first_seen_at, job.last_seen_at, job.consecutive_misses, job.details_scraped
    )


def _build_id_placeholders(ids: List[str]) -> str:
    """
    Build SQL placeholders for a list of IDs.

    Args:
        ids: List of IDs

    Returns:
        Comma-separated %s placeholders (e.g., "%s,%s,%s")
    """
    return ','.join(['%s' for _ in ids])


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
    Ensure the database schema is up to date by applying any pending migrations.

    Schema is managed via numbered migration files in scripts/shared/migrations/.
    Applied versions are tracked in schema_migrations_{env}. See that package
    for the migration runner and individual migration files.

    Args:
        conn: Database connection
        env: Environment name (used for table suffix)
    """
    from .migrations.runner import migrate_up

    applied = migrate_up(conn, env)
    if applied:
        logger.info(
            f"Applied {len(applied)} migration(s) for env={env}: {applied}"
        )
    else:
        logger.info(f"Database schema up to date for env={env}")


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
    jobs_table = _get_table_name(env)

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
    jobs_table = _get_table_name(env)

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
    jobs_table = _get_table_name(env)

    cursor.execute(
        f"INSERT INTO {jobs_table} ({_JOB_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        _build_job_values(job)
    )

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
    jobs_table = _get_table_name(env)

    cursor.execute(
        f"""
        INSERT INTO {jobs_table} ({_JOB_COLUMNS})
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        {_UPSERT_ON_CONFLICT}
        RETURNING (xmax = 0) AS inserted
        """,
        _build_job_values(job)
    )

    result = cursor.fetchone()
    was_inserted = result['inserted'] if result else True

    conn.commit()

    if was_inserted:
        logger.debug(f"Inserted new job: {job.id} - {job.title}")
    else:
        logger.info(f"Reactivated job: {job.id} - {job.title}")

    return was_inserted


def upsert_jobs_batch(conn: Connection, jobs: List[JobListing], env: str = "local") -> int:
    """
    Batch upsert multiple jobs in a single transaction.

    More efficient than calling upsert_job() in a loop - uses execute_values
    for bulk operations (10-50x faster for large batches).

    Args:
        conn: Database connection
        jobs: List of JobListing models
        env: Environment name

    Returns:
        Number of jobs in the batch (all are upserted)
    """
    if not jobs:
        return 0

    cursor = conn.cursor()
    jobs_table = _get_table_name(env)
    values = [_build_job_values(job) for job in jobs]

    execute_values(
        cursor,
        f"INSERT INTO {jobs_table} ({_JOB_COLUMNS}) VALUES %s {_UPSERT_ON_CONFLICT}",
        values,
        page_size=100
    )

    conn.commit()
    logger.info(f"Batch upserted {len(jobs)} jobs")
    return len(jobs)


def insert_jobs_batch(conn: Connection, jobs: List[JobListing], env: str = "local") -> int:
    """
    Batch insert multiple jobs in a single transaction.

    Skips jobs that already exist (ON CONFLICT DO NOTHING).
    More efficient than calling insert_job() in a loop.

    Args:
        conn: Database connection
        jobs: List of JobListing models
        env: Environment name

    Returns:
        Number of jobs actually inserted (excludes duplicates skipped by ON CONFLICT)
    """
    if not jobs:
        return 0

    cursor = conn.cursor()
    jobs_table = _get_table_name(env)
    values = [_build_job_values(job) for job in jobs]

    execute_values(
        cursor,
        f"INSERT INTO {jobs_table} ({_JOB_COLUMNS}) VALUES %s ON CONFLICT (id) DO NOTHING",
        values,
        page_size=100
    )

    actual_inserted = cursor.rowcount
    conn.commit()
    logger.info(f"Batch inserted {actual_inserted}/{len(jobs)} jobs (skipped {len(jobs) - actual_inserted} duplicates)")
    return actual_inserted


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
    jobs_table = _get_table_name(env)
    placeholders = _build_id_placeholders(job_ids)

    cursor.execute(
        f"UPDATE {jobs_table} SET last_seen_at = %s, consecutive_misses = 0 WHERE id IN ({placeholders})",
        [timestamp] + job_ids
    )

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
    jobs_table = _get_table_name(env)
    placeholders = _build_id_placeholders(job_ids)

    cursor.execute(
        f"UPDATE {jobs_table} SET consecutive_misses = consecutive_misses + 1 WHERE id IN ({placeholders})",
        job_ids
    )

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
    jobs_table = _get_table_name(env)
    placeholders = _build_id_placeholders(job_ids)

    cursor.execute(
        f"UPDATE {jobs_table} SET status = 'CLOSED', closed_on = %s WHERE id IN ({placeholders})",
        [timestamp] + job_ids
    )

    conn.commit()
    logger.info(f"Marked {len(job_ids)} jobs as CLOSED")


def get_jobs_exceeding_miss_threshold(
    conn: Connection, job_ids: List[str], threshold: int, env: str = "local"
) -> Set[str]:
    """
    Get job IDs where consecutive_misses >= threshold in a single query.

    Args:
        conn: Database connection
        job_ids: List of job IDs to check
        threshold: Minimum consecutive_misses value
        env: Environment name

    Returns:
        Set of job IDs that have consecutive_misses >= threshold
    """
    if not job_ids:
        return set()

    cursor = conn.cursor()
    jobs_table = _get_table_name(env)
    placeholders = _build_id_placeholders(job_ids)

    cursor.execute(
        f"SELECT id FROM {jobs_table} WHERE id IN ({placeholders}) AND consecutive_misses >= %s",
        job_ids + [threshold]
    )

    return {row['id'] for row in cursor.fetchall()}


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
    jobs_table = _get_table_name(env)

    cursor.execute(
        f"UPDATE {jobs_table} SET status = 'OPEN', closed_on = NULL, last_seen_at = %s, consecutive_misses = 0 WHERE id = %s",
        (timestamp, job_id)
    )

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
    runs_table = _get_table_name(env, "runs")

    cursor.execute(
        f"""
        INSERT INTO {runs_table} (
            run_id, company, started_at, completed_at, mode,
            jobs_seen, new_jobs, closed_jobs, details_fetched, error_count
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            run_data.run_id, run_data.company, run_data.started_at, run_data.completed_at,
            run_data.mode, run_data.jobs_seen, run_data.new_jobs, run_data.closed_jobs,
            run_data.details_fetched, run_data.error_count
        )
    )

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
    jobs_table = _get_table_name(env)

    cursor.execute(
        f"SELECT * FROM {jobs_table} WHERE company = %s AND status = 'OPEN'",
        (company,)
    )

    jobs = []
    for row in cursor.fetchall():
        row_dict = dict(row)
        for json_col in ('details', 'ai_metadata'):
            if isinstance(row_dict.get(json_col), str):
                row_dict[json_col] = json.loads(row_dict[json_col])
        # Timestamptz columns come back as tz-aware datetime objects, but
        # JobListing models these as ISO 8601 strings (scraper-side contract).
        # Normalize before constructing the Pydantic model.
        for ts_col in ('posted_on', 'created_at', 'closed_on', 'first_seen_at', 'last_seen_at'):
            value = row_dict.get(ts_col)
            if hasattr(value, 'isoformat'):
                row_dict[ts_col] = value.isoformat()
        jobs.append(JobListing(**row_dict))

    return jobs
