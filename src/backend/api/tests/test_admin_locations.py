"""Integration tests for the Unit-8 location-normalization admin endpoints.

Auth-gate tests mirror test_admin_router.py (pop the require_admin override to
exercise the real gate). Defer tests mirror test_jobs_qa_router.py's
procrastinate_open fixture: open the real connector, call the endpoint, then
SELECT from procrastinate_jobs to assert the deferred row + queueing_lock + args
(this repo tests defers against the real queue, not a mock).
"""

import os

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from psycopg2 import sql

from api.tasks.procrastinate_app import ensure_schema_async, procrastinate_app

from .conftest import _insert_job, _insert_user, _make_job, _make_user


# --- procrastinate connector fixture (mirrors test_jobs_qa_router.py) ---------

@pytest_asyncio.fixture
async def procrastinate_open(db_conn):
    schema = os.environ.get("PYTEST_SCHEMA")
    assert schema, "db_conn fixture must set PYTEST_SCHEMA"

    prev_pgoptions = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = f'-c search_path="{schema}",public'
    try:
        await procrastinate_app.open_async()
        try:
            await ensure_schema_async(procrastinate_app)
            cur = db_conn.cursor()
            cur.execute(
                "DELETE FROM procrastinate_jobs "
                "WHERE task_name IN ('normalize_location', 'scan_unnormalized')"
            )
            db_conn.commit()
            yield
        finally:
            await procrastinate_app.close_async()
    finally:
        if prev_pgoptions is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = prev_pgoptions


def _normalize_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status FROM procrastinate_jobs "
        "WHERE task_name = 'normalize_location' ORDER BY id"
    )
    return list(cur.fetchall())


def _scan_jobs(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, task_name, args, queueing_lock, status FROM procrastinate_jobs "
        "WHERE task_name = 'scan_unnormalized' ORDER BY id"
    )
    return list(cur.fetchall())


def _seed_alias(conn, raw_text, source, confidence, specs):
    """Seed an alias + locations + mapping directly (for inspect / overwrite tests).

    `specs` is a list of dicts with location columns. position = index.
    """
    cur = conn.cursor()
    loc_ids = []
    for s in specs:
        cur.execute(
            sql.SQL(
                "INSERT INTO {} (canonical_name, kind, city, region, country, remote_scope) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT ON CONSTRAINT uq_locations_canonical DO NOTHING RETURNING id"
            ).format(sql.Identifier("locations")),
            (s["canonical_name"], s["kind"], s.get("city"), s.get("region"),
             s.get("country"), s.get("remote_scope")),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                sql.SQL(
                    "SELECT id FROM {} WHERE kind=%s AND city IS NOT DISTINCT FROM %s "
                    "AND region IS NOT DISTINCT FROM %s AND country IS NOT DISTINCT FROM %s "
                    "AND remote_scope IS NOT DISTINCT FROM %s"
                ).format(sql.Identifier("locations")),
                (s["kind"], s.get("city"), s.get("region"), s.get("country"), s.get("remote_scope")),
            )
            row = cur.fetchone()
        loc_ids.append(row["id"])
    cur.execute(
        sql.SQL("INSERT INTO {} (raw_text, source, confidence) VALUES (%s,%s,%s)").format(
            sql.Identifier("location_aliases")
        ),
        (raw_text, source, confidence),
    )
    for pos, lid in enumerate(loc_ids):
        cur.execute(
            sql.SQL("INSERT INTO {} (raw_text, normalized_location_id, position) VALUES (%s,%s,%s)").format(
                sql.Identifier("alias_locations")
            ),
            (raw_text, lid, pos),
        )
    conn.commit()
    return loc_ids


SF_SPEC = {"canonicalName": "San Francisco, CA, US", "kind": "city",
           "city": "San Francisco", "region": "CA", "country": "US",
           "remoteScope": None}


# ===== POST /api/admin/jobs/{job_id}/normalize ===============================

