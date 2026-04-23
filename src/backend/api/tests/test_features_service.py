"""Unit tests for features_service.py."""

import pytest
from psycopg2 import sql

from api.services.features_service import (
    FeatureNotFound,
    add_upvote,
    list_features_with_upvotes,
    remove_upvote,
)
from scripts.shared.database import _get_table_name

from .conftest import _insert_user, _make_user


def _insert_feature(db_conn, env, feature_id, title="T", description="D"):
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL("INSERT INTO {} (id, title, description) VALUES (%s, %s, %s)").format(
            sql.Identifier(f"features_{env}")
        ),
        (feature_id, title, description),
    )
    db_conn.commit()


def _seed_user(db_conn, test_env, overrides=None):
    user = _make_user(overrides)
    _insert_user(db_conn, test_env, user)
    return user["id"]


class TestListFeaturesWithUpvotes:
    def test_empty_state_returns_empty_list(self, db_conn, test_env):
        assert list_features_with_upvotes(db_conn, test_env, user_id=None) == []

    def test_lists_features_with_zero_upvotes_when_none(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1", "Title 1", "Desc 1")
        _insert_feature(db_conn, test_env, "f2", "Title 2", "Desc 2")
        rows = list_features_with_upvotes(db_conn, test_env, user_id=None)
        assert {r["id"] for r in rows} == {"f1", "f2"}
        for r in rows:
            assert r["upvote_count"] == 0
            assert r["has_upvoted"] is False

    def test_has_upvoted_false_for_anonymous(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        user_id = _seed_user(db_conn, test_env)
        add_upvote(db_conn, test_env, "f1", user_id)
        [row] = list_features_with_upvotes(db_conn, test_env, user_id=None)
        assert row["upvote_count"] == 1
        assert row["has_upvoted"] is False

    def test_has_upvoted_true_only_for_upvoter(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        user_a = _seed_user(db_conn, test_env, {"auth0_id": "auth0|a", "email": "a@ex.com"})
        user_b = _seed_user(db_conn, test_env, {"auth0_id": "auth0|b", "email": "b@ex.com"})
        add_upvote(db_conn, test_env, "f1", user_a)
        rows_a = list_features_with_upvotes(db_conn, test_env, user_a)
        rows_b = list_features_with_upvotes(db_conn, test_env, user_b)
        assert rows_a[0]["has_upvoted"] is True
        assert rows_a[0]["upvote_count"] == 1
        assert rows_b[0]["has_upvoted"] is False
        assert rows_b[0]["upvote_count"] == 1


class TestAddUpvote:
    def test_adds_upvote(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        user_id = _seed_user(db_conn, test_env)
        result = add_upvote(db_conn, test_env, "f1", user_id)
        assert result == {"feature_id": "f1", "upvote_count": 1, "has_upvoted": True}

    def test_double_add_is_idempotent(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        user_id = _seed_user(db_conn, test_env)
        first = add_upvote(db_conn, test_env, "f1", user_id)
        second = add_upvote(db_conn, test_env, "f1", user_id)
        assert first == second == {"feature_id": "f1", "upvote_count": 1, "has_upvoted": True}

    def test_unknown_feature_raises_FeatureNotFound(self, db_conn, test_env):
        user_id = _seed_user(db_conn, test_env)
        with pytest.raises(FeatureNotFound):
            add_upvote(db_conn, test_env, "does-not-exist", user_id)

    def test_cascade_on_feature_delete(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        user_id = _seed_user(db_conn, test_env)
        add_upvote(db_conn, test_env, "f1", user_id)
        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(f"features_{test_env}")),
            ("f1",),
        )
        db_conn.commit()
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {}").format(
                sql.Identifier(f"feature_upvotes_{test_env}")
            )
        )
        assert cursor.fetchone()["n"] == 0

    def test_cascade_on_user_delete(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        user_id = _seed_user(db_conn, test_env)
        add_upvote(db_conn, test_env, "f1", user_id)
        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE id = %s").format(
                sql.Identifier(_get_table_name(test_env, "users"))
            ),
            (user_id,),
        )
        db_conn.commit()
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {}").format(
                sql.Identifier(f"feature_upvotes_{test_env}")
            )
        )
        assert cursor.fetchone()["n"] == 0


class TestRemoveUpvote:
    def test_removes_existing_upvote(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        user_id = _seed_user(db_conn, test_env)
        add_upvote(db_conn, test_env, "f1", user_id)
        result = remove_upvote(db_conn, test_env, "f1", user_id)
        assert result == {"feature_id": "f1", "upvote_count": 0, "has_upvoted": False}

    def test_remove_without_prior_upvote_is_idempotent(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        user_id = _seed_user(db_conn, test_env)
        result = remove_upvote(db_conn, test_env, "f1", user_id)
        assert result == {"feature_id": "f1", "upvote_count": 0, "has_upvoted": False}

    def test_double_remove_is_idempotent(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        user_id = _seed_user(db_conn, test_env)
        add_upvote(db_conn, test_env, "f1", user_id)
        remove_upvote(db_conn, test_env, "f1", user_id)
        second = remove_upvote(db_conn, test_env, "f1", user_id)
        assert second == {"feature_id": "f1", "upvote_count": 0, "has_upvoted": False}

    def test_remove_preserves_other_users_upvotes(self, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        ua = _seed_user(db_conn, test_env, {"auth0_id": "auth0|a", "email": "a@ex.com"})
        ub = _seed_user(db_conn, test_env, {"auth0_id": "auth0|b", "email": "b@ex.com"})
        add_upvote(db_conn, test_env, "f1", ua)
        add_upvote(db_conn, test_env, "f1", ub)
        result = remove_upvote(db_conn, test_env, "f1", ua)
        assert result["upvote_count"] == 1
        rows_b = list_features_with_upvotes(db_conn, test_env, ub)
        assert rows_b[0]["has_upvoted"] is True
        assert rows_b[0]["upvote_count"] == 1

    def test_unknown_feature_raises_FeatureNotFound(self, db_conn, test_env):
        user_id = _seed_user(db_conn, test_env)
        with pytest.raises(FeatureNotFound):
            remove_upvote(db_conn, test_env, "does-not-exist", user_id)
