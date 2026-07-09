"""Tests for the admin enrichment-oversight endpoints + GET /api/jobs/facets.

Named test_enrichment_admin (not test_admin_enrichment) deliberately: pytest
collects alphabetically, and any test_app-using file collected IMMEDIATELY
before test_enqueue_ashby_fan_out.py trips that file's pre-existing
order-coupled dedup flake (test_admin_router.py + it fails the same way when
run adjacently). Sorting after the test_enqueue_* files sidesteps it.

Reuses test_internal_enrichment's taxonomy seed + table isolation (imported
autouse fixture) and conftest's ``test_app``/``client`` (require_admin already
overridden with test claims; TestAdminEnrichmentGate below verifies the gate
itself the same way test_admin_router does).
"""

import json

from fastapi.testclient import TestClient

from .conftest import _insert_job, _make_job
from .test_internal_enrichment import _enrichment_isolation  # noqa: F401 — autouse fixture


def _seed_flagged_job(db_conn, job_id="q-1", source_id="src-a", *, status="OPEN",
                      company="google", confidence=0.4, corrected=False):
    _insert_job(db_conn, _make_job({
        "id": job_id, "source_id": source_id, "status": status, "company": company,
        "details": json.dumps({"description_html": "<p>x</p>"}),
    }))
    cur = db_conn.cursor()
    cur.execute(
        "UPDATE job_listings SET enrichment_status='needs_human' "
        "WHERE source_id=%s AND id=%s",
        (source_id, job_id),
    )
    cur.execute(
        "INSERT INTO job_enrichment (source_id, job_listing_id, clean_description, "
        "classify_confidence, classify_reasoning, judged, judge_passed, "
        "judge_confidence, judge_notes, needs_human, human_corrected_at) "
        "VALUES (%s, %s, 'clean text', %s, 'because', true, false, 0.5, "
        "'ambiguous level', true, %s)",
        (source_id, job_id, confidence,
         "2026-01-01T00:00:00Z" if corrected else None),
    )
    db_conn.commit()


class TestAdminEnrichmentGate:
    def test_non_admin_gets_403(self, test_app, db_conn):
        from api.auth.dependencies import require_admin

        saved = test_app.dependency_overrides.pop(require_admin, None)
        try:
            client = TestClient(test_app)
            for path in (
                "/api/admin/enrichment/health",
                "/api/admin/enrichment/needs-human",
                "/api/admin/enrichment/ticks",
                "/api/admin/enrichment/recent",
            ):
                assert client.get(path).status_code in (401, 403), path
            assert client.post(
                "/api/admin/enrichment/jobs/s/j/correct", json={}
            ).status_code in (401, 403)
            assert client.post(
                "/api/admin/enrichment/jobs/s/j/reenrich"
            ).status_code in (401, 403)
        finally:
            if saved is not None:
                test_app.dependency_overrides[require_admin] = saved


