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


def _insert_company(db_conn, cid, *, enabled=True, created_at="2021-01-01T00:00:00Z"):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled, created_at) "
        "VALUES (%s, %s, 'greenhouse', %s, %s, %s)",
        (cid, cid.title(), cid, enabled, created_at),
    )
    db_conn.commit()


def _set_watermark(db_conn, user_id, ts):
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE users SET company_enroll_watermark = %s WHERE id = %s", (ts, user_id)
    )
    db_conn.commit()


def _add_enabled_row(db_conn, user_id, cid):
    """Insert a stored row directly, WITHOUT bumping the watermark (unlike
    set_enabled_companies), so tests control the watermark independently."""
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO user_enabled_companies (user_id, company_id) VALUES (%s, %s)",
        (user_id, cid),
    )
    db_conn.commit()


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

    def test_persists_auto_enroll_toggle(self, db_conn):
        user_id = _seed_user(db_conn)
        set_enabled_companies(db_conn, user_id, ["alpha"], auto_enroll_new_companies=False)
        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT auto_enroll_new_companies FROM users WHERE id = %s", (user_id,)
        )
        assert cursor.fetchone()["auto_enroll_new_companies"] is False


class TestAutoEnrollMerge:
    """list_enabled_companies merges companies added after the watermark."""

    def test_merges_company_added_after_watermark(self, db_conn):
        user_id = _seed_user(db_conn)
        _add_enabled_row(db_conn, user_id, "alpha")
        _set_watermark(db_conn, user_id, "2020-01-01T00:00:00Z")
        _insert_company(db_conn, "beta", created_at="2021-01-01T00:00:00Z")
        assert list_enabled_companies(db_conn, user_id) == ["alpha", "beta"]

    def test_zero_row_user_stays_see_all(self, db_conn):
        """A user with no stored rows must resolve to [] (see-all), never get
        the merge — otherwise a brand-new signup is silently converted to an
        explicit list."""
        user_id = _seed_user(db_conn)
        _set_watermark(db_conn, user_id, "2020-01-01T00:00:00Z")
        _insert_company(db_conn, "beta", created_at="2021-01-01T00:00:00Z")
        assert list_enabled_companies(db_conn, user_id) == []

    def test_forward_only_ignores_company_before_watermark(self, db_conn):
        user_id = _seed_user(db_conn)
        _add_enabled_row(db_conn, user_id, "alpha")
        _set_watermark(db_conn, user_id, "2021-06-01T00:00:00Z")
        _insert_company(db_conn, "old", created_at="2021-01-01T00:00:00Z")
        assert list_enabled_companies(db_conn, user_id) == ["alpha"]

    def test_disabled_company_not_merged(self, db_conn):
        user_id = _seed_user(db_conn)
        _add_enabled_row(db_conn, user_id, "alpha")
        _set_watermark(db_conn, user_id, "2020-01-01T00:00:00Z")
        _insert_company(db_conn, "beta", enabled=False, created_at="2021-01-01T00:00:00Z")
        assert list_enabled_companies(db_conn, user_id) == ["alpha"]

    def test_toggle_off_suppresses_merge(self, db_conn):
        user_id = _seed_user(db_conn)
        _add_enabled_row(db_conn, user_id, "alpha")
        _set_watermark(db_conn, user_id, "2020-01-01T00:00:00Z")
        cursor = db_conn.cursor()
        cursor.execute(
            "UPDATE users SET auto_enroll_new_companies = false WHERE id = %s", (user_id,)
        )
        db_conn.commit()
        _insert_company(db_conn, "beta", created_at="2021-01-01T00:00:00Z")
        assert list_enabled_companies(db_conn, user_id) == ["alpha"]

    def test_opt_out_sticks_after_save(self, db_conn):
        """A merged company that the user removes and saves must not re-merge:
        the save bumps the watermark past the company's created_at."""
        user_id = _seed_user(db_conn)
        _add_enabled_row(db_conn, user_id, "alpha")
        _set_watermark(db_conn, user_id, "2020-01-01T00:00:00Z")
        _insert_company(db_conn, "beta", created_at="2021-01-01T00:00:00Z")
        assert list_enabled_companies(db_conn, user_id) == ["alpha", "beta"]

        # User opts out of beta -> saves the set without it; watermark -> now().
        set_enabled_companies(db_conn, user_id, ["alpha"])
        assert list_enabled_companies(db_conn, user_id) == ["alpha"]
