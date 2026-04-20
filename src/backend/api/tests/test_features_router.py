"""Integration tests for features router (GET/POST/DELETE /api/features)."""

from unittest.mock import patch

import psycopg2
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth.dependencies import get_current_user, get_optional_user


def _insert_feature(db_conn, env, feature_id, title="T", description="D"):
    cursor = db_conn.cursor()
    cursor.execute(
        sql.SQL("INSERT INTO {} (id, title, description) VALUES (%s, %s, %s)").format(
            sql.Identifier(f"features_{env}")
        ),
        (feature_id, title, description),
    )
    db_conn.commit()


class TestListFeaturesAnonymous:
    def test_returns_empty_list_when_no_features(self, test_app, db_conn, test_env):
        test_app.dependency_overrides[get_optional_user] = lambda: None
        try:
            client = TestClient(test_app)
            resp = client.get("/api/features")
            assert resp.status_code == 200
            assert resp.json() == {"features": []}
        finally:
            test_app.dependency_overrides.pop(get_optional_user, None)

    def test_returns_features_with_has_upvoted_false(self, test_app, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1", "Title 1", "Desc 1")
        test_app.dependency_overrides[get_optional_user] = lambda: None
        try:
            client = TestClient(test_app)
            resp = client.get("/api/features")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["features"]) == 1
            feat = data["features"][0]
            assert feat["id"] == "f1"
            assert feat["title"] == "Title 1"
            assert feat["description"] == "Desc 1"
            assert feat["upvoteCount"] == 0
            assert feat["hasUpvoted"] is False
            assert "createdAt" in feat
        finally:
            test_app.dependency_overrides.pop(get_optional_user, None)

    def test_camel_case_keys(self, test_app, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        test_app.dependency_overrides[get_optional_user] = lambda: None
        try:
            client = TestClient(test_app)
            data = client.get("/api/features").json()
            feat = data["features"][0]
            assert set(feat.keys()) == {
                "id", "title", "description", "createdAt",
                "upvoteCount", "hasUpvoted",
            }
        finally:
            test_app.dependency_overrides.pop(get_optional_user, None)


class TestListFeaturesAuthed:
    def test_has_upvoted_reflects_own_upvote(self, test_app, client, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        resp_post = client.post("/api/features/f1/upvote")
        assert resp_post.status_code == 200
        test_app.dependency_overrides[get_optional_user] = lambda: {
            "sub": "auth0|test_user_123",
            "email": "test@example.com",
            "given_name": "Test",
            "family_name": "User",
            "picture": "https://example.com/photo.jpg",
        }
        try:
            resp_get = client.get("/api/features")
            assert resp_get.status_code == 200
            feat = resp_get.json()["features"][0]
            assert feat["upvoteCount"] == 1
            assert feat["hasUpvoted"] is True
        finally:
            test_app.dependency_overrides.pop(get_optional_user, None)


class TestPostUpvote:
    def test_creates_upvote_and_user_row(self, client, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        resp = client.post("/api/features/f1/upvote")
        assert resp.status_code == 200
        assert resp.json() == {
            "featureId": "f1",
            "upvoteCount": 1,
            "hasUpvoted": True,
        }

    def test_idempotent_double_post(self, client, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        r1 = client.post("/api/features/f1/upvote").json()
        r2 = client.post("/api/features/f1/upvote").json()
        assert r1 == r2
        assert r2["upvoteCount"] == 1

    def test_404_on_unknown_feature(self, client):
        resp = client.post("/api/features/does-not-exist/upvote")
        assert resp.status_code == 404

    def test_401_without_auth(self, test_app, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        saved = test_app.dependency_overrides.pop(get_current_user, None)
        try:
            no_auth_client = TestClient(test_app)
            resp = no_auth_client.post("/api/features/f1/upvote")
            assert resp.status_code == 401
        finally:
            if saved is not None:
                test_app.dependency_overrides[get_current_user] = saved


class TestDeleteUpvote:
    def test_removes_upvote(self, client, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        client.post("/api/features/f1/upvote")
        resp = client.delete("/api/features/f1/upvote")
        assert resp.status_code == 200
        assert resp.json() == {
            "featureId": "f1",
            "upvoteCount": 0,
            "hasUpvoted": False,
        }

    def test_idempotent_double_delete(self, client, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        client.post("/api/features/f1/upvote")
        r1 = client.delete("/api/features/f1/upvote").json()
        r2 = client.delete("/api/features/f1/upvote").json()
        assert r1 == r2
        assert r2["upvoteCount"] == 0

    def test_delete_without_prior_upvote_is_idempotent(self, client, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        resp = client.delete("/api/features/f1/upvote")
        assert resp.status_code == 200
        assert resp.json()["upvoteCount"] == 0
        assert resp.json()["hasUpvoted"] is False

    def test_404_on_unknown_feature(self, client):
        resp = client.delete("/api/features/does-not-exist/upvote")
        assert resp.status_code == 404

    def test_401_without_auth(self, test_app, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        saved = test_app.dependency_overrides.pop(get_current_user, None)
        try:
            no_auth_client = TestClient(test_app)
            resp = no_auth_client.delete("/api/features/f1/upvote")
            assert resp.status_code == 401
        finally:
            if saved is not None:
                test_app.dependency_overrides[get_current_user] = saved


class TestResolveUserIdForMutationErrorBranches:
    """Covers the 401/500 branches in `_resolve_user_id_for_mutation` that the
    happy-path tests above do not exercise. The FastAPI `get_current_user`
    dependency can be overridden to yield TokenClaims missing the required
    `sub`/`email` fields — the router should 401 rather than crash when it
    reaches into the claim dict.
    """

    def test_missing_sub_claim_returns_401(self, test_app, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        saved = test_app.dependency_overrides.get(get_current_user)
        # Claims without "sub" — simulates a malformed/unsupported issuer
        # that validate_token didn't normalize before returning.
        test_app.dependency_overrides[get_current_user] = lambda: {
            "email": "nosub@example.com",
        }
        try:
            client = TestClient(test_app)
            resp = client.post("/api/features/f1/upvote")
            assert resp.status_code == 401
            assert "sub" in resp.json()["detail"]
        finally:
            if saved is not None:
                test_app.dependency_overrides[get_current_user] = saved

    def test_missing_email_claim_returns_401(self, test_app, db_conn, test_env):
        _insert_feature(db_conn, test_env, "f1")
        saved = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {
            "sub": "auth0|no_email_user",
        }
        try:
            client = TestClient(test_app)
            resp = client.post("/api/features/f1/upvote")
            assert resp.status_code == 401
            assert "email" in resp.json()["detail"]
        finally:
            if saved is not None:
                test_app.dependency_overrides[get_current_user] = saved

    def test_db_error_in_get_or_create_user_returns_500(
        self, test_app, db_conn, test_env
    ):
        _insert_feature(db_conn, test_env, "f1")
        # Force the user upsert to raise a psycopg2.Error; the router should
        # log + return 500 instead of leaking the exception.
        with patch(
            "api.routers.features.get_or_create_user",
            side_effect=psycopg2.OperationalError("simulated DB outage"),
        ):
            client = TestClient(test_app)
            resp = client.post("/api/features/f1/upvote")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Failed to resolve user"


class TestListFeaturesNoUserRow:
    """Covers `_resolve_optional_user_id` returning None because a signed-in
    user has no row in users_<env> yet. The endpoint should succeed and report
    `hasUpvoted: false` for every feature — treating the caller as anonymous
    is the best-effort fallback.
    """

    def test_signed_in_user_without_users_row_sees_has_upvoted_false(
        self, test_app, db_conn, test_env
    ):
        _insert_feature(db_conn, test_env, "f1", "Title", "Desc")
        # Override get_optional_user with claims for a user whose row we have
        # NOT inserted into users_<env>. get_user_by_email will return None
        # and _resolve_optional_user_id should fall back to None silently.
        test_app.dependency_overrides[get_optional_user] = lambda: {
            "sub": "auth0|first_visit_user",
            "email": "first_visit@example.com",
        }
        try:
            client = TestClient(test_app)
            resp = client.get("/api/features")
            assert resp.status_code == 200
            features = resp.json()["features"]
            assert len(features) == 1
            assert features[0]["hasUpvoted"] is False
            assert features[0]["upvoteCount"] == 0
        finally:
            test_app.dependency_overrides.pop(get_optional_user, None)
