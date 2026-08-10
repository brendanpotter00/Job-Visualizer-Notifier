"""Integration tests for the ``/api/users/companies`` endpoints (E7 Phase 1).

Discovery of a direct ``boards.greenhouse.io/<token>`` URL is IO-free (L0), so
the only outbound call is the probe (``greenhouse_client.fetch_jobs``), mocked
here with an ``httpx.MockTransport`` injected via the router's ``_http_client``
factory. The non-ATS case exercises the full discovery ladder and mocks DNS +
transport the same way ``test_companies_resolve_endpoint`` does.
"""

from __future__ import annotations

import socket

import httpx
import pytest
from psycopg2 import sql

from api.auth.dependencies import get_current_user
from api.config import settings
from api.services import custom_companies_service as svc
from scripts.shared.constants import custom

GREENHOUSE_URL = "https://boards.greenhouse.io/duolingo"


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "custom_company_sources_enabled", True)


@pytest.fixture(autouse=True)
def restore_auth(client):
    """Each test may re-point get_current_user; restore the default afterward."""
    original = client.app.dependency_overrides.get(get_current_user)
    yield
    if original is not None:
        client.app.dependency_overrides[get_current_user] = original


def _login(client, sub: str, email: str) -> None:
    client.app.dependency_overrides[get_current_user] = lambda: {
        "sub": sub, "email": email,
        "given_name": "A", "family_name": "B", "picture": None,
    }


def _raw_job(i: int) -> dict:
    return {
        "id": i, "title": "Engineer", "absolute_url": f"https://x/{i}",
        "location": {"name": "Remote"}, "offices": [{"name": "Remote"}],
        "departments": [{"name": "Eng"}], "metadata": [],
        "first_published": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z", "content": "<p>d</p>",
    }


def _install_greenhouse(monkeypatch, job_ids: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        if "boards-api.greenhouse.io/v1/boards/duolingo/jobs" in str(request.url):
            return httpx.Response(200, json={"jobs": [_raw_job(i) for i in job_ids]})
        return httpx.Response(404)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr("api.routers.user_companies._http_client", factory)


def _count(db_conn, table: str, where: str = "", params: tuple = ()) -> int:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT count(*) AS n FROM {} " + where).format(sql.Identifier(table)),
        params,
    )
    return int(cur.fetchone()["n"])


def _seed_job_for(db_conn, company_id: str, job_id: str) -> None:
    cur = db_conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES (%s, %s, %s, %s, %s, %s, %s, 'OPEN')"
        ).format(sql.Identifier("job_listings")),
        (job_id, "Eng", company_id, "https://x/1", custom(company_id),
         "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
    )
    db_conn.commit()


# --- POST ---------------------------------------------------------------------


def test_add_creates_all_four_rows(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2, 3])

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ats"] == "greenhouse"
    assert body["boardToken"] == "duolingo"
    assert body["healthState"] == "unverified"
    assert body["sourceId"] == custom(body["id"])
    assert body["openJobCount"] == 0
    company_id = body["id"]

    assert _count(db_conn, "companies", "WHERE id = %s AND visibility = 'user' AND enabled", (company_id,)) == 1
    assert _count(db_conn, "user_companies", "WHERE company_id = %s", (company_id,)) == 1
    assert _count(db_conn, "company_scripts", "WHERE company_id = %s", (company_id,)) == 1
    assert _count(db_conn, "company_add_attempts", "WHERE company_id = %s AND outcome = 'added'", (company_id,)) == 1

    cur = db_conn.cursor()
    cur.execute(
        sql.SQL("SELECT script, transport, oracle_kind, script_version FROM {} WHERE company_id = %s")
        .format(sql.Identifier("company_scripts")),
        (company_id,),
    )
    row = cur.fetchone()
    assert row["script"] == {"kind": "ats_client", "provider": "greenhouse", "token": "duolingo"}
    assert row["transport"] == "ats_client"
    # E7 Phase 2 (DECISION D2): a new add stores the real provider-derived oracle
    # — Greenhouse is declared_probed (its meta.total is the trusted total).
    assert row["oracle_kind"] == "declared_probed"
    assert row["script_version"] == 1


def test_add_is_idempotent_per_user(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2, 3])

    first = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert first.status_code == 201
    second = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    # Exactly one of each core row; the audit log records both attempts.
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 1
    assert _count(db_conn, "user_companies") == 1
    assert _count(db_conn, "company_scripts") == 1
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'added'") == 2


