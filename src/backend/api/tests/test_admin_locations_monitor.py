"""Integration tests for the read-only Location-Normalization Monitor endpoints.

Covers the five new admin GET endpoints + the offset/total extension to the
existing aliases list endpoint. Mirrors test_admin_locations.py's harness
(client / db_conn fixtures, admin-override pop for the 403 gate, _insert_job,
_seed_alias).

worker_heartbeats IS an ORM model (api.db_models.WorkerHeartbeat), so the health
tests seed it directly. procrastinate_jobs / procrastinate_events are NOT ORM
tables and are absent from the default per-worker test schema — so the health
endpoint's to_regclass guards are exercised here (normalizeQueue == {} and
throughputInWindow is None without a procrastinate fixture).
"""

import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from .conftest import _insert_job, _insert_user, _make_job, _make_user
from .test_admin_locations import _seed_alias


def _clear_location_tables(conn) -> None:
    """Truncate the location-normalization tables.

    The autouse ``clean_tables`` fixture (conftest) does NOT touch these tables
    (the Unit-8 plan deliberately leaves conftest alone), and ``db_conn`` is
    module-scoped — so location rows seeded by one test bleed into the next.
    Tests that assert on the *global* state of these tables (e.g. the empty-DB
    integrity check, where every count must be 0) call this first to get a clean
    slate independent of test ordering. job_listings is already truncated by the
    autouse fixture.
    """
    cur = conn.cursor()
    cur.execute(
        sql.SQL("TRUNCATE {}, {}, {}, {} CASCADE").format(
            sql.Identifier("job_locations"),
            sql.Identifier("alias_locations"),
            sql.Identifier("location_aliases"),
            sql.Identifier("locations"),
        )
    )
    conn.commit()


def _set_normalized(conn, job_id: str, status: str | None) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE job_listings SET normalization_status=%s WHERE id=%s", (status, job_id)
    )
    conn.commit()


def _seed_heartbeat(conn, minutes_ago: float = 0.0) -> None:
    """Insert a worker_heartbeats row `minutes_ago` minutes in the past.

    Uses make_interval's `secs` parameter (double precision) — `mins` is
    integer-typed and rejects a float bind.
    """
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (at) VALUES (now() - make_interval(secs => %s))"
        ).format(sql.Identifier("worker_heartbeats")),
        (minutes_ago * 60.0,),
    )
    conn.commit()


def _seed_location(conn, spec: dict) -> int:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (canonical_name, kind, city, region, country, remote_scope, lat, lng) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id"
        ).format(sql.Identifier("locations")),
        (spec["canonical_name"], spec["kind"], spec.get("city"), spec.get("region"),
         spec.get("country"), spec.get("remote_scope"), spec.get("lat"), spec.get("lng")),
    )
    loc_id = cur.fetchone()["id"]
    conn.commit()
    return loc_id


def _insert_job_loc(conn, job_id: str, loc_id: int, is_primary: bool) -> None:
    cur = conn.cursor()
    cur.execute(
        sql.SQL(
            "INSERT INTO {} (job_listing_id, normalized_location_id, is_primary) "
            "VALUES (%s,%s,%s)"
        ).format(sql.Identifier("job_locations")),
        (job_id, loc_id, is_primary),
    )
    conn.commit()


def _pop_admin(test_app):
    """Pop the require_admin override; returns (saved, restore_fn)."""
    from api.auth.dependencies import require_admin

    saved = test_app.dependency_overrides.pop(require_admin, None)

    def restore():
        if saved is not None:
            test_app.dependency_overrides[require_admin] = saved

    return restore


# ===== GET /api/admin/locations/health =======================================