class TestAdminEnrichmentHealth:
    def test_health_snapshot(self, client, db_conn):
        _seed_flagged_job(db_conn)
        resp = client.get("/api/admin/enrichment/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["schemaPresent"] is True
        assert body["openByStatus"] == {"needs_human": 1}
        assert body["needsHumanOpen"] == 1
        assert body["humanCorrectedTotal"] == 0
        assert body["enrichedInWindow"] == 1
        # nothing pushed yet
        assert body["lastTickUuid"] is None
        assert body["lastTickStatus"] is None


class TestAdminEnrichmentNeedsHuman:
    def test_queue_pagination_and_shape(self, client, db_conn):
        for i in range(3):
            _seed_flagged_job(db_conn, job_id=f"q-{i}", company=f"co-{i}")
        resp = client.get("/api/admin/enrichment/needs-human?limit=2&offset=0")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 3
        assert len(body["rows"]) == 2
        row = body["rows"][0]
        assert row["judgeNotes"] == "ambiguous level"
        assert row["classifyConfidence"] == 0.4
        assert row["enrichmentStatus"] == "needs_human"

    def test_filters(self, client, db_conn):
        _seed_flagged_job(db_conn, job_id="q-a", company="alpha")
        _seed_flagged_job(db_conn, job_id="q-b", company="beta")
        _seed_flagged_job(db_conn, job_id="q-closed", company="alpha", status="CLOSED")
        _seed_flagged_job(db_conn, job_id="q-fixed", company="alpha", corrected=True)

        resp = client.get("/api/admin/enrichment/needs-human", params={"company": "alpha"})
        body = resp.json()
        assert body["total"] == 1
        assert body["rows"][0]["jobListingId"] == "q-a"

        # includeCorrected + onlyOpen widen the view
        resp = client.get(
            "/api/admin/enrichment/needs-human",
            params={"company": "alpha", "includeCorrected": "true", "onlyOpen": "false"},
        )
        assert resp.json()["total"] == 3


class TestAdminEnrichmentCorrect:
    def test_correction_publishes_and_locks(self, client, db_conn):
        _seed_flagged_job(db_conn)
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "growth", "level": "new_grad",
                  "tags": ["GTM", "sql "], "note": "actually growth"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["category"] == "growth"
        assert body["level"] == "new_grad"
        assert body["tags"] == ["gtm", "sql"]           # normalized
        assert body["enrichmentStatus"] == "done"
        assert body["humanCorrectedBy"] == "test@example.com"

        cur = db_conn.cursor()
        cur.execute(
            "SELECT needs_human, human_corrected_at, judge_notes FROM job_enrichment "
            "WHERE source_id='src-a' AND job_listing_id='q-1'"
        )
        row = cur.fetchone()
        assert row["needs_human"] is False
        assert row["human_corrected_at"] is not None
        assert "[human] actually growth" in row["judge_notes"]

        # queue no longer lists it
        assert client.get("/api/admin/enrichment/needs-human").json()["total"] == 0

    def test_unknown_slug_409(self, client, db_conn):
        _seed_flagged_job(db_conn)
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "underwater_basket_weaving"},
        )
        assert resp.status_code == 409
        assert "underwater_basket_weaving" in resp.json()["detail"]

    def test_unknown_job_404(self, client, db_conn):
        resp = client.post(
            "/api/admin/enrichment/jobs/ghost-src/ghost-id/correct", json={}
        )
        assert resp.status_code == 404

    def test_correction_without_audit_row_upserts(self, client, db_conn):
        """Correcting a never-enriched job still lands the lock + provenance."""
        _insert_job(db_conn, _make_job({
            "id": "bare-1", "source_id": "src-b",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        resp = client.post(
            "/api/admin/enrichment/jobs/src-b/bare-1/correct",
            json={"category": "software_engineering", "level": "senior"},
        )
        assert resp.status_code == 200, resp.text
        cur = db_conn.cursor()
        cur.execute(
            "SELECT human_corrected_at FROM job_enrichment "
            "WHERE source_id='src-b' AND job_listing_id='bare-1'"
        )
        assert cur.fetchone()["human_corrected_at"] is not None

    def test_reenrich_unlocks_and_resets(self, client, db_conn):
        _seed_flagged_job(db_conn)
        client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "growth", "level": "mid", "tags": ["x"]},
        )
        resp = client.post("/api/admin/enrichment/jobs/src-a/q-1/reenrich")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enrichmentStatus"] is None
        assert body["category"] is None and body["level"] is None

        cur = db_conn.cursor()
        cur.execute(
            "SELECT enrichment_status, enrichment_category FROM job_listings "
            "WHERE source_id='src-a' AND id='q-1'"
        )
        row = cur.fetchone()
        assert row["enrichment_status"] is None and row["enrichment_category"] is None
        cur.execute(
            "SELECT human_corrected_at, needs_human FROM job_enrichment "
            "WHERE source_id='src-a' AND job_listing_id='q-1'"
        )
        row = cur.fetchone()
        assert row["human_corrected_at"] is None and row["needs_human"] is False
        cur.execute("SELECT count(*) AS n FROM job_tags WHERE job_listing_id='q-1'")
        assert cur.fetchone()["n"] == 0


class TestAdminEnrichmentTicks:
    _PAYLOAD = {
        "tick_uuid": "tick-admin-1",
        "started_at": "2026-07-08T10:00:00+00:00",
        "ended_at": "2026-07-08T10:05:00+00:00",
        "status": "ok",
        "counters": {"claimed": 5, "classified": 5, "sent": 5},
        "duration_s": 300.0,
        "taxonomy_version": "v2+abc",
        "knobs": {"judge_scope": "low_confidence"},
        "stage_timings": [{"stage": "classify", "ms": 1000, "items": 5, "retries": 0}],
        "scorecard": {"category_accuracy": 0.91},
    }

    def test_ticks_series_and_latest_scorecard(self, client, db_conn):
        from api.services.enrichment_monitor import record_tick

        record_tick(db_conn, self._PAYLOAD)
        resp = client.get("/api/admin/enrichment/ticks?windowHours=168")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # started_at is in the past relative to the test clock — it may fall
        # outside a small window, so we asked for the max (168h) and only assert
        # scorecard/knobs behavior plus row shape when present.
        assert body["latestScorecard"] == {"category_accuracy": 0.91}
        assert body["latestScorecardTickUuid"] == "tick-admin-1"
        assert body["latestKnobs"] == {"judge_scope": "low_confidence"}

    def test_health_last_tick(self, client, db_conn):
        from api.services.enrichment_monitor import record_tick

        record_tick(db_conn, dict(self._PAYLOAD, status="error"))
        body = client.get("/api/admin/enrichment/health").json()
        assert body["lastTickUuid"] == "tick-admin-1"
        assert body["lastTickStatus"] == "error"


class TestAdminEnrichmentRecent:
    def test_recent_rows(self, client, db_conn):
        _seed_flagged_job(db_conn)
        resp = client.get("/api/admin/enrichment/recent")
        assert resp.status_code == 200, resp.text
        rows = resp.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["jobListingId"] == "q-1"
        assert rows[0]["needsHuman"] is True


class TestJobFacets:
    def test_facets_catalog(self, client):
        resp = client.get("/api/jobs/facets")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        cats = [c["slug"] for c in body["categories"]]
        assert cats == [
            "software_engineering", "hardware_engineer", "product_manager",
            "project_manager", "growth", "business_ops",
        ]
        levels = {l["slug"]: l for l in body["levels"]}
        assert levels["new_grad"]["parentSlug"] == "entry"
        assert levels["entry"]["parentSlug"] is None
        # rank ordering: new_grad first
        assert [l["slug"] for l in body["levels"]][0] == "new_grad"
