"""
Database abstraction layer for job scrapers

PostgreSQL only. Uses bare table names (job_listings, scrape_runs, users)
across all environments after envAgnosticTables.
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Set, List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from .models import JobListing, ScrapeRun

logger = logging.getLogger(__name__)

# Type alias for database connections
Connection = psycopg2.extensions.connection

# Pattern matching Shared Contracts §Test schema isolation.
# Tight regex: prevents SQL injection via a crafted PYTEST_SCHEMA env var
# since the name is interpolated into a quoted identifier below.
_PYTEST_SCHEMA_RE = re.compile(r"^(?:public|test_[a-f0-9]{8,})$")

# Bare table names (post envAgnosticTables).
_JOBS_TABLE = "job_listings"
_RUNS_TABLE = "scrape_runs"

# Column list for job_listings table (used in INSERT statements)
_JOB_COLUMNS = """
    id, title, company, location, url, source_id,
    details, posted_on, created_at, closed_on, status,
    has_matched, ai_metadata,
    first_seen_at, last_seen_at, consecutive_misses, details_scraped
""".strip()

# ON CONFLICT clause for upsert operations
_UPSERT_ON_CONFLICT = """
    ON CONFLICT (source_id, id) DO UPDATE SET
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


def get_connection(db_url: str) -> Connection:
    """
    Create a PostgreSQL database connection from a URL

    Args:
        db_url: Database URL (postgresql://user:pass@host:port/dbname)

    Returns:
        PostgreSQL connection object

    Notes:
        If PYTEST_SCHEMA is set (pytest-driven isolation), the returned
        connection has search_path pinned to that schema. Unset in prod
        and normal local dev — behavior is identical to not having the
        feature then. Per-connection, not session-global — each call to
        get_connection gets a fresh SET.
    """
    parsed = urlparse(db_url)

    if parsed.scheme != "postgresql":
        raise ValueError(
            f"Unsupported database scheme: {parsed.scheme}. "
            "Only 'postgresql' is supported."
        )

    logger.info(f"Connecting to PostgreSQL database: {parsed.hostname}")
    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)

    pytest_schema = os.environ.get("PYTEST_SCHEMA")
    if pytest_schema is not None:
        if not _PYTEST_SCHEMA_RE.match(pytest_schema):
            conn.close()
            raise ValueError(
                f"PYTEST_SCHEMA={pytest_schema!r} does not match expected "
                f"pattern 'test_<hex>' or 'public'. Refusing to interpolate "
                f"into SQL."
            )
        cursor = conn.cursor()
        try:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{pytest_schema}"')
            cursor.execute(f'SET search_path TO "{pytest_schema}", public')
            conn.commit()
        finally:
            cursor.close()

    return conn


def get_active_job_ids(
    conn: Connection, source_id: str, company: str
) -> Set[str]:
    """
    Get set of all active (OPEN) job IDs for a company within one source.

    Scoping by ``source_id`` matches the composite ``(source_id, id)`` PK
    on ``job_listings`` — without it, a future multi-source-per-company
    setup (e.g. Greenhouse + an additional ATS for the same company) would
    silently merge id spaces and break the consecutive-misses lifecycle.

    Args:
        conn: Database connection
        source_id: Source namespace (e.g., ``"greenhouse_api"``,
            ``"google_scraper"``). Must be a non-empty string; an empty
            string would silently build ``WHERE source_id = ''`` and return
            no rows, masking a misconfigured caller.
        company: Company name (e.g., "google")

    Returns:
        Set of job IDs that are currently marked as OPEN for the given
        ``(source_id, company)`` pair.
    """
    if not source_id:
        raise ValueError(
            "get_active_job_ids requires a non-empty source_id"
        )
    cursor = conn.cursor()

    cursor.execute(
        f"SELECT id FROM {_JOBS_TABLE} "
        f"WHERE source_id = %s AND company = %s AND status = 'OPEN'",
        (source_id, company)
    )

    rows = cursor.fetchall()
    return {row['id'] for row in rows}


