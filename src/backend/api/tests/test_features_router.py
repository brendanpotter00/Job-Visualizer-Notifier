"""Integration tests for features router (GET/POST/DELETE /api/features)."""

import logging
from unittest.mock import MagicMock, patch

import psycopg2
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth.dependencies import get_current_user, get_optional_user
from api.dependencies import get_db


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


class TestListFeaturesDbErrorRollback:
    """Covers the `list_features_with_upvotes` -> psycopg2.Error rollback
    branch in `list_features` (routers/features.py:83-89). If the SELECT
    raises, the pooled connection must be rolled back (else the next caller
    sees 'current transaction is aborted') and the endpoint must return 500.
    """

    def test_list_features_with_upvotes_error_returns_500_and_rolls_back(
        self, test_app, db_conn, test_env
    ):
        _insert_feature(db_conn, test_env, "f1")
        # Replace the connection yielded by get_db with a Mock that records
        # whether `.rollback()` was called. The rollback branch under test
        # calls `conn.rollback()` directly on the pooled connection before
        # raising HTTPException(500). Restore the prior override in finally
        # (test_app is module-scoped and its conftest-registered override
        # of get_db must survive past this test, else sibling tests see
        # `RuntimeError: Connection pool not initialized`).
        mock_conn = MagicMock()

        def _override_get_db():
            yield mock_conn

        saved_get_db = test_app.dependency_overrides.get(get_db)
        test_app.dependency_overrides[get_optional_user] = lambda: None
        test_app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch(
                "api.routers.features.list_features_with_upvotes",
                side_effect=psycopg2.OperationalError("boom"),
            ):
                client = TestClient(test_app)
                resp = client.get("/api/features")
            assert resp.status_code == 500
            assert resp.json()["detail"] == "Failed to list features"
            mock_conn.rollback.assert_called_once()
        finally:
            test_app.dependency_overrides.pop(get_optional_user, None)
            if saved_get_db is not None:
                test_app.dependency_overrides[get_db] = saved_get_db
            else:
                test_app.dependency_overrides.pop(get_db, None)


class TestResolveOptionalUserIdDbErrorFallback:
    """Covers the `_resolve_optional_user_id` psycopg2.Error fallback branch
    (routers/features.py:62-69). When `get_user_by_email` raises, the router
    must: (a) roll back the connection so the transaction isn't aborted for
    downstream reads, (b) log at ERROR level, (c) fall back to treating the
    caller as anonymous — still returning 200 with `has_upvoted: false` on
    every row (best-effort GET semantics, not a failure).
    """

    def test_get_user_by_email_db_error_falls_back_to_anonymous(
        self, test_app, db_conn, test_env, caplog
    ):
        _insert_feature(db_conn, test_env, "f1", "Title", "Desc")
        _insert_feature(db_conn, test_env, "f2", "Another", "Desc2")
        # test_app's conftest already overrides `get_db` to yield the real
        # test db_conn, so we don't need to touch it here — just override
        # get_optional_user so the code path under test (auth-resolution
        # email lookup) actually runs.
        test_app.dependency_overrides[get_optional_user] = lambda: {
            "sub": "auth0|some_user",
            "email": "anyone@example.com",
        }
        try:
            # Capture log records so we can assert an ERROR-level record was
            # emitted from the features router (logger.exception logs at
            # ERROR with exc_info attached).
            with caplog.at_level(logging.ERROR, logger="api.routers.features"):
                with patch(
                    "api.routers.features.get_user_by_email",
                    side_effect=psycopg2.OperationalError("simulated email lookup outage"),
                ):
                    client = TestClient(test_app)
                    resp = client.get("/api/features")
            # Endpoint falls back to anonymous path -> 200, every row
            # hasUpvoted=false (no upvotes seeded anyway, so this also guards
            # against the fallback accidentally inverting the flag).
            assert resp.status_code == 200
            features = resp.json()["features"]
            assert len(features) == 2
            for feat in features:
                assert feat["hasUpvoted"] is False
            # ERROR-level log record was emitted by the router.
            error_records = [
                r for r in caplog.records
                if r.levelno == logging.ERROR
                and r.name == "api.routers.features"
            ]
            assert error_records, (
                "Expected at least one ERROR log record from "
                "api.routers.features when get_user_by_email raises psycopg2.Error"
            )
        finally:
            test_app.dependency_overrides.pop(get_optional_user, None)

    def test_rollback_invoked_on_get_user_by_email_db_error(
        self, test_app, db_conn, test_env
    ):
        """Narrower assertion that isolates the `conn.rollback()` call — we
        substitute a Mock connection so the rollback invocation is directly
        observable without having to introspect connection state."""
        _insert_feature(db_conn, test_env, "f1")
        mock_conn = MagicMock()

        def _override_get_db():
            yield mock_conn

        saved_get_db = test_app.dependency_overrides.get(get_db)
        test_app.dependency_overrides[get_optional_user] = lambda: {
            "sub": "auth0|some_user",
            "email": "anyone@example.com",
        }
        test_app.dependency_overrides[get_db] = _override_get_db
        try:
            # After _resolve_optional_user_id's rollback + fallback to None,
            # list_features still calls list_features_with_upvotes(conn, ...).
            # Patch that too so it returns an empty result set (the mock conn
            # isn't a real cursor-backing connection).
            with patch(
                "api.routers.features.get_user_by_email",
                side_effect=psycopg2.OperationalError("boom"),
            ), patch(
                "api.routers.features.list_features_with_upvotes",
                return_value=[],
            ):
                client = TestClient(test_app)
                resp = client.get("/api/features")
            assert resp.status_code == 200
            # rollback() was called exactly once by _resolve_optional_user_id
            # after the get_user_by_email failure.
            mock_conn.rollback.assert_called_once()
        finally:
            test_app.dependency_overrides.pop(get_optional_user, None)
            if saved_get_db is not None:
                test_app.dependency_overrides[get_db] = saved_get_db
            else:
                test_app.dependency_overrides.pop(get_db, None)
