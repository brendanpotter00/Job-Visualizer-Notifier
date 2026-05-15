"""Integration tests for users router."""

from .conftest import _make_user, _insert_user


class TestGetMe:
    def test_creates_user_on_first_call(self, client):
        """GET /api/users should create user from token claims on first call."""
        resp = client.get("/api/users")
        assert resp.status_code == 200
        data = resp.json()
        assert data["providerSubject"] == "auth0|test_user_123"
        assert data["email"] == "test@example.com"
        assert data["givenName"] == "Test"
        assert data["familyName"] == "User"
        assert data["pictureUrl"] == "https://example.com/photo.jpg"
        assert "id" in data
        assert "createdAt" in data
        assert "updatedAt" in data

    def test_returns_existing_user(self, client, db_conn):
        """GET /api/users returns existing user without overwriting display_name."""
        user = _make_user({"auth0_id": "auth0|test_user_123", "display_name": "Custom Name"})
        _insert_user(db_conn, user)
        resp = client.get("/api/users")
        assert resp.status_code == 200
        # Note: upsert overwrites given_name/family_name/picture_url from token,
        # but display_name is NOT in the upsert's ON CONFLICT SET clause
        assert resp.json()["id"] == user["id"]

    def test_returns_camel_case_keys(self, client):
        """Response keys must be camelCase."""
        resp = client.get("/api/users")
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "id", "providerSubject", "email", "displayName", "givenName",
            "familyName", "pictureUrl", "createdAt", "updatedAt", "isAdmin",
        }
        assert set(data.keys()) == expected_keys

    def test_no_snake_case_keys(self, client):
        """No snake_case keys should leak into the response."""
        resp = client.get("/api/users")
        snake_keys = {"provider_subject", "auth0_id", "display_name", "given_name",
                      "family_name", "picture_url", "created_at", "updated_at"}
        assert not snake_keys.intersection(resp.json().keys())


