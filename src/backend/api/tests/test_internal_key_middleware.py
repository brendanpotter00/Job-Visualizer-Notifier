"""Tests for the require_internal_key middleware.

Exercises the gate against a minimal FastAPI app rather than the real one
in ``api.main`` so the tests stay focused on the middleware contract and
don't need to stand up the lifespan, DB pool, or auto-scraper.
"""

import logging

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from api.auth.internal_key import require_internal_key, warn_if_unset
from api.config import settings


# Override conftest's autouse ``clean_tables`` fixture so these tests don't
# pull in the real ``db_conn`` fixture (which bootstraps a Postgres schema
# + Alembic — overkill for an in-memory middleware test).
@pytest.fixture(autouse=True)
def clean_tables():
    yield


@pytest.fixture
def app_factory(monkeypatch):
    """Build a FastAPI app with the gate installed for a chosen key value."""

    def _build(key: str | None) -> FastAPI:
        monkeypatch.setattr(settings, "internal_api_key", key)
        app = FastAPI()
        app.middleware("http")(require_internal_key)

        @app.get("/api/jobs")
        def list_jobs():
            return {"ok": True}

        @app.get("/health")
        def health():
            return PlainTextResponse("OK")

        return app

    return _build


class TestKeyEnforced:
    """When settings.internal_api_key is set, the gate must enforce it."""

    def test_missing_header_is_rejected(self, app_factory):
        app = app_factory("expected-secret")
        with TestClient(app) as client:
            resp = client.get("/api/jobs")
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}

    def test_wrong_header_is_rejected(self, app_factory):
        app = app_factory("expected-secret")
        with TestClient(app) as client:
            resp = client.get(
                "/api/jobs", headers={"X-Internal-Key": "wrong-secret"}
            )
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}

    def test_non_ascii_header_is_rejected_not_500(self, app_factory):
        """A non-ASCII header byte must be a clean 401, never a 500.

        HTTP headers travel as latin-1 bytes; a raw high byte like 0xe9 decodes
        server-side into a non-ASCII str ("é"). secrets.compare_digest raises
        TypeError on a str with non-ASCII characters, so comparing raw strings
        would crash this request into the 500 handler instead of denying it.
        Encoding to bytes first keeps it a deterministic Unauthorized. The
        header value is sent as raw bytes because an HTTP client cannot encode
        a non-latin-1 str into a header at all.
        """
        app = app_factory("expected-secret")
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/jobs", headers={"X-Internal-Key": b"\xe9"})
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Unauthorized"}

    def test_correct_header_is_accepted(self, app_factory):
        app = app_factory("expected-secret")
        with TestClient(app) as client:
            resp = client.get(
                "/api/jobs", headers={"X-Internal-Key": "expected-secret"}
            )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_health_is_exempt_without_header(self, app_factory):
        """Railway healthcheck + uptime monitors hit /health without the key."""
        app = app_factory("expected-secret")
        with TestClient(app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.text == "OK"


class TestKeyUnset:
    """When the env var is missing (local dev), the gate is a pass-through."""

    def test_requests_pass_through_when_key_is_none(self, app_factory):
        app = app_factory(None)
        with TestClient(app) as client:
            resp = client.get("/api/jobs")
        assert resp.status_code == 200

    def test_warn_if_unset_logs_when_key_is_none(self, caplog, monkeypatch):
        monkeypatch.setattr(settings, "internal_api_key", None)
        with caplog.at_level(logging.WARNING, logger="api.auth.internal_key"):
            warn_if_unset()
        assert any(
            "INTERNAL_API_KEY is unset" in record.message for record in caplog.records
        ), f"expected unset warning; got {[r.message for r in caplog.records]}"

    def test_warn_if_unset_is_silent_when_key_is_set(self, caplog, monkeypatch):
        monkeypatch.setattr(settings, "internal_api_key", "set-value")
        with caplog.at_level(logging.WARNING, logger="api.auth.internal_key"):
            warn_if_unset()
        assert not any(
            "INTERNAL_API_KEY is unset" in record.message for record in caplog.records
        )
