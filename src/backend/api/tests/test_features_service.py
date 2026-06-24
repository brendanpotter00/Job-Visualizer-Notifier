"""Unit tests for features_service.py."""

from datetime import datetime, timezone

import pytest
from psycopg2 import sql

from api.services.features_service import (
    FeatureNotFound,
    add_upvote,
    list_features_with_upvotes,
    remove_upvote,
)

from .conftest import _insert_user, _make_user


def _insert_feature(db_conn, feature_id, title="T", description="D", completed_at=None):
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, description, completed_at)"
            " VALUES (%s, %s, %s, %s)"
        ).format(sql.Identifier("features")),
        (feature_id, title, description, completed_at),
    )
    db_conn.commit()


def _seed_user(db_conn, overrides=None):
    user = _make_user(overrides)
    _insert_user(db_conn, user)
    return user["id"]


class TestListFeaturesWithUpvotes:
    def test_empty_state_returns_empty_list(self, db_conn):
        assert list_features_with_upvotes(db_conn, user_id=None) == []

    def test_lists_features_with_zero_upvotes_when_none(self, db_conn):
        _insert_feature(db_conn, "f1", "Title 1", "Desc 1")
        _insert_feature(db_conn, "f2", "Title 2", "Desc 2")
        rows = list_features_with_upvotes(db_conn, user_id=None)
        assert {r["id"] for r in rows} == {"f1", "f2"}
        for r in rows:
            assert r["upvote_count"] == 0
            assert r["has_upvoted"] is False

    def test_has_upvoted_false_for_anonymous(self, db_conn):
        _insert_feature(db_conn, "f1")
        user_id = _seed_user(db_conn)
        add_upvote(db_conn, "f1", user_id)
        [row] = list_features_with_upvotes(db_conn, user_id=None)
        assert row["upvote_count"] == 1
        assert row["has_upvoted"] is False

    def test_has_upvoted_true_only_for_upvoter(self, db_conn):
        _insert_feature(db_conn, "f1")
        user_a = _seed_user(db_conn, {"auth0_id": "auth0|a", "email": "a@ex.com"})
        user_b = _seed_user(db_conn, {"auth0_id": "auth0|b", "email": "b@ex.com"})
        add_upvote(db_conn, "f1", user_a)
        rows_a = list_features_with_upvotes(db_conn, user_a)
        rows_b = list_features_with_upvotes(db_conn, user_b)
        assert rows_a[0]["has_upvoted"] is True
        assert rows_a[0]["upvote_count"] == 1
        assert rows_b[0]["has_upvoted"] is False
        assert rows_b[0]["upvote_count"] == 1

    def test_completed_at_is_none_by_default(self, db_conn):
        _insert_feature(db_conn, "f1")
        [row] = list_features_with_upvotes(db_conn, user_id=None)
        assert "completed_at" in row
        assert row["completed_at"] is None

    def test_completed_at_returned_when_set(self, db_conn):
        shipped = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        _insert_feature(db_conn, "f1", completed_at=shipped)
        # Authed path exercises the BOOL_OR branch's SELECT too.
        user_id = _seed_user(db_conn)
        [row] = list_features_with_upvotes(db_conn, user_id)
        assert row["completed_at"] == shipped


class TestAddUpvote:
    def test_adds_upvote(self, db_conn):
        _insert_feature(db_conn, "f1")
        user_id = _seed_user(db_conn)
        result = add_upvote(db_conn, "f1", user_id)
        assert result == {"feature_id": "f1", "upvote_count": 1, "has_upvoted": True}

    def test_double_add_is_idempotent(self, db_conn):
        _insert_feature(db_conn, "f1")
        user_id = _seed_user(db_conn)
        first = add_upvote(db_conn, "f1", user_id)
        second = add_upvote(db_conn, "f1", user_id)
        assert first == second == {"feature_id": "f1", "upvote_count": 1, "has_upvoted": True}

    def test_unknown_feature_raises_FeatureNotFound(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(FeatureNotFound):
            add_upvote(db_conn, "does-not-exist", user_id)

    def test_cascade_on_feature_delete(self, db_conn):
        _insert_feature(db_conn, "f1")
        user_id = _seed_user(db_conn)
        add_upvote(db_conn, "f1", user_id)
        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier("features")),
            ("f1",),
        )
        db_conn.commit()
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {}").format(
                sql.Identifier("feature_upvotes")
            )
        )
        assert cursor.fetchone()["n"] == 0

    def test_cascade_on_user_delete(self, db_conn):
        _insert_feature(db_conn, "f1")
        user_id = _seed_user(db_conn)
        add_upvote(db_conn, "f1", user_id)
        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE id = %s").format(
                sql.Identifier("users")
            ),
            (user_id,),
        )
        db_conn.commit()
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {}").format(
                sql.Identifier("feature_upvotes")
            )
        )
        assert cursor.fetchone()["n"] == 0


class TestRemoveUpvote:
    def test_removes_existing_upvote(self, db_conn):
        _insert_feature(db_conn, "f1")
        user_id = _seed_user(db_conn)
        add_upvote(db_conn, "f1", user_id)
        result = remove_upvote(db_conn, "f1", user_id)
        assert result == {"feature_id": "f1", "upvote_count": 0, "has_upvoted": False}

    def test_remove_without_prior_upvote_is_idempotent(self, db_conn):
        _insert_feature(db_conn, "f1")
        user_id = _seed_user(db_conn)
        result = remove_upvote(db_conn, "f1", user_id)
        assert result == {"feature_id": "f1", "upvote_count": 0, "has_upvoted": False}

    def test_double_remove_is_idempotent(self, db_conn):
        _insert_feature(db_conn, "f1")
        user_id = _seed_user(db_conn)
        add_upvote(db_conn, "f1", user_id)
        remove_upvote(db_conn, "f1", user_id)
        second = remove_upvote(db_conn, "f1", user_id)
        assert second == {"feature_id": "f1", "upvote_count": 0, "has_upvoted": False}

    def test_remove_preserves_other_users_upvotes(self, db_conn):
        _insert_feature(db_conn, "f1")
        ua = _seed_user(db_conn, {"auth0_id": "auth0|a", "email": "a@ex.com"})
        ub = _seed_user(db_conn, {"auth0_id": "auth0|b", "email": "b@ex.com"})
        add_upvote(db_conn, "f1", ua)
        add_upvote(db_conn, "f1", ub)
        result = remove_upvote(db_conn, "f1", ua)
        assert result["upvote_count"] == 1
        rows_b = list_features_with_upvotes(db_conn, ub)
        assert rows_b[0]["has_upvoted"] is True
        assert rows_b[0]["upvote_count"] == 1

    def test_unknown_feature_raises_FeatureNotFound(self, db_conn):
        user_id = _seed_user(db_conn)
        with pytest.raises(FeatureNotFound):
            remove_upvote(db_conn, "does-not-exist", user_id)
