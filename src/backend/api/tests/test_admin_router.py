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


class TestGrantAdmin:
    """POST /api/admin/users/{user_id}/admin promotes a user."""

    def _setup_caller(self, db_conn):
        """Insert the test caller (the default admin from conftest) into users."""
        caller = _make_user(
            {
                "id": "caller-id",
                "auth0_id": "auth0|test_user_123",
                "email": "test@example.com",
            }
        )
        _insert_user(db_conn, caller)
        return caller

    def test_grant_admin_inserts_row(self, client, db_conn):
        self._setup_caller(db_conn)
        target = _make_user(
            {"id": "target1", "auth0_id": "auth0|t1", "email": "promote@example.com"}
        )
        _insert_user(db_conn, target)

        resp = client.post(f"/api/admin/users/{target['id']}/admin")
        assert resp.status_code == 204

        listing = client.get("/api/admin/users").json()["users"]
        promoted = {u["id"]: u["isAdmin"] for u in listing}
        assert promoted[target["id"]] is True

    def test_grant_admin_idempotent(self, client, db_conn):
        self._setup_caller(db_conn)
        target = _make_user(
            {"id": "target2", "auth0_id": "auth0|t2", "email": "twice@example.com"}
        )
        _insert_user(db_conn, target)

        first = client.post(f"/api/admin/users/{target['id']}/admin")
        second = client.post(f"/api/admin/users/{target['id']}/admin")
        assert first.status_code == 204
        assert second.status_code == 204

    def test_grant_admin_unknown_user_returns_404(self, client, db_conn):
        self._setup_caller(db_conn)

        resp = client.post("/api/admin/users/does-not-exist/admin")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_grant_admin_records_granted_by(self, client, db_conn):
        caller = self._setup_caller(db_conn)
        target = _make_user(
            {"id": "target3", "auth0_id": "auth0|t3", "email": "audit@example.com"}
        )
        _insert_user(db_conn, target)

        resp = client.post(f"/api/admin/users/{target['id']}/admin")
        assert resp.status_code == 204

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT granted_by FROM admins WHERE user_id = %s", (target["id"],)
            )
            row = cur.fetchone()
        assert row is not None
        assert row["granted_by"] == caller["id"]

    def test_grant_admin_idempotent_preserves_original_granted_by(
        self, client, test_app, db_conn
    ):
        """``ON CONFLICT DO NOTHING`` must preserve the original granter.

        If admin A grants user X, then admin B calls grant again on X, the
        ``granted_by`` row must still point to A — the audit anchor is the
        *first* grant, not the most recent retry. Regression guard for any
        future switch to ``DO UPDATE``.
        """
        from api.auth.dependencies import get_current_user, require_admin

        admin_a = self._setup_caller(db_conn)  # auth0|test_user_123 / test@example.com
        target = _make_user(
            {"id": "audit-target", "auth0_id": "auth0|tg", "email": "audit2@example.com"}
        )
        _insert_user(db_conn, target)

        # First grant: as admin A (the default test caller).
        resp_a = client.post(f"/api/admin/users/{target['id']}/admin")
        assert resp_a.status_code == 204

        # Insert admin B into users and admins, then flip the auth overrides
        # so the next grant call is "as admin B".
        admin_b = _make_user(
            {"id": "admin-b-id", "auth0_id": "auth0|b", "email": "b@example.com"}
        )
        _insert_user(db_conn, admin_b)
        _insert_admin(db_conn, admin_b["id"])

        b_claims = {"sub": "auth0|b", "email": "b@example.com"}
        saved_cu = test_app.dependency_overrides.get(get_current_user)
        saved_ra = test_app.dependency_overrides.get(require_admin)
        test_app.dependency_overrides[get_current_user] = lambda: b_claims
        test_app.dependency_overrides[require_admin] = lambda: b_claims
        try:
            client_b = TestClient(test_app)
            resp_b = client_b.post(f"/api/admin/users/{target['id']}/admin")
            assert resp_b.status_code == 204
        finally:
            if saved_cu is not None:
                test_app.dependency_overrides[get_current_user] = saved_cu
            if saved_ra is not None:
                test_app.dependency_overrides[require_admin] = saved_ra

        # The audit row must STILL credit admin A.
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT granted_by FROM admins WHERE user_id = %s", (target["id"],)
            )
            row = cur.fetchone()
        assert row is not None
        assert row["granted_by"] == admin_a["id"], (
            "ON CONFLICT DO NOTHING must preserve the original granter row"
        )

    def test_grant_admin_granter_fk_violation_returns_500_not_404(self):
        """Granter-row-deleted race: 500, not a misleading 404.

        ``admins`` has two FKs to ``users.id``. If the granter's user row
        is deleted between ``_resolve_granter_id`` and the INSERT, the
        ForeignKeyViolation comes from ``admins_granted_by_fkey`` — NOT
        from the target user FK. The original handler mapped any FK
        violation to "User not found", which pointed admins at the wrong
        record. Unit-test the constraint-name branch here because the race
        is impractical to integration-test.

        psycopg2's real ``ForeignKeyViolation.diag`` is a C-level read-only
        attribute, so we use a Python subclass that overrides ``diag`` via
        a class-level descriptor — the router reads it via
        ``getattr(exc.diag, "constraint_name", None)``, so duck-typing is
        sufficient.
        """
        import psycopg2
        from fastapi import HTTPException
        from api.routers.admin import grant_user_admin

        class _Diag:
            constraint_name = "admins_granted_by_fkey"

        class _FKViolation(psycopg2.errors.ForeignKeyViolation):
            diag = _Diag()

        exc = _FKViolation()

        class _Conn:
            def rollback(self):
                pass

        def _raising_grant(_conn, _user_id, granted_by_id):
            raise exc

        import api.routers.admin as admin_router

        saved = admin_router.grant_admin
        admin_router.grant_admin = _raising_grant
        saved_resolve = admin_router._resolve_granter_id
        admin_router._resolve_granter_id = lambda _c, _a: "granter-id"
        try:
            try:
                grant_user_admin(
                    user_id="any-target",
                    conn=_Conn(),
                    admin={"sub": "x", "email": "x@x"},
                )
            except HTTPException as http_exc:
                assert http_exc.status_code == 500
                assert "granter" in http_exc.detail.lower()
            else:
                raise AssertionError(
                    "grant_user_admin should have raised HTTPException(500)"
                )
        finally:
            admin_router.grant_admin = saved
            admin_router._resolve_granter_id = saved_resolve

    def test_grant_admin_target_fk_violation_returns_404(self):
        """Sibling assertion to the granter-FK test: when the constraint
        is ``admins_user_id_fkey`` (target user doesn't exist), the router
        keeps the existing 404 → "User not found" translation."""
        import psycopg2
        from fastapi import HTTPException
        from api.routers.admin import grant_user_admin

        class _Diag:
            constraint_name = "admins_user_id_fkey"

        class _FKViolation(psycopg2.errors.ForeignKeyViolation):
            diag = _Diag()

        exc = _FKViolation()

        class _Conn:
            def rollback(self):
                pass

        def _raising_grant(_conn, _user_id, granted_by_id):
            raise exc

        import api.routers.admin as admin_router

        saved = admin_router.grant_admin
        admin_router.grant_admin = _raising_grant
        saved_resolve = admin_router._resolve_granter_id
        admin_router._resolve_granter_id = lambda _c, _a: "granter-id"
        try:
            try:
                grant_user_admin(
                    user_id="missing-target",
                    conn=_Conn(),
                    admin={"sub": "x", "email": "x@x"},
                )
            except HTTPException as http_exc:
                assert http_exc.status_code == 404
                assert "not found" in http_exc.detail.lower()
            else:
                raise AssertionError(
                    "grant_user_admin should have raised HTTPException(404)"
                )
        finally:
            admin_router.grant_admin = saved
            admin_router._resolve_granter_id = saved_resolve


