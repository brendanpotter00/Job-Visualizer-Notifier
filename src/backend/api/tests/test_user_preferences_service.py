"""Unit tests for user_preferences_service.py CRUD operations."""

import psycopg2
import pytest
from psycopg2 import sql

from api.services.user_preferences_service import (
    list_enabled_companies,
    set_enabled_companies,
)

from .conftest import _insert_user, _make_user


def _seed_user(db_conn, overrides=None) -> str:
    user = _make_user(overrides)
    _insert_user(db_conn, user)
    return user["id"]


class TestListEnabledCompanies:
    def test_returns_empty_list_when_no_rows(self, db_conn):
        user_id = _seed_user(db_conn)
        assert list_enabled_companies(db_conn, user_id) == []

    def test_returns_sorted_list(self, db_conn):
        user_id = _seed_user(db_conn)
        set_enabled_companies(db_conn, user_id, ["c", "a", "b"])
        assert list_enabled_companies(db_conn, user_id) == ["a", "b", "c"]

    def test_isolates_users(self, db_conn):
        user_a = _seed_user(db_conn, {"email": "a@example.com", "auth0_id": "auth0|a"})
        user_b = _seed_user(db_conn, {"email": "b@example.com", "auth0_id": "auth0|b"})
        set_enabled_companies(db_conn, user_a, ["airbnb"])
        set_enabled_companies(db_conn, user_b, ["stripe"])
        assert list_enabled_companies(db_conn, user_a) == ["airbnb"]
        assert list_enabled_companies(db_conn, user_b) == ["stripe"]


class TestSetEnabledCompanies:
    def test_stores_sorted_dedup(self, db_conn):
        user_id = _seed_user(db_conn)
        result = set_enabled_companies(db_conn, user_id, ["c", "a", "b"])
        assert result == ["a", "b", "c"]
        assert list_enabled_companies(db_conn, user_id) == ["a", "b", "c"]

    def test_dedupes_input(self, db_conn):
        user_id = _seed_user(db_conn)
        result = set_enabled_companies(db_conn, user_id, ["a", "a", "b"])
        assert result == ["a", "b"]
        assert list_enabled_companies(db_conn, user_id) == ["a", "b"]

    def test_empty_list_clears_existing(self, db_conn):
        user_id = _seed_user(db_conn)
        set_enabled_companies(db_conn, user_id, ["a", "b"])
        result = set_enabled_companies(db_conn, user_id, [])
        assert result == []
        assert list_enabled_companies(db_conn, user_id) == []

    def test_replaces_previous_set(self, db_conn):
        user_id = _seed_user(db_conn)
        set_enabled_companies(db_conn, user_id, ["a", "b", "c"])
        set_enabled_companies(db_conn, user_id, ["x", "y"])
        assert list_enabled_companies(db_conn, user_id) == ["x", "y"]

    def test_round_trip(self, db_conn):
        user_id = _seed_user(db_conn)
        payload = ["zz", "alpha", "beta", "alpha"]
        saved = set_enabled_companies(db_conn, user_id, payload)
        assert saved == list_enabled_companies(db_conn, user_id)
        assert saved == ["alpha", "beta", "zz"]

    def test_cascade_delete_when_user_removed(self, db_conn):
        user_id = _seed_user(db_conn)
        set_enabled_companies(db_conn, user_id, ["a", "b"])

        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier("users")),
            (user_id,),
        )
        db_conn.commit()

        assert list_enabled_companies(db_conn, user_id) == []

    def test_database_error_triggers_rollback(self):
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.OperationalError("connection lost")

        with pytest.raises(psycopg2.OperationalError, match="connection lost"):
            set_enabled_companies(mock_conn, "user-id", ["a"])
        mock_conn.rollback.assert_called_once()
