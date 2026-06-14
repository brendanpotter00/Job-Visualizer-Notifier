"""Integration tests for the public feedback router (POST /api/feedback)."""

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth.dependencies import get_optional_user_lenient
from api.config import settings
from api.services.rate_limit import feedback_rate_limiter


@pytest.fixture(autouse=True)
def _reset_feedback_rate_limiter():
    """The limiter is a module-level singleton keyed by client IP. Every request
    from TestClient shares one key, so without a reset the per-IP window would
    leak across tests and trip the limit. Clear it around each test."""
    feedback_rate_limiter.reset()
    yield
    feedback_rate_limiter.reset()


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


class TestSubmitFeedbackRateLimit:
    def test_429_after_exceeding_per_ip_limit(self, test_app, db_conn):
        # The same IP submitting faster than the limit gets a 429 with a
        # Retry-After header; everything up to the limit succeeds.
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: None
        max_allowed = settings.feedback_rate_limit_max
        headers = {"X-Forwarded-For": "203.0.113.5"}
        try:
            client = TestClient(test_app)
            for _ in range(max_allowed):
                ok = client.post(
                    "/api/feedback", json={"message": "hi"}, headers=headers
                )
                assert ok.status_code == 201, ok.text
            blocked = client.post(
                "/api/feedback", json={"message": "too fast"}, headers=headers
            )
            assert blocked.status_code == 429
            assert "Retry-After" in blocked.headers
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)

    def test_distinct_ips_are_limited_independently(self, test_app, db_conn):
        # Exhausting one IP's budget must not block a different IP.
        test_app.dependency_overrides[get_optional_user_lenient] = lambda: None
        max_allowed = settings.feedback_rate_limit_max
        try:
            client = TestClient(test_app)
            for _ in range(max_allowed):
                client.post(
                    "/api/feedback",
                    json={"message": "a"},
                    headers={"X-Forwarded-For": "198.51.100.1"},
                )
            blocked = client.post(
                "/api/feedback",
                json={"message": "a"},
                headers={"X-Forwarded-For": "198.51.100.1"},
            )
            assert blocked.status_code == 429
            # A fresh IP is unaffected.
            other = client.post(
                "/api/feedback",
                json={"message": "b"},
                headers={"X-Forwarded-For": "198.51.100.2"},
            )
            assert other.status_code == 201, other.text
        finally:
            test_app.dependency_overrides.pop(get_optional_user_lenient, None)