class TestRevokeAdmin:
    """DELETE /api/admin/users/{user_id}/admin revokes a user."""

    def _setup_caller_with_grant(self, db_conn):
        caller = _make_user(
            {
                "id": "caller-id",
                "auth0_id": "auth0|test_user_123",
                "email": "test@example.com",
            }
        )
        _insert_user(db_conn, caller)
        _insert_admin(db_conn, caller["id"])
        return caller

    def test_revoke_admin_deletes_row(self, client, db_conn):
        self._setup_caller_with_grant(db_conn)
        target = _make_user(
            {"id": "target1", "auth0_id": "auth0|t1", "email": "demote@example.com"}
        )
        _insert_user(db_conn, target)
        _insert_admin(db_conn, target["id"])

        resp = client.delete(f"/api/admin/users/{target['id']}/admin")
        assert resp.status_code == 204

        listing = client.get("/api/admin/users").json()["users"]
        demoted = {u["id"]: u["isAdmin"] for u in listing}
        assert demoted[target["id"]] is False

    def test_revoke_admin_idempotent_on_non_admin(self, client, db_conn):
        self._setup_caller_with_grant(db_conn)
        target = _make_user(
            {"id": "target2", "auth0_id": "auth0|t2", "email": "notadmin@example.com"}
        )
        _insert_user(db_conn, target)

        resp = client.delete(f"/api/admin/users/{target['id']}/admin")
        assert resp.status_code == 204

    def test_revoke_self_returns_400(self, client, db_conn):
        caller = self._setup_caller_with_grant(db_conn)

        resp = client.delete(f"/api/admin/users/{caller['id']}/admin")
        assert resp.status_code == 400
        assert "own" in resp.json()["detail"].lower()

    def test_revoke_last_admin_returns_409(self, client, db_conn):
        """Last-admin guardrail: revoking the only admin must 409, not 204.

        The router-level self-revoke 400 only protects against a single
        admin revoking themselves. Two admins acting concurrently can each
        pass the self-check and try to revoke the other; the service-level
        ``FOR UPDATE`` + count guard is what actually prevents zero-admins.

        Setup: caller is a *non-admin* (the require_admin override below is
        what lets them past the auth gate). The only admin row in the table
        belongs to a different user — and revoking it would leave zero.
        """
        # Caller must exist in users (for granter resolution), but is NOT
        # the admin in this scenario.
        caller = _make_user(
            {
                "id": "caller-id-not-admin",
                "auth0_id": "auth0|test_user_123",
                "email": "test@example.com",
            }
        )
        _insert_user(db_conn, caller)
        # The single admin in the system is a DIFFERENT user.
        sole_admin = _make_user(
            {"id": "sole-admin", "auth0_id": "auth0|sole", "email": "sole@example.com"}
        )
        _insert_user(db_conn, sole_admin)
        _insert_admin(db_conn, sole_admin["id"])

        # The caller passes require_admin via the default test override,
        # so they reach the revoke handler. Since caller != sole_admin, the
        # self-revoke 400 doesn't fire; the LastAdminError → 409 does.
        resp = client.delete(f"/api/admin/users/{sole_admin['id']}/admin")
        assert resp.status_code == 409, resp.text
        assert "last admin" in resp.json()["detail"].lower()

        # Row must still be present — guardrail must NOT delete-then-undo.
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM admins WHERE user_id = %s", (sole_admin["id"],)
            )
            row = cur.fetchone()
        assert row is not None

    def test_revoke_admin_uses_for_update_lock(self):
        """Source-level pin: the FOR UPDATE row lock is the entire contract
        of the last-admin guardrail. The single-connection test suite cannot
        reliably reproduce the concurrent revoke race (a true two-connection
        race would be flaky against TestClient's threading model), so this
        guard inspects ``inspect.getsource(revoke_admin)`` and fails if
        ``FOR UPDATE`` is silently removed. Ugly, but it pins the SQL
        invariant that ``test_revoke_last_admin_returns_409`` only weakly
        implies through behavior.
        """
        import inspect
        from api.services.admin_service import revoke_admin

        source = inspect.getsource(revoke_admin)
        assert "FOR UPDATE" in source, (
            "revoke_admin must hold a SELECT ... FOR UPDATE lock on admins "
            "to serialize concurrent revokes — see LastAdminError docstring."
        )

    def test_revoke_when_multiple_admins_exist_succeeds(self, client, db_conn):
        """The last-admin guardrail must NOT fire when 2+ admins exist."""
        caller = self._setup_caller_with_grant(db_conn)
        # caller is an admin (granted in setup helper). Add a SECOND admin.
        second = _make_user(
            {"id": "second-admin", "auth0_id": "auth0|second", "email": "second@example.com"}
        )
        _insert_user(db_conn, second)
        _insert_admin(db_conn, second["id"])

        # Revoke the second admin — caller stays admin. Count goes 2 → 1,
        # so the guardrail must allow it.
        resp = client.delete(f"/api/admin/users/{second['id']}/admin")
        assert resp.status_code == 204

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM admins")
            assert cur.fetchone()["n"] == 1
            cur.execute("SELECT 1 FROM admins WHERE user_id = %s", (caller["id"],))
            assert cur.fetchone() is not None


