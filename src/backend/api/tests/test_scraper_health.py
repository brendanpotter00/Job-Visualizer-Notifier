"""Tests for the dead-scraper staleness probe.

Two layers:

* ``TestGetStaleCompanies`` exercises the service SQL against a real
  per-worker Postgres schema (``db_conn``).
* ``TestScraperHealthRoute`` mounts the ``jobs_qa`` router WITHOUT an
  admin override — the endpoint must be reachable with only the
  ``X-Internal-Key`` header, because the scheduled GitHub Action that
  consumes it can present a static header but cannot mint an admin JWT.

Background: ``appliedintuition`` (56 days dead, 16,913 failed runs),
``unity3d`` (28d), ``fal`` (19d) and ``merge`` were all 100% dead in
production with ~460 phantom OPEN jobs still showing in the UI, and
nothing anywhere noticed.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2.extensions
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.auth.dependencies import require_admin
from api.auth.internal_key import require_internal_key
from api.config import settings
from api.dependencies import get_db
from api.routers import jobs_qa
from api.services.scraper_health import get_stale_companies


def _seed_company(conn, company_id: str, *, ats: str = "greenhouse", enabled: bool = True) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, display_name, ats, board_token, enabled) "
            "VALUES (%s, %s, %s, %s, %s)"
        ).format(sql.Identifier("companies")),
        (company_id, company_id.title(), ats, company_id, enabled),
    )
    conn.commit()


def _seed_job(
    conn,
    company: str,
    *,
    last_seen_at: datetime,
    status: str = "OPEN",
) -> str:
    """Seed one job row "last seen" at the given time.

    ``job_listings`` has carried no freshness columns since ``18fe9c20a8fd``
    (#239) — the timestamp is routed through ``first_seen_at``, which the
    ``job_freshness_sync`` AFTER INSERT trigger copies into the sidecar's
    ``last_seen_at``. Tests that need last-seen to diverge from first-seen
    UPDATE ``job_freshness`` directly afterwards.
    """
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("job_listings")),
        (
            job_id,
            "Software Engineer",
            company,
            "https://example.com/1",
            "test_scraper",
            last_seen_at,
            last_seen_at,
            status,
        ),
    )
    conn.commit()
    return job_id


def _hours_ago(hours: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _entry(result: dict, company: str) -> dict | None:
    return next((e for e in result["stale"] if e["company"] == company), None)


class TestGetStaleCompanies:
    def test_fresh_company_is_not_stale(self, db_conn):
        _seed_company(db_conn, "freshco")
        _seed_job(db_conn, "freshco", last_seen_at=_hours_ago(1))

        result = get_stale_companies(db_conn, threshold_hours=24)

        assert result["staleCount"] == 0
        assert result["okCount"] == 1
        assert result["stale"] == []
        assert result["thresholdHours"] == 24
        assert result["checkedAt"]

    def test_company_past_threshold_is_stale_with_correct_hours(self, db_conn):
        """A 30h-old last_seen_at against a 24h threshold. ``hoursStale`` is
        computed in Postgres from ``now()``, so it must land on ~30 without
        any client-clock or naive/aware timezone drift."""
        _seed_company(db_conn, "deadco", ats="lever")
        _seed_job(db_conn, "deadco", last_seen_at=_hours_ago(30))
        _seed_job(db_conn, "deadco", last_seen_at=_hours_ago(31))

        result = get_stale_companies(db_conn, threshold_hours=24)

        assert result["staleCount"] == 1
        assert result["okCount"] == 0
        entry = _entry(result, "deadco")
        assert entry is not None
        assert entry["ats"] == "lever"
        assert entry["openJobs"] == 2
        assert entry["lastSeenAt"] is not None
        # MAX(last_seen_at) is the 30h row, not the 31h one.
        assert 29.5 < entry["hoursStale"] < 30.5

    def test_freshness_reads_the_job_freshness_sidecar(self, db_conn):
        """Since ``18fe9c20a8fd`` (#239) the sidecar is the ONLY freshness
        store — ``job_listings`` has no last_seen_at at all. A job whose row
        was inserted 48h ago but whose sidecar row has been advanced (the
        ``update_last_seen`` write-path shape) must read fresh with no
        ``job_listings`` write; winding the sidecar back must read stale at
        the sidecar's age, not the insert's."""
        _seed_company(db_conn, "sidecarco")
        job_id = _seed_job(db_conn, "sidecarco", last_seen_at=_hours_ago(48))
        cur = db_conn.cursor()
        cur.execute(
            sql.SQL(
                "UPDATE {} SET last_seen_at = %s "
                "WHERE source_id = %s AND id = %s"
            ).format(sql.Identifier("job_freshness")),
            (_hours_ago(1), "test_scraper", job_id),
        )
        db_conn.commit()

        result = get_stale_companies(db_conn, threshold_hours=24)
        assert _entry(result, "sidecarco") is None, (
            "an advanced sidecar row alone must make the company fresh"
        )

        cur.execute(
            sql.SQL(
                "UPDATE {} SET last_seen_at = %s "
                "WHERE source_id = %s AND id = %s"
            ).format(sql.Identifier("job_freshness")),
            (_hours_ago(48), "test_scraper", job_id),
        )
        db_conn.commit()

        result = get_stale_companies(db_conn, threshold_hours=24)
        entry = _entry(result, "sidecarco")
        assert entry is not None, (
            "a stale sidecar row must flag the company"
        )
        assert 47.5 < entry["hoursStale"] < 48.5

    def test_freshness_uses_last_seen_at_not_scrape_runs(self, db_conn):
        """A company can be writing perfectly healthy ``scrape_runs`` rows
        while writing zero jobs — several of the four dead prod scrapers did
        exactly that. Only ``job_freshness.last_seen_at`` catches it, so a
        recent successful run must NOT make a stale company look fresh."""
        _seed_company(db_conn, "liarco")
        _seed_job(db_conn, "liarco", last_seen_at=_hours_ago(48))

        cur = db_conn.cursor()
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (run_id, company, started_at, completed_at, mode, "
                "jobs_seen, new_jobs, closed_jobs, details_fetched, error_count) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            ).format(sql.Identifier("scrape_runs")),
            (
                "run-liar", "liarco",
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                "full", 0, 0, 0, 0, 0,
            ),
        )
        db_conn.commit()

        result = get_stale_companies(db_conn, threshold_hours=24)

        assert result["staleCount"] == 1
        assert _entry(result, "liarco") is not None

    def test_company_with_no_jobs_at_all_is_stale(self, db_conn):
        """The most broken state there is — and the one an INNER JOIN would
        hide entirely. ``lastSeenAt``/``hoursStale`` are None, and the
        company is stale regardless of the threshold."""
        _seed_company(db_conn, "ghostco", ats="ashby")

        result = get_stale_companies(db_conn, threshold_hours=720)

        assert result["staleCount"] == 1
        entry = _entry(result, "ghostco")
        assert entry is not None
        assert entry["lastSeenAt"] is None
        assert entry["hoursStale"] is None
        assert entry["openJobs"] == 0

    def test_disabled_companies_are_excluded(self, db_conn):
        """A deliberately disabled company is not a broken scraper. Counting
        it would make the daily check permanently red and train the owner to
        ignore the alert email."""
        _seed_company(db_conn, "offco", enabled=False)
        _seed_job(db_conn, "offco", last_seen_at=_hours_ago(500))

        result = get_stale_companies(db_conn, threshold_hours=24)

        assert result["staleCount"] == 0
        assert result["okCount"] == 0
        assert _entry(result, "offco") is None

    def test_script_ats_companies_are_included(self, db_conn):
        """REGRESSION GUARD. google/apple/microsoft are seeded with the
        sentinel ``ats='script'`` and are matched by NONE of the per-ATS
        fan-out queries. Any future 'optimization' that filters this query
        by ATS would silently stop watching Apple — the company this entire
        change exists because of."""
        _seed_company(db_conn, "apple", ats="script")
        _seed_company(db_conn, "google", ats="script")
        _seed_job(db_conn, "apple", last_seen_at=_hours_ago(72))
        _seed_job(db_conn, "google", last_seen_at=_hours_ago(1))

        result = get_stale_companies(db_conn, threshold_hours=24)

        apple = _entry(result, "apple")
        assert apple is not None, "ats='script' company was not evaluated at all"
        assert apple["ats"] == "script"
        assert result["okCount"] == 1  # google is fresh but still evaluated

    def test_open_jobs_counts_only_open_rows(self, db_conn):
        """``openJobs`` is the phantom-listing blast radius — rows still shown
        as OPEN in the UI that nothing has confirmed. CLOSED rows are already
        gone from the UI and must not inflate it."""
        _seed_company(db_conn, "mixedco")
        _seed_job(db_conn, "mixedco", last_seen_at=_hours_ago(40))
        _seed_job(db_conn, "mixedco", last_seen_at=_hours_ago(40), status="CLOSED")
        _seed_job(db_conn, "mixedco", last_seen_at=_hours_ago(40), status="CLOSED")

        result = get_stale_companies(db_conn, threshold_hours=24)

        assert _entry(result, "mixedco")["openJobs"] == 1

    def test_threshold_is_honored(self, db_conn):
        _seed_company(db_conn, "borderco")
        _seed_job(db_conn, "borderco", last_seen_at=_hours_ago(30))

        assert get_stale_companies(db_conn, threshold_hours=24)["staleCount"] == 1
        assert get_stale_companies(db_conn, threshold_hours=48)["staleCount"] == 0

    def test_leaves_no_open_transaction(self, db_conn):
        """SELECT-only contract: an idle-in-transaction pooled connection
        pins the xmin horizon and blocks vacuum."""
        _seed_company(db_conn, "txnco")
        get_stale_companies(db_conn)
        assert db_conn.status == psycopg2.extensions.STATUS_READY


class TestScraperHealthRoute:
    """The route must be reachable with ONLY the internal key."""

    @pytest.fixture
    def health_app(self, db_conn, monkeypatch):
        monkeypatch.setattr(settings, "internal_api_key", "test-internal-key")

        app = FastAPI()
        app.middleware("http")(require_internal_key)
        # No ``require_admin`` override is registered, because this route
        # deliberately does not use ``require_admin`` — the scheduled GitHub
        # Action can present a static header but cannot mint an admin JWT.
        #
        # Which means ``require_internal_key`` is this route's ONLY gate, and
        # anyone holding the internal key is fully authorized. The public
        # Vercel proxy holds it unconditionally, so the route must simply not
        # be reachable through the proxy: ``scraper-health`` is in
        # ``NOT_PROXIED_PATHS`` in ``api/jobs-qa.ts`` and 404s from the public
        # internet. ``test_proxy_denies_non_admin_jobs_qa_routes`` below is
        # what keeps those two facts in sync.
        #
        # Two earlier versions of this comment were wrong and are worth
        # remembering: the first implied internal-key alone was sufficient;
        # the second pointed at a proxy gate that merely required an
        # ``Authorization`` header to be PRESENT, which
        # ``curl -H "Authorization: x"`` satisfied. Presence is not
        # authentication.
        app.include_router(jobs_qa.router, prefix="/api/jobs-qa")

        def override_get_db():
            yield db_conn

        app.dependency_overrides[get_db] = override_get_db
        return app

    @pytest.fixture
    def health_client(self, health_app):
        return TestClient(health_app)

    def test_returns_200_with_internal_key_only(self, db_conn, health_client):
        _seed_company(db_conn, "routeco")
        _seed_job(db_conn, "routeco", last_seen_at=_hours_ago(1))

        resp = health_client.get(
            "/api/jobs-qa/scraper-health",
            headers={"X-Internal-Key": "test-internal-key"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["staleCount"] == 0
        assert body["thresholdHours"] == 24
        assert body["stale"] == []

    def test_requires_internal_key(self, health_client):
        resp = health_client.get("/api/jobs-qa/scraper-health")
        assert resp.status_code == 401

    def test_wrong_internal_key_is_rejected(self, health_client):
        resp = health_client.get(
            "/api/jobs-qa/scraper-health",
            headers={"X-Internal-Key": "nope"},
        )
        assert resp.status_code == 401

    def test_threshold_hours_query_param_is_camel_case(self, db_conn, health_client):
        _seed_company(db_conn, "paramco")
        _seed_job(db_conn, "paramco", last_seen_at=_hours_ago(30))

        headers = {"X-Internal-Key": "test-internal-key"}
        strict = health_client.get(
            "/api/jobs-qa/scraper-health?thresholdHours=24", headers=headers
        ).json()
        lenient = health_client.get(
            "/api/jobs-qa/scraper-health?thresholdHours=48", headers=headers
        ).json()

        assert strict["staleCount"] == 1
        assert strict["thresholdHours"] == 24
        assert lenient["staleCount"] == 0
        assert lenient["thresholdHours"] == 48

    def test_returns_200_even_when_everything_is_stale(self, db_conn, health_client):
        """Always 200; the caller decides red/green. A 5xx here would make the
        body unreadable in CI logs and would tempt someone into wiring this
        into Railway's healthcheckPath — which would restart-loop the
        container over a single dead scraper."""
        _seed_company(db_conn, "dead1")
        _seed_company(db_conn, "dead2")
        _seed_job(db_conn, "dead1", last_seen_at=_hours_ago(500))

        resp = health_client.get(
            "/api/jobs-qa/scraper-health",
            headers={"X-Internal-Key": "test-internal-key"},
        )

        assert resp.status_code == 200
        assert resp.json()["staleCount"] == 2


class TestProxyAllowlistInvariant:
    """Cross-layer guard: the public Vercel proxy must forward ONLY routes the
    backend independently authenticates.

    The proxy (``api/jobs-qa.ts``) attaches ``X-Internal-Key``
    unconditionally, so it always clears ``require_internal_key``. The only
    real identity check on any jobs-qa route is ``Depends(require_admin)``,
    which verifies an Auth0 JWT. A route without it is, from the proxy's
    perspective, fully public — which is how ``scraper-health`` returned the
    internal company roster to plain ``curl``.

    This was a DENYLIST for one round and got bypassed six different ways
    (``scraper-health/``, ``/scraper-health``, ``scraper-health//``,
    ``./scraper-health``, ``scraper%2Dhealth``, and the array form). A
    denylist on a key-injecting proxy fails open by construction: every path
    nobody enumerated is forwarded. The allowlist inverts the default, and
    these tests pin both directions of the invariant so it cannot rot back.
    """

    PROXY = Path(__file__).resolve().parents[4] / "api" / "jobs-qa.ts"

    @staticmethod
    def _route_has_require_admin(route) -> bool:
        for dep in route.dependant.dependencies:
            if getattr(dep, "call", None) is require_admin:
                return True
        return False

    def _proxy_allowlist(self) -> set[str]:
        src = self.PROXY.read_text()
        match = re.search(r"const PROXIED_PATHS = new Set\(\[(.*?)\]\)", src, re.S)
        assert match, (
            "PROXIED_PATHS is missing from api/jobs-qa.ts. If it was replaced "
            "by a denylist, read the class docstring first — that shape was "
            "bypassed six ways in review."
        )
        return set(re.findall(r"'([^']+)'", match.group(1)))

    def _routes_by_admin_gating(self) -> tuple[set[str], set[str]]:
        gated, ungated = set(), set()
        for route in jobs_qa.router.routes:
            (gated if self._route_has_require_admin(route) else ungated).add(
                route.path.lstrip("/")
            )
        return gated, ungated

    def test_proxy_file_exists(self):
        assert self.PROXY.exists(), self.PROXY

    def test_every_allowlisted_path_is_admin_gated(self):
        """Direction 1: nothing reachable through the proxy may rely on the
        internal key alone for authorization."""
        allowlist = self._proxy_allowlist()
        gated, ungated = self._routes_by_admin_gating()

        assert allowlist, "the allowlist is empty — QAPage would be broken"
        leaked = allowlist & ungated
        assert not leaked, (
            f"these paths are proxied to the public internet but have no "
            f"require_admin, so the proxy's injected X-Internal-Key fully "
            f"authorizes any caller: {sorted(leaked)}"
        )
        unknown = allowlist - gated
        assert not unknown, (
            f"allowlisted paths that are not admin-gated routes on the "
            f"jobs_qa router at all: {sorted(unknown)}"
        )

    def test_every_non_admin_route_is_unreachable_through_the_proxy(self):
        """Direction 2: the inverse, stated explicitly rather than implied.

        Fails the moment someone adds another internal-key-only route to the
        jobs_qa router and also adds it to PROXIED_PATHS.
        """
        allowlist = self._proxy_allowlist()
        _, ungated = self._routes_by_admin_gating()

        assert ungated, (
            "expected at least one internal-key-only route (scraper-health); "
            "if that changed, revisit this test rather than delete it"
        )
        reachable = ungated & allowlist
        assert not reachable, sorted(reachable)

    def test_scraper_health_is_not_proxied(self):
        """Named explicitly so the invariants above cannot be satisfied by
        some accident of how routes are classified."""
        assert "scraper-health" not in self._proxy_allowlist()

    def test_allowlist_is_minimal(self):
        """The allowlist must stay at exactly what the browser needs.

        QAPage makes two /api/jobs-qa calls. Every operator runbook
        (docs/implementations/*/DEPLOY.md) curls Railway directly, and so
        does the scheduled Action — so no trigger-*-fetch / -fan-out route
        needs a public door. Growing this set is a security decision and
        should have to edit a test that says so.
        """
        assert self._proxy_allowlist() == {"scrape-runs", "trigger-scrape"}

    def test_proxy_does_not_follow_redirects(self):
        """``redirect: 'manual'`` is load-bearing.

        Node's fetch defaults to following redirects and preserves headers
        across a same-origin 3xx — including the injected X-Internal-Key.
        The backend app uses Starlette's default ``redirect_slashes=True``,
        so a trailing slash 307s to the canonical path; with the default
        follow behaviour the proxy would chase that redirect into a path it
        had just refused.
        """
        src = self.PROXY.read_text()
        assert "redirect: 'manual'" in src, (
            "api/jobs-qa.ts must set redirect: 'manual' on its upstream fetch"
        )

    def test_proxy_normalizes_before_matching(self):
        """The allowlist comparison must run on a canonical path.

        Without normalization the six known bypass spellings each miss the
        allowlist too — which fails CLOSED, so it is not a vulnerability —
        but ``scrape-runs/`` would then 404 a legitimate caller. The
        canonicalizer is what makes both directions correct.
        """
        src = self.PROXY.read_text()
        assert "function canonicalizeProxyPath" in src
        assert "decodeURIComponent" in src
        for guard in ("'..'", "'.'", "\\0"):
            assert guard in src, f"canonicalizeProxyPath is missing {guard}"
