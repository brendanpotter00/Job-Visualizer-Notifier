"""Tests for auth service functions and auth API endpoints."""

from unittest.mock import patch

import jwt as pyjwt
import pytest

from api.services.auth import create_jwt, decode_jwt


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------

TEST_SECRET = "test-jwt-secret"

TEST_USER = {
    "id": 1,
    "email": "alice@example.com",
    "name": "Alice",
    "picture": "https://example.com/alice.jpg",
    "is_admin": False,
}


def test_create_and_decode_jwt_round_trip():
    token = create_jwt(TEST_USER, TEST_SECRET)
    payload = decode_jwt(token, TEST_SECRET)
    assert payload["sub"] == "1"
    assert payload["email"] == "alice@example.com"
    assert payload["name"] == "Alice"
    assert payload["picture"] == "https://example.com/alice.jpg"
    assert payload["is_admin"] is False


def test_create_jwt_sub_is_string():
    token = create_jwt({**TEST_USER, "id": 42}, TEST_SECRET)
    payload = decode_jwt(token, TEST_SECRET)
    assert payload["sub"] == "42"
    assert isinstance(payload["sub"], str)


def test_decode_jwt_expired():
    token = create_jwt(TEST_USER, TEST_SECRET, expires_hours=0)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_jwt(token, TEST_SECRET)


def test_decode_jwt_wrong_secret():
    token = create_jwt(TEST_USER, TEST_SECRET)
    with pytest.raises(pyjwt.InvalidSignatureError):
        decode_jwt(token, "wrong-secret")


def test_decode_jwt_tampered():
    token = create_jwt(TEST_USER, TEST_SECRET)
    # Flip a character in the payload section
    parts = token.split(".")
    parts[1] = parts[1][::-1]
    tampered = ".".join(parts)
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_jwt(tampered, TEST_SECRET)


# ---------------------------------------------------------------------------
# Router integration tests
# ---------------------------------------------------------------------------

MOCK_GOOGLE_USER = {
    "sub": "google-12345",
    "email": "alice@example.com",
    "name": "Alice",
    "picture": "https://example.com/alice.jpg",
}


@patch("api.routers.auth.verify_google_token", return_value=MOCK_GOOGLE_USER)
def test_post_google_login_creates_user(mock_verify, client):
    resp = client.post("/api/auth/google", json={"credential": "fake-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["name"] == "Alice"
    assert "isAdmin" in data["user"]
    assert data["user"]["isAdmin"] is False


@patch("api.routers.auth.verify_google_token", return_value=MOCK_GOOGLE_USER)
def test_post_google_login_returns_same_user_on_re_login(mock_verify, client):
    resp1 = client.post("/api/auth/google", json={"credential": "fake-token"})
    resp2 = client.post("/api/auth/google", json={"credential": "fake-token"})
    assert resp1.json()["user"]["id"] == resp2.json()["user"]["id"]


@patch("api.routers.auth.verify_google_token", side_effect=ValueError("bad token"))
def test_post_google_login_invalid_token(mock_verify, client):
    resp = client.post("/api/auth/google", json={"credential": "bad-token"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid Google token"


def test_post_google_login_missing_body(client):
    resp = client.post("/api/auth/google")
    assert resp.status_code == 422


def test_post_google_login_empty_credential(client):
    resp = client.post("/api/auth/google", json={})
    assert resp.status_code == 422


@patch("api.routers.auth.verify_google_token", return_value=MOCK_GOOGLE_USER)
def test_get_me_with_valid_token(mock_verify, client):
    # Login first to create user and get JWT
    login_resp = client.post("/api/auth/google", json={"credential": "fake-token"})
    token = login_resp.json()["token"]

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"
    assert "isAdmin" in resp.json()


def test_get_me_no_auth_header(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_get_me_invalid_token(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


def test_get_me_malformed_auth_header(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "NotBearer token"})
    assert resp.status_code == 401


def test_get_me_user_deleted(client, db_conn):
    # Create a JWT for a user that doesn't exist in DB
    fake_user = {**TEST_USER, "id": 99999}
    token = create_jwt(fake_user, "test-jwt-secret")

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "User not found"


def test_post_google_login_no_client_id_configured(client, test_app):
    # Temporarily clear google_client_id
    original = test_app.state.config.google_client_id
    test_app.state.config.google_client_id = ""
    try:
        resp = client.post("/api/auth/google", json={"credential": "fake-token"})
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Google OAuth not configured"
    finally:
        test_app.state.config.google_client_id = original