class TestNormalizeJob:
    @pytest.mark.asyncio
    async def test_resets_status_and_defers(self, procrastinate_open, db_conn, client):
        _insert_job(db_conn, _make_job({"id": "job-1", "normalization_status": "done"}))
        db_conn.commit()

        resp = client.post("/api/admin/jobs/job-1/normalize")
        db_conn.rollback()
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["jobId"] == "job-1"
        assert body["status"] == "queued"

        # status reset to NULL
        cur = db_conn.cursor()
        cur.execute("SELECT normalization_status FROM job_listings WHERE id=%s", ("job-1",))
        assert cur.fetchone()["normalization_status"] is None

        # normalize_location deferred with the per-job queueing lock + arg
        jobs = _normalize_jobs(db_conn)
        assert len(jobs) == 1
        assert jobs[0]["queueing_lock"] == "normalize:job-1"
        assert jobs[0]["args"]["job_id"] == "job-1"

    def test_returns_200_when_defer_fails_after_reset(self, db_conn, client, monkeypatch):
        """A failed defer AFTER the reset committed must NOT 500 (mirrors the
        FIX-4 semantics on re-normalize-all): the row is NULL now, the periodic
        scan picks it up, and the response says what actually happened."""
        from procrastinate import exceptions as procrastinate_exceptions

        from api.routers import admin as admin_router

        _insert_job(db_conn, _make_job({"id": "job-df1", "normalization_status": "done"}))
        db_conn.commit()

        class _StubConfigured:
            async def defer_async(self, **kwargs):
                raise procrastinate_exceptions.ConnectorException("simulated connector failure")

        class _StubTask:
            def configure(self, **kwargs):
                return _StubConfigured()

        monkeypatch.setattr(admin_router, "normalize_location", _StubTask())

        resp = client.post("/api/admin/jobs/job-df1/normalize")
        db_conn.rollback()
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "reset_defer_failed"

        # The reset still committed despite the defer failure.
        cur = db_conn.cursor()
        cur.execute("SELECT normalization_status FROM job_listings WHERE id=%s", ("job-df1",))
        assert cur.fetchone()["normalization_status"] is None

    @pytest.mark.asyncio
    async def test_key_configured_flag_reflects_settings(self, procrastinate_open, db_conn, client, monkeypatch):
        from api.config import settings

        _insert_job(db_conn, _make_job({"id": "job-kc1", "normalization_status": "done"}))
        db_conn.commit()

        monkeypatch.setattr(settings, "anthropic_api_key", None)
        resp = client.post("/api/admin/jobs/job-kc1/normalize")
        db_conn.rollback()
        assert resp.status_code == 200, resp.text
        assert resp.json()["keyConfigured"] is False

        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        resp = client.post("/api/admin/jobs/job-kc1/normalize")
        db_conn.rollback()
        assert resp.status_code == 200, resp.text
        assert resp.json()["keyConfigured"] is True

    @pytest.mark.asyncio
    async def test_unknown_job_returns_404(self, procrastinate_open, db_conn, client):
        resp = client.post("/api/admin/jobs/does-not-exist/normalize")
        db_conn.rollback()
        assert resp.status_code == 404
        assert _normalize_jobs(db_conn) == []

    def test_without_admin_returns_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin
        _insert_user(db_conn, _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}))
        db_conn.commit()
        saved = test_app.dependency_overrides.pop(require_admin, None)
        try:
            resp = TestClient(test_app).post("/api/admin/jobs/job-1/normalize")
            assert resp.status_code == 403
        finally:
            if saved is not None:
                test_app.dependency_overrides[require_admin] = saved

    def test_without_auth_returns_401(self, test_app):
        from api.auth.dependencies import get_current_user, require_admin
        saved_a = test_app.dependency_overrides.pop(require_admin, None)
        saved_u = test_app.dependency_overrides.pop(get_current_user, None)
        try:
            resp = TestClient(test_app).post("/api/admin/jobs/job-1/normalize")
            assert resp.status_code == 401
        finally:
            if saved_a is not None:
                test_app.dependency_overrides[require_admin] = saved_a
            if saved_u is not None:
                test_app.dependency_overrides[get_current_user] = saved_u


