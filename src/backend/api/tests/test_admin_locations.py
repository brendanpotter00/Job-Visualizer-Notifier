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

    def test_empty_locations_rejected_422(self, client):
        resp = client.put("/api/admin/locations/aliases/foo", json={"locations": []})
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
