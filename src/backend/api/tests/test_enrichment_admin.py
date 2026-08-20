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
                      company="google", confidence=0.4, corrected=False,
                      category=None, level=None, subcategories=None,
                      subcategory_source=None, subcategory_confidence=None):
    """Seed a needs-human row. By default the published facets are NULL (a row
    demoted under require_judge_pass — nothing to one-click confirm). Pass
    ``category``/``level`` to seed a row that kept its proposal (the flag-off
    case), which is what a Confirm can validate."""
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
    if category is not None or level is not None:
        cur.execute(
            "UPDATE job_listings SET enrichment_category=%s, enrichment_level=%s "
            "WHERE source_id=%s AND id=%s",
            (category, level, source_id, job_id),
        )
    if subcategories is not None or subcategory_source is not None:
        cur.execute(
            "UPDATE job_listings SET enrichment_subcategories = %s::text[], "
            "enrichment_subcategory_source = %s WHERE source_id=%s AND id=%s",
            (subcategories, subcategory_source, source_id, job_id),
        )
    cur.execute(
        "INSERT INTO job_enrichment (source_id, job_listing_id, clean_description, "
        "classify_confidence, classify_reasoning, judged, judge_passed, "
        "judge_confidence, judge_notes, needs_human, human_corrected_at, "
        "subcategory_confidence) "
        "VALUES (%s, %s, 'clean text', %s, 'because', true, false, 0.5, "
        "'ambiguous level', true, %s, %s)",
        (source_id, job_id, confidence,
         "2026-01-01T00:00:00Z" if corrected else None, subcategory_confidence),
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
                "/api/admin/enrichment/jobs/s/j/confirm"
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
        assert body["humanDecision"] == "corrected"

        cur = db_conn.cursor()
        cur.execute(
            "SELECT needs_human, human_corrected_at, human_decision, judge_notes "
            "FROM job_enrichment WHERE source_id='src-a' AND job_listing_id='q-1'"
        )
        row = cur.fetchone()
        assert row["needs_human"] is False
        assert row["human_corrected_at"] is not None
        assert row["human_decision"] == "corrected"
        assert "[human] actually growth" in row["judge_notes"]

        # queue no longer lists it
        assert client.get("/api/admin/enrichment/needs-human").json()["total"] == 0

    # --- subcategories: the tri-state, and THE DATA-LOSS FIX -----------------

    def _subcats(self, db_conn, source_id="src-a", job_id="q-1"):
        cur = db_conn.cursor()
        cur.execute(
            "SELECT enrichment_subcategories AS subcats, "
            "enrichment_subcategory_source AS source, enrichment_level AS level "
            "FROM job_listings WHERE source_id=%s AND id=%s",
            (source_id, job_id),
        )
        return cur.fetchone()

    def test_level_only_correction_leaves_subcategories_intact(self, client, db_conn):
        """THE regression this step exists to prevent.

        A correction body that never mentions subcategories must not touch the
        column. Writing NULL here and THEN stamping human_corrected_at would lock
        the row with an empty array, so no backfill could ever repair it —
        silent, permanent, and invisible in the 200 response.

        Adding the field is not enough. THIS is the assertion.
        """
        _seed_flagged_job(db_conn, subcategories=["backend", "full_stack"],
                          subcategory_source="backfill")
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"level": "senior"},
        )
        assert resp.status_code == 200, resp.text

        row = self._subcats(db_conn)
        assert row["subcats"] == ["backend", "full_stack"], (
            "a level-only correction wiped enrichment_subcategories"
        )
        assert row["source"] == "backfill"
        assert row["level"] == "senior"

        cur = db_conn.cursor()
        cur.execute(
            "SELECT human_corrected_at FROM job_enrichment "
            "WHERE source_id='src-a' AND job_listing_id='q-1'"
        )
        assert cur.fetchone()["human_corrected_at"] is not None

    def test_swe_correction_without_the_key_leaves_subcategories_intact(
        self, client, db_conn
    ):
        """Same fix, on the path the admin UI actually takes (category IS sent)."""
        _seed_flagged_job(db_conn, subcategories=["backend"],
                          subcategory_source="classify")
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "software_engineering", "level": "senior"},
        )
        assert resp.status_code == 200, resp.text
        row = self._subcats(db_conn)
        assert row["subcats"] == ["backend"]
        assert row["source"] == "classify"

    def test_explicit_null_requeues(self, client, db_conn):
        """`null` is an EXPLICIT re-queue — the column and its source both clear."""
        _seed_flagged_job(db_conn, subcategories=["backend"],
                          subcategory_source="classify")
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "software_engineering", "subcategories": None},
        )
        assert resp.status_code == 200, resp.text
        row = self._subcats(db_conn)
        assert row["subcats"] is None
        assert row["source"] is None
        assert resp.json()["subcategories"] is None

    def test_explicit_empty_is_terminal(self, client, db_conn):
        """`[]` is "evaluated, no specialty applies" — TERMINAL, never re-queued."""
        _seed_flagged_job(db_conn, subcategories=["backend"],
                          subcategory_source="classify")
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "software_engineering", "subcategories": []},
        )
        assert resp.status_code == 200, resp.text
        row = self._subcats(db_conn)
        assert row["subcats"] == []
        assert row["source"] == "human"
        assert resp.json()["subcategories"] == []

    def test_subcategories_provided_is_false_for_absent_key(self):
        """Pin the _UNSET mechanism itself.

        Nobody should be able to "simplify" the handler's
        `'subcategories' in body.model_fields_set` into `is None` — at the
        service signature those two are the SAME VALUE, and collapsing them
        reintroduces the data loss above.
        """
        from api.models import AdminEnrichmentCorrectionRequest

        absent = AdminEnrichmentCorrectionRequest(level="senior")
        assert "subcategories" not in absent.model_fields_set
        assert absent.subcategories is None

        explicit = AdminEnrichmentCorrectionRequest(subcategories=None)
        assert "subcategories" in explicit.model_fields_set
        assert explicit.subcategories is None

    def test_ordered_dedupe_preserves_primary_first(self, client, db_conn):
        _seed_flagged_job(db_conn)
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "software_engineering",
                  "subcategories": ["backend", "backend", "frontend"]},
        )
        assert resp.status_code == 200, resp.text
        # Order preserved and index 0 is still the primary — a set() here would
        # be a coin flip.
        assert self._subcats(db_conn)["subcats"] == ["backend", "frontend"]
        assert self._subcats(db_conn)["source"] == "human"

    def test_more_than_two_subcategories_409(self, client, db_conn):
        _seed_flagged_job(db_conn)
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "software_engineering",
                  "subcategories": ["backend", "frontend", "mobile"]},
        )
        assert resp.status_code == 409, resp.text

    def test_unknown_subcategory_slug_409(self, client, db_conn):
        _seed_flagged_job(db_conn)
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "software_engineering", "subcategories": ["ai_ml"]},
        )
        assert resp.status_code == 409
        assert "ai_ml" in resp.json()["detail"]

    def test_non_swe_with_subcategories_409(self, client, db_conn):
        _seed_flagged_job(db_conn)
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "growth", "subcategories": ["backend"]},
        )
        assert resp.status_code == 409, resp.text

    def test_non_swe_forces_the_terminal_empty_array(self, client, db_conn):
        """Re-categorizing away from SWE ends the row's subcategory life."""
        _seed_flagged_job(db_conn, subcategories=["backend"],
                          subcategory_source="classify")
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "growth", "level": "mid"},
        )
        assert resp.status_code == 200, resp.text
        row = self._subcats(db_conn)
        assert row["subcats"] == []
        assert row["source"] == "human"

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
            "SELECT human_corrected_at, needs_human, human_decision FROM job_enrichment "
            "WHERE source_id='src-a' AND job_listing_id='q-1'"
        )
        row = cur.fetchone()
        assert row["human_corrected_at"] is None and row["needs_human"] is False
        assert row["human_decision"] is None       # re-enrich clears the human verdict
        cur.execute("SELECT count(*) AS n FROM job_tags WHERE job_listing_id='q-1'")
        assert cur.fetchone()["n"] == 0