def count_active_jobs(
    conn: Connection, source_id: str, company: str
) -> int:
    """
    Count active (OPEN) jobs for a company within one source.

    Args:
        conn: Database connection
        source_id: Source namespace (e.g., ``"greenhouse_api"``). Must be a
            non-empty string; an empty string would silently return 0 and
            mask a misconfigured caller.
        company: Company name (e.g., "stripe")

    Returns:
        Number of jobs currently marked as OPEN for the given
        ``(source_id, company)`` pair.
    """
    if not source_id:
        raise ValueError(
            "count_active_jobs requires a non-empty source_id"
        )
    cursor = conn.cursor()

    cursor.execute(
        f"SELECT COUNT(*) AS n FROM {_JOBS_TABLE} "
        f"WHERE source_id = %s AND company = %s AND status = 'OPEN'",
        (source_id, company)
    )

    row = cursor.fetchone()
    return int(row['n']) if row else 0


def list_enabled_companies(conn: Connection, ats: str) -> List[Dict[str, Any]]:
    """
    List all enabled companies for a given ATS.

    Used by the Greenhouse periodic fan-out task to discover which
    companies to defer per-company fetch tasks for.

    Args:
        conn: Database connection
        ats: ATS name to filter by (e.g., "greenhouse")

    Returns:
        List of dicts with keys ``id`` and ``board_token``, ordered
        deterministically by ``id``. Empty list if no rows match.
    """
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, board_token FROM companies "
        "WHERE ats = %s AND enabled = true "
        "ORDER BY id",
        (ats,),
    )

    return [dict(row) for row in cursor.fetchall()]


def get_job_by_id(
    conn: Connection, source_id: str, job_id: str
) -> Optional[Dict[str, Any]]:
    """
    Retrieve a job by composite (source_id, id) key.

    Args:
        conn: Database connection
        source_id: Source namespace (e.g., "greenhouse_api", "google_scraper").
            Must be non-empty; an empty value would silently 404 every lookup
            with no signal at the call site.
        job_id: Job id within that source

    Returns:
        Job data as dict, or None if not found
    """
    if not source_id:
        raise ValueError(
            "get_job_by_id requires a non-empty source_id"
        )
    cursor = conn.cursor()

    cursor.execute(
        f"SELECT * FROM {_JOBS_TABLE} WHERE source_id = %s AND id = %s",
        (source_id, job_id),
    )
    row = cursor.fetchone()

    if row:
        return dict(row)
    return None


def insert_job(conn: Connection, job: JobListing) -> None:
    """
    Insert a new job into the database

    Args:
        conn: Database connection
        job: JobListing model
    """
    cursor = conn.cursor()

    cursor.execute(
        f"INSERT INTO {_JOBS_TABLE} ({_JOB_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        _build_job_values(job)
    )

    conn.commit()
    logger.debug(f"Inserted job: {job.id} - {job.title}")


