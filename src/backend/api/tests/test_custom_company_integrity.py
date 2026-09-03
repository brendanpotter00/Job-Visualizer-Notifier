"""A ``visibility='user'`` company with no owner cannot exist — so prove we notice.

The dev database holds ``u-6hkpc6fh0z`` ("Amazon (live check)"): 100 job rows, zero
``user_companies`` rows. Every add path creates ownership in the same statement block
as the company, and ``remove_owned_company`` purges the company once the last owner
goes, so the model says the state is unreachable. It was reached anyway, by a test
path, and it is invisible to every UI (the list JOINs ``user_companies``) and
un-deletable through the API (the delete route first proves the caller owns it).

Two layers, mirroring ``test_scraper_health.py``: the service SQL against a real
per-worker Postgres schema, then the route with only the internal key.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth.internal_key import require_internal_key
from api.config import settings
from api.dependencies import get_db
from api.routers import jobs_qa
from api.services.custom_company_integrity import get_ownerless_custom_companies


def _seed_company(conn, company_id: str, *, visibility: str, enabled: bool = True) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled, visibility) "
            "VALUES (%s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), "greenhouse", company_id, enabled, visibility),
    )
    conn.commit()


def _seed_owner(conn, company_id: str) -> str:
    """One ``user_companies`` row, plus the ``users`` row its FK requires."""
    user_id = f"u{uuid.uuid4().hex[:10]}"
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, auth0_id, email, created_at, updated_at) "
            "VALUES (%s, %s, %s, now(), now())"
        ).format(sql.Identifier("users")),
        (user_id, f"auth0|{user_id}", f"{user_id}@example.com"),
    )
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (user_id, company_id, canonical_source_key) "
            "VALUES (%s, %s, %s)"
        ).format(sql.Identifier("user_companies")),
        (user_id, company_id, f"greenhouse:{company_id}"),
    )
    conn.commit()
    return user_id


def _seed_job(conn, company_id: str, *, status: str = "OPEN") -> None:
    """A job in the company's PRIVATE namespace — the scoping a purge would use."""
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) VALUES (%s, %s, %s, %s, %s, now(), now(), %s)"
        ).format(sql.Identifier("job_listings")),
        (
            f"job-{uuid.uuid4().hex[:8]}",
            "Software Engineer",
            company_id,
            "https://example.com/1",
            f"custom:{company_id}",
            status,
        ),
    )
    conn.commit()


def _ids(result: dict) -> list[str]:
    return [c["companyId"] for c in result["ownerless"]]