class TestGrantRevokeGate:
    """Grant/revoke endpoints are also behind require_admin."""

    def test_grant_without_admin_returns_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin

        _insert_user(
            db_conn,
            _make_user(
                {"auth0_id": "auth0|test_user_123", "email": "test@example.com"}
            ),
        )
        target = _make_user(
            {"id": "tg1", "auth0_id": "auth0|tg1", "email": "t@example.com"}
        )
        _insert_user(db_conn, target)

        saved = test_app.dependency_overrides.pop(require_admin, None)
        try:
            client = TestClient(test_app)
            resp = client.post(f"/api/admin/users/{target['id']}/admin")
            assert resp.status_code == 403
        finally:
            if saved is not None:
                test_app.dependency_overrides[require_admin] = saved

    def test_revoke_without_admin_returns_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin

        _insert_user(
            db_conn,
            _make_user(
                {"auth0_id": "auth0|test_user_123", "email": "test@example.com"}
            ),
        )
        target = _make_user(
            {"id": "tr1", "auth0_id": "auth0|tr1", "email": "t@example.com"}
        )
        _insert_user(db_conn, target)
        _insert_admin(db_conn, target["id"])

        saved = test_app.dependency_overrides.pop(require_admin, None)
        try:
            client = TestClient(test_app)
            resp = client.delete(f"/api/admin/users/{target['id']}/admin")
            assert resp.status_code == 403
        finally:
            if saved is not None:
                test_app.dependency_overrides[require_admin] = saved


