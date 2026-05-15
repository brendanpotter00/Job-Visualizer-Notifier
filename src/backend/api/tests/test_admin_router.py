"""Integration tests for the admin router and the require_admin gate."""

from fastapi.testclient import TestClient

from .conftest import _insert_admin, _insert_user, _make_user


class TestAdminGate:
    """Verifies require_admin behavior on the admin-only endpoints."""

    def test_admin_users_without_admin_grant_returns_403(self, test_app, db_conn):
        """A signed-in non-admin must get 403, not 200, on /api/admin/*."""
        from api.auth.dependencies import require_admin

        # Insert the signed-in user but DO NOT grant admin.
        _insert_user(
            db_conn,
            _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}),
        )

        saved_override = test_app.dependency_overrides.pop(require_admin, None)
        try:
            client = TestClient(test_app)
            resp = client.get("/api/admin/users")
            assert resp.status_code == 403
            assert "admin" in resp.json()["detail"].lower()
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[require_admin] = saved_override

    def test_admin_users_without_auth_returns_401(self, test_app):
        """An unauthenticated caller gets 401 before require_admin runs."""
        from api.auth.dependencies import get_current_user, require_admin

        saved_admin = test_app.dependency_overrides.pop(require_admin, None)
        saved_current = test_app.dependency_overrides.pop(get_current_user, None)
        try:
            client = TestClient(test_app)
            resp = client.get("/api/admin/users")
            assert resp.status_code == 401
        finally:
            if saved_current is not None:
                test_app.dependency_overrides[get_current_user] = saved_current
            if saved_admin is not None:
                test_app.dependency_overrides[require_admin] = saved_admin

    def test_admin_users_with_grant_returns_200(self, test_app, db_conn):
        """Inserting an admin row for the test user removes the gate."""
        from api.auth.dependencies import require_admin

        user = _make_user(
            {"auth0_id": "auth0|test_user_123", "email": "test@example.com"}
        )
        _insert_user(db_conn, user)
        _insert_admin(db_conn, user["id"])

        saved_override = test_app.dependency_overrides.pop(require_admin, None)
        try:
            client = TestClient(test_app)
            resp = client.get("/api/admin/users")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert "users" in body
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[require_admin] = saved_override


class TestAdminUsersList:
    """GET /api/admin/users payload shape and content."""

    def test_returns_users_with_signup_provider_derived(self, client, db_conn):
        _insert_user(
            db_conn,
            _make_user({
                "id": "u1",
                "auth0_id": "google-oauth2|abc",
                "email": "g1@example.com",
            }),
        )
        _insert_user(
            db_conn,
            _make_user({
                "id": "u2",
                "auth0_id": "google|xyz",
                "email": "g2@example.com",
            }),
        )
        _insert_user(
            db_conn,
            _make_user({
                "id": "u3",
                "auth0_id": "auth0|email-user",
                "email": "e@example.com",
            }),
        )

        resp = client.get("/api/admin/users")
        assert resp.status_code == 200
        users = resp.json()["users"]
        by_email = {u["email"]: u for u in users}
        assert by_email["g1@example.com"]["signupProvider"] == "google"
        assert by_email["g2@example.com"]["signupProvider"] == "google"
        assert by_email["e@example.com"]["signupProvider"] == "email"

    def test_is_admin_reflects_admin_table(self, client, db_conn):
        admin_user = _make_user(
            {"id": "admin1", "auth0_id": "auth0|a1", "email": "admin@example.com"}
        )
        plain_user = _make_user(
            {"id": "plain1", "auth0_id": "auth0|p1", "email": "plain@example.com"}
        )
        _insert_user(db_conn, admin_user)
        _insert_user(db_conn, plain_user)
        _insert_admin(db_conn, admin_user["id"])

        resp = client.get("/api/admin/users")
        users = resp.json()["users"]
        by_email = {u["email"]: u for u in users}
        assert by_email["admin@example.com"]["isAdmin"] is True
        assert by_email["plain@example.com"]["isAdmin"] is False

    def test_response_uses_camel_case_keys(self, client, db_conn):
        _insert_user(
            db_conn,
            _make_user({
                "id": "u1",
                "auth0_id": "auth0|a",
                "email": "a@example.com",
            }),
        )
        resp = client.get("/api/admin/users")
        row = resp.json()["users"][0]
        expected = {
            "id",
            "email",
            "displayName",
            "signupProvider",
            "createdAt",
            "isAdmin",
        }
        assert set(row.keys()) == expected


class TestAdminUsersStats:
    """GET /api/admin/users/stats payload shape."""

    def test_returns_totals_and_provider_breakdown(self, client, db_conn):
        for i, (auth_prefix, email) in enumerate(
            [
                ("google-oauth2|", "a@example.com"),
                ("google|", "b@example.com"),
                ("auth0|", "c@example.com"),
            ]
        ):
            _insert_user(
                db_conn,
                _make_user({
                    "id": f"u{i}",
                    "auth0_id": f"{auth_prefix}{i}",
                    "email": email,
                }),
            )

        resp = client.get("/api/admin/users/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalUsers"] == 3
        assert data["firstSignupAt"] is not None
        assert data["latestSignupAt"] is not None
        assert data["byProvider"]["google"] == 2
        assert data["byProvider"]["email"] == 1

    def test_returns_zero_when_no_users(self, client):
        resp = client.get("/api/admin/users/stats")
        data = resp.json()
        assert data["totalUsers"] == 0
        assert data["firstSignupAt"] is None
        assert data["latestSignupAt"] is None
        assert data["byProvider"] == {}


class TestJobsQaGate:
    """jobs_qa router is now gated behind require_admin."""

    def test_jobs_qa_stats_without_admin_returns_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin

        _insert_user(
            db_conn,
            _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}),
        )

        saved_override = test_app.dependency_overrides.pop(require_admin, None)
        try:
            client = TestClient(test_app)
            resp = client.get("/api/jobs-qa/stats")
            assert resp.status_code == 403
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[require_admin] = saved_override