# ===== PUT /api/admin/locations/aliases/{raw_text} ===========================

class TestOverrideAlias:
    def test_creates_manual_alias_and_mapping(self, client, db_conn):
        resp = client.put(
            "/api/admin/locations/aliases/San%20Francisco%2C%20CA",
            json={"locations": [SF_SPEC]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["rawText"] == "san francisco, ca"   # normalize_string applied
        assert body["source"] == "manual"
        assert body["confidence"] == 1.0
        assert len(body["locations"]) == 1
        assert body["locations"][0]["canonicalName"] == "San Francisco, CA, US"
        assert body["locations"][0]["position"] == 0

        # DB: alias is source='manual', mapping matches
        cur = db_conn.cursor()
        cur.execute("SELECT source, confidence FROM location_aliases WHERE raw_text=%s",
                    ("san francisco, ca",))
        row = cur.fetchone()
        assert row["source"] == "manual"
        cur.execute("SELECT COUNT(*) AS n FROM alias_locations WHERE raw_text=%s",
                    ("san francisco, ca",))
        assert cur.fetchone()["n"] == 1

    def test_overwrites_existing_llm_alias(self, client, db_conn):
        # The location tables are NOT truncated by the autouse clean_tables
        # fixture (Unit-8 plan: do not touch conftest), and db_conn is
        # module-scoped — so each test uses a UNIQUE key to avoid cross-test
        # bleed. This test keys on "oakland, ca".
        # Pre-seed a WRONG llm alias for the same normalized key.
        _seed_alias(
            db_conn, "oakland, ca", "llm", 0.4,
            [{"canonical_name": "Wrongville, ZZ, US", "kind": "city",
              "city": "Wrongville", "region": "ZZ", "country": "US"}],
        )
        resp = client.put(
            "/api/admin/locations/aliases/Oakland%2C%20CA",
            json={"locations": [
                {"canonicalName": "Oakland, CA, US", "kind": "city",
                 "city": "Oakland", "region": "CA", "country": "US"},
            ]},
        )
        assert resp.status_code == 200, resp.text

        cur = db_conn.cursor()
        cur.execute("SELECT source FROM location_aliases WHERE raw_text=%s", ("oakland, ca",))
        assert cur.fetchone()["source"] == "manual"   # promoted llm -> manual
        # mapping replaced: only the Oakland location, not Wrongville
        cur.execute(
            "SELECT l.canonical_name FROM alias_locations al "
            "JOIN locations l ON l.id = al.normalized_location_id "
            "WHERE al.raw_text=%s ORDER BY al.position", ("oakland, ca",))
        names = [r["canonical_name"] for r in cur.fetchall()]
        assert names == ["Oakland, CA, US"]

    def test_multi_location_override_ordered(self, client, db_conn):
        resp = client.put(
            "/api/admin/locations/aliases/sunnyvale%3B%20kirkland",
            json={"locations": [
                {"canonicalName": "Sunnyvale, CA, US", "kind": "city",
                 "city": "Sunnyvale", "region": "CA", "country": "US"},
                {"canonicalName": "Kirkland, WA, US", "kind": "city",
                 "city": "Kirkland", "region": "WA", "country": "US"},
            ]},
        )
        assert resp.status_code == 200, resp.text
        locs = resp.json()["locations"]
        assert [l["position"] for l in locs] == [0, 1]
        assert locs[0]["canonicalName"] == "Sunnyvale, CA, US"
        assert locs[1]["canonicalName"] == "Kirkland, WA, US"

    def test_noncanonical_spec_is_canonicalized_before_upsert(self, client, db_conn):
        """REGRESSION GUARD for _upsert_location's `c = canonicalize(spec)` wiring.

        A manual override may carry a non-canonical country ("USA") and a full
        US state name ("California"). The persisted location MUST land on the
        canonical codes (country='US', region='CA') with a RECOMPUTED city label
        ("San Jose, CA, US"), NOT the raw spec values. Every other PUT spec in
        this class already uses canonical values (country='US', USPS region
        codes) — fixed points of canonicalize — so removing the canonicalize()
        call would leave them green. This non-canonical input fails the moment
        that call is reverted.
        """
        resp = client.put(
            "/api/admin/locations/aliases/san-jose-noncanon-key",
            json={"locations": [
                {"canonicalName": "San Jose, California, USA", "kind": "city",
                 "city": "San Jose", "region": "California", "country": "USA"},
            ]},
        )
        assert resp.status_code == 200, resp.text
        loc = resp.json()["locations"][0]
        # Response reflects the canonicalized codes + recomputed label.
        assert loc["country"] == "US"
        assert loc["region"] == "CA"
        assert loc["canonicalName"] == "San Jose, CA, US"
        # The raw, non-canonical values must NOT survive.
        assert loc["country"] != "USA"
        assert loc["region"] != "California"

        # DB confirms the persisted locations row carries the canonical columns.
        cur = db_conn.cursor()
        cur.execute(
            "SELECT l.canonical_name, l.region, l.country FROM alias_locations al "
            "JOIN locations l ON l.id = al.normalized_location_id "
            "WHERE al.raw_text=%s", ("san-jose-noncanon-key",))
        row = cur.fetchone()
        assert row["country"] == "US"
        assert row["region"] == "CA"
        assert row["canonical_name"] == "San Jose, CA, US"

    def test_region_scoped_remote_override_accepted(self, client, db_conn):
        """A manual override can create a region/country-scoped remote (prod has
        'US - AZ - Remote', etc.): city stays None, region/country carry the
        scope. Mirrors the relaxed CanonicalLocation invariant on the LLM path."""
        resp = client.put(
            "/api/admin/locations/aliases/us-az-remote-key",
            json={"locations": [
                {"canonicalName": "Remote (AZ, US)", "kind": "remote",
                 "city": None, "region": "AZ", "country": "US",
                 "remoteScope": "us"},
            ]},
        )
        assert resp.status_code == 200, resp.text
        loc = resp.json()["locations"][0]
        assert loc["kind"] == "remote"
        assert loc["city"] is None
        assert loc["region"] == "AZ"
        assert loc["country"] == "US"

        cur = db_conn.cursor()
        cur.execute(
            "SELECT l.kind, l.region, l.country FROM alias_locations al "
            "JOIN locations l ON l.id = al.normalized_location_id "
            "WHERE al.raw_text=%s", ("us-az-remote-key",))
        row = cur.fetchone()
        assert (row["kind"], row["region"], row["country"]) == ("remote", "AZ", "US")

    def test_slash_in_raw_text_routes_and_upserts(self, client, db_conn):
        """Real location strings carry literal slashes ("EMEA / Remote",
        "Bellevue, WA / Seattle, WA"). The `:path` converter must route them to
        this endpoint instead of 404ing the primary correction primitive."""
        resp = client.put(
            "/api/admin/locations/aliases/Bellevue, WA %2F Seattle, WA",
            json={"locations": [
                {"canonicalName": "Bellevue, WA, US", "kind": "city",
                 "city": "Bellevue", "region": "WA", "country": "US"},
                {"canonicalName": "Seattle, WA, US", "kind": "city",
                 "city": "Seattle", "region": "WA", "country": "US"},
            ]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["rawText"] == "bellevue, wa / seattle, wa"
        assert len(body["locations"]) == 2

        cur = db_conn.cursor()
        cur.execute("SELECT source FROM location_aliases WHERE raw_text=%s",
                    ("bellevue, wa / seattle, wa",))
        assert cur.fetchone()["source"] == "manual"

    def test_duplicate_canonical_specs_dedup_not_500(self, client, db_conn):
        """Two specs resolving to the same canonical identity (same
        kind/city/region/country/remote_scope, different canonicalName) must
        collapse to one mapping row — not PK-violate alias_locations and 500."""
        resp = client.put(
            "/api/admin/locations/aliases/dupe-city-key",
            json={"locations": [
                {"canonicalName": "Dupe City, DD, US", "kind": "city",
                 "city": "Dupe City", "region": "DD", "country": "US"},
                {"canonicalName": "DUPE CITY (alt spelling), DD, US", "kind": "city",
                 "city": "Dupe City", "region": "DD", "country": "US"},
            ]},
        )
        assert resp.status_code == 200, resp.text
        locs = resp.json()["locations"]
        assert len(locs) == 1
        assert locs[0]["position"] == 0

        cur = db_conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM alias_locations WHERE raw_text=%s",
                    ("dupe-city-key",))
        assert cur.fetchone()["n"] == 1

    def test_empty_locations_rejected_422(self, client):
        resp = client.put("/api/admin/locations/aliases/foo", json={"locations": []})
        assert resp.status_code == 422

    def test_contradictory_spec_rejected_422(self, client):
        # LocationSpec cross-field invariant: kind='remote' carrying a city is a
        # validation error -> 422 (never reaches the DB writer).
        resp = client.put(
            "/api/admin/locations/aliases/bad-remote",
            json={"locations": [
                {"canonicalName": "Remote (US)", "kind": "remote",
                 "city": "San Jose", "region": None, "country": None,
                 "remoteScope": "us"},
            ]},
        )
        assert resp.status_code == 422

    def test_without_admin_returns_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin
        _insert_user(db_conn, _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}))
        db_conn.commit()
        saved = test_app.dependency_overrides.pop(require_admin, None)
        try:
            resp = TestClient(test_app).put("/api/admin/locations/aliases/foo",
                                            json={"locations": [SF_SPEC]})
            assert resp.status_code == 403
        finally:
            if saved is not None:
                test_app.dependency_overrides[require_admin] = saved


# ===== GET /api/admin/locations/aliases ======================================

class TestListAliases:
    def test_filter_by_contains(self, client, db_conn):
        # Unique substring "zzqq" so the contains filter is robust against
        # location-alias rows seeded by other tests in this module (the
        # location tables are not truncated between tests — see note above).
        _seed_alias(db_conn, "zzqqville, ca", "llm", 0.95,
                    [{"canonical_name": "Zzqqville, CA, US", "kind": "city",
                      "city": "Zzqqville", "region": "CA", "country": "US"}])
        _seed_alias(db_conn, "austin, tx", "manual", 1.0,
                    [{"canonical_name": "Austin, TX, US", "kind": "city",
                      "city": "Austin", "region": "TX", "country": "US"}])

        resp = client.get("/api/admin/locations/aliases", params={"contains": "zzqq"})
        assert resp.status_code == 200
        aliases = resp.json()["aliases"]
        assert len(aliases) == 1
        assert aliases[0]["rawText"] == "zzqqville, ca"
        assert aliases[0]["locations"][0]["canonicalName"] == "Zzqqville, CA, US"

    def test_no_filter_returns_recent_bounded(self, client, db_conn):
        for i in range(3):
            _seed_alias(db_conn, f"city-{i}", "llm", 0.9,
                        [{"canonical_name": f"City{i}", "kind": "city", "city": f"City{i}"}])
        resp = client.get("/api/admin/locations/aliases", params={"limit": 2})
        assert resp.status_code == 200
        assert len(resp.json()["aliases"]) == 2

    def test_limit_over_cap_returns_422(self, client):
        resp = client.get("/api/admin/locations/aliases", params={"limit": 5000})
        assert resp.status_code == 422

    def test_without_admin_returns_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin
        _insert_user(db_conn, _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}))
        db_conn.commit()
        saved = test_app.dependency_overrides.pop(require_admin, None)
        try:
            resp = TestClient(test_app).get("/api/admin/locations/aliases")
            assert resp.status_code == 403
        finally:
            if saved is not None:
                test_app.dependency_overrides[require_admin] = saved