def test_two_users_get_distinct_companies_and_delete_is_isolated(client, db_conn, monkeypatch):
    _install_greenhouse(monkeypatch, [1, 2, 3])

    _login(client, "auth0|A", "a@example.com")
    a = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()

    _login(client, "auth0|B", "b@example.com")
    b = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()

    assert a["id"] != b["id"]
    assert a["sourceId"] != b["sourceId"]
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 2

    # A deletes A's company (last owner → disabled). B's rows untouched.
    _login(client, "auth0|A", "a@example.com")
    resp = client.delete(f"/api/users/companies/{a['id']}")
    assert resp.status_code == 204

    assert _count(db_conn, "user_companies", "WHERE company_id = %s", (a["id"],)) == 0
    assert _count(db_conn, "user_companies", "WHERE company_id = %s", (b["id"],)) == 1
    assert _count(db_conn, "companies", "WHERE id = %s AND enabled", (a["id"],)) == 0
    assert _count(db_conn, "companies", "WHERE id = %s AND enabled", (b["id"],)) == 1
    # Rows are disabled, never deleted.
    assert _count(db_conn, "companies", "WHERE id = %s", (a["id"],)) == 1


# --- GET list -----------------------------------------------------------------


def test_get_returns_owner_list(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1, 2, 3])
    added = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    _seed_job_for(db_conn, added["id"], "900")

    resp = client.get("/api/users/companies")
    assert resp.status_code == 200
    companies = resp.json()["companies"]
    assert len(companies) == 1
    assert companies[0]["id"] == added["id"]
    assert companies[0]["healthState"] == "unverified"
    assert companies[0]["openJobCount"] == 1


# --- DELETE -------------------------------------------------------------------


def test_delete_last_owner_disables_company(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [1])
    added = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()

    resp = client.delete(f"/api/users/companies/{added['id']}")
    assert resp.status_code == 204
    assert _count(db_conn, "companies", "WHERE id = %s AND NOT enabled", (added["id"],)) == 1


def test_delete_unknown_company_is_404(client, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    # No user row / no ownership → 404.
    resp = client.delete("/api/users/companies/u-doesnotexist")
    assert resp.status_code == 404


# --- GET owner-scoped jobs ----------------------------------------------------


def test_get_jobs_403_for_non_owner_200_for_owner(client, db_conn, monkeypatch):
    _install_greenhouse(monkeypatch, [1, 2, 3])
    _login(client, "auth0|A", "a@example.com")
    a = client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).json()
    _seed_job_for(db_conn, a["id"], "555")

    # Owner: 200 with the job.
    resp_owner = client.get(f"/api/users/companies/{a['id']}/jobs")
    assert resp_owner.status_code == 200
    ids = {j["id"] for j in resp_owner.json()}
    assert "555" in ids

    # Non-owner B: 403.
    _login(client, "auth0|B", "b@example.com")
    # Ensure B exists as a user but does not own A's company.
    client.get("/api/users/companies")  # creates nothing; B has no row yet
    resp_b = client.get(f"/api/users/companies/{a['id']}/jobs")
    assert resp_b.status_code == 403


# --- Non-ATS / empty board ----------------------------------------------------


def test_non_ats_url_returns_422_and_records_unsupported(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")

    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>no ats here</html>")

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=False
        )

    monkeypatch.setattr("api.routers.user_companies._http_client", factory)

    resp = client.post("/api/users/companies", json={"url": "https://careers.acme.test/jobs"})
    assert resp.status_code == 422
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'unsupported'") == 1


