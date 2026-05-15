"""FastAPI dependencies for database connection management."""

import logging
import os
import re
import threading
import uuid
from typing import Generator

import psycopg2.extensions
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None
_pool_semaphore: threading.Semaphore | None = None
_pool_timeout: float = 5.0

# Identifier safety: interpolated into SET search_path below.
_PYTEST_SCHEMA_RE = re.compile(r"^(?:public|test_[a-f0-9]{8,})$")


def init_pool(dsn: str, minconn: int = 1, maxconn: int = 15, timeout: float = 5.0) -> None:
    """Create the connection pool. Called once during app lifespan startup."""
    global _pool, _pool_semaphore, _pool_timeout
    _pool = ThreadedConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        dsn=dsn,
        cursor_factory=RealDictCursor,
    )
    _pool_semaphore = threading.Semaphore(maxconn)
    _pool_timeout = timeout
    logger.info("Database connection pool created (min=%d, max=%d, timeout=%.1fs)", minconn, maxconn, timeout)


def close_pool() -> None:
    """Close all connections in the pool. Called during app lifespan shutdown."""
    global _pool, _pool_semaphore
    if _pool is not None:
        _pool.closeall()
        _pool = None
        _pool_semaphore = None
        logger.info("Database connection pool closed")


def pool_is_healthy() -> bool:
    """Check whether the connection pool is available and not closed."""
    return _pool is not None and not _pool.closed


def get_db() -> Generator[psycopg2.extensions.connection, None, None]:
    """FastAPI dependency that yields a connection from the pool.

    Uses a semaphore so requests wait for a free connection instead of
    getting an immediate PoolError when the pool is exhausted.

    Checks for stale connections before yielding. Rolls back on error to
    prevent leaving the connection in an aborted transaction state, then
    returns it to the pool.

    When PYTEST_SCHEMA is set, pins the connection's search_path to the
    test schema before yielding. `SET search_path` persists on the psycopg2
    connection across putconn/getconn cycles within the same process, so
    reapplying on each checkout is defensive but cheap (one round-trip).

    Note: connections are NOT auto-committed. Callers performing writes
    must call conn.commit() explicitly.
    """
    if _pool is None or _pool_semaphore is None:
        raise RuntimeError("Connection pool not initialized")
    pool = _pool  # Capture reference before yield to avoid shutdown race
    semaphore = _pool_semaphore

    if not semaphore.acquire(timeout=_pool_timeout):
        raise RuntimeError("Timed out waiting for a database connection")

    # Use an explicit key instead of the default thread-id key.
    # FastAPI runs __enter__ and __exit__ of sync generators in different
    # threads via run_in_threadpool, so thread-based keying leaks connections.
    key = str(uuid.uuid4())
    conn = pool.getconn(key=key)
    try:
        if conn.closed:
            logger.warning("Pool returned a closed connection, replacing")
            pool.putconn(conn, key=key, close=True)
            conn = pool.getconn(key=key)
            if conn.closed:
                pool.putconn(conn, key=key, close=True)
                raise RuntimeError("Pool unable to provide a healthy connection")
        elif conn.info.transaction_status != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
            logger.warning("Connection in unexpected transaction state, resetting")
            conn.rollback()
        # Probe for stale connections whose TCP socket is broken but
        # conn.closed still reads as 0 (e.g. after a database restart).
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.rollback()
        except Exception:
            logger.warning("Stale connection detected, replacing")
            pool.putconn(conn, key=key, close=True)
            conn = pool.getconn(key=key)
            if conn.closed:
                pool.putconn(conn, key=key, close=True)
                raise RuntimeError("Pool unable to provide a healthy connection")

        # Test-isolation hook: pin search_path per checkout when pytest
        # owns this process. Unset in prod and normal local dev.
        pytest_schema = os.environ.get("PYTEST_SCHEMA")
        if pytest_schema is not None:
            if not _PYTEST_SCHEMA_RE.match(pytest_schema):
                pool.putconn(conn, key=key, close=True)
                raise ValueError(
                    f"PYTEST_SCHEMA={pytest_schema!r} does not match expected "
                    f"pattern 'test_<hex>' or 'public'."
                )
            with conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{pytest_schema}", public')
            conn.rollback()  # SET search_path opens a transaction; reset it.

        yield conn
    except Exception:
        if not conn.closed:
            conn.rollback()
        raise
    finally:
        if not conn.closed:
            pool.putconn(conn, key=key)
        semaphore.release()