class TestHealth:
    def test_happy_path_counts_and_ratio(self, client, db_conn):
        _insert_job(db_conn, _make_job({"id": "h-done1", "normalization_status": "done"}))
        _insert_job(db_conn, _make_job({"id": "h-done2", "normalization_status": "done"}))
        # failed-nonblank (has a real location)
        _insert_job(db_conn, _make_job(
            {"id": "h-failnb", "normalization_status": "failed", "location": "Somewhere, ZZ"}))
        # failed-blank (empty location) — excluded from the nonblank ratio
        _insert_job(db_conn, _make_job(
            {"id": "h-failb", "normalization_status": "failed", "location": ""}))
        # NULL backlog row
        _insert_job(db_conn, _make_job({"id": "h-null1", "normalization_status": None}))
        _seed_heartbeat(db_conn, minutes_ago=3.0)

        resp = client.get("/api/admin/locations/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["schemaPresent"] is True
        assert body["windowHours"] == 24
        assert body["done"] == 2
        assert body["failed"] == 2
        assert body["nullBacklog"] == 1
        assert body["total"] == 5
        assert body["failedBlank"] == 1
        assert body["failedNonblank"] == 1
        # 100 * 1 / (2 done + 1 failed_nonblank) = 33.33...
        assert body["failedNonblankRatio"] == pytest.approx(100.0 / 3.0, rel=1e-6)
        # heartbeat ~3 min ago
        assert body["heartbeatAgeMinutes"] is not None
        assert 2.0 < body["heartbeatAgeMinutes"] < 6.0

    def test_procrastinate_guard_no_crash(self, client, db_conn):
        """The to_regclass guard around the procrastinate tables must keep the
        endpoint from ever 500ing on those tables.

        When the procrastinate schema is ABSENT (the default per-worker test
        schema; also a clean CI database), the guard yields normalizeQueue == {}
        and throughputInWindow is None. In a polluted dev DB the procrastinate
        tables may resolve via the `public` fallback in the search_path
        ("test_xxx", public) — in that case the guard still must not crash, so we
        only assert the response shape (dict / int-or-None). Either way: 200, no
        500. We probe the table's resolvability from the test's own connection to
        pick the right assertion."""
        _insert_job(db_conn, _make_job({"id": "h-pg1", "normalization_status": "done"}))
        cur = db_conn.cursor()
        cur.execute("SELECT to_regclass('procrastinate_jobs') AS oid")
        procrastinate_present = cur.fetchone()["oid"] is not None
        db_conn.rollback()

        resp = client.get("/api/admin/locations/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if procrastinate_present:
            # Polluted dev DB: guard resolved the public tables — must not crash.
            assert isinstance(body["normalizeQueue"], dict)
            assert body["throughputInWindow"] is None or isinstance(
                body["throughputInWindow"], int
            )
        else:
            # Clean schema (CI / isolated): guard short-circuits to empty/None.
            assert body["normalizeQueue"] == {}
            assert body["throughputInWindow"] is None

    def test_no_heartbeat_yields_null_age(self, client, db_conn):
        """worker_heartbeats exists (ORM table) but is empty -> max(at) is NULL ->
        heartbeatAgeMinutes is null (the table-present, no-rows path)."""
        _insert_job(db_conn, _make_job({"id": "h-nh1", "normalization_status": "done"}))
        resp = client.get("/api/admin/locations/health")
        assert resp.status_code == 200, resp.text
        assert resp.json()["heartbeatAgeMinutes"] is None

    def test_empty_db_zeros_and_zero_ratio(self, client, db_conn):
        resp = client.get("/api/admin/locations/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 0
        assert body["done"] == 0
        assert body["failed"] == 0
        assert body["nullBacklog"] == 0
        # denom 0 -> ratio 0.0 (not a division error)
        assert body["failedNonblankRatio"] == 0.0

    def test_key_configured_flag(self, client, db_conn, monkeypatch):
        from api.config import settings

        monkeypatch.setattr(settings, "anthropic_api_key", None)
        assert client.get("/api/admin/locations/health").json()["keyConfigured"] is False
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        assert client.get("/api/admin/locations/health").json()["keyConfigured"] is True

    def test_dormant_inference(self, client, db_conn, monkeypatch):
        """No key + large NULL backlog + nothing processed -> dormant True."""
        from api.config import settings

        _insert_job(db_conn, _make_job({"id": "h-dm1", "normalization_status": None}))
        _insert_job(db_conn, _make_job({"id": "h-dm2", "normalization_status": None}))

        monkeypatch.setattr(settings, "anthropic_api_key", None)
        assert client.get("/api/admin/locations/health").json()["dormant"] is True
        # With a key configured, never dormant even with a backlog.
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        assert client.get("/api/admin/locations/health").json()["dormant"] is False

    def test_window_hours_bounds(self, client):
        assert client.get("/api/admin/locations/health", params={"windowHours": 0}).status_code == 422
        assert client.get("/api/admin/locations/health", params={"windowHours": 200}).status_code == 422
        assert client.get("/api/admin/locations/health", params={"windowHours": 168}).status_code == 200
        assert client.get("/api/admin/locations/health", params={"windowHours": 1}).status_code == 200

    def test_without_admin_returns_403(self, test_app, db_conn):
        _insert_user(db_conn, _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}))
        db_conn.commit()
        restore = _pop_admin(test_app)
        try:
            resp = TestClient(test_app).get("/api/admin/locations/health")
            assert resp.status_code == 403
        finally:
            restore()


# ===== GET /api/admin/locations/integrity ====================================

class TestIntegrity:
    def test_empty_db_all_checks_ok(self, client, db_conn):
        _clear_location_tables(db_conn)
        resp = client.get("/api/admin/locations/integrity")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["schemaPresent"] is True
        checks = body["checks"]
        assert [c["id"] for c in checks] == [f"C{i}" for i in range(1, 10)]
        assert all(c["count"] == 0 for c in checks)
        assert all(c["severity"] == "ok" for c in checks)

    def test_c5_remote_with_city_warn(self, client, db_conn):
        # A remote location carrying a city violates C5.
        _clear_location_tables(db_conn)
        _seed_location(db_conn, {"canonical_name": "Remote-with-city", "kind": "remote",
                                 "city": "Oops City", "region": None, "country": None})
        body = client.get("/api/admin/locations/integrity").json()
        c5 = next(c for c in body["checks"] if c["id"] == "C5")
        assert c5["count"] == 1
        assert c5["severity"] == "warn"

    def test_c7_low_confidence_llm_warn(self, client, db_conn):
        _clear_location_tables(db_conn)
        _seed_alias(db_conn, "lowconf, ca", "llm", 0.3,
                    [{"canonical_name": "Lowconf, CA, US", "kind": "city",
                      "city": "Lowconf", "region": "CA", "country": "US"}])
        body = client.get("/api/admin/locations/integrity").json()
        c7 = next(c for c in body["checks"] if c["id"] == "C7")
        assert c7["count"] == 1
        assert c7["severity"] == "warn"

    def test_c1_done_without_locations_crit(self, client, db_conn):
        # A 'done' job with NO job_locations row violates C1 (crit).
        _clear_location_tables(db_conn)
        _insert_job(db_conn, _make_job({"id": "i-c1", "normalization_status": "done"}))
        body = client.get("/api/admin/locations/integrity").json()
        c1 = next(c for c in body["checks"] if c["id"] == "C1")
        assert c1["count"] == 1
        assert c1["severity"] == "crit"

    def test_c1_done_with_location_ok(self, client, db_conn):
        # A 'done' job WITH a job_locations row does not violate C1.
        _clear_location_tables(db_conn)
        loc_id = _seed_location(db_conn, {"canonical_name": "SF, CA, US", "kind": "city",
                                          "city": "SF", "region": "CA", "country": "US"})
        _insert_job(db_conn, _make_job({"id": "i-c1ok", "normalization_status": "done"}))
        _insert_job_loc(db_conn, "i-c1ok", loc_id, True)
        body = client.get("/api/admin/locations/integrity").json()
        c1 = next(c for c in body["checks"] if c["id"] == "C1")
        assert c1["count"] == 0
        assert c1["severity"] == "ok"

    def test_without_admin_returns_403(self, test_app, db_conn):
        _insert_user(db_conn, _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}))
        db_conn.commit()
        restore = _pop_admin(test_app)
        try:
            assert TestClient(test_app).get("/api/admin/locations/integrity").status_code == 403
        finally:
            restore()


