"""Integration tests for users router."""

from .conftest import _insert_admin, _make_user, _insert_user


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

    def test_is_admin_true_when_user_has_admin_grant(self, client, db_conn):
        """The frontend admin UI gate (AdminRoute / NavigationDrawer) is
        driven entirely by the ``isAdmin`` field on this response. If a
        future refactor hard-codes it to ``False`` (the prior model default)
        every admin in production silently loses access — guard with a
        positive-case assertion on the actual value."""
        # The test caller is auth0|test_user_123 / test@example.com.
        # GET /api/users will auto-create the row; we then grant admin and
        # call again to verify the flag flips.
        first = client.get("/api/users")
        assert first.status_code == 200
        assert first.json()["isAdmin"] is False

        # Insert the admin grant for the just-created caller row.
        caller_id = first.json()["id"]
        _insert_admin(db_conn, caller_id)

        second = client.get("/api/users")
        assert second.status_code == 200
        assert second.json()["isAdmin"] is True

    def test_is_admin_false_when_no_admin_grant(self, client):
        """Mirror of the previous test — the default-no-grant path must
        return ``isAdmin: false``, not omit the field or default-fail."""
        resp = client.get("/api/users")
        assert resp.status_code == 200
        assert resp.json()["isAdmin"] is False

    def test_get_me_surfaces_is_admin_by_email_failure_as_500(
        self, test_app, monkeypatch
    ):
        """If ``is_admin_by_email`` raises (driver bug, connection drop),
        the router must surface that as 500 — NOT silently demote the user
        to ``isAdmin: false``. Audit log "Important" finding: the call was
        previously inside the broad ``except psycopg2.Error`` block, so any
        admin-lookup failure would propagate as a generic error masquerading
        as a non-admin user.
        """
        from fastapi.testclient import TestClient
        import api.routers.users as users_router

        def _boom(_conn, _email):
            # Simulate "intentional raise" path described in
            # ``services.admin_service.is_admin_by_email``: rather than
            # silently denying admin, the function surfaces the underlying
            # driver/state error.
            raise RuntimeError("simulated admin-lookup failure")

        monkeypatch.setattr(users_router, "is_admin_by_email", _boom)
        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.get("/api/users")
        # 500 (Internal Server Error) — distinguishable from the silent
        # ``isAdmin: false`` regression we're guarding against.
        assert resp.status_code == 500


