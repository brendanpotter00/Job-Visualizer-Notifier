"""Tests for database connection pool management (dependencies.py)."""

from unittest.mock import MagicMock, patch, PropertyMock

import psycopg2.extensions
import pytest

from api.dependencies import get_db, pool_is_healthy


class TestPoolIsHealthy:
    def test_returns_false_when_pool_is_none(self):
        with patch("api.dependencies._pool", None):
            assert pool_is_healthy() is False

    def test_returns_false_when_pool_is_closed(self):
        mock_pool = MagicMock()
        mock_pool.closed = True
        with patch("api.dependencies._pool", mock_pool):
            assert pool_is_healthy() is False

    def test_returns_true_when_pool_is_open(self):
        mock_pool = MagicMock()
        mock_pool.closed = False
        with patch("api.dependencies._pool", mock_pool):
            assert pool_is_healthy() is True


class TestGetDb:
    def test_raises_when_pool_not_initialized(self):
        with patch("api.dependencies._pool", None):
            gen = get_db()
            with pytest.raises(RuntimeError, match="Connection pool not initialized"):
                next(gen)

    def test_replaces_closed_connection(self):
        closed_conn = MagicMock()
        closed_conn.closed = True

        good_conn = MagicMock()
        good_conn.closed = False
        good_conn.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE

        mock_pool = MagicMock()
        mock_pool.getconn = MagicMock(side_effect=[closed_conn, good_conn])

        with patch("api.dependencies._pool", mock_pool):
            gen = get_db()
            conn = next(gen)
            assert conn is good_conn
            mock_pool.putconn.assert_any_call(closed_conn, close=True)
            # Cleanup
            try:
                next(gen)
            except StopIteration:
                pass

    def test_resets_bad_transaction_state(self):
        conn = MagicMock()
        conn.closed = False
        conn.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_INERROR

        mock_pool = MagicMock()
        mock_pool.getconn = MagicMock(return_value=conn)

        with patch("api.dependencies._pool", mock_pool):
            gen = get_db()
            yielded = next(gen)
            assert yielded is conn
            conn.rollback.assert_called_once()
            try:
                next(gen)
            except StopIteration:
                pass

    def test_rollbacks_on_exception(self):
        conn = MagicMock()
        conn.closed = False
        conn.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE

        mock_pool = MagicMock()
        mock_pool.getconn = MagicMock(return_value=conn)

        with patch("api.dependencies._pool", mock_pool):
            gen = get_db()
            next(gen)
            with pytest.raises(ValueError):
                gen.throw(ValueError("test error"))
            conn.rollback.assert_called_once()

    def test_returns_connection_to_pool(self):
        conn = MagicMock()
        conn.closed = False
        conn.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE

        mock_pool = MagicMock()
        mock_pool.getconn = MagicMock(return_value=conn)

        with patch("api.dependencies._pool", mock_pool):
            gen = get_db()
            next(gen)
            try:
                next(gen)
            except StopIteration:
                pass
            mock_pool.putconn.assert_called_with(conn)
