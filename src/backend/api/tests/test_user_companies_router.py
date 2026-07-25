"""Integration tests for the add-company endpoints on the users router."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.routers import users as users_router
from api.services import company_add_service
from api.services.ats_detector import Detection
from api.services.rate_limit import SlidingWindowRateLimiter
from api.services.url_guard import BlockedURLError


@pytest.fixture(autouse=True)
def _reset_add_company_limiter():
    users_router._add_company_rate_limiter.reset()
    yield
    users_router._add_company_rate_limiter.reset()


def _rows(db_conn, table: str, where: str, params) -> list:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT * FROM {} WHERE " + where).format(sql.Identifier(table)),
        params,
    )
    return cur.fetchall()


def _patch_detect(monkeypatch, result):
    async def _fake(url, http):
        return result

    monkeypatch.setattr(company_add_service, "detect_ats", _fake)
    monkeypatch.setattr(company_add_service, "validate_public_url", lambda u: None)


class TestAddCompany:
    def test_add_greenhouse_creates_and_enables(self, test_app, db_conn, monkeypatch):
        _patch_detect(
            monkeypatch,
            Detection(
                ats="greenhouse", company_id="acmeco", display_name="Acmeco",
                board_token="acmeco", provider_config={}, job_count=3,
            ),
        )
        client = TestClient(test_app)
        resp = client.post(
            "/api/users/companies", json={"url": "https://boards.greenhouse.io/acmeco"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "added"
        assert body["company"]["id"] == "acmeco"
        assert body["company"]["sourceAts"] == "greenhouse"
        assert body["company"]["jobsUrl"] == "https://boards.greenhouse.io/acmeco"

        companies = _rows(db_conn, "companies", "id = %s", ("acmeco",))
        assert len(companies) == 1
        assert companies[0]["listed"] is False
        assert companies[0]["ats"] == "greenhouse"
        enabled = _rows(
            db_conn, "user_enabled_companies", "company_id = %s", ("acmeco",)
        )
        assert len(enabled) == 1

    def test_add_existing_board_is_already_tracked(self, test_app, db_conn, monkeypatch):
        det = Detection(
            ats="lever", company_id="dedupco", display_name="Dedupco",
            board_token="dedupco", provider_config={}, job_count=1,
        )
        _patch_detect(monkeypatch, det)
        client = TestClient(test_app)
        first = client.post(
            "/api/users/companies", json={"url": "https://jobs.lever.co/dedupco"}
        )
        assert first.json()["status"] == "added"
        second = client.post(
            "/api/users/companies", json={"url": "https://jobs.lever.co/dedupco"}
        )
        assert second.status_code == 200
        assert second.json()["status"] == "alreadyTracked"
        # Still exactly one company row.
        assert len(_rows(db_conn, "companies", "id = %s", ("dedupco",))) == 1

    def test_bad_url_returns_422(self, test_app, monkeypatch):
        def _raise(u):
            raise BlockedURLError("blocked")

        monkeypatch.setattr(company_add_service, "validate_public_url", _raise)
        client = TestClient(test_app)
        resp = client.post(
            "/api/users/companies", json={"url": "http://169.254.169.254/"}
        )
        assert resp.status_code == 422

    def test_unknown_site_queues_onboarding(self, test_app, db_conn, monkeypatch):
        _patch_detect(monkeypatch, None)  # no ATS detected

        from api.tasks.onboard_custom_company import onboard_custom_company

        calls = {}

        async def _fake_defer(**kwargs):
            calls.update(kwargs)

        monkeypatch.setattr(onboard_custom_company, "defer_async", _fake_defer)

        client = TestClient(test_app)
        resp = client.post(
            "/api/users/companies", json={"url": "https://careers.tesla.com/jobs"}
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        submission_id = body["submissionId"]
        assert submission_id
        assert calls["submission_id"] == submission_id
        subs = _rows(db_conn, "company_submissions", "id = %s", (submission_id,))
        assert len(subs) == 1 and subs[0]["status"] == "pending"

        # And it's pollable.
        poll = client.get(f"/api/users/companies/submissions/{submission_id}")
        assert poll.status_code == 200
        assert poll.json()["status"] == "pending"

    def test_rate_limited_returns_429(self, test_app, monkeypatch):
        monkeypatch.setattr(
            users_router, "_add_company_rate_limiter",
            SlidingWindowRateLimiter(1, 60),
        )
        _patch_detect(
            monkeypatch,
            Detection(
                ats="greenhouse", company_id="rlco", display_name="Rlco",
                board_token="rlco", provider_config={}, job_count=1,
            ),
        )
        client = TestClient(test_app)
        first = client.post(
            "/api/users/companies", json={"url": "https://boards.greenhouse.io/rlco"}
        )
        assert first.status_code == 200
        second = client.post(
            "/api/users/companies", json={"url": "https://boards.greenhouse.io/rlco"}
        )
        assert second.status_code == 429
        assert "Retry-After" in second.headers


class TestGetUserCompanies:
    def test_lists_only_tracked_custom_companies(self, test_app, db_conn, monkeypatch):
        _patch_detect(
            monkeypatch,
            Detection(
                ats="greenhouse", company_id="listco", display_name="Listco",
                board_token="listco", provider_config={}, job_count=1,
            ),
        )
        client = TestClient(test_app)
        client.post(
            "/api/users/companies", json={"url": "https://boards.greenhouse.io/listco"}
        )
        resp = client.get("/api/users/companies")
        assert resp.status_code == 200
        ids = [c["id"] for c in resp.json()["companies"]]
        assert "listco" in ids

    def test_submission_not_owned_returns_404(self, test_app):
        client = TestClient(test_app)
        resp = client.get("/api/users/companies/submissions/does-not-exist")
        assert resp.status_code == 404
