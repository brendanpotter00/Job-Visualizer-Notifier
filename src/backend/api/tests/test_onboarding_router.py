"""First-sign-in onboarding: ``users.onboarding_completed_at`` and ``POST /api/users/onboarding``.

The flag decides whether the SPA shows the three questions, so the tests pin
the two ways it can go wrong for a user: the questions showing again for an
account that already answered them (a re-stamp, or a NULL served for a
stamped row), and answers being lost or clobbered (Skip dropping them, a
second call replacing the first, a new saved-filters row landing on the stale
'3h'/'7d' column defaults).
"""

from __future__ import annotations

from datetime import datetime

import psycopg2
from psycopg2.extras import Json

from .conftest import _insert_user, _make_user

_CALLER_SUB = "auth0|test_user_123"
_CALLER_EMAIL = "test@example.com"


class _FakePostHog:
    """Records ``capture`` calls; optionally raises to prove analytics never
    fails the request."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def capture(self, event, *, distinct_id, properties):
        if self.fail:
            raise RuntimeError("simulated PostHog outage")
        self.calls.append(
            {"event": event, "distinct_id": distinct_id, "properties": properties}
        )


def _install_fake_posthog(monkeypatch, *, fail: bool = False) -> _FakePostHog:
    import api.routers.users as users_router

    fake = _FakePostHog(fail=fail)
    monkeypatch.setattr(users_router, "get_posthog", lambda: fake)
    return fake


def _caller_row(db_conn) -> dict | None:
    cur = db_conn.cursor()
    cur.execute(
        "SELECT id, onboarding_completed_at FROM users WHERE auth0_id = %s",
        (_CALLER_SUB,),
    )
    row = cur.fetchone()
    db_conn.commit()
    return row


def _saved_row(db_conn, user_id: str) -> dict | None:
    cur = db_conn.cursor()
    cur.execute(
        "SELECT recent_time_window, trend_time_window, locations, category, level,"
        " subcategory, recent_active_keyword_list_id, trend_active_keyword_list_id"
        " FROM user_saved_filters WHERE user_id = %s",
        (user_id,),
    )
    row = cur.fetchone()
    db_conn.commit()
    return row


def _insert_caller(db_conn, **overrides) -> dict:
    user = _make_user({"auth0_id": _CALLER_SUB, "email": _CALLER_EMAIL, **overrides})
    _insert_user(db_conn, user)
    return user


_ANSWERS = {
    "category": ["software_engineering", "product_manager"],
    "subcategory": ["backend"],
    "level": ["entry"],
    "locations": ["San Francisco, CA, US", "Remote (US)"],
}


class TestUserResponseCarriesTheStamp:
    def test_new_account_reads_null(self, client):
        """A brand-new row has no stamp: the field is present and null, which
        is the one value that opens the questions."""
        resp = client.get("/api/users")
        assert resp.status_code == 200
        body = resp.json()
        assert "onboardingCompletedAt" in body
        assert body["onboardingCompletedAt"] is None

    def test_stamped_account_reads_its_timestamp(self, client, db_conn):
        _insert_caller(db_conn, onboarding_completed_at="2026-11-01T12:00:00+00:00")
        body = client.get("/api/users").json()
        assert body["onboardingCompletedAt"] is not None
        assert datetime.fromisoformat(body["onboardingCompletedAt"]) == datetime.fromisoformat(
            "2026-11-01T12:00:00+00:00"
        )

    def test_put_returns_the_stamp_too(self, client, db_conn):
        _insert_caller(db_conn, onboarding_completed_at="2026-11-01T12:00:00+00:00")
        body = client.put("/api/users", json={"displayName": "N"}).json()
        assert body["onboardingCompletedAt"] is not None


class TestPostOnboarding:
    def test_first_call_stamps_and_saves_the_answers(self, client, db_conn):
        client.get("/api/users")
        assert _caller_row(db_conn)["onboarding_completed_at"] is None

        resp = client.post("/api/users/onboarding", json=_ANSWERS)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        row = _caller_row(db_conn)
        assert row["onboarding_completed_at"] is not None
        assert datetime.fromisoformat(body["onboardingCompletedAt"]) == row[
            "onboarding_completed_at"
        ]
        saved = body["savedFilters"]
        assert saved["category"] == _ANSWERS["category"]
        assert saved["subcategory"] == ["backend"]
        assert saved["level"] == ["entry"]
        assert saved["locations"] == _ANSWERS["locations"]
        # GET now reads the same stamp, so a later sign-in skips the questions.
        assert client.get("/api/users").json()["onboardingCompletedAt"] == body[
            "onboardingCompletedAt"
        ]

    def test_works_before_the_first_get(self, client, db_conn):
        """The row is upserted first (like /visit), so a POST that races ahead
        of GET /api/users does not 404."""
        resp = client.post("/api/users/onboarding", json={"skipped": True})
        assert resp.status_code == 200, resp.text
        assert _caller_row(db_conn)["onboarding_completed_at"] is not None

    def test_new_row_uses_the_app_time_windows_not_the_column_defaults(
        self, client, db_conn
    ):
        """The columns default to '3h'/'7d'; the app's defaults are 'all'/'90d'.
        A new row written with only the four answer columns would land on the
        stale pair and shrink both pages for a brand-new user."""
        client.post("/api/users/onboarding", json=_ANSWERS)
        row = _saved_row(db_conn, _caller_row(db_conn)["id"])
        assert row["recent_time_window"] == "all"
        assert row["trend_time_window"] == "90d"

    def test_existing_row_keeps_its_windows_and_list_pointers(self, client, db_conn):
        user = _insert_caller(db_conn)
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO user_saved_filters (user_id, recent_time_window,"
            " trend_time_window, locations, category, level, subcategory,"
            " recent_active_keyword_list_id)"
            " VALUES (%s, '24h', '30d', %s, %s, %s, %s, 'builtin-swe')",
            (user["id"], Json(["Austin, TX, US"]), Json(["growth"]), Json([]), Json([])),
        )
        db_conn.commit()

        resp = client.post("/api/users/onboarding", json=_ANSWERS)

        assert resp.status_code == 200, resp.text
        row = _saved_row(db_conn, user["id"])
        assert row["recent_time_window"] == "24h"
        assert row["trend_time_window"] == "30d"
        assert row["recent_active_keyword_list_id"] == "builtin-swe"
        assert row["category"] == _ANSWERS["category"]
        assert row["locations"] == _ANSWERS["locations"]

    def test_second_call_changes_nothing(self, client, db_conn):
        """A retry or a second tab must neither re-stamp nor replace the answers."""
        first = client.post("/api/users/onboarding", json=_ANSWERS).json()
        stamp = _caller_row(db_conn)["onboarding_completed_at"]

        second = client.post(
            "/api/users/onboarding",
            json={"category": ["growth"], "level": ["senior"], "skipped": True},
        )

        assert second.status_code == 200, second.text
        assert _caller_row(db_conn)["onboarding_completed_at"] == stamp
        assert second.json()["onboardingCompletedAt"] == first["onboardingCompletedAt"]
        # The response reports what is stored: the FIRST answers.
        assert second.json()["savedFilters"]["category"] == _ANSWERS["category"]
        row = _saved_row(db_conn, _caller_row(db_conn)["id"])
        assert row["category"] == _ANSWERS["category"]
        assert row["level"] == ["entry"]

    def test_an_already_stamped_account_is_not_restamped(self, client, db_conn):
        """The backfilled accounts (every row that existed at the migration)."""
        _insert_caller(db_conn, onboarding_completed_at="2026-01-01T00:00:00+00:00")
        resp = client.post("/api/users/onboarding", json=_ANSWERS)
        assert resp.status_code == 200
        assert _caller_row(db_conn)["onboarding_completed_at"] == datetime.fromisoformat(
            "2026-01-01T00:00:00+00:00"
        )
        # Nothing written: no saved-filters row appears.
        assert _saved_row(db_conn, _caller_row(db_conn)["id"]) is None

    def test_skip_keeps_the_answers_already_given(self, client, db_conn):
        resp = client.post(
            "/api/users/onboarding",
            json={"category": ["data_scientist"], "skipped": True, "step": 2},
        )
        assert resp.status_code == 200, resp.text
        row = _saved_row(db_conn, _caller_row(db_conn)["id"])
        assert row["category"] == ["data_scientist"]
        assert row["level"] == []
        assert _caller_row(db_conn)["onboarding_completed_at"] is not None

    def test_skip_with_no_answers_still_stamps(self, client, db_conn):
        resp = client.post("/api/users/onboarding", json={"skipped": True, "step": 1})
        assert resp.status_code == 200, resp.text
        assert _caller_row(db_conn)["onboarding_completed_at"] is not None
        saved = resp.json()["savedFilters"]
        assert saved["category"] == saved["level"] == saved["locations"] == []

    def test_subcategory_is_dropped_without_software_engineering(self, client, db_conn):
        resp = client.post(
            "/api/users/onboarding",
            json={"category": ["product_manager"], "subcategory": ["backend"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["savedFilters"]["subcategory"] == []
        row = _saved_row(db_conn, _caller_row(db_conn)["id"])
        assert row["subcategory"] == []
        assert row["category"] == ["product_manager"]

    def test_subcategory_is_dropped_with_no_category(self, client, db_conn):
        resp = client.post("/api/users/onboarding", json={"subcategory": ["backend"]})
        assert resp.status_code == 200
        assert resp.json()["savedFilters"]["subcategory"] == []

    def test_lists_are_deduped(self, client):
        resp = client.post(
            "/api/users/onboarding",
            json={"level": ["entry", "entry"], "locations": ["Remote (US)", "Remote (US)"]},
        )
        assert resp.status_code == 200
        assert resp.json()["savedFilters"]["level"] == ["entry"]
        assert resp.json()["savedFilters"]["locations"] == ["Remote (US)"]

    def test_unknown_key_is_rejected(self, client, db_conn):
        resp = client.post("/api/users/onboarding", json={"salary": 1})
        assert resp.status_code == 422
        # A rejected body writes nothing: no stamp.
        row = _caller_row(db_conn)
        assert row is None or row["onboarding_completed_at"] is None

    def test_oversize_list_is_rejected(self, client):
        resp = client.post(
            "/api/users/onboarding", json={"level": [f"l{i}" for i in range(51)]}
        )
        assert resp.status_code == 422

    def test_empty_slug_is_rejected(self, client):
        resp = client.post("/api/users/onboarding", json={"category": [""]})
        assert resp.status_code == 422

    def test_step_out_of_range_is_rejected(self, client):
        assert client.post("/api/users/onboarding", json={"step": 4}).status_code == 422
        assert client.post("/api/users/onboarding", json={"step": 0}).status_code == 422

    def test_response_is_camel_case(self, client):
        body = client.post("/api/users/onboarding", json={}).json()
        assert set(body) == {"onboardingCompletedAt", "savedFilters"}
        assert "recentTimeWindow" in body["savedFilters"]

    def test_without_auth_returns_401(self, test_app):
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.pop(get_current_user, None)
        try:
            resp = TestClient(test_app).post("/api/users/onboarding", json={})
            assert resp.status_code == 401
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override

    def test_without_email_claim_returns_401(self, test_app):
        from fastapi.testclient import TestClient
        from api.auth.dependencies import get_current_user

        saved_override = test_app.dependency_overrides.get(get_current_user)
        test_app.dependency_overrides[get_current_user] = lambda: {"sub": "auth0|no_email"}
        try:
            resp = TestClient(test_app).post("/api/users/onboarding", json={})
            assert resp.status_code == 401
        finally:
            if saved_override is not None:
                test_app.dependency_overrides[get_current_user] = saved_override

    def test_driver_error_is_a_500_and_writes_nothing(
        self, test_app, db_conn, monkeypatch
    ):
        from fastapi.testclient import TestClient
        import api.routers.users as users_router

        def _boom(*_args, **_kwargs):
            raise psycopg2.OperationalError("simulated")

        monkeypatch.setattr(users_router, "complete_onboarding", _boom)
        resp = TestClient(test_app, raise_server_exceptions=False).post(
            "/api/users/onboarding", json=_ANSWERS
        )
        assert resp.status_code == 500
        assert _caller_row(db_conn)["onboarding_completed_at"] is None


class TestOnboardingAnalytics:
    def test_finish_mirrors_onboarding_completed_with_counts(self, client, monkeypatch):
        fake = _install_fake_posthog(monkeypatch)
        client.post("/api/users/onboarding", json={**_ANSWERS, "sessionId": "sess-1"})
        events = [c for c in fake.calls if c["event"].startswith("onboarding_")]
        assert len(events) == 1
        event = events[0]
        assert event["event"] == "onboarding_completed"
        assert event["distinct_id"] == _CALLER_SUB
        assert event["properties"] == {
            "category_count": 2,
            "subcategory_count": 1,
            "level_count": 1,
            "location_count": 2,
            "$session_id": "sess-1",
        }

    def test_skip_mirrors_onboarding_skipped_with_its_step(self, client, monkeypatch):
        fake = _install_fake_posthog(monkeypatch)
        client.post(
            "/api/users/onboarding",
            json={"category": ["growth"], "skipped": True, "step": 2},
        )
        events = [c for c in fake.calls if c["event"].startswith("onboarding_")]
        assert [e["event"] for e in events] == ["onboarding_skipped"]
        assert events[0]["properties"]["step"] == 2
        assert events[0]["properties"]["category_count"] == 1
        assert "$session_id" not in events[0]["properties"]

    def test_second_call_mirrors_nothing(self, client, monkeypatch):
        client.post("/api/users/onboarding", json=_ANSWERS)
        fake = _install_fake_posthog(monkeypatch)
        client.post("/api/users/onboarding", json=_ANSWERS)
        assert [c for c in fake.calls if c["event"].startswith("onboarding_")] == []

    def test_posthog_failure_does_not_fail_the_request(self, client, db_conn, monkeypatch):
        _install_fake_posthog(monkeypatch, fail=True)
        resp = client.post("/api/users/onboarding", json=_ANSWERS)
        assert resp.status_code == 200
        assert _caller_row(db_conn)["onboarding_completed_at"] is not None


class TestCompleteOnboardingService:
    def test_no_such_user_returns_none(self, db_conn):
        from api.services.user_service import complete_onboarding

        assert (
            complete_onboarding(
                db_conn, "nope", category=[], subcategory=[], level=[], locations=[]
            )
            is None
        )

    def test_reports_whether_it_set_the_stamp(self, db_conn):
        from api.services.user_service import complete_onboarding

        user = _insert_caller(db_conn)
        first = complete_onboarding(
            db_conn, user["id"], category=["growth"], subcategory=[], level=[], locations=[]
        )
        second = complete_onboarding(
            db_conn, user["id"], category=["mid"], subcategory=[], level=[], locations=[]
        )
        assert first is not None and first["newly_completed"] is True
        assert second is not None and second["newly_completed"] is False
        assert second["completed_at"] == first["completed_at"]
        assert second["saved_filters"]["category"] == ["growth"]