# ===== POST /api/admin/locations/re-normalize-all ============================

class TestReNormalizeAll:
    @pytest.mark.asyncio
    async def test_resets_done_failed_and_defers_scan(self, procrastinate_open, db_conn, client):
        _insert_job(db_conn, _make_job({"id": "d1", "normalization_status": "done"}))
        _insert_job(db_conn, _make_job({"id": "f1", "normalization_status": "failed"}))
        _insert_job(db_conn, _make_job({"id": "n1", "normalization_status": None}))
        db_conn.commit()

        resp = client.post("/api/admin/locations/re-normalize-all")
        db_conn.rollback()
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["resetCount"] == 2          # only done + failed flipped
        assert body["scanDeferred"] is True
        assert "fresh LLM" in body["note"]

        # all three now NULL
        cur = db_conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM job_listings WHERE normalization_status IS NOT NULL")
        assert cur.fetchone()["n"] == 0

        # scan_unnormalized deferred with timestamp=0
        scans = _scan_jobs(db_conn)
        assert len(scans) == 1
        assert scans[0]["args"]["timestamp"] == 0

    @pytest.mark.asyncio
    async def test_returns_200_when_scan_defer_fails(self, db_conn, client, monkeypatch):
        """FIX-4: a failed scan_unnormalized defer AFTER the reset committed must
        NOT 500 — return 200 with scanDeferred=False (the destructive reset stands
        and the periodic scan picks it up)."""
        from procrastinate import exceptions as procrastinate_exceptions

        from api.routers import admin as admin_router

        _insert_job(db_conn, _make_job({"id": "rd1", "normalization_status": "done"}))
        db_conn.commit()

        async def _boom(*args, **kwargs):
            raise procrastinate_exceptions.ConnectorException("simulated connector failure")

        monkeypatch.setattr(admin_router.scan_unnormalized, "defer_async", _boom)

        resp = client.post("/api/admin/locations/re-normalize-all")
        db_conn.rollback()
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["scanDeferred"] is False
        assert body["resetCount"] >= 1

        # The reset still committed despite the defer failure.
        cur = db_conn.cursor()
        cur.execute("SELECT normalization_status FROM job_listings WHERE id=%s", ("rd1",))
        assert cur.fetchone()["normalization_status"] is None

    @pytest.mark.asyncio
    async def test_no_key_surfaces_paused_draining(self, procrastinate_open, db_conn, client, monkeypatch):
        """With ANTHROPIC_API_KEY unset the reset still happens, but the response
        must say draining is paused (keyConfigured=False + WARNING note) instead
        of implying the backlog will drain — the deferred scan skips while the
        key is absent, so a bare success response would be a silent no-op."""
        from api.config import settings

        _insert_job(db_conn, _make_job({"id": "nk1", "normalization_status": "done"}))
        db_conn.commit()

        monkeypatch.setattr(settings, "anthropic_api_key", None)
        resp = client.post("/api/admin/locations/re-normalize-all")
        db_conn.rollback()
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["keyConfigured"] is False
        assert "PAUSED" in body["note"]

        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        resp = client.post("/api/admin/locations/re-normalize-all")
        db_conn.rollback()
        body = resp.json()
        assert body["keyConfigured"] is True
        assert "PAUSED" not in body["note"]

    def test_without_admin_returns_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin
        _insert_user(db_conn, _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}))
        db_conn.commit()
        saved = test_app.dependency_overrides.pop(require_admin, None)
        try:
            resp = TestClient(test_app).post("/api/admin/locations/re-normalize-all")
            assert resp.status_code == 403
        finally:
            if saved is not None:
                test_app.dependency_overrides[require_admin] = saved