def upsert_job(conn: Connection, job: JobListing) -> bool:
    """
    Insert a new job or update an existing one (e.g., reactivate a closed job)

    Uses PostgreSQL's ON CONFLICT to atomically handle both cases.
    On conflict: updates mutable fields and reactivates the job (status='OPEN').
    Preserves: first_seen_at, created_at (original discovery metadata).

    Args:
        conn: Database connection
        job: JobListing model

    Returns:
        True if a new job was inserted, False if an existing job was updated
    """
    cursor = conn.cursor()

    cursor.execute(
        f"""
        INSERT INTO {_JOBS_TABLE} ({_JOB_COLUMNS})
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


def upsert_jobs_batch(conn: Connection, jobs: List[JobListing]) -> int:
    """
    Batch upsert multiple jobs in a single transaction.

    More efficient than calling upsert_job() in a loop - uses execute_values
    for bulk operations (10-50x faster for large batches).

    Args:
        conn: Database connection
        jobs: List of JobListing models

    Returns:
        Number of jobs in the batch (all are upserted)
    """
    if not jobs:
        return 0

    cursor = conn.cursor()
    values = [_build_job_values(job) for job in jobs]

    execute_values(
        cursor,
        f"INSERT INTO {_JOBS_TABLE} ({_JOB_COLUMNS}) VALUES %s {_UPSERT_ON_CONFLICT}",
        values,
        page_size=100
    )

    # execute_values returns the rowcount of the LAST page only in psycopg2
    # < 2.9; from 2.9 onward it sums across pages. Project pins
    # psycopg2-binary >= 2.9.9 (scripts/requirements.txt,
    # src/backend/api/requirements.txt) so rowcount is reliable for divergence
    # detection. Source_id comes from per-row `_build_job_values(job.source_id)`
    # rather than a uniform arg, so a future scraper constructing a JobListing
    # with the wrong source_id would silently upsert into the wrong namespace —
    # the divergence warning here is the first signal that something is off.
    affected = cursor.rowcount
    conn.commit()
    if affected != len(jobs):
        logger.warning(
            "upsert_jobs_batch affected %d/%d rows — %d jobs did not produce "
            "an insert-or-update (psycopg2 rowcount divergence may indicate a "
            "constraint conflict or pre-2.9 page-only rowcount bug)",
            affected, len(jobs), len(jobs) - affected,
        )
    else:
        logger.info(f"Batch upserted {affected}/{len(jobs)} jobs")
    return len(jobs)


def insert_jobs_batch(conn: Connection, jobs: List[JobListing]) -> int:
    """
    Batch insert multiple jobs in a single transaction.

    Skips jobs that already exist (ON CONFLICT DO NOTHING).
    More efficient than calling insert_job() in a loop.

    Args:
        conn: Database connection
        jobs: List of JobListing models

    Returns:
        Number of jobs actually inserted (excludes duplicates skipped by ON CONFLICT)
    """
    if not jobs:
        return 0

    cursor = conn.cursor()
    values = [_build_job_values(job) for job in jobs]

    execute_values(
        cursor,
        f"INSERT INTO {_JOBS_TABLE} ({_JOB_COLUMNS}) VALUES %s ON CONFLICT (source_id, id) DO NOTHING",
        values,
        page_size=100
    )

    actual_inserted = cursor.rowcount
    conn.commit()
    logger.info(f"Batch inserted {actual_inserted}/{len(jobs)} jobs (skipped {len(jobs) - actual_inserted} duplicates)")
    return actual_inserted


def update_last_seen(
    conn: Connection, source_id: str, job_ids: List[str], timestamp: str
) -> None:
    """
    Update last_seen_at timestamp for jobs and reset consecutive_misses to 0

    Args:
        conn: Database connection
        source_id: Source namespace; ``job_ids`` must all belong to this
            source. Must be non-empty; an empty value would silently no-op
            every row.
        job_ids: List of job IDs to update
        timestamp: ISO 8601 timestamp
    """
    if not source_id:
        raise ValueError(
            "update_last_seen requires a non-empty source_id"
        )
    if not job_ids:
        return

    cursor = conn.cursor()
    placeholders = _build_id_placeholders(job_ids)

    cursor.execute(
        f"UPDATE {_JOBS_TABLE} SET last_seen_at = %s, consecutive_misses = 0 "
        f"WHERE source_id = %s AND id IN ({placeholders})",
        [timestamp, source_id] + job_ids
    )

    affected = cursor.rowcount
    conn.commit()
    if affected != len(job_ids):
        logger.warning(
            "update_last_seen affected %d/%d rows for source_id=%s — "
            "%d ids did not match the composite (source_id, id) key",
            affected, len(job_ids), source_id, len(job_ids) - affected,
        )
    else:
        logger.info(
            "Updated last_seen for %d/%d jobs (source_id=%s)",
            affected, len(job_ids), source_id,
        )


def increment_consecutive_misses(
    conn: Connection, source_id: str, job_ids: List[str]
) -> None:
    """
    Increment consecutive_misses counter for jobs

    Args:
        conn: Database connection
        source_id: Source namespace; ``job_ids`` must all belong to this
            source. Must be non-empty; an empty value would silently no-op.
        job_ids: List of job IDs to update
    """
    if not source_id:
        raise ValueError(
            "increment_consecutive_misses requires a non-empty source_id"
        )
    if not job_ids:
        return

    cursor = conn.cursor()
    placeholders = _build_id_placeholders(job_ids)

    cursor.execute(
        f"UPDATE {_JOBS_TABLE} SET consecutive_misses = consecutive_misses + 1 "
        f"WHERE source_id = %s AND id IN ({placeholders})",
        [source_id] + job_ids
    )

    affected = cursor.rowcount
    conn.commit()
    if affected != len(job_ids):
        logger.warning(
            "increment_consecutive_misses affected %d/%d rows for "
            "source_id=%s — %d ids did not match the composite "
            "(source_id, id) key",
            affected, len(job_ids), source_id, len(job_ids) - affected,
        )
    else:
        logger.info(
            "Incremented misses for %d/%d jobs (source_id=%s)",
            affected, len(job_ids), source_id,
        )


def mark_jobs_closed(
    conn: Connection, source_id: str, job_ids: List[str], timestamp: str
) -> None:
    """
    Mark jobs as CLOSED with closed_on timestamp

    Args:
        conn: Database connection
        source_id: Source namespace; ``job_ids`` must all belong to this
            source. Must be non-empty; an empty value would silently no-op
            and the jobs would never get closed.
        job_ids: List of job IDs to mark as closed
        timestamp: ISO 8601 timestamp
    """
    if not source_id:
        raise ValueError(
            "mark_jobs_closed requires a non-empty source_id"
        )
    if not job_ids:
        return

    cursor = conn.cursor()
    placeholders = _build_id_placeholders(job_ids)

    cursor.execute(
        f"UPDATE {_JOBS_TABLE} SET status = 'CLOSED', closed_on = %s "
        f"WHERE source_id = %s AND id IN ({placeholders})",
        [timestamp, source_id] + job_ids
    )

    affected = cursor.rowcount
    conn.commit()
    if affected != len(job_ids):
        logger.warning(
            "mark_jobs_closed affected %d/%d rows for source_id=%s — "
            "%d ids did not match the composite (source_id, id) key",
            affected, len(job_ids), source_id, len(job_ids) - affected,
        )
    else:
        logger.info(
            "Marked %d/%d jobs as CLOSED (source_id=%s)",
            affected, len(job_ids), source_id,
        )


def get_jobs_exceeding_miss_threshold(
    conn: Connection, source_id: str, job_ids: List[str], threshold: int
) -> Set[str]:
    """
    Get job IDs where consecutive_misses >= threshold in a single query.

    Args:
        conn: Database connection
        source_id: Source namespace; ``job_ids`` must all belong to this
            source. Must be non-empty; an empty value would silently return
            an empty set and skip the close phase.
        job_ids: List of job IDs to check
        threshold: Minimum consecutive_misses value

    Returns:
        Set of job IDs that have consecutive_misses >= threshold
    """
    if not source_id:
        raise ValueError(
            "get_jobs_exceeding_miss_threshold requires a non-empty source_id"
        )
    if not job_ids:
        return set()

    cursor = conn.cursor()
    placeholders = _build_id_placeholders(job_ids)

    cursor.execute(
        f"SELECT id FROM {_JOBS_TABLE} "
        f"WHERE source_id = %s AND id IN ({placeholders}) "
        f"AND consecutive_misses >= %s",
        [source_id] + job_ids + [threshold]
    )

    return {row['id'] for row in cursor.fetchall()}


def reactivate_job(
    conn: Connection, source_id: str, job_id: str, timestamp: str
) -> None:
    """
    Reactivate a closed job (if it reappears in search results).

    **Contract: the (source_id, id) row MUST already exist.** Callers are
    expected to look up the job first (e.g. via ``get_job_by_id``) and only
    call ``reactivate_job`` when they have confirmed the row is present —
    typically when a previously-closed job reappears in a scrape. The
    ``affected != 1`` branch therefore logs a WARNING (not an INFO):
    reaching it means a caller violated the contract and the reactivation
    silently no-op'd, which is a real bug worth surfacing in Railway logs.

    Today's tests (``scripts/tests/integration/test_database.py``) are the
    only callers; they always insert + close + reactivate, so the warning
    only ever fires on regression.

    Args:
        conn: Database connection
        source_id: Source namespace. Must be non-empty; an empty value
            would silently match zero rows and the WARN log below would be
            the only signal.
        job_id: Job ID to reactivate
        timestamp: ISO 8601 timestamp
    """
    if not source_id:
        raise ValueError(
            "reactivate_job requires a non-empty source_id"
        )
    cursor = conn.cursor()

    cursor.execute(
        f"UPDATE {_JOBS_TABLE} SET status = 'OPEN', closed_on = NULL, "
        f"last_seen_at = %s, consecutive_misses = 0 "
        f"WHERE source_id = %s AND id = %s",
        (timestamp, source_id, job_id)
    )

    affected = cursor.rowcount
    conn.commit()
    if affected != 1:
        logger.warning(
            "reactivate_job affected %d/1 rows for source_id=%s id=%s — "
            "no row matched the composite (source_id, id) key (contract "
            "violation: caller must ensure the row exists before calling)",
            affected, source_id, job_id,
        )
    else:
        logger.info(f"Reactivated job: {job_id} (source_id={source_id})")


def record_scrape_run(conn: Connection, run_data: ScrapeRun) -> None:
    """
    Record metadata about a scrape run

    Args:
        conn: Database connection
        run_data: ScrapeRun model
    """
    cursor = conn.cursor()

    cursor.execute(
        f"""
        INSERT INTO {_RUNS_TABLE} (
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


def get_all_active_jobs(conn: Connection, company: str) -> List[JobListing]:
    """
    Get all active jobs for a company

    Args:
        conn: Database connection
        company: Company name

    Returns:
        List of JobListing objects
    """
    cursor = conn.cursor()

    cursor.execute(
        f"SELECT * FROM {_JOBS_TABLE} WHERE company = %s AND status = 'OPEN'",
        (company,)
    )

    jobs = []
    for row in cursor.fetchall():
        row_dict = dict(row)
        for json_col in ('details', 'ai_metadata'):
            if isinstance(row_dict.get(json_col), str):
                row_dict[json_col] = json.loads(row_dict[json_col])
        # Timestamptz columns come back as tz-aware `datetime` objects, but
        # JobListing models these as ISO 8601 strings (scraper-side contract).
        # Normalize to `datetime.isoformat()` — note this emits `+00:00` (not
        # `Z`) as the UTC offset, a one-way wire-format shift once data flows
        # through this path. All current callers accept both since they pass
        # through `datetime.fromisoformat(v.replace("Z", "+00:00"))`.
        # We intentionally restrict the branch to `datetime` so unexpected
        # types (bytes, Decimal, malformed strings) surface loudly rather
        # than silently no-op past this conversion.
        for ts_col in ('posted_on', 'created_at', 'closed_on', 'first_seen_at', 'last_seen_at'):
            value = row_dict.get(ts_col)
            if value is None:
                continue
            if isinstance(value, datetime):
                row_dict[ts_col] = value.isoformat()
            elif isinstance(value, str):
                # Post-0003/0004 every row is `datetime`. A `str` here means
                # schema drift (column reverted to TEXT, or a new TEXT column
                # was added) — log so the regression is grep-able rather than
                # silently passing strings through.
                logger.warning(
                    "Schema drift suspected: %s.%s is str (expected tz-aware "
                    "datetime post-0003/0004)",
                    _JOBS_TABLE, ts_col,
                )
                continue
            else:
                raise TypeError(
                    f"Unexpected type for {_JOBS_TABLE}.{ts_col}: "
                    f"{type(value).__name__} (expected datetime, str, or None)"
                )
        jobs.append(JobListing(**row_dict))

    return jobs
