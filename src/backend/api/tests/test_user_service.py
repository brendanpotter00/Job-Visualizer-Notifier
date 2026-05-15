"""Unit tests for user_service.py CRUD operations."""

import psycopg2
import pytest
from psycopg2 import sql

from api.services.user_service import get_or_create_user, update_user

from .conftest import _make_user, _insert_user


class TestGetOrCreateUser:
    def test_creates_new_user(self, db_conn):
        """get_or_create_user inserts a new user when neither key matches."""
        result = get_or_create_user(
            db_conn,
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

    def test_upsert_updates_token_fields_on_email_match(self, db_conn):
        """Cross-provider merge: same email, different auth0_id → UPDATE existing row."""
        user = _make_user({
            "auth0_id": "auth0|upsert_test",
            "email": "shared@example.com",
            "display_name": "Custom Name",
            "given_name": "Old",
            "family_name": "Name",
        })
        _insert_user(db_conn, user)

        result = get_or_create_user(
            db_conn,
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
        # display_name is NOT in the UPDATE SET clause, so it's preserved
        assert result["display_name"] == "Custom Name"

    def test_upsert_preserves_original_id(self, db_conn):
        """Existing row's id is preserved across cross-provider re-login."""
        user = _make_user({"auth0_id": "auth0|id_test", "email": "id_test@example.com"})
        _insert_user(db_conn, user)

        result = get_or_create_user(
            db_conn,
            auth0_id="auth0|id_test",
            email="id_test@example.com",
        )
        assert result["id"] == user["id"]

    def test_cross_provider_login_merges_to_one_row(self, db_conn):
        """Two different auth0_ids sharing an email resolve to ONE row."""
        first = get_or_create_user(
            db_conn,
            auth0_id="auth0|alice",
            email="alice@example.com",
        )
        second = get_or_create_user(
            db_conn,
            auth0_id="google|alice",
            email="alice@example.com",
        )
        assert second["id"] == first["id"]
        assert second["auth0_id"] == "google|alice"

        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE email = %s").format(
                sql.Identifier("users")
            ),
            ("alice@example.com",),
        )
        assert cursor.fetchone()["n"] == 1

    def test_idp_email_change_updates_existing_row(self, db_conn):
        """Same auth0_id, new email → UPDATE existing row's email. One row, not two.

        This is the IdP email-change case. A prior design dropped
        UNIQUE(auth0_id) to avoid crashing here, but that silently created a
        duplicate row. The two-key lookup matches by auth0_id and UPDATEs the
        email field instead.
        """
        existing = _make_user({
            "auth0_id": "auth0|email_change",
            "email": "old@example.com",
            "display_name": "Custom",
        })
        _insert_user(db_conn, existing)

        result = get_or_create_user(
            db_conn,
            auth0_id="auth0|email_change",
            email="new@example.com",
        )
        assert result["id"] == existing["id"], "should update the existing row"
        assert result["email"] == "new@example.com"
        assert result["auth0_id"] == "auth0|email_change"
        assert result["display_name"] == "Custom"  # preserved

        # Exactly one row for this auth0_id, and zero for the old email
        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE auth0_id = %s").format(
                sql.Identifier("users")
            ),
            ("auth0|email_change",),
        )
        assert cursor.fetchone()["n"] == 1
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE email = %s").format(
                sql.Identifier("users")
            ),
            ("old@example.com",),
        )
        assert cursor.fetchone()["n"] == 0

    def test_ambiguous_identity_raises(self, db_conn):
        """Two pre-existing rows, one matches by auth0_id, the other by email
        → RuntimeError rather than silent merge.

        This should not happen under correct operation (both columns are UNIQUE
        and maintained by this service), but if the identity model is ever
        corrupted by external writes or a bug, surface it loudly.
        """
        row_a = _make_user({
            "auth0_id": "auth0|person_a",
            "email": "a@example.com",
            "id": "row_a_id",
        })
        row_b = _make_user({
            "auth0_id": "auth0|person_b",
            "email": "b@example.com",
            "id": "row_b_id",
        })
        _insert_user(db_conn, row_a)
        _insert_user(db_conn, row_b)

        # Token claims: auth0_id matches row A, email matches row B — ambiguous
        with pytest.raises(RuntimeError, match="Ambiguous identity"):
            get_or_create_user(
                db_conn,
                auth0_id="auth0|person_a",
                email="b@example.com",
            )

    def test_concurrent_first_login_is_idempotent(self, db_conn):
        """Two sequential upserts for the same user produce one row."""
        first = get_or_create_user(
            db_conn,
            auth0_id="auth0|rapid",
            email="rapid@example.com",
        )
        second = get_or_create_user(
            db_conn,
            auth0_id="auth0|rapid",
            email="rapid@example.com",
        )
        assert second["id"] == first["id"]

        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE email = %s").format(
                sql.Identifier("users")
            ),
            ("rapid@example.com",),
        )
        assert cursor.fetchone()["n"] == 1

    def test_unique_violation_retries_once(self, db_conn):
        """Simulated UniqueViolation on first attempt retries and succeeds.

        Models the concurrent-first-login race: two transactions SELECT empty,
        both INSERT, the second hits UniqueViolation. The retry re-runs SELECT,
        finds the row the other transaction just committed, and UPDATEs it.
        """
        from unittest.mock import patch

        # Pre-insert the row that the "other transaction" would have created.
        user = _make_user({
            "auth0_id": "auth0|race",
            "email": "race@example.com",
        })
        _insert_user(db_conn, user)

        # Patch _lookup_and_upsert to raise UniqueViolation on first call,
        # then delegate to the real implementation on second call.
        from api.services import user_service

        real = user_service._lookup_and_upsert
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise psycopg2.errors.UniqueViolation("simulated race")
            return real(*args, **kwargs)

        with patch.object(user_service, "_lookup_and_upsert", side_effect=flaky):
            result = get_or_create_user(
                db_conn,
                auth0_id="auth0|race",
                email="race@example.com",
            )

        assert calls["n"] == 2, "should retry exactly once"
        assert result["id"] == user["id"]

    def test_handles_null_optional_fields(self, db_conn):
        """get_or_create_user works when optional fields are None."""
        result = get_or_create_user(
            db_conn,
            auth0_id="auth0|null_test",
            email="null@example.com",
        )
        assert result["given_name"] is None
        assert result["family_name"] is None
        assert result["picture_url"] is None

    def test_database_error_triggers_rollback(self):
        """Non-unique DB errors are caught, rolled back, and re-raised."""
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.OperationalError("connection lost")

        with pytest.raises(psycopg2.OperationalError, match="connection lost"):
            get_or_create_user(
                mock_conn, auth0_id="auth0|err", email="err@example.com"
            )
        mock_conn.rollback.assert_called_once()