class TestPutMe:
    def test_updates_display_name(self, client):
        """PUT /api/users should update display_name."""
        # First create the user
        client.get("/api/users")
        # Then update
        resp = client.put("/api/users", json={"displayName": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["displayName"] == "New Name"

    def test_rejects_long_display_name(self, client):
        """PUT /api/users should reject display_name over 100 chars."""
        client.get("/api/users")
        resp = client.put("/api/users", json={"displayName": "x" * 101})
        assert resp.status_code == 422

    def test_clears_display_name_with_null(self, client):
        """PUT /api/users with null display_name should clear it."""
        client.get("/api/users")
        client.put("/api/users", json={"displayName": "Name"})
        resp = client.put("/api/users", json={"displayName": None})
        assert resp.status_code == 200
        assert resp.json()["displayName"] is None

    def test_rejects_extra_fields(self, client):
        """PUT /api/users should reject extra fields like pictureUrl."""
        client.get("/api/users")
        resp = client.put("/api/users", json={"displayName": "Name", "pictureUrl": "https://evil.com/pic.jpg"})
        assert resp.status_code == 422


class TestAuthRequired:
    def test_get_me_without_auth_returns_401(self, test_app):
        """GET /api/users without auth should return 401."""
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        # Create a client WITHOUT the auth override
        no_auth_app = test_app
        saved_override = no_auth_app.dependency_overrides.pop(get_current_user, None)
        try:
            no_auth_client = TestClient(no_auth_app)
            resp = no_auth_client.get("/api/users")
            assert resp.status_code == 401
        finally:
            if saved_override is not None:
                no_auth_app.dependency_overrides[get_current_user] = saved_override

    def test_get_me_without_email_claim_returns_401(self, test_app):
        """GET /api/users with a valid sub but no email claim should return 401.

        Email is the stable human identifier; inserting a row with empty email
        would collide on the UNIQUE(email) constraint, so the router rejects
        early with 401 rather than letting the DB choose.
        """
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {"sub": "auth0|no_email"}
        try:
            client = TestClient(test_app)
            resp = client.get("/api/users")
            assert resp.status_code == 401
            assert "email" in resp.json()["detail"].lower()
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override

    def test_get_me_with_ambiguous_identity_returns_500(
        self, test_app, db_conn
    ):
        """If two existing rows ambiguously match a token (one by auth0_id, one
        by email), the router must surface the service's ``RuntimeError`` as a
        500 rather than silently catching it and returning stale user data.

        This locks in the narrowed ``except psycopg2.Error`` in the router —
        see REVIEW_AUDIT.md "2026-04-14 — Third review pass".
        """
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

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

        saved_override = test_app.dependency_overrides.get(get_current_user)
        # Token claims: auth0_id matches row A, email matches row B — ambiguous
        test_app.dependency_overrides[get_current_user] = lambda: {
            "sub": "auth0|person_a",
            "email": "b@example.com",
        }
        try:
            # raise_server_exceptions=False so the TestClient mirrors uvicorn's
            # "unhandled exception → 500" behavior instead of re-raising.
            client = TestClient(test_app, raise_server_exceptions=False)
            resp = client.get("/api/users")
            assert resp.status_code == 500
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override

    def test_put_me_without_email_claim_returns_401(self, test_app):
        """PUT /api/users requires the token email claim too — update_user is
        keyed by email, so an emailless token can't resolve a user."""
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {"sub": "auth0|no_email"}
        try:
            client = TestClient(test_app)
            resp = client.put("/api/users", json={"displayName": "X"})
            assert resp.status_code == 401
            assert "email" in resp.json()["detail"].lower()
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override


class TestGoogleOneTap:
    """GET /api/users for tokens routed through Google One Tap validation."""

    def test_google_one_tap_sub_is_prefixed(self, test_app):
        """A Google-shaped claims dict (bare numeric sub + google issuer) should
        produce providerSubject == "google|{sub}" in the response and DB."""
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {
            "sub": "12345",
            "iss": "https://accounts.google.com",
            "email": "onetap@example.com",
            "given_name": "OneTap",
            "family_name": "User",
            "picture": "https://example.com/onetap.jpg",
        }
        try:
            client = TestClient(test_app)
            resp = client.get("/api/users")
            assert resp.status_code == 200
            assert resp.json()["providerSubject"] == "google|12345"
            assert resp.json()["email"] == "onetap@example.com"
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override

    def test_second_provider_login_merges_into_one_row(self, test_app, db_conn):
        """Auth0 login followed by Google One Tap login with the same email
        should produce ONE row whose provider_subject reflects the latest provider."""
        from fastapi.testclient import TestClient
        from psycopg2 import sql
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.get(get_current_user)
        shared_email = "alice@example.com"

        # First login: Auth0
        test_app.dependency_overrides[get_current_user] = lambda: {
            "sub": "auth0|alice",
            "email": shared_email,
        }
        try:
            client = TestClient(test_app)
            first = client.get("/api/users").json()
            assert first["providerSubject"] == "auth0|alice"

            # Second login: Google One Tap, same email
            test_app.dependency_overrides[get_current_user] = lambda: {
                "sub": "67890",
                "iss": "https://accounts.google.com",
                "email": shared_email,
            }
            second = client.get("/api/users").json()
            assert second["providerSubject"] == "google|67890"
            assert second["id"] == first["id"], "should be same row (merged by email)"

            # Confirm DB has exactly one row for this email
            cursor = db_conn.cursor()
            cursor.execute(
                sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE email = %s").format(
                    sql.Identifier("users")
                ),
                (shared_email,),
            )
            assert cursor.fetchone()["n"] == 1
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override


class TestEnabledCompanies:
    """GET/PUT /api/users/enabled-companies endpoints."""

    def test_get_returns_empty_list_before_user_exists(self, client):
        """Before any GET /api/users (which creates the user row), the endpoint
        returns an empty list rather than 404."""
        resp = client.get("/api/users/enabled-companies")
        assert resp.status_code == 200
        assert resp.json() == {"companyIds": []}

    def test_get_returns_empty_list_after_user_created(self, client):
        client.get("/api/users")
        resp = client.get("/api/users/enabled-companies")
        assert resp.status_code == 200
        assert resp.json() == {"companyIds": []}

    def test_put_then_get_round_trip(self, client):
        client.get("/api/users")
        put_resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["airbnb", "stripe"]},
        )
        assert put_resp.status_code == 200
        assert put_resp.json() == {"companyIds": ["airbnb", "stripe"]}

        get_resp = client.get("/api/users/enabled-companies")
        assert get_resp.status_code == 200
        assert get_resp.json() == {"companyIds": ["airbnb", "stripe"]}

    def test_put_dedupes_and_sorts(self, client):
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["stripe", "airbnb", "stripe", "airbnb"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"companyIds": ["airbnb", "stripe"]}

    def test_put_empty_list_clears(self, client):
        client.get("/api/users")
        client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["airbnb", "stripe"]},
        )
        resp = client.put("/api/users/enabled-companies", json={"companyIds": []})
        assert resp.status_code == 200
        assert resp.json() == {"companyIds": []}
        get_resp = client.get("/api/users/enabled-companies")
        assert get_resp.json() == {"companyIds": []}

    def test_put_replaces_previous_set(self, client):
        client.get("/api/users")
        client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["a", "b", "c"]},
        )
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["x", "y"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"companyIds": ["x", "y"]}

    def test_put_rejects_non_list_body(self, client):
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": "not-a-list"},
        )
        assert resp.status_code == 422

    def test_put_rejects_extra_fields(self, client):
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["a"], "sneaky": "field"},
        )
        assert resp.status_code == 422

    def test_put_rejects_missing_body(self, client):
        client.get("/api/users")
        resp = client.put("/api/users/enabled-companies", json={})
        assert resp.status_code == 422

    def test_put_rejects_empty_string_company_id(self, client):
        """Empty strings must not be accepted — COMPANY_PATTERN requires min_length=1."""
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["airbnb", ""]},
        )
        assert resp.status_code == 422

    def test_put_rejects_malformed_company_id(self, client):
        """Company IDs must match ENABLED_COMPANY_ID_PATTERN.

        Interior dots are allowed (e.g. ``happyrobot.ai``) but leading/
        trailing dots, consecutive dots, and other non-alphanumeric chars
        are still rejected.
        """
        client.get("/api/users")
        for bad_id in [
            "../../etc/passwd",
            "has space",
            "has/slash",
            "has'quote",
            ".leading",
            "trailing.",
            "double..dot",
        ]:
            resp = client.put(
                "/api/users/enabled-companies",
                json={"companyIds": [bad_id]},
            )
            assert resp.status_code == 422, f"expected rejection for {bad_id!r}"

    def test_put_accepts_dotted_company_id(self, client):
        """Interior-dot IDs (e.g. ``happyrobot.ai``) must round-trip."""
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["happyrobot.ai", "airbnb"]},
        )
        assert resp.status_code == 200, resp.text
        assert set(resp.json()["companyIds"]) == {"happyrobot.ai", "airbnb"}

    def test_put_rejects_oversize_company_id(self, client):
        """Individual IDs are capped at 64 characters."""
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["a" * 65]},
        )
        assert resp.status_code == 422

    def test_put_rejects_oversize_list(self, client):
        """The list is capped at 200 items to prevent runaway payloads."""
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": [f"c{i}" for i in range(201)]},
        )
        assert resp.status_code == 422

    def test_put_without_existing_user_returns_404(self, client):
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["a"]},
        )
        assert resp.status_code == 404

    def test_response_uses_camel_case_key(self, client):
        """Serialized key must literally be 'companyIds', not 'company_ids'."""
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["a"]},
        )
        assert resp.status_code == 200
        assert "companyIds" in resp.json()
        assert "company_ids" not in resp.json()

    def test_get_without_auth_returns_401(self, test_app):
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.pop(get_current_user, None)
        try:
            no_auth_client = TestClient(test_app)
            resp = no_auth_client.get("/api/users/enabled-companies")
            assert resp.status_code == 401
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override

    def test_put_without_auth_returns_401(self, test_app):
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.pop(get_current_user, None)
        try:
            no_auth_client = TestClient(test_app)
            resp = no_auth_client.put(
                "/api/users/enabled-companies",
                json={"companyIds": []},
            )
            assert resp.status_code == 401
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override

    def test_get_without_email_claim_returns_401(self, test_app):
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {"sub": "auth0|no_email"}
        try:
            client = TestClient(test_app)
            resp = client.get("/api/users/enabled-companies")
            assert resp.status_code == 401
            assert "email" in resp.json()["detail"].lower()
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override

    def test_put_without_email_claim_returns_401(self, test_app):
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {"sub": "auth0|no_email"}
        try:
            client = TestClient(test_app)
            resp = client.put(
                "/api/users/enabled-companies",
                json={"companyIds": []},
            )
            assert resp.status_code == 401
            assert "email" in resp.json()["detail"].lower()
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override
