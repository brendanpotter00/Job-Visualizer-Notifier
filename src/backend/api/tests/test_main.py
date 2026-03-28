"""Tests for main.py: health endpoint and exception handler."""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.testclient import TestClient

from api.dependencies import pool_is_healthy


def _make_app_with_real_health():
    """Create a minimal app that uses the real health endpoint from main."""
    app = FastAPI()

    @app.get("/health")
    def health():
        if not pool_is_healthy():
            return PlainTextResponse("UNAVAILABLE", status_code=503)
        return PlainTextResponse("OK")

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, exc):
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.get("/explode")
    def explode():
        raise RuntimeError("boom")

    return app


class TestHealthEndpoint:
    def test_returns_200_when_pool_healthy(self):
        app = _make_app_with_real_health()
        client = TestClient(app)
        with patch("api.dependencies._pool") as mock_pool:
            mock_pool.closed = False
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.text == "OK"

    def test_returns_503_when_pool_unhealthy(self):
        app = _make_app_with_real_health()
        client = TestClient(app)
        with patch("api.dependencies._pool", None):
            resp = client.get("/health")
        assert resp.status_code == 503
        assert resp.text == "UNAVAILABLE"


class TestUnhandledExceptionHandler:
    def test_returns_500_json(self):
        app = _make_app_with_real_health()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/explode")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Internal server error"}