class TestUpdateUser:
    def test_updates_display_name(self, db_conn):
        """update_user sets the display_name field, keyed by email."""
        user = _make_user({"email": "update@example.com"})
        _insert_user(db_conn, user)

        result = update_user(
            db_conn, email="update@example.com", display_name="Updated Name"
        )
        assert result is not None
        assert result["display_name"] == "Updated Name"
        assert result["email"] == "update@example.com"

    def test_clears_display_name_with_none(self, db_conn):
        """update_user can clear display_name by passing None."""
        user = _make_user({"email": "clear@example.com", "display_name": "Has Name"})
        _insert_user(db_conn, user)

        result = update_user(
            db_conn, email="clear@example.com", display_name=None
        )
        assert result is not None
        assert result["display_name"] is None

    def test_returns_none_for_nonexistent_user(self, db_conn):
        """update_user returns None when the email doesn't exist."""
        result = update_user(
            db_conn, email="nonexistent@example.com", display_name="Name"
        )
        assert result is None

    def test_updates_updated_at_timestamp(self, db_conn):
        """update_user refreshes the updated_at timestamp."""
        user = _make_user({
            "email": "ts@example.com",
            "updated_at": "2020-01-01T00:00:00Z",
        })
        _insert_user(db_conn, user)

        result = update_user(
            db_conn, email="ts@example.com", display_name="New"
        )
        assert result["updated_at"] != "2020-01-01T00:00:00Z"

    def test_database_error_triggers_rollback(self):
        """Database errors are caught, connection is rolled back, and error is re-raised."""
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.OperationalError("connection lost")

        with pytest.raises(psycopg2.OperationalError, match="connection lost"):
            update_user(mock_conn, email="err@example.com", display_name="x")
        mock_conn.rollback.assert_called_once()