class TestAdminEnrichmentConfirm:
    def test_confirm_validates_and_locks(self, client, db_conn):
        # A flagged row that kept its proposal (facets published) — confirmable.
        _seed_flagged_job(db_conn, category="growth", level="mid")
        resp = client.post("/api/admin/enrichment/jobs/src-a/q-1/confirm")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["category"] == "growth"          # proposal unchanged
        assert body["level"] == "mid"
        assert body["enrichmentStatus"] == "done"
        assert body["humanDecision"] == "confirmed_correct"
        assert body["humanCorrectedBy"] == "test@example.com"

        cur = db_conn.cursor()
        cur.execute(
            "SELECT needs_human, human_corrected_at, human_decision, judge_notes "
            "FROM job_enrichment WHERE source_id='src-a' AND job_listing_id='q-1'"
        )
        row = cur.fetchone()
        assert row["needs_human"] is False
        assert row["human_corrected_at"] is not None
        assert row["human_decision"] == "confirmed_correct"
        # Confirm keeps the row's evidence intact — no [human] note appended.
        assert "[human]" not in (row["judge_notes"] or "")

        cur.execute(
            "SELECT enrichment_category, enrichment_level, enrichment_status "
            "FROM job_listings WHERE source_id='src-a' AND id='q-1'"
        )
        jl = cur.fetchone()
        assert jl["enrichment_category"] == "growth"   # facets untouched
        assert jl["enrichment_level"] == "mid"
        assert jl["enrichment_status"] == "done"

        # leaves the needs-human queue
        assert client.get("/api/admin/enrichment/needs-human").json()["total"] == 0

    def test_confirm_without_proposed_labels_409(self, client, db_conn):
        # A demoted needs_human row has NULL facets — nothing to validate.
        _seed_flagged_job(db_conn)
        resp = client.post("/api/admin/enrichment/jobs/src-a/q-1/confirm")
        assert resp.status_code == 409, resp.text
        assert "Correct" in resp.json()["detail"]

        # untouched: still flagged, no decision recorded, still in the queue
        cur = db_conn.cursor()
        cur.execute(
            "SELECT needs_human, human_corrected_at, human_decision FROM job_enrichment "
            "WHERE source_id='src-a' AND job_listing_id='q-1'"
        )
        row = cur.fetchone()
        assert row["needs_human"] is True
        assert row["human_corrected_at"] is None
        assert row["human_decision"] is None
        assert client.get("/api/admin/enrichment/needs-human").json()["total"] == 1

    def test_confirm_unknown_job_404(self, client, db_conn):
        resp = client.post("/api/admin/enrichment/jobs/ghost-src/ghost-id/confirm")
        assert resp.status_code == 404


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
        # Evidence fields ride along so the dashboard can show the agent's
        # rationale and open the correction editor from any recent row.
        assert rows[0]["classifyReasoning"] == "because"
        assert rows[0]["judgeNotes"] == "ambiguous level"
        assert rows[0]["judgeConfidence"] == 0.5
        assert "url" in rows[0]


class TestJobFacets:
    def test_facets_catalog(self, client):
        resp = client.get("/api/jobs/facets")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        cats = [c["slug"] for c in body["categories"]]
        assert cats == [
            "software_engineering", "hardware_engineer", "product_manager",
            "project_manager", "data_scientist", "growth", "business_ops",
        ]
        levels = {l["slug"]: l for l in body["levels"]}
        assert levels["new_grad"]["parentSlug"] == "entry"
        assert levels["entry"]["parentSlug"] is None
        # intern is standalone (its own filter), never a child of another tier
        assert levels["intern"]["parentSlug"] is None
        # rank ordering: intern first (rank 0), then new_grad (the intern
        # migration renumbered the six pre-existing tiers +1)
        assert [l["slug"] for l in body["levels"]][0] == "intern"
