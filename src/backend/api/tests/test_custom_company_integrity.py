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
        assert result == {
            "schemaPresent": True,
            "ownerlessCount": 0,
            "ownerless": [],
            "strandedCount": 0,
            "strandedJobCount": 0,
            "stranded": [],
        }


class TestStrandedCorpus:
    """The MIRROR-IMAGE orphan: job rows whose ``companies`` row is gone.

    THE STATE, and why it needs its own detector. ``TestGetOwnerlessCustomCompanies``
    asks "is there a company nobody owns?" and is ``visibility='user'``-scoped, which
    is correct for that question and blind to this one — a stranded corpus HAS no
    company row, so there is no visibility left to filter on. The recipe seed
    migration's own ``downgrade()`` produced exactly this shape (~3,000 stranded
    ``recipe:oracle`` rows) until it was taught to delete the jobs too, and the
    2026-09-05 purge race produced 2,057 ``custom:`` ones.

    The reason it must be REPORTED rather than merely prevented: the read paths were
    deliberately taught to hide it (``/api/jobs`` INNER JOINs ``companies``,
    ``/api/jobs/search`` carries the orphan predicate). Hiding it was the right fix for
    the leak, and it is what makes the state undetectable by looking at the product.
    """

    def _seed_stranded(self, conn, company_id: str, source_id: str, *, n: int,
                       open_n: int) -> None:
        """``n`` job rows in ``source_id`` with NO ``companies`` row at all."""
        cur = conn.cursor()
        for i in range(n):
            cur.execute(
                sql.SQL(
                    "INSERT INTO {} (id, title, company, url, source_id, created_at, "
                    "first_seen_at, status) VALUES (%s, %s, %s, %s, %s, now(), now(), %s)"
                ).format(sql.Identifier("job_listings")),
                (
                    f"strand-{uuid.uuid4().hex[:8]}", "Engineer", company_id,
                    "https://example.com/1", source_id,
                    "OPEN" if i < open_n else "CLOSED",
                ),
            )
        conn.commit()

    def test_a_stranded_published_recipe_corpus_is_reported(self, db_conn):
        """THE case the ``visibility='user'`` scoping could never see."""
        self._seed_stranded(db_conn, "oracle", "recipe:oracle", n=3, open_n=2)

        result = get_ownerless_custom_companies(db_conn)

        assert result["strandedCount"] == 1
        assert result["strandedJobCount"] == 3
        assert result["stranded"] == [{
            "sourceId": "recipe:oracle",
            "companyId": "oracle",
            "jobCount": 3,
            "openJobCount": 2,
        }]
        # ...and it is NOT reported as an ownerless company: different invariant.
        assert result["ownerlessCount"] == 0

    def test_a_stranded_private_corpus_is_reported_too(self, db_conn):
        """The 2026-09-05 shape. Both recipe-engine namespaces, one report."""
        self._seed_stranded(db_conn, "u-gone01", "custom:u-gone01", n=2, open_n=2)

        result = get_ownerless_custom_companies(db_conn)

        assert result["strandedCount"] == 1
        assert result["stranded"][0]["sourceId"] == "custom:u-gone01"

    def test_a_live_board_is_not_reported_as_stranded(self, db_conn):
        """The negative case. A recipe board WITH its company row is the normal state
        of the published fleet — reporting it would make the check useless on day one."""
        _seed_company(db_conn, "atlassian", visibility="public")
        self._seed_stranded(db_conn, "atlassian", "recipe:atlassian", n=2, open_n=2)

        result = get_ownerless_custom_companies(db_conn)

        assert result["strandedCount"] == 0
        assert result["stranded"] == []

    def test_public_ats_rows_with_no_company_are_not_stranded(self, db_conn):
        """Scope check. A vendor-ATS row with no ``companies`` row is the documented,
        deliberate fail-OPEN case (``database._HIDDEN_COMPANY_PREDICATE``) — it is
        served on purpose, so calling it an integrity failure would be crying wolf."""
        self._seed_stranded(db_conn, "legacy-co", "greenhouse_api", n=2, open_n=2)

        result = get_ownerless_custom_companies(db_conn)

        assert result["strandedCount"] == 0

    def test_the_stranded_count_is_honest_when_the_list_is_truncated(self, db_conn):
        """Same bounded-read contract as the ownerless list: the COUNT is computed
        separately, so a capped list cannot understate a fleet-wide strand."""
        for i in range(3):
            self._seed_stranded(
                db_conn, f"gone{i}", f"recipe:gone{i}", n=2, open_n=1
            )

        result = get_ownerless_custom_companies(db_conn, limit=1)

        assert result["strandedCount"] == 3
        assert result["strandedJobCount"] == 6
        assert len(result["stranded"]) == 1


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