# ===== GET /api/admin/locations/reverse ======================================

class TestReverse:
    def test_groups_raw_texts_per_location(self, client, db_conn):
        # Two alias keys both mapping to the same canonical location.
        spec = {"canonical_name": "Reverseville, RV, US", "kind": "city",
                "city": "Reverseville", "region": "RV", "country": "US"}
        _seed_alias(db_conn, "reverseville", "llm", 0.9, [spec])
        _seed_alias(db_conn, "reverseville, rv", "manual", 1.0, [spec])

        resp = client.get("/api/admin/locations/reverse", params={"contains": "Reverseville"})
        assert resp.status_code == 200, resp.text
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["location"]["canonicalName"] == "Reverseville, RV, US"
        assert "position" not in results[0]["location"]
        assert sorted(results[0]["rawTexts"]) == ["reverseville", "reverseville, rv"]

    def test_no_match_empty(self, client, db_conn):
        resp = client.get("/api/admin/locations/reverse", params={"contains": "no-such-place-xyz"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["results"] == []

    def test_limit_over_cap_422(self, client):
        assert client.get("/api/admin/locations/reverse", params={"limit": 5000}).status_code == 422

    def test_without_admin_returns_403(self, test_app, db_conn):
        _insert_user(db_conn, _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}))
        db_conn.commit()
        restore = _pop_admin(test_app)
        try:
            assert TestClient(test_app).get("/api/admin/locations/reverse").status_code == 403
        finally:
            restore()


