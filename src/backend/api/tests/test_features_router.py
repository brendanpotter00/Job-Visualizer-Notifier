"""Integration tests for features router (GET/POST/DELETE /api/features)."""

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
