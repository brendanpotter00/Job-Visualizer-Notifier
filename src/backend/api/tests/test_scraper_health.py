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

import uuid
from datetime import datetime, timedelta, timezone

import psycopg2.extensions
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2 import sql

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
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (id, title, company, url, source_id, created_at, "
            "first_seen_at, last_seen_at, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier("job_listings")),
        (
            job_id,
            "Software Engineer",
            company,
            "https://example.com/1",
            "test_scraper",
            last_seen_at,
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

    def test_freshness_uses_last_seen_at_not_scrape_runs(self, db_conn):
        """A company can be writing perfectly healthy ``scrape_runs`` rows
        while writing zero jobs — several of the four dead prod scrapers did
        exactly that. Only ``job_listings.last_seen_at`` catches it, so a
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
        # NOTE: no ``require_admin`` override is registered. If the route ever
        # grows a ``Depends(require_admin)`` this fixture fails outright,
        # which is the point.
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