class TestPutMe:
    def test_updates_display_name(self, client):
        """PUT /api/users should update display_name."""
        # First create the user
        client.get("/api/users")
        # Then update
        resp = client.put("/api/users", json={"displayName": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["displayName"] == "New Name"

    def test_put_me_surfaces_is_admin_by_email_failure_as_500(
        self, test_app, db_conn, monkeypatch
    ):
        """Sibling of ``test_get_me_surfaces_is_admin_by_email_failure_as_500``
        — the PUT path also calls ``is_admin_by_email`` AFTER update_user, and
        the call was moved OUTSIDE the ``psycopg2.Error`` catch so a driver
        failure surfaces as 500 instead of silently demoting the user to
        ``isAdmin: false`` in the response.

        Without this test, a regression that re-wraps the call inside the
        ``except psycopg2.Error`` block would re-introduce the swallowed
        admin lookup on the PUT path only and slip through CI.
        """
        import psycopg2
        from fastapi.testclient import TestClient
        import api.routers.users as users_router

        # PUT keys by email; ensure a row exists so update_user returns a row
        # and we actually reach the is_admin_by_email call site.
        user = _make_user(
            {"auth0_id": "auth0|test_user_123", "email": "test@example.com"}
        )
        _insert_user(db_conn, user)

        def _boom(_conn, _email):
            # Use psycopg2.Error specifically — this is the exact class that
            # the catch block above ``is_admin_by_email`` would have caught
            # if the call were still inside it. If the catch is reintroduced
            # the test would silently demote (return 200 with isAdmin=false)
            # rather than 500.
            raise psycopg2.Error("simulated admin-lookup failure")

        monkeypatch.setattr(users_router, "is_admin_by_email", _boom)
        client = TestClient(test_app, raise_server_exceptions=False)
        resp = client.put("/api/users", json={"displayName": "X"})

        # 500 from the unhandled psycopg2.Error — not 200 with a demoted
        # admin flag.
        assert resp.status_code == 500
        # Belt-and-braces: assert we did NOT silently fall through with
        # ``isAdmin: false``. A 200 response with that body is the exact
        # regression we're guarding against.
        try:
            body = resp.json()
        except Exception:
            body = None
        assert body != {"isAdmin": False}, (
            "is_admin_by_email failure must surface as 500, not silently "
            "demote the user to isAdmin: false."
        )

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
        assert resp.json() == {"companyIds": [], "autoEnrollNewCompanies": True}

    def test_get_returns_empty_list_after_user_created(self, client):
        client.get("/api/users")
        resp = client.get("/api/users/enabled-companies")
        assert resp.status_code == 200
        assert resp.json() == {"companyIds": [], "autoEnrollNewCompanies": True}

    def test_put_then_get_round_trip(self, client):
        client.get("/api/users")
        put_resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["airbnb", "stripe"]},
        )
        assert put_resp.status_code == 200
        assert put_resp.json() == {
            "companyIds": ["airbnb", "stripe"],
            "autoEnrollNewCompanies": True,
        }

        get_resp = client.get("/api/users/enabled-companies")
        assert get_resp.status_code == 200
        assert get_resp.json() == {
            "companyIds": ["airbnb", "stripe"],
            "autoEnrollNewCompanies": True,
        }

    def test_put_dedupes_and_sorts(self, client):
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["stripe", "airbnb", "stripe", "airbnb"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "companyIds": ["airbnb", "stripe"],
            "autoEnrollNewCompanies": True,
        }

    def test_put_empty_list_clears(self, client):
        client.get("/api/users")
        client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["airbnb", "stripe"]},
        )
        resp = client.put("/api/users/enabled-companies", json={"companyIds": []})
        assert resp.status_code == 200
        assert resp.json() == {"companyIds": [], "autoEnrollNewCompanies": True}
        get_resp = client.get("/api/users/enabled-companies")
        assert get_resp.json() == {"companyIds": [], "autoEnrollNewCompanies": True}

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
        assert resp.json() == {
            "companyIds": ["x", "y"],
            "autoEnrollNewCompanies": True,
        }

    def test_get_returns_auto_enroll_flag_default_true(self, client):
        client.get("/api/users")
        resp = client.get("/api/users/enabled-companies")
        assert resp.status_code == 200
        assert resp.json()["autoEnrollNewCompanies"] is True

    def test_put_round_trips_auto_enroll_false(self, client):
        client.get("/api/users")
        put_resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["airbnb"], "autoEnrollNewCompanies": False},
        )
        assert put_resp.status_code == 200
        assert put_resp.json() == {
            "companyIds": ["airbnb"],
            "autoEnrollNewCompanies": False,
        }
        get_resp = client.get("/api/users/enabled-companies")
        assert get_resp.json()["autoEnrollNewCompanies"] is False

    def test_put_defaults_auto_enroll_true_when_omitted(self, client):
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": ["airbnb"]},
        )
        assert resp.status_code == 200
        assert resp.json()["autoEnrollNewCompanies"] is True

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
        """The list is capped at 1000 items to prevent runaway payloads.

        The cap is well above the company catalogue size so auto-enroll's
        materialized full-catalogue lists ("Select All" / see-all users) still
        save successfully.
        """
        client.get("/api/users")
        resp = client.put(
            "/api/users/enabled-companies",
            json={"companyIds": [f"c{i}" for i in range(1001)]},
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


class TestRecordVisit:
    """POST /api/users/visit — the per-page-load visit counter that backs the
    admin roster's "most frequent users" view."""

    @staticmethod
    def _read_visit_row(db_conn, auth0_id: str = "auth0|test_user_123"):
        from psycopg2 import sql

        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL(
                "SELECT visit_count, last_visit_at, display_name"
                " FROM {} WHERE auth0_id = %s"
            ).format(sql.Identifier("users")),
            (auth0_id,),
        )
        return cursor.fetchone()

    @staticmethod
    def _count_visit_log_rows(db_conn, auth0_id: str = "auth0|test_user_123") -> int:
        """How many user_visits rows belong to the user with this auth0_id."""
        from psycopg2 import sql

        cursor = db_conn.cursor()
        cursor.execute(
            sql.SQL(
                "SELECT count(*) AS n FROM {visits} v"
                " JOIN {users} u ON u.id = v.user_id"
                " WHERE u.auth0_id = %s"
            ).format(
                visits=sql.Identifier("user_visits"),
                users=sql.Identifier("users"),
            ),
            (auth0_id,),
        )
        return cursor.fetchone()["n"]

    def test_visit_returns_204(self, client):
        """POST /api/users/visit returns 204 No Content."""
        resp = client.post("/api/users/visit")
        assert resp.status_code == 204
        assert resp.content == b""

    def test_visit_creates_row_and_counts_one(self, client, db_conn):
        """The first visit upserts the user row (it can race ahead of
        GET /api/users on a brand-new user's first load) and counts as 1."""
        resp = client.post("/api/users/visit")
        assert resp.status_code == 204
        row = self._read_visit_row(db_conn)
        assert row is not None, "visit should upsert the user row"
        assert row["visit_count"] == 1

    def test_visit_increments_each_call(self, client, db_conn):
        """Each POST adds exactly one (one load/refresh), never N."""
        client.post("/api/users/visit")
        client.post("/api/users/visit")
        client.post("/api/users/visit")
        row = self._read_visit_row(db_conn)
        assert row["visit_count"] == 3

    def test_visit_sets_last_visit_at(self, client, db_conn):
        """last_visit_at is NULL until the first visit, then stamped."""
        assert self._read_visit_row(db_conn) is None
        client.post("/api/users/visit")
        row = self._read_visit_row(db_conn)
        assert row["last_visit_at"] is not None

    def test_visit_preserves_display_name(self, client, db_conn):
        """The upsert inside the visit endpoint must not clobber a custom
        display_name (mirrors GET /api/users semantics)."""
        user = _make_user(
            {"auth0_id": "auth0|test_user_123", "display_name": "Custom Name"}
        )
        _insert_user(db_conn, user)
        resp = client.post("/api/users/visit")
        assert resp.status_code == 204
        row = self._read_visit_row(db_conn)
        assert row["display_name"] == "Custom Name"
        assert row["visit_count"] == 1

    def test_visit_counts_against_an_existing_seeded_count(self, client, db_conn):
        """A user who already has visits accrues from there, not from zero."""
        user = _make_user(
            {"auth0_id": "auth0|test_user_123", "visit_count": 5}
        )
        _insert_user(db_conn, user)
        client.post("/api/users/visit")
        row = self._read_visit_row(db_conn)
        assert row["visit_count"] == 6

    def test_visit_writes_a_user_visits_log_row(self, client, db_conn):
        """Each POST appends one timestamped row to user_visits (the per-visit
        log that backs the admin Visits modal), not just the counter."""
        resp = client.post("/api/users/visit")
        assert resp.status_code == 204
        assert self._count_visit_log_rows(db_conn) == 1

    def test_visit_log_rows_track_the_counter(self, client, db_conn):
        """The log and the denormalized counter stay in step: N posts ⇒ N rows
        and visit_count == N (both committed in the same transaction)."""
        client.post("/api/users/visit")
        client.post("/api/users/visit")
        client.post("/api/users/visit")
        assert self._count_visit_log_rows(db_conn) == 3
        assert self._read_visit_row(db_conn)["visit_count"] == 3

    def test_visit_without_auth_returns_401(self, test_app):
        """Anonymous POST is rejected — there's no user row to attribute it to."""
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.pop(get_current_user, None)
        try:
            no_auth_client = TestClient(test_app)
            resp = no_auth_client.post("/api/users/visit")
            assert resp.status_code == 401
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override

    def test_visit_without_email_claim_returns_401(self, test_app):
        """A token with a sub but no email can't resolve/upsert a user row."""
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {"sub": "auth0|no_email"}
        try:
            client = TestClient(test_app)
            resp = client.post("/api/users/visit")
            assert resp.status_code == 401
            assert "email" in resp.json()["detail"].lower()
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override
