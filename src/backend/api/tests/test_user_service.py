"""Unit tests for user_service.py CRUD operations."""

import uuid

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from api.services.user_service import get_or_create_user, update_user
from scripts.shared.database import _get_table_name

from .conftest import _make_user, _insert_user


class TestGetOrCreateUser:
    def test_creates_new_user(self, db_conn, test_env):
        """get_or_create_user inserts a new user when auth0_id doesn't exist."""
        result = get_or_create_user(
            db_conn,
            test_env,
            auth0_id="auth0|new_user_001",
            email="new@example.com",
            given_name="New",
            family_name="User",
            picture_url="https://example.com/pic.jpg",
        )
        assert result["auth0_id"] == "auth0|new_user_001"
        assert result["email"] == "new@example.com"
        assert result["given_name"] == "New"
        assert result["family_name"] == "User"
        assert result["picture_url"] == "https://example.com/pic.jpg"
        assert result["display_name"] is None
        assert result["id"] is not None

    def test_upsert_updates_token_fields_on_conflict(self, db_conn, test_env):
        """On email conflict, upsert updates auth0_id/name/picture but NOT display_name."""
        user = _make_user({
            "auth0_id": "auth0|upsert_test",
            "email": "shared@example.com",
            "display_name": "Custom Name",
            "given_name": "Old",
            "family_name": "Name",
        })
        _insert_user(db_conn, test_env, user)

        result = get_or_create_user(
            db_conn,
            test_env,
            auth0_id="google|upsert_test",  # different provider, same human
            email="shared@example.com",
            given_name="New",
            family_name="Person",
            picture_url="https://example.com/new.jpg",
        )
        # auth0_id IS updated — tracks the most recent login provider
        assert result["auth0_id"] == "google|upsert_test"
        assert result["given_name"] == "New"
        assert result["family_name"] == "Person"
        assert result["picture_url"] == "https://example.com/new.jpg"
        # display_name is NOT in the ON CONFLICT SET clause, so it's preserved
        assert result["display_name"] == "Custom Name"

    def test_upsert_preserves_original_id(self, db_conn, test_env):
        """On email conflict, the original row ID is preserved (not replaced)."""
        user = _make_user({"auth0_id": "auth0|id_test", "email": "id_test@example.com"})
        _insert_user(db_conn, test_env, user)

        result = get_or_create_user(
            db_conn,
            test_env,
            auth0_id="auth0|id_test",
            email="id_test@example.com",
        )
        assert result["id"] == user["id"]

    def test_cross_provider_login_merges_to_one_row(self, db_conn, test_env):
        """Two different auth0_ids sharing an email resolve to ONE row (email is identity)."""
        first = get_or_create_user(
            db_conn,
            test_env,
            auth0_id="auth0|alice",
            email="alice@example.com",
        )
        second = get_or_create_user(
            db_conn,
            test_env,
            auth0_id="google|alice",
            email="alice@example.com",
        )
        assert second["id"] == first["id"]
        assert second["auth0_id"] == "google|alice"

        # Exactly one row in DB for this email
        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE email = %s").format(
                sql.Identifier(_get_table_name(test_env, "users"))
            ),
            ("alice@example.com",),
        )
        assert cursor.fetchone()["n"] == 1

    def test_concurrent_first_login_is_idempotent(self, db_conn, test_env):
        """Two rapid upserts for the same user produce one row and return the same id."""
        first = get_or_create_user(
            db_conn,
            test_env,
            auth0_id="auth0|rapid",
            email="rapid@example.com",
        )
        second = get_or_create_user(
            db_conn,
            test_env,
            auth0_id="auth0|rapid",
            email="rapid@example.com",
        )
        assert second["id"] == first["id"]

        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE email = %s").format(
                sql.Identifier(_get_table_name(test_env, "users"))
            ),
            ("rapid@example.com",),
        )
        assert cursor.fetchone()["n"] == 1

    def test_handles_null_optional_fields(self, db_conn, test_env):
        """get_or_create_user works when optional fields are None."""
        result = get_or_create_user(
            db_conn,
            test_env,
            auth0_id="auth0|null_test",
            email="null@example.com",
        )
        assert result["given_name"] is None
        assert result["family_name"] is None
        assert result["picture_url"] is None

    def test_database_error_triggers_rollback(self, test_env):
        """Database errors are caught, connection is rolled back, and error is re-raised."""
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.OperationalError("connection lost")

        with pytest.raises(psycopg2.OperationalError, match="connection lost"):
            get_or_create_user(
                mock_conn, test_env, auth0_id="auth0|err", email="err@example.com"
            )
        mock_conn.rollback.assert_called_once()


class TestUpdateUser:
    def test_updates_display_name(self, db_conn, test_env):
        """update_user sets the display_name field."""
        user = _make_user({"auth0_id": "auth0|update_test"})
        _insert_user(db_conn, test_env, user)

        result = update_user(db_conn, test_env, auth0_id="auth0|update_test", display_name="Updated Name")
        assert result is not None
        assert result["display_name"] == "Updated Name"
        assert result["auth0_id"] == "auth0|update_test"

    def test_clears_display_name_with_none(self, db_conn, test_env):
        """update_user can clear display_name by passing None."""
        user = _make_user({"auth0_id": "auth0|clear_test", "display_name": "Has Name"})
        _insert_user(db_conn, test_env, user)

        result = update_user(db_conn, test_env, auth0_id="auth0|clear_test", display_name=None)
        assert result is not None
        assert result["display_name"] is None

    def test_returns_none_for_nonexistent_user(self, db_conn, test_env):
        """update_user returns None when auth0_id doesn't exist."""
        result = update_user(db_conn, test_env, auth0_id="auth0|nonexistent", display_name="Name")
        assert result is None

    def test_updates_updated_at_timestamp(self, db_conn, test_env):
        """update_user refreshes the updated_at timestamp."""
        user = _make_user({"auth0_id": "auth0|ts_test", "updated_at": "2020-01-01T00:00:00Z"})
        _insert_user(db_conn, test_env, user)

        result = update_user(db_conn, test_env, auth0_id="auth0|ts_test", display_name="New")
        assert result["updated_at"] != "2020-01-01T00:00:00Z"

    def test_database_error_triggers_rollback(self, test_env):
        """Database errors are caught, connection is rolled back, and error is re-raised."""
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.OperationalError("connection lost")

        with pytest.raises(psycopg2.OperationalError, match="connection lost"):
            update_user(mock_conn, test_env, auth0_id="auth0|err", display_name="x")
        mock_conn.rollback.assert_called_once()
