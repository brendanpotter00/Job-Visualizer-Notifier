"""The LOCAL-ONLY admin auth bypass (``api/auth/dev_bypass.py``, DEV_AUTH_BYPASS_EMAIL).

Pins every fence: ignored without the setting; honoured only for a loopback
client with no ``Authorization`` header; never on Railway (startup refuses, and
the per-request check refuses too); never against a database that is not local
(startup refuses); a real bearer token still goes through ``validate_token``;
and ``require_admin`` still checks the ``admins`` table for the bypass email.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from api.auth import dev_bypass
from api.auth.dependencies import get_optional_user
from api.config import settings
from api.dependencies import get_db
from api.routers import admin

from .conftest import _insert_admin, _insert_user, _make_user
from .test_launch_radar_service import _launch_radar_isolation  # noqa: F401

EMAIL = "dev-admin@example.com"
CARDS = "/api/admin/launch-radar/cards?status=new"
LOCAL = "http://localhost:8000"  # TestClient's default Host is "testserver", which the bypass refuses
LOCAL_DB = "postgresql://postgres:postgres@localhost:5432/jobscraper"
# Nothing here ever connects to it: the guard only parses the string.
REMOTE_DB = "postgresql://admin:s3cret-pw@prod-db.example.com:5432/railway"


@pytest.fixture(autouse=True)
def _no_railway_and_bypass_reset(monkeypatch) -> Iterator[None]:
    for name in dev_bypass.RAILWAY_MARKERS:
        monkeypatch.delenv(name, raising=False)
    prev = settings.dev_auth_bypass_email
    settings.dev_auth_bypass_email = None
    # The startup guard reads settings.database_url; pin a local one so these
    # tests do not depend on whatever DATABASE_URL the run was started with.
    monkeypatch.setattr(settings, "database_url", LOCAL_DB)
    yield
    settings.dev_auth_bypass_email = prev


@pytest.fixture
def bypass_on() -> None:
    settings.dev_auth_bypass_email = EMAIL


def _request(client: tuple[str, int] | None, headers: dict[str, str] | None = None) -> Request:
    all_headers = {"host": "localhost:8000", **{k.lower(): v for k, v in (headers or {}).items()}}
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.encode(), v.encode()) for k, v in all_headers.items()],
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)


# ---------------------------------------------------------------------------
# dev_bypass_claims
# ---------------------------------------------------------------------------


def test_ignored_without_the_setting() -> None:
    assert dev_bypass.dev_bypass_claims(_request(("127.0.0.1", 5000))) is None


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "127.0.0.2"])
def test_honoured_for_loopback_without_header(bypass_on, host: str) -> None:
    assert dev_bypass.dev_bypass_claims(_request((host, 5000))) == {
        "sub": f"dev-bypass|{EMAIL}",
        "email": EMAIL,
        "given_name": None,
        "family_name": None,
        "picture": None,
    }


@pytest.mark.parametrize(
    "client", [("10.0.0.5", 5000), ("testclient", 50000), ("192.168.1.2", 1), None]
)
def test_rejected_for_non_loopback_or_unknown_client(bypass_on, client) -> None:
    assert dev_bypass.dev_bypass_claims(_request(client)) is None


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "LOCALHOST", "127.0.0.1"])
def test_honoured_for_local_host_headers(bypass_on, host: str) -> None:
    assert dev_bypass.dev_bypass_claims(_request(("127.0.0.1", 5000), {"Host": host})) is not None


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8000", "192.168.1.5:8000",
                                  "localhost.evil.com", ""])
def test_rejected_for_a_non_local_host_header(bypass_on, host: str) -> None:
    """A DNS-rebinding page reaches 127.0.0.1 but keeps its own Host header."""
    assert dev_bypass.dev_bypass_claims(_request(("127.0.0.1", 5000), {"Host": host})) is None


@pytest.mark.parametrize(
    "header", ["Bearer x", "Basic dXNlcjpwYXNz", "garbage", ""]
)
def test_any_authorization_header_disables_it(bypass_on, header: str) -> None:
    req = _request(("127.0.0.1", 5000), {"Authorization": header})
    assert dev_bypass.dev_bypass_claims(req) is None


@pytest.mark.parametrize("marker", dev_bypass.RAILWAY_MARKERS)
def test_per_request_check_refuses_on_railway(bypass_on, monkeypatch, marker: str) -> None:
    monkeypatch.setenv(marker, "production")
    assert dev_bypass.dev_bypass_claims(_request(("127.0.0.1", 5000))) is None


def test_empty_marker_does_not_count(monkeypatch) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "")
    assert dev_bypass.running_on_railway() is False


# ---------------------------------------------------------------------------
# Startup guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("marker", dev_bypass.RAILWAY_MARKERS)
def test_guard_raises_on_railway(bypass_on, monkeypatch, marker: str) -> None:
    monkeypatch.setenv(marker, "some-value")
    with pytest.raises(RuntimeError) as exc:
        dev_bypass.enforce_dev_auth_bypass_guard()
    message = str(exc.value)
    assert "DEV_AUTH_BYPASS_EMAIL" in message and marker in message
    assert EMAIL not in message  # names the variable, never the email


def test_guard_quiet_without_the_setting(monkeypatch, caplog) -> None:
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    with caplog.at_level(logging.WARNING):
        dev_bypass.enforce_dev_auth_bypass_guard()
    assert "DEV_AUTH_BYPASS_EMAIL" not in caplog.text


def test_guard_warns_loudly_when_on_locally(bypass_on, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        dev_bypass.enforce_dev_auth_bypass_guard()
    assert "DEV_AUTH_BYPASS_EMAIL is ON" in caplog.text
    assert "Never set this outside local development" in caplog.text


def test_lifespan_refuses_to_start_on_railway(bypass_on, monkeypatch) -> None:
    """The guard is the FIRST thing the real lifespan does: with a marker set,
    startup raises before migrations or the pool are touched."""
    from api import main as api_main

    monkeypatch.setenv("RAILWAY_PROJECT_ID", "proj")
    with patch.object(api_main, "apply_alembic_migrations_with_retry") as migrate, \
            patch.object(api_main, "init_pool") as init_pool:
        with pytest.raises(RuntimeError, match="DEV_AUTH_BYPASS_EMAIL"):
            with TestClient(api_main.app):
                pass
        migrate.assert_not_called()
        init_pool.assert_not_called()


# ---------------------------------------------------------------------------
# Startup guard: the database must be local
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        LOCAL_DB,
        "postgresql://postgres:postgres@127.0.0.1:5432/jvn_launch_radar",
        "postgresql://postgres:postgres@127.0.0.2/jobscraper",
        "postgresql://postgres:postgres@[::1]:5432/jobscraper",
        "postgresql://postgres:postgres@LOCALHOST:5432/jobscraper",
        "postgresql+psycopg2://postgres:postgres@localhost:5432/jobscraper",
        "postgres://postgres:postgres@localhost/jobscraper",
        # docker-compose.yml's service name, for a backend inside that network.
        "postgresql://postgres:postgres@postgres:5432/jobscraper",
        "postgresql://postgres:postgres@localhost:5432/jobscraper?host=127.0.0.1",
        "host=localhost dbname=jobscraper user=postgres",
    ],
)
def test_local_database_urls_are_local(url: str) -> None:
    assert dev_bypass.non_local_database_reason(url) is None


@pytest.mark.parametrize(
    "url",
    [
        REMOTE_DB,
        "postgresql://u:p@monorail.proxy.rlwy.net:41234/railway",
        "postgresql://u:p@10.0.0.5:5432/jobscraper",
        # libpq lets a query parameter override the authority: the URL says
        # localhost but connects elsewhere.
        "postgresql://u:p@localhost:5432/db?host=prod.railway.internal",
        "postgresql://u:p@localhost:5432/db?hostaddr=10.0.0.5",
        # A userinfo section ends at the LAST "@": the real host is evil.example.
        "postgresql://localhost@evil.example/db",
        "postgresql://u:p@localhost.evil.com/db",
        "postgresql://u:p@postgres.railway.internal:5432/railway",
        "host=prod.example.com dbname=jobscraper",
        # Fail closed: no host at all (a Unix socket), or nothing parseable.
        "postgresql:///jobscraper",
        "not a database url",
    ],
)
def test_non_local_database_urls_are_refused(url: str) -> None:
    assert dev_bypass.non_local_database_reason(url) is not None


def test_guard_raises_for_a_remote_database(bypass_on, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", REMOTE_DB)
    with pytest.raises(RuntimeError) as exc:
        dev_bypass.enforce_dev_auth_bypass_guard()
    message = str(exc.value)
    assert "DEV_AUTH_BYPASS_EMAIL" in message and "prod-db.example.com" in message
    assert "s3cret-pw" not in message  # names the host, never the URL
    assert EMAIL not in message


def test_guard_raises_for_a_host_query_parameter(bypass_on, monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "database_url", "postgresql://u:p@localhost:5432/db?host=prod.railway.internal"
    )
    with pytest.raises(RuntimeError, match="prod.railway.internal"):
        dev_bypass.enforce_dev_auth_bypass_guard()


def test_guard_ignores_a_remote_database_without_the_setting(monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", REMOTE_DB)
    dev_bypass.enforce_dev_auth_bypass_guard()  # no bypass, nothing to refuse


def test_lifespan_refuses_to_start_against_a_remote_database(bypass_on, monkeypatch) -> None:
    """A laptop backend pointed at the production database with the bypass on
    never gets as far as migrations or the pool."""
    from api import main as api_main

    monkeypatch.setattr(settings, "database_url", REMOTE_DB)
    with patch.object(api_main, "apply_alembic_migrations_with_retry") as migrate, \
            patch.object(api_main, "init_pool") as init_pool:
        with pytest.raises(RuntimeError, match="DEV_AUTH_BYPASS_EMAIL"):
            with TestClient(api_main.app):
                pass
        migrate.assert_not_called()
        init_pool.assert_not_called()


# ---------------------------------------------------------------------------
# get_optional_user
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Creds:
    def __init__(self, token: str) -> None:
        self.scheme = "Bearer"
        self.credentials = token


def test_get_optional_user_uses_bypass_only_without_credentials(bypass_on) -> None:
    claims = _run(get_optional_user(_request(("127.0.0.1", 1)), None))
    assert claims is not None and claims["email"] == EMAIL
    assert _run(get_optional_user(_request(("10.0.0.5", 1)), None)) is None


def test_real_bearer_still_goes_to_validate_token(bypass_on) -> None:
    req = _request(("127.0.0.1", 1), {"Authorization": "Bearer x"})
    real = {"sub": "auth0|real", "email": "real@example.com"}
    with patch("api.auth.dependencies.validate_token", return_value=real) as validate:
        assert _run(get_optional_user(req, _Creds("x"))) == real
    validate.assert_called_once_with("x")


def test_invalid_bearer_is_still_401_with_bypass_on(bypass_on) -> None:
    req = _request(("127.0.0.1", 1), {"Authorization": "Bearer not.a.jwt"})
    with pytest.raises(HTTPException) as exc:
        _run(get_optional_user(req, _Creds("not.a.jwt")))
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# Route level: the real require_admin chain with a loopback TestClient
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bypass_app(db_conn) -> FastAPI:
    app = FastAPI()
    app.include_router(admin.router, prefix="/api/admin")

    def _override_get_db() -> Iterator[Any]:
        yield db_conn

    app.dependency_overrides[get_db] = _override_get_db
    return app


def test_route_without_bypass_is_401(bypass_app) -> None:
    resp = TestClient(bypass_app, client=("127.0.0.1", 50000), base_url=LOCAL).get(CARDS)
    assert resp.status_code == 401


def test_route_bypass_non_admin_is_403(bypass_app, bypass_on) -> None:
    resp = TestClient(bypass_app, client=("127.0.0.1", 50000), base_url=LOCAL).get(CARDS)
    assert resp.status_code == 403


def test_route_bypass_admin_is_200(bypass_app, bypass_on, db_conn) -> None:
    user = _make_user({"email": EMAIL})
    _insert_user(db_conn, user)
    _insert_admin(db_conn, user["id"])
    resp = TestClient(bypass_app, client=("127.0.0.1", 50000), base_url=LOCAL).get(CARDS)
    assert resp.status_code == 200
    # Same app, non-loopback client: the bypass does not apply.
    assert TestClient(bypass_app).get(CARDS).status_code == 401
    # Loopback, but a real (invalid) token: normal verification, 401.
    resp = TestClient(bypass_app, client=("127.0.0.1", 50000), base_url=LOCAL).get(
        CARDS, headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert resp.status_code == 401