class TestSignupProviderHelper:
    """Direct unit tests for ``_signup_provider_from_auth0_id``.

    The helper is the *producer* of ``SignupProvider`` literals consumed by
    ``AdminUsersStatsResponse.by_provider: dict[SignupProvider, int]`` —
    Pydantic v2 validates that dict's keys at runtime, so a producer that
    silently returns a non-Literal would make ``/api/admin/users/stats``
    500 for every admin once a new IdP prefix landed in production.

    The previous ``-> str`` return type was permissive enough that a
    future ``return "github"`` would type-check but blow up at the
    serialization boundary. With the tightened ``-> SignupProvider``
    return type these tests pin both the mapping AND the closed-set
    contract; a regression to ``-> str`` would still pass the tests but
    fail mypy/pyright in CI.
    """

    def test_unknown_prefix_returns_other(self):
        from api.services.admin_service import _signup_provider_from_auth0_id

        # A wholly-new IdP prefix must fall through to "other" — never
        # raise, never return a raw prefix that would then violate the
        # AdminUsersStatsResponse Pydantic Literal validation.
        assert _signup_provider_from_auth0_id("github|abc123") == "other"

    def test_no_pipe_returns_other(self):
        from api.services.admin_service import _signup_provider_from_auth0_id

        # Malformed auth0_id with no pipe separator still maps to a
        # closed-set value (the prefix-extraction branch returns the
        # whole string when there's no pipe).
        assert _signup_provider_from_auth0_id("bareid") == "other"

    def test_google_prefix(self):
        from api.services.admin_service import _signup_provider_from_auth0_id

        assert _signup_provider_from_auth0_id("google|123") == "google"

    def test_google_oauth2_prefix(self):
        from api.services.admin_service import _signup_provider_from_auth0_id

        assert _signup_provider_from_auth0_id("google-oauth2|abc") == "google"

    def test_auth0_prefix_maps_to_email(self):
        from api.services.admin_service import _signup_provider_from_auth0_id

        assert _signup_provider_from_auth0_id("auth0|abc") == "email"