class TestGetOwnerlessCustomCompanies:
    def test_a_private_company_with_no_owner_is_reported(self, db_conn):
        """``u-6hkpc6fh0z``'s exact shape: private, ownerless, holding jobs."""
        _seed_company(db_conn, "u-orphan01", visibility="user", enabled=False)
        _seed_job(db_conn, "u-orphan01")
        _seed_job(db_conn, "u-orphan01", status="CLOSED")

        result = get_ownerless_custom_companies(db_conn)

        assert result["schemaPresent"] is True
        assert result["ownerlessCount"] == 1
        assert _ids(result) == ["u-orphan01"]
        entry = result["ownerless"][0]
        assert entry["jobCount"] == 2, "the blast radius a cleanup would remove"
        assert entry["openJobCount"] == 1
        assert entry["enabled"] is False

    def test_a_private_company_with_one_owner_is_not_reported(self, db_conn):
        """The negative case that keeps this check from crying wolf on every board."""
        _seed_company(db_conn, "u-owned01", visibility="user")
        _seed_owner(db_conn, "u-owned01")
        _seed_job(db_conn, "u-owned01")

        result = get_ownerless_custom_companies(db_conn)

        assert result["ownerlessCount"] == 0
        assert result["ownerless"] == []

    def test_public_companies_are_ignored_entirely(self, db_conn):
        """A curated company has no owner BY DESIGN. Without the
        ``visibility='user'`` predicate all 129 public rows report as orphans on the
        first run, which is how a check gets switched off and never switched back on."""
        _seed_company(db_conn, "publicco", visibility="public")
        _seed_job(db_conn, "publicco")
        _seed_company(db_conn, "u-orphan02", visibility="user")

        result = get_ownerless_custom_companies(db_conn)

        assert _ids(result) == ["u-orphan02"]

    def test_an_owner_of_a_different_company_does_not_launder_the_orphan(self, db_conn):
        """The join has to be per-company. An ownership row pointing somewhere else is
        not ownership of this one — and ``user_companies.company_id`` is a soft link
        with no FK, so nothing at the schema level rules that out."""
        _seed_company(db_conn, "u-owned02", visibility="user")
        _seed_owner(db_conn, "u-owned02")
        _seed_company(db_conn, "u-orphan03", visibility="user")

        result = get_ownerless_custom_companies(db_conn)

        assert _ids(result) == ["u-orphan03"]

    def test_still_enabled_orphans_sort_first(self, db_conn):
        """An ownerless company that is still ``enabled`` keeps drawing a nightly
        harvest — real requests, real rows, real enrichment budget — for nobody. It is
        strictly worse than a disabled one and must lead the report."""
        _seed_company(db_conn, "u-orphan-off", visibility="user", enabled=False)
        _seed_company(db_conn, "u-orphan-on", visibility="user", enabled=True)

        result = get_ownerless_custom_companies(db_conn)

        assert _ids(result) == ["u-orphan-on", "u-orphan-off"]

    def test_the_count_is_honest_when_the_list_is_truncated(self, db_conn):
        """The list is bounded (unbounded-reads rule) but the COUNT is not derived
        from it — a capped list reporting its own length would understate the problem
        at exactly the scale where it matters."""
        for i in range(3):
            _seed_company(db_conn, f"u-many{i}", visibility="user")

        result = get_ownerless_custom_companies(db_conn, limit=1)

        assert result["ownerlessCount"] == 3
        assert len(result["ownerless"]) == 1

    def test_a_clean_database_reports_nothing(self, db_conn):
        result = get_ownerless_custom_companies(db_conn)
        assert result == {"schemaPresent": True, "ownerlessCount": 0, "ownerless": []}


class TestCustomCompanyIntegrityRoute:
    """Same posture as ``/scraper-health``: reachable with the internal key alone."""

    @pytest.fixture
    def integrity_app(self, db_conn, monkeypatch):
        monkeypatch.setattr(settings, "internal_api_key", "test-internal-key")
        app = FastAPI()
        app.middleware("http")(require_internal_key)
        app.include_router(jobs_qa.router, prefix="/api/jobs-qa")

        def override_get_db():
            yield db_conn

        app.dependency_overrides[get_db] = override_get_db
        return app

    @pytest.fixture
    def integrity_client(self, integrity_app):
        return TestClient(integrity_app)

    def test_returns_200_with_internal_key_only(self, db_conn, integrity_client):
        _seed_company(db_conn, "u-routeorphan", visibility="user")
        _seed_job(db_conn, "u-routeorphan")

        response = integrity_client.get(
            "/api/jobs-qa/custom-company-integrity",
            headers={"X-Internal-Key": "test-internal-key"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ownerlessCount"] == 1
        assert body["ownerless"][0]["companyId"] == "u-routeorphan"

    def test_a_broken_state_is_still_a_200(self, db_conn, integrity_client):
        """The endpoint REPORTS; the caller decides red/green. A 503 here would make
        the body unreadable in CI logs and tempt someone into wiring it into a
        container healthcheck, turning a signal into an outage."""
        _seed_company(db_conn, "u-routeorphan2", visibility="user")

        response = integrity_client.get(
            "/api/jobs-qa/custom-company-integrity",
            headers={"X-Internal-Key": "test-internal-key"},
        )

        assert response.status_code == 200
        assert response.json()["ownerlessCount"] == 1

    def test_without_the_internal_key_it_is_rejected(self, integrity_client):
        response = integrity_client.get("/api/jobs-qa/custom-company-integrity")
        assert response.status_code == 401

    def test_the_route_is_not_forwarded_by_the_public_proxy(self):
        """It carries no ``require_admin``, so the internal key is its only gate — and
        the Vercel proxy attaches that key unconditionally. Appearing in
        ``PROXIED_PATHS`` would publish the private-company roster to plain ``curl``.
        ``TestProxyAllowlistInvariant`` in ``test_scraper_health.py`` enforces this in
        general; this is the named case."""
        from pathlib import Path

        proxy = Path(__file__).resolve().parents[4] / "api" / "jobs-qa.ts"
        assert "custom-company-integrity" not in proxy.read_text()