# ===== GET /api/admin/locations/alias-originals ==============================

class TestAliasOriginals:
    def test_casing_and_whitespace_variants_grouped(self, client, db_conn):
        # Two job locations that normalize_string collapses to "san jose, ca";
        # one that does NOT (different place).
        _insert_job(db_conn, _make_job({"id": "ao-1", "location": "San Jose, CA"}))
        _insert_job(db_conn, _make_job({"id": "ao-2", "location": "  SAN   JOSE,  CA  "}))
        _insert_job(db_conn, _make_job({"id": "ao-3", "location": "Austin, TX"}))

        resp = client.get("/api/admin/locations/alias-originals",
                          params={"rawText": "san jose, ca"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["rawText"] == "san jose, ca"
        originals = {o["original"]: o["jobIds"] for o in body["originals"]}
        # Both variants present, grouped by verbatim string.
        assert "San Jose, CA" in originals
        assert "  SAN   JOSE,  CA  " in originals
        assert originals["San Jose, CA"] == ["ao-1"]
        assert originals["  SAN   JOSE,  CA  "] == ["ao-2"]
        # The non-matching Austin job is absent.
        assert "Austin, TX" not in originals
        assert body["total"] == 2

    def test_no_match_empty(self, client, db_conn):
        _insert_job(db_conn, _make_job({"id": "ao-nm", "location": "Austin, TX"}))
        resp = client.get("/api/admin/locations/alias-originals",
                          params={"rawText": "nowhere, zz"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 0
        assert body["originals"] == []

    def test_missing_rawtext_422(self, client):
        assert client.get("/api/admin/locations/alias-originals").status_code == 422

    def test_limit_over_cap_422(self, client):
        resp = client.get("/api/admin/locations/alias-originals",
                          params={"rawText": "x", "limit": 5000})
        assert resp.status_code == 422

    def test_without_admin_returns_403(self, test_app, db_conn):
        _insert_user(db_conn, _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}))
        db_conn.commit()
        restore = _pop_admin(test_app)
        try:
            resp = TestClient(test_app).get("/api/admin/locations/alias-originals",
                                            params={"rawText": "x"})
            assert resp.status_code == 403
        finally:
            restore()


# ===== GET /api/admin/locations/problem-jobs =================================

class TestProblemJobs:
    def test_only_failed_nonblank_returned(self, client, db_conn):
        _insert_job(db_conn, _make_job(
            {"id": "pj-nb1", "normalization_status": "failed", "location": "Bad Place, XX",
             "last_seen_at": "2025-03-01T10:00:00Z"}))
        _insert_job(db_conn, _make_job(
            {"id": "pj-nb2", "normalization_status": "failed", "location": "Other Bad, YY",
             "last_seen_at": "2025-03-02T10:00:00Z"}))
        # failed-blank: excluded
        _insert_job(db_conn, _make_job(
            {"id": "pj-blank", "normalization_status": "failed", "location": "   "}))
        # done: excluded
        _insert_job(db_conn, _make_job(
            {"id": "pj-done", "normalization_status": "done", "location": "Fine, CA"}))

        resp = client.get("/api/admin/locations/problem-jobs")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = [j["id"] for j in body["jobs"]]
        assert set(ids) == {"pj-nb1", "pj-nb2"}
        assert body["total"] == 2
        # Ordered by last_seen_at DESC: pj-nb2 (Mar 2) before pj-nb1 (Mar 1).
        assert ids == ["pj-nb2", "pj-nb1"]
        first = body["jobs"][0]
        assert first["normalizationStatus"] == "failed"
        assert first["location"] == "Other Bad, YY"
        assert first["company"] == "google"

    def test_pagination_offset(self, client, db_conn):
        for i in range(3):
            _insert_job(db_conn, _make_job(
                {"id": f"pj-pg{i}", "normalization_status": "failed",
                 "location": f"Place {i}",
                 "last_seen_at": f"2025-04-0{i + 1}T10:00:00Z"}))
        page1 = client.get("/api/admin/locations/problem-jobs",
                           params={"limit": 2, "offset": 0}).json()
        page2 = client.get("/api/admin/locations/problem-jobs",
                           params={"limit": 2, "offset": 2}).json()
        assert page1["total"] == 3
        assert page2["total"] == 3
        assert len(page1["jobs"]) == 2
        assert len(page2["jobs"]) == 1
        # No overlap between the pages.
        ids1 = {j["id"] for j in page1["jobs"]}
        ids2 = {j["id"] for j in page2["jobs"]}
        assert ids1.isdisjoint(ids2)

    def test_empty_db(self, client, db_conn):
        resp = client.get("/api/admin/locations/problem-jobs")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["jobs"] == []
        assert body["total"] == 0

    def test_bad_params_422(self, client):
        assert client.get("/api/admin/locations/problem-jobs", params={"limit": 5000}).status_code == 422
        assert client.get("/api/admin/locations/problem-jobs", params={"offset": -1}).status_code == 422

    def test_without_admin_returns_403(self, test_app, db_conn):
        _insert_user(db_conn, _make_user({"auth0_id": "auth0|test_user_123", "email": "test@example.com"}))
        db_conn.commit()
        restore = _pop_admin(test_app)
        try:
            assert TestClient(test_app).get("/api/admin/locations/problem-jobs").status_code == 403
        finally:
            restore()


# ===== GET /api/admin/locations/aliases — offset/total regression ============

class TestAliasesOffsetTotal:
    def test_total_independent_of_limit(self, client, db_conn):
        for i in range(5):
            _seed_alias(db_conn, f"ot-city-{i}", "llm", 0.9,
                        [{"canonical_name": f"OtCity{i}", "kind": "city", "city": f"OtCity{i}"}])
        body = client.get("/api/admin/locations/aliases", params={"limit": 2}).json()
        assert len(body["aliases"]) == 2
        # total counts ALL aliases regardless of the page limit.
        assert body["total"] >= 5

    def test_offset_paginates(self, client, db_conn):
        for i in range(4):
            _seed_alias(db_conn, f"ofs-city-{i}", "manual", 1.0,
                        [{"canonical_name": f"OfsCity{i}", "kind": "city", "city": f"OfsCity{i}"}])
        page1 = client.get("/api/admin/locations/aliases",
                           params={"contains": "ofs-city", "limit": 2, "offset": 0}).json()
        page2 = client.get("/api/admin/locations/aliases",
                           params={"contains": "ofs-city", "limit": 2, "offset": 2}).json()
        assert page1["total"] == 4
        assert page2["total"] == 4
        keys1 = {a["rawText"] for a in page1["aliases"]}
        keys2 = {a["rawText"] for a in page2["aliases"]}
        assert keys1.isdisjoint(keys2)
        assert len(keys1) == 2
        assert len(keys2) == 2

    def test_limit_over_cap_still_422(self, client):
        # The existing cap behavior is preserved after adding offset/total.
        assert client.get("/api/admin/locations/aliases", params={"limit": 5000}).status_code == 422

    def test_negative_offset_422(self, client):
        assert client.get("/api/admin/locations/aliases", params={"offset": -1}).status_code == 422