class TestResolveGranterIdBranches:
    """Edge branches of ``_resolve_granter_id`` that aren't covered by the
    happy-path grant tests."""

    def test_grant_without_email_claim_returns_401(self, test_app, db_conn):
        """``require_admin`` would normally 401 first, but if a custom override
        ever returns claims without ``email`` (e.g. a misconfigured auth
        bypass), the granter resolver's defensive 401 must still fire."""
        from api.auth.dependencies import get_current_user, require_admin

        target = _make_user(
            {"id": "tg-no-email", "auth0_id": "auth0|tge", "email": "tge@example.com"}
        )
        _insert_user(db_conn, target)

        no_email_claims = {"sub": "auth0|no_email"}
        saved_cu = test_app.dependency_overrides.get(get_current_user)
        saved_ra = test_app.dependency_overrides.get(require_admin)
        test_app.dependency_overrides[get_current_user] = lambda: no_email_claims
        # Force past require_admin even though there's no email — the bypass
        # is what makes the granter-resolver branch reachable.
        test_app.dependency_overrides[require_admin] = lambda: no_email_claims
        try:
            client = TestClient(test_app)
            resp = client.post(f"/api/admin/users/{target['id']}/admin")
            assert resp.status_code == 401
            assert "email" in resp.json()["detail"].lower()
        finally:
            if saved_cu is not None:
                test_app.dependency_overrides[get_current_user] = saved_cu
            if saved_ra is not None:
                test_app.dependency_overrides[require_admin] = saved_ra


class TestJobsQaGate:
    """jobs_qa router is now gated behind require_admin.

    Each endpoint declares its own ``Depends(require_admin)`` rather than
    inheriting a router-level dependency, so the gate has to be re-checked
    per endpoint — a future endpoint added without the dep would silently
    re-open the hole that motivated this PR.
    """

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

    def test_jobs_qa_scrape_runs_without_admin_returns_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin

        _insert_user(
            db_conn,
            _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}),
        )

        saved_override = test_app.dependency_overrides.pop(require_admin, None)
        try:
            client = TestClient(test_app)
            resp = client.get("/api/jobs-qa/scrape-runs")
            assert resp.status_code == 403
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[require_admin] = saved_override

    def test_jobs_qa_trigger_scrape_without_admin_returns_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin

        _insert_user(
            db_conn,
            _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}),
        )

        saved_override = test_app.dependency_overrides.pop(require_admin, None)
        try:
            client = TestClient(test_app)
            resp = client.post("/api/jobs-qa/trigger-scrape", params={"company": "google"})
            assert resp.status_code == 403
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[require_admin] = saved_override
