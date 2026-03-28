"""FastAPI dependencies for database connection management."""

import logging
from typing import Generator

import psycopg2.extensions
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

_pool: ThreadedConnectionPool | None = None


def init_pool(dsn: str, minconn: int = 2, maxconn: int = 10) -> None:
    """Create the connection pool. Called once during app lifespan startup."""
    global _pool
    _pool = ThreadedConnectionPool(
        minconn=minconn,
        maxconn=maxconn,
        dsn=dsn,
        cursor_factory=RealDictCursor,
    )
    logger.info("Database connection pool created (min=%d, max=%d)", minconn, maxconn)


def close_pool() -> None:
    """Close all connections in the pool. Called during app lifespan shutdown."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Database connection pool closed")


def pool_is_healthy() -> bool:
    """Check whether the connection pool is available and not closed."""
    return _pool is not None and not _pool.closed


def get_db() -> Generator[psycopg2.extensions.connection, None, None]:
    """FastAPI dependency that yields a connection from the pool.

    Checks for stale connections before yielding. Rolls back on error to
    prevent leaving the connection in an aborted transaction state, then
    returns it to the pool.

    Note: connections are NOT auto-committed. Callers performing writes
    must call conn.commit() explicitly.
    """
    if _pool is None:
        raise RuntimeError("Connection pool not initialized")
    conn = _pool.getconn()
    try:
        if conn.closed:
            logger.warning("Pool returned a closed connection, replacing")
            _pool.putconn(conn, close=True)
            conn = _pool.getconn()
        else:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                conn.rollback()
            except Exception:
                logger.warning("Stale connection detected, replacing")
                _pool.putconn(conn, close=True)
                conn = _pool.getconn()
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)
