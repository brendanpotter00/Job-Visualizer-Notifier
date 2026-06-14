"""Integration tests for the public feedback router (POST /api/feedback)."""

from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth.dependencies import get_optional_user_lenient


def _count_users(db_conn) -> int:
    cur = db_conn.cursor()
    cur.execute(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(sql.Identifier("users")))
    return int(cur.fetchone()["n"])


class TestSubmitFeedbackAnonymous:
    def test_anonymous_submit_returns_201_with_null_user_fields(
        self, test_app, db_conn
    ):
        # No Authorization header => get_optional_user yields None => anonymous.
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: None
        try:
            client = TestClient(test_app)
            resp = client.post("/api/feedback", json={"message": "love it"})
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["message"] == "love it"
            assert body["userId"] is None
            assert body["userEmail"] is None
            assert body["displayName"] is None
            assert body["id"]
            assert "createdAt" in body
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)

    def test_camel_case_keys(self, test_app, db_conn):
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: None
        try:
            client = TestClient(test_app)
            body = client.post("/api/feedback", json={"message": "hi"}).json()
            assert set(body.keys()) == {
                "id", "message", "userId", "userEmail", "displayName", "createdAt",
            }
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)

    def test_no_users_row_created_for_anonymous(self, test_app, db_conn):
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: None
        try:
            client = TestClient(test_app)
            client.post("/api/feedback", json={"message": "anon"})
            assert _count_users(db_conn) == 0
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)


class TestSubmitFeedbackAuthed:
    def test_authed_submit_snapshots_user_and_creates_users_row(
        self, test_app, db_conn
    ):
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: {
            "sub": "auth0|test_user_123",
            "email": "test@example.com",
            "given_name": "Test",
            "family_name": "User",
            "picture": "https://example.com/photo.jpg",
        }
        try:
            client = TestClient(test_app)
            resp = client.post("/api/feedback", json={"message": "from me"})
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["userId"] is not None
            assert body["userEmail"] == "test@example.com"
            # get_or_create_user created exactly one users row.
            assert _count_users(db_conn) == 1
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)


class TestSubmitFeedbackBadToken:
    def test_invalid_token_is_treated_as_anonymous(self, test_app, db_conn):
        # A bad/expired bearer token must NOT 401 the public endpoint — feedback
        # degrades to an anonymous submission. The real get_optional_user_lenient
        # runs here (the fixture doesn't override it); we force validate_token to
        # raise so no live JWKS call is made.
        from unittest.mock import patch

        import jwt as pyjwt

        with patch(
            "api.auth.dependencies.validate_token",
            side_effect=pyjwt.InvalidTokenError("bad"),
        ):
            client = TestClient(test_app)
            resp = client.post(
                "/api/feedback",
                json={"message": "submitted with a stale token"},
                headers={"Authorization": "Bearer garbage.token.here"},
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["userId"] is None
        assert body["userEmail"] is None
        assert _count_users(db_conn) == 0


class TestSubmitFeedbackValidation:
    def test_empty_message_returns_422(self, test_app, db_conn):
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: None
        try:
            client = TestClient(test_app)
            resp = client.post("/api/feedback", json={"message": ""})
            assert resp.status_code == 422
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)

    def test_whitespace_only_message_returns_422(self, test_app, db_conn):
        # Passes Pydantic min_length but the router .strip() guard rejects it.
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: None
        try:
            client = TestClient(test_app)
            resp = client.post("/api/feedback", json={"message": "   \n\t  "})
            assert resp.status_code == 422
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)

    def test_overlong_message_returns_422(self, test_app, db_conn):
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: None
        try:
            client = TestClient(test_app)
            resp = client.post("/api/feedback", json={"message": "x" * 5001})
            assert resp.status_code == 422
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)

    def test_extra_field_returns_422(self, test_app, db_conn):
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: None
        try:
            client = TestClient(test_app)
            resp = client.post(
                "/api/feedback", json={"message": "ok", "userId": "spoof"}
            )
            assert resp.status_code == 422
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)