def test_resolvable_board_with_zero_jobs_is_422(client, db_conn, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    _install_greenhouse(monkeypatch, [])  # board resolves but has no jobs

    resp = client.post("/api/users/companies", json={"url": GREENHOUSE_URL})
    assert resp.status_code == 422
    assert resp.json()["reason"] == "empty"
    assert _count(db_conn, "companies", "WHERE visibility = 'user'") == 0
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'empty'") == 1


# --- delete_ownership defense-in-depth guard ----------------------------------


def test_delete_ownership_never_disables_a_public_company(client, db_conn):
    """FIX 3: even if a public company id reaches delete_ownership as the 'last
    owner', the ``AND visibility = 'user'`` guard must leave it enabled — a
    public board's jobs must never be pulled off the site through this path."""
    cur = db_conn.cursor()
    # A public company + a contrived ownership row pointing at it.
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility) "
            "VALUES ('pub-guard', 'Pub', 'greenhouse', 'pub', TRUE, 'public')"
        ).format(sql.Identifier("companies"))
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, created_at, updated_at) "
            "VALUES ('uguard', 'auth0|uguard', 'g@example.com', '2025-01-01', '2025-01-01')"
        ).format(sql.Identifier("users"))
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (user_id, company_id, canonical_source_key) "
            "VALUES ('uguard', 'pub-guard', 'greenhouse:pub')"
        ).format(sql.Identifier("user_companies"))
    )
    db_conn.commit()

    svc.delete_ownership(db_conn, "uguard", "pub-guard")

    cur.execute("SELECT enabled FROM companies WHERE id = 'pub-guard'")
    assert cur.fetchone()["enabled"] is True, "public company must stay enabled"


# --- Feature flag -------------------------------------------------------------


def test_flag_off_returns_503(client, monkeypatch):
    _login(client, "auth0|A", "a@example.com")
    monkeypatch.setattr(settings, "custom_company_sources_enabled", False)
    assert client.post("/api/users/companies", json={"url": GREENHOUSE_URL}).status_code == 503
    assert client.get("/api/users/companies").status_code == 503
    assert client.delete("/api/users/companies/u-x").status_code == 503
    assert client.get("/api/users/companies/u-x/jobs").status_code == 503


# --- E7 Phase 3b: non-ATS URL → async discovery (202) behind the sub-flag ------

_NON_ATS_URL = "https://acme.example/careers"


def _patch_no_ats(monkeypatch, final_url: str = _NON_ATS_URL):
    from api.services.ats_discovery import DiscoveryResult

    async def _fake_discover_ats(url, http, *, deadline):
        return DiscoveryResult(
            candidate=None, via="unsupported", hops=(), final_url=final_url,
            reason="no_ats_detected",
        )

    monkeypatch.setattr("api.routers.user_companies.discover_ats", _fake_discover_ats)


def _capture_defer(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def _fake_defer(*, user_id, submitted_url, normalized_url, display_name):
        calls.append({
            "user_id": user_id, "submitted_url": submitted_url,
            "normalized_url": normalized_url, "display_name": display_name,
        })

    monkeypatch.setattr("api.routers.user_companies._defer_discovery", _fake_defer)
    return calls


def test_non_ats_url_enqueues_discovery_202(client, db_conn, monkeypatch):
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", True)
    _login(client, "auth0|A", "a@example.com")
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "discovery_pending"
    assert body["finalUrl"] == _NON_ATS_URL

    # The one-time discovery task was enqueued exactly once, with the final URL.
    assert len(calls) == 1
    assert calls[0]["normalized_url"] == _NON_ATS_URL
    assert calls[0]["display_name"] == "acme.example"
    # A discovery_pending attempt row was recorded (E7 Stagehand pivot §7).
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'discovery_pending'") == 1
    # A PROVISIONAL 'discovering' companies row now exists so the list shows the
    # board as "Setting up…" immediately — DISABLED (no scraping) and script-less
    # until the discovery task flips it to tracked or refused.
    cur = db_conn.cursor()
    cur.execute(
        "SELECT health_state, enabled, next_run_at, board_token FROM companies "
        "WHERE visibility = 'user'"
    )
    placeholder = cur.fetchone()
    assert placeholder is not None
    assert placeholder["health_state"] == "discovering"
    assert placeholder["enabled"] is False
    assert placeholder["next_run_at"] is None
    assert placeholder["board_token"] == _NON_ATS_URL
    assert _count(db_conn, "company_scripts") == 0


def test_non_ats_url_without_subflag_stays_422_unsupported(client, db_conn, monkeypatch):
    # Sub-flag OFF (the default): the non-ATS branch keeps today's 422 unsupported;
    # discovery (and its spend) never runs.
    monkeypatch.setattr(settings, "custom_company_discovery_enabled", False)
    _login(client, "auth0|B", "b@example.com")
    _patch_no_ats(monkeypatch)
    calls = _capture_defer(monkeypatch)

    resp = client.post("/api/users/companies", json={"url": _NON_ATS_URL})
    assert resp.status_code == 422, resp.text
    assert resp.json()["reason"] == "no_ats_detected"
    assert len(calls) == 0
    assert _count(db_conn, "company_add_attempts", "WHERE outcome = 'unsupported'") == 1
