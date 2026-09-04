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

    def test_subcategory_coverage_counters(self, client, db_conn):
        """Coverage counts EVALUATED rows, and the denominator is OPEN SWE only.

        `'{}'` is a legitimate terminal answer, so it counts toward coverage.
        Defining coverage as non-empty instead asymptotes near 91% and can never
        cross the 90% reveal threshold.
        """
        _seed_flagged_job(db_conn, job_id="c-lab", category="software_engineering",
                          subcategories=["backend"])
        _seed_flagged_job(db_conn, job_id="c-empty", category="software_engineering",
                          subcategories=[])
        _seed_flagged_job(db_conn, job_id="c-null1", category="software_engineering")
        _seed_flagged_job(db_conn, job_id="c-null2", category="software_engineering")
        # Not SWE -> outside the denominator even though it carries an array.
        _seed_flagged_job(db_conn, job_id="c-ds", category="data_scientist",
                          subcategories=["backend"])
        # CLOSED -> outside the denominator.
        _seed_flagged_job(db_conn, job_id="c-closed", status="CLOSED",
                          category="software_engineering", subcategories=["backend"])

        body = client.get("/api/admin/enrichment/health").json()
        assert body["sweOpenTotal"] == 4
        assert body["sweSubcategorized"] == 2       # {backend} + '{}'
        assert body["sweSubcategoryLabelled"] == 1  # only {backend}

    def test_unknown_slug_counter_stays_zero_for_LEGITIMATE_slugs_in_phase_1(
        self, client, db_conn
    ):
        """⚠ THE PHASE-1 WINDOW IS THE WHOLE POINT.

        `job_subcategories` ships EMPTY (SCHEMA-7 seeds it later), so comparing
        persisted slugs against the *table* makes every legitimate slug
        "unknown" — the counter reads non-zero from the moment PR-C/D start
        labelling, AdminEnrichmentPage renders a permanent red warning, and the
        only compensating control for the array having no FK gets ignored
        exactly when it matters. The reference set is the TAXONOMY; the
        dimension is only its persisted form.

        The old version of this test exercised `not_a_real_slug` only, so it
        passed against that broken shape.
        """
        _seed_flagged_job(db_conn, job_id="c-be", category="software_engineering",
                          subcategories=["backend"])
        _seed_flagged_job(db_conn, job_id="c-fe", category="software_engineering",
                          subcategories=["frontend"])
        _seed_flagged_job(db_conn, job_id="c-mob", category="software_engineering",
                          subcategories=["mobile"])
        body = client.get("/api/admin/enrichment/health").json()
        assert body["subcategoryUnknownSlugs"] == 0

    def test_unknown_slug_counter_still_catches_a_bogus_slug_in_phase_1(
        self, client, db_conn
    ):
        """The control must not be inert while the dimension is empty: falling
        back to the code arbiter still flags a producer writing off-taxonomy
        slugs, which is the only thing this counter exists for."""

    def test_unknown_slug_counter_against_the_SEEDED_dimension(
        self, client, db_conn
    ):
        """The counter's contract is 'permanently 0 once seeded'.

        Phase 2 seeds the dimension (SCHEMA-7) and the fixture now mirrors that,
        so this reads the counter the way prod does: a real slug does not count,
        a slug absent from `job_subcategories` does. Before the seed every
        persisted slug was 'unknown' by definition, which is why the assertion
        was only worth making once the fixture and prod agreed.
        """
        body = client.get("/api/admin/enrichment/health").json()
        assert body["subcategoryUnknownSlugs"] == 0

        # A REAL slug stays uncounted — that is the "permanently 0" half.
        _seed_flagged_job(db_conn, job_id="c-good", category="software_engineering",
                          subcategories=["backend"])
        body = client.get("/api/admin/enrichment/health").json()
        assert body["subcategoryUnknownSlugs"] == 0

        _seed_flagged_job(db_conn, job_id="c-bad", category="software_engineering",
                          subcategories=["not_a_real_slug"])
        _seed_flagged_job(db_conn, job_id="c-ok", category="software_engineering",
                          subcategories=["backend"])
        body = client.get("/api/admin/enrichment/health").json()
        assert body["subcategoryUnknownSlugs"] == 1

    def test_a_seeded_dimension_takes_over_from_the_code_arbiter(
        self, client, db_conn
    ):
        """Once SCHEMA-7 seeds the table, the DIMENSION is authoritative again —
        the fallback is scoped to the empty-table window and nothing else. Seed
        a PARTIAL dimension: slugs the code knows but the table does not must
        now count, or the post-Phase-1 semantics silently never come back."""
        _seed_flagged_job(db_conn, job_id="c-be", category="software_engineering",
                          subcategories=["backend"])
        _seed_flagged_job(db_conn, job_id="c-fe", category="software_engineering",
                          subcategories=["frontend"])
        # PARTIAL means partial. Once SCHEMA-7 (PR-F) landed, the conftest
        # fixture seeds all fifteen slugs to mirror prod — so INSERTing 'backend'
        # no longer creates a gap and this test silently asserted nothing. Remove
        # 'frontend' instead, which produces the gap under either fixture.
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO job_subcategories (slug, label, parent_slug, sort_order) "
            "VALUES ('backend','Backend','software_engineering',1) "
            "ON CONFLICT (slug) DO NOTHING"
        )
        cur.execute("SELECT label, sort_order FROM job_subcategories WHERE slug='frontend'")
        restore = cur.fetchone()
        cur.execute("DELETE FROM job_subcategories WHERE slug='frontend'")
        db_conn.commit()
        try:
            body = client.get("/api/admin/enrichment/health").json()
            assert body["subcategoryUnknownSlugs"] == 1  # 'frontend' is not seeded
        finally:
            if restore is not None:
                cur.execute(
                    "INSERT INTO job_subcategories (slug, label, parent_slug, sort_order) "
                    "VALUES ('frontend', %s, 'software_engineering', %s) "
                    "ON CONFLICT (slug) DO NOTHING",
                    (restore["label"], restore["sort_order"]),
                )
            cur.execute("DELETE FROM job_subcategories WHERE slug='backend'")
            db_conn.commit()

    def test_health_still_200s_when_the_dimension_table_is_absent(
        self, client, db_conn
    ):
        """THE GUARD IS LOAD-BEARING: without it a pre-migration process raises
        UndefinedColumn and the router 500s the ENTIRE endpoint — blanking the
        verdict banner, not just the new tile."""
        cur = db_conn.cursor()
        cur.execute("DROP TABLE IF EXISTS job_subcategories")
        db_conn.commit()
        try:
            resp = client.get("/api/admin/enrichment/health")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["sweOpenTotal"] == 0
            assert body["sweSubcategorized"] == 0
            assert body["subcategoryUnknownSlugs"] == 0
        finally:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS job_subcategories ("
                "  slug TEXT PRIMARY KEY,"
                "  label TEXT NOT NULL,"
                "  parent_slug TEXT NOT NULL REFERENCES job_categories(slug),"
                "  sort_order INTEGER NOT NULL DEFAULT 0)"
            )
            db_conn.commit()


class TestAdminSubcategoryReset:
    """POST /api/admin/enrichment/subcategories/reset — the scoped rollback."""

    RESET_URL = "/api/admin/enrichment/subcategories/reset"

    def _seed_one_per_source(self, db_conn):
        for i, src in enumerate(("backfill", "classify", "judge", "human", "rule")):
            _seed_flagged_job(db_conn, job_id=f"r-{src}", category="software_engineering",
                              subcategories=["backend"], subcategory_source=src)
        # A second backfill row so `matched` is not trivially 1.
        _seed_flagged_job(db_conn, job_id="r-backfill-2",
                          category="software_engineering",
                          subcategories=["frontend"], subcategory_source="backfill")

    def _count(self, db_conn, source):
        cur = db_conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS n FROM job_listings "
            "WHERE enrichment_subcategory_source = %s",
            (source,),
        )
        return cur.fetchone()["n"]

    def test_dry_run_is_the_default_and_changes_nothing(self, client, db_conn):
        """The destructive form needs an explicit false. Omitting the key must
        NOT run it for real."""
        self._seed_one_per_source(db_conn)
        resp = client.post(self.RESET_URL, json={"source": "backfill"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["matched"] == 2
        assert body["applied"] == 0
        assert self._count(db_conn, "backfill") == 2

    def test_apply_requires_an_explicit_false(self, client, db_conn):
        self._seed_one_per_source(db_conn)
        resp = client.post(self.RESET_URL, json={"source": "backfill", "dryRun": False})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"source": "backfill", "matched": 2, "applied": 2}
        assert self._count(db_conn, "backfill") == 0

        cur = db_conn.cursor()
        cur.execute(
            "SELECT enrichment_subcategories AS s FROM job_listings "
            "WHERE source_id='src-a' AND id='r-backfill'"
        )
        # NULL, not '{}' — a reset row must RE-ENTER the backfill queue.
        assert cur.fetchone()["s"] is None

    def test_human_rows_are_never_matched_implicitly(self, client, db_conn):
        """An unscoped variant would destroy the only ground truth the eval gate
        has. Every other source is reachable; 'human' only when named."""
        self._seed_one_per_source(db_conn)
        for source in ("backfill", "classify", "judge", "rule"):
            client.post(self.RESET_URL, json={"source": source, "dryRun": False})
        assert self._count(db_conn, "human") == 1

    def test_human_is_reachable_when_passed_explicitly(self, client, db_conn):
        self._seed_one_per_source(db_conn)
        resp = client.post(self.RESET_URL, json={"source": "human", "dryRun": False})
        assert resp.json()["applied"] == 1
        assert self._count(db_conn, "human") == 0

    def _confidence(self, db_conn, job_id, source_id="src-a"):
        cur = db_conn.cursor()
        cur.execute(
            "SELECT subcategory_confidence AS c FROM job_enrichment "
            "WHERE source_id=%s AND job_listing_id=%s",
            (source_id, job_id),
        )
        return cur.fetchone()["c"]

    def test_apply_also_clears_the_audit_confidence(self, client, db_conn):
        """The array and the confidence describe the SAME decision.

        Withdrawing the label while leaving its score behind strands a
        confidence beside a NULL array — the disagreement §1.2 forbids, and one
        the NeedsHuman/Recent admin tables actually render.
        """
        _seed_flagged_job(db_conn, job_id="rc-hit", category="software_engineering",
                          subcategories=["backend"], subcategory_source="backfill",
                          subcategory_confidence=0.91)
        # An unmatched source must keep BOTH halves — the reset stays scoped.
        _seed_flagged_job(db_conn, job_id="rc-miss", category="software_engineering",
                          subcategories=["frontend"], subcategory_source="human",
                          subcategory_confidence=0.42)

        resp = client.post(self.RESET_URL, json={"source": "backfill", "dryRun": False})
        assert resp.status_code == 200, resp.text
        assert self._confidence(db_conn, "rc-hit") is None
        assert self._confidence(db_conn, "rc-miss") == 0.42

    def test_a_dry_run_does_not_clear_the_confidence_either(self, client, db_conn):
        """The audit UPDATE runs inside the same `if not dry_run` — a preview
        that silently wiped confidences would be the worst kind of surprise."""
        _seed_flagged_job(db_conn, job_id="rc-hit", category="software_engineering",
                          subcategories=["backend"], subcategory_source="backfill",
                          subcategory_confidence=0.91)
        resp = client.post(self.RESET_URL, json={"source": "backfill"})
        assert resp.status_code == 200, resp.text
        assert self._confidence(db_conn, "rc-hit") == 0.91

    def test_invalid_source_400s(self, client, db_conn):
        resp = client.post(self.RESET_URL, json={"source": "backfill_failed"})
        assert resp.status_code == 400
        assert "backfill_failed" in resp.json()["detail"]

    def test_unknown_key_422s(self, client, db_conn):
        resp = client.post(
            self.RESET_URL, json={"source": "backfill", "dryrun": False}
        )
        assert resp.status_code == 422


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

    def test_sort_by_classify_confidence_puts_unscored_rows_LAST_both_ways(
        self, client, db_conn
    ):
        """NULLS LAST IN BOTH DIRECTIONS IS THE POINT.

        Postgres defaults to NULLS FIRST on DESC, so a descending confidence
        sort would open with a wall of unscored rows — defeating the only query
        an auditor actually runs.
        """
        for job_id, conf in (("s-hi", 0.9), ("s-lo", 0.1), ("s-mid", 0.5),
                             ("s-null", None)):
            _seed_flagged_job(db_conn, job_id=job_id, confidence=conf)

        asc = client.get(
            "/api/admin/enrichment/needs-human",
            params={"sort": "classify_confidence", "sortDir": "asc"},
        ).json()["rows"]
        assert [r["classifyConfidence"] for r in asc] == [0.1, 0.5, 0.9, None]

        desc = client.get(
            "/api/admin/enrichment/needs-human",
            params={"sort": "classify_confidence", "sortDir": "desc"},
        ).json()["rows"]
        assert [r["classifyConfidence"] for r in desc] == [0.9, 0.5, 0.1, None]

    def test_sort_by_subcategory_confidence(self, client, db_conn):
        _seed_flagged_job(db_conn, job_id="sc-hi", subcategory_confidence=0.8)
        _seed_flagged_job(db_conn, job_id="sc-lo", subcategory_confidence=0.2)
        _seed_flagged_job(db_conn, job_id="sc-null")

        rows = client.get(
            "/api/admin/enrichment/needs-human",
            params={"sort": "subcategory_confidence", "sortDir": "asc"},
        ).json()["rows"]
        assert [r["subcategoryConfidence"] for r in rows] == [0.2, 0.8, None]

    def test_paging_over_ties_is_stable(self, client, db_conn):
        """Without the composite-PK tiebreak, OFFSET paging over equal sort keys
        duplicates some rows and hides others. Confidences tie constantly."""
        for i in range(6):
            _seed_flagged_job(db_conn, job_id=f"tie-{i}", confidence=0.5)

        seen = []
        for offset in (0, 2, 4):
            page = client.get(
                "/api/admin/enrichment/needs-human",
                params={"sort": "classify_confidence", "sortDir": "desc",
                        "limit": 2, "offset": offset},
            ).json()["rows"]
            seen.extend(r["jobListingId"] for r in page)
        assert sorted(seen) == [f"tie-{i}" for i in range(6)]
        assert len(set(seen)) == 6

    def test_unknown_sort_key_falls_back_instead_of_erroring(self, client, db_conn):
        _seed_flagged_job(db_conn)
        resp = client.get(
            "/api/admin/enrichment/needs-human", params={"sort": "drop_table"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 1

    def test_subcategory_filter(self, client, db_conn):
        _seed_flagged_job(db_conn, job_id="f-be", subcategories=["backend"],
                          category="software_engineering")
        _seed_flagged_job(db_conn, job_id="f-fe", subcategories=["frontend"],
                          category="software_engineering")
        _seed_flagged_job(db_conn, job_id="f-none", category="software_engineering")

        body = client.get(
            "/api/admin/enrichment/needs-human", params={"subcategory": "backend"}
        ).json()
        assert body["total"] == 1
        assert body["rows"][0]["jobListingId"] == "f-be"
        assert body["rows"][0]["subcategories"] == ["backend"]

    def test_subcategory_state_unlabelled_swe_surfaces_human_locked_rows(
        self, client, db_conn
    ):
        """The lens that finds SWE rows nothing has evaluated — including the
        human-locked ones every other view hides."""
        _seed_flagged_job(db_conn, job_id="u-swe", category="software_engineering")
        _seed_flagged_job(db_conn, job_id="u-locked", category="software_engineering",
                          corrected=True)
        _seed_flagged_job(db_conn, job_id="u-labelled", category="software_engineering",
                          subcategories=["backend"])
        _seed_flagged_job(db_conn, job_id="u-growth", category="growth")

        body = client.get(
            "/api/admin/enrichment/needs-human",
            params={"subcategoryState": "unlabelled_swe", "includeCorrected": "true"},
        ).json()
        ids = {r["jobListingId"] for r in body["rows"]}
        assert ids == {"u-swe", "u-locked"}

        labelled = client.get(
            "/api/admin/enrichment/needs-human",
            params={"subcategoryState": "labelled"},
        ).json()
        assert {r["jobListingId"] for r in labelled["rows"]} == {"u-labelled"}

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

    def _confidence(self, db_conn, source_id="src-a", job_id="q-1"):
        cur = db_conn.cursor()
        cur.execute(
            "SELECT subcategory_confidence AS c FROM job_enrichment "
            "WHERE source_id=%s AND job_listing_id=%s",
            (source_id, job_id),
        )
        return cur.fetchone()["c"]

    def test_an_explicit_requeue_clears_the_stale_model_confidence(
        self, client, db_conn
    ):
        """§1.2: confidence MUST be null when the array is `[]` or null.

        A surviving score describes a producer's guess that no longer exists,
        and `enrichment_monitor`'s NeedsHuman/Recent queries select it straight
        into the admin tables — so the admin sees `subcategories: null` beside
        a confident-looking number.
        """
        _seed_flagged_job(db_conn, subcategories=["backend"],
                          subcategory_source="classify", subcategory_confidence=0.88)
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "software_engineering", "subcategories": None},
        )
        assert resp.status_code == 200, resp.text
        assert self._subcats(db_conn)["subcats"] is None
        assert self._confidence(db_conn) is None

    def test_recategorising_away_from_swe_clears_the_confidence_too(
        self, client, db_conn
    ):
        """The forced `'{}'` path. `[]` is terminal, so the score beside it has
        nothing left to score."""
        _seed_flagged_job(db_conn, subcategories=["backend"],
                          subcategory_source="classify", subcategory_confidence=0.88)
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "growth", "level": "mid"},
        )
        assert resp.status_code == 200, resp.text
        assert self._subcats(db_conn)["subcats"] == []
        assert self._confidence(db_conn) is None

    def test_a_LEVEL_ONLY_correction_leaves_the_confidence_alone(
        self, client, db_conn
    ):
        """The mirror of the UNTOUCHED array rule. If the correction says
        nothing about subcategories, it must say nothing about their score
        either — clearing it would silently degrade the sort the admin queue
        offers on `subcategory_confidence`."""
        _seed_flagged_job(db_conn, subcategories=["backend"],
                          subcategory_source="classify", subcategory_confidence=0.88)
        resp = client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "software_engineering", "level": "senior"},
        )
        assert resp.status_code == 200, resp.text
        assert self._subcats(db_conn)["subcats"] == ["backend"]
        assert self._confidence(db_conn) == 0.88

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

    def test_reenrich_clears_the_WHOLE_subcategory_triple(self, client, db_conn):
        """⚠ THE ESCAPE HATCH HAS TO ACTUALLY OPEN.

        `request_reenrich` promises the row is "fully reopened" with the
        human-correction lock LIFTED. Leaving the subcategory triple behind
        breaks that three ways: (a) a NULL-category row keeps publishing
        subcategory labels to /api/jobs; (b) a surviving `source='human'` makes
        `apply_subcategory_result` refuse the row forever with
        `reason: "human-locked"` — on a row whose lock was just lifted, which
        is the ONLY way to undo a wrongly-written terminal `'{}'`; and (c) a
        stale confidence sits beside a NULL array.

        NULLing the array is also what re-enters the backfill queue: a NULL
        array IS the queue.
        """
        _seed_flagged_job(db_conn, category="software_engineering", level="senior",
                          subcategories=["backend"], subcategory_source="human",
                          subcategory_confidence=0.66)
        client.post(
            "/api/admin/enrichment/jobs/src-a/q-1/correct",
            json={"category": "software_engineering", "subcategories": ["backend"]},
        )
        # Re-score AFTER the correction: the correction legitimately clears the
        # confidence itself, so seeding it earlier would let this test pass
        # against a re-enrich that never touches the column. A backfill run
        # landing on a human-labelled row is exactly how this state arises.
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_enrichment SET subcategory_confidence = 0.66 "
            "WHERE source_id='src-a' AND job_listing_id='q-1'"
        )
        db_conn.commit()

        resp = client.post("/api/admin/enrichment/jobs/src-a/q-1/reenrich")
        assert resp.status_code == 200, resp.text
        # Reported, not merely defaulted-to-null by the response model.
        assert resp.json()["subcategories"] is None

        cur = db_conn.cursor()
        cur.execute(
            "SELECT enrichment_subcategories AS s, enrichment_subcategory_source AS src "
            "FROM job_listings WHERE source_id='src-a' AND id='q-1'"
        )
        row = cur.fetchone()
        assert row["s"] is None, "a re-enriched row still carries subcategory labels"
        assert row["src"] is None, "the human lock survived an explicit re-enrich"
        cur.execute(
            "SELECT subcategory_confidence AS c FROM job_enrichment "
            "WHERE source_id='src-a' AND job_listing_id='q-1'"
        )
        assert cur.fetchone()["c"] is None


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

    def test_confirm_reads_subcategories_BACK_FROM_THE_ROW(self, client, db_conn):
        """A confirmation changes no labels, so it must report the ones the row
        still holds. `AdminEnrichmentCorrectionResponse.subcategories` defaults
        to None, so an omitted SELECT column reported `null` on a row carrying
        real labels — indistinguishable from "never evaluated"."""
        _seed_flagged_job(db_conn, category="software_engineering", level="senior",
                          subcategories=["backend", "full_stack"],
                          subcategory_source="classify")
        resp = client.post("/api/admin/enrichment/jobs/src-a/q-1/confirm")
        assert resp.status_code == 200, resp.text
        assert resp.json()["subcategories"] == ["backend", "full_stack"]

    def test_confirm_reports_null_for_a_never_evaluated_row(self, client, db_conn):
        """The other half: `null` still has to mean null, not `[]`."""
        _seed_flagged_job(db_conn, category="software_engineering", level="senior")
        resp = client.post("/api/admin/enrichment/jobs/src-a/q-1/confirm")
        assert resp.status_code == 200, resp.text
        assert resp.json()["subcategories"] is None

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


class TestPublicSettings:
    """GET /api/jobs/settings — the unauthenticated reveal-flag read."""

    URL = "/api/jobs/settings"

    def test_unauthenticated_get_returns_the_default_on_an_empty_table(self, client):
        resp = client.get(self.URL)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"sweSubcategoriesEnabled": False}

    def test_reflects_a_directly_inserted_row(self, client, db_conn):
        cur = db_conn.cursor()
        cur.execute("TRUNCATE app_settings")
        cur.execute(
            "INSERT INTO app_settings (key, value) VALUES "
            "('swe_subcategories_enabled', 'true'::jsonb)"
        )
        db_conn.commit()
        try:
            assert client.get(self.URL).json() == {"sweSubcategoriesEnabled": True}
        finally:
            cur.execute("TRUNCATE app_settings")
            db_conn.commit()

    def test_a_read_failure_returns_false_NOT_a_500(self, client, db_conn):
        """FAIL CLOSED. This endpoint is unauthenticated and on the critical
        path for every visitor; a 500 mid-deploy would break the page. Hidden is
        the right failure direction for a reveal flag — the alternative is
        revealing a filter that returns nothing."""
        cur = db_conn.cursor()
        cur.execute("DROP TABLE IF EXISTS app_settings")
        db_conn.commit()
        try:
            resp = client.get(self.URL)
            assert resp.status_code == 200, resp.text
            assert resp.json() == {"sweSubcategoriesEnabled": False}
        finally:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS app_settings ("
                "  key TEXT PRIMARY KEY,"
                "  value JSONB NOT NULL,"
                "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
                "  updated_by TEXT)"
            )
            db_conn.commit()

    def test_the_response_names_its_fields_and_leaks_nothing_else(self, client):
        """A hard boundary: the model names one field rather than dumping the
        settings table, so an admin-only setting added later cannot leak by
        being appended to one dict."""
        assert set(client.get(self.URL).json()) == {"sweSubcategoriesEnabled"}


class TestJobFacets:
    def test_facets_catalog(self, client):
        resp = client.get("/api/jobs/facets")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        cats = [c["slug"] for c in body["categories"]]
        # SIX, not seven: `project_manager` was retired by
        # `retire_project_manager_category` — it had been seeded here and listed
        # in CATEGORY_SLUGS while being ABSENT from the enricher's own taxonomy.
        assert cats == [
            "software_engineering", "hardware_engineer", "product_manager",
            "data_scientist", "growth", "business_ops",
        ]
        levels = {l["slug"]: l for l in body["levels"]}
        assert levels["new_grad"]["parentSlug"] == "entry"
        assert levels["entry"]["parentSlug"] is None
        # intern is standalone (its own filter), never a child of another tier
        assert levels["intern"]["parentSlug"] is None
        # rank ordering: intern first (rank 0), then new_grad (the intern
        # migration renumbered the six pre-existing tiers +1)
        assert [l["slug"] for l in body["levels"]][0] == "intern"

    def test_facets_catalog_carries_the_third_dimension(self, client):
        """PHASE 2: `subcategories` is populated, not `[]`.

        The prod equivalent is
        `curl .../api/jobs/facets | jq '[.subcategories|length,(.categories|length)]'`
        returning `[15, 6]`.
        """
        body = client.get("/api/jobs/facets").json()

        assert set(body) >= {"categories", "levels", "subcategories"}
        subs = body["subcategories"]
        assert len(subs) == 15
        assert len(body["categories"]) == 6
        assert "project_manager" not in [c["slug"] for c in body["categories"]]

        # `parentSlug` on THIS dimension is a GROUPING edge — uniformly the one
        # parent category — and must never be fed to the client's LEVEL
        # expansion builder, where the same field name means something else.
        assert [s["parentSlug"] for s in subs] == ["software_engineering"] * 15

        # Ordered by sort_order, contiguous 0..14.
        assert [s["sortOrder"] for s in subs] == list(range(15))
        assert [s["slug"] for s in subs] == sorted(s["slug"] for s in subs)
        assert subs[1]["slug"] == "backend"
        assert subs[1]["label"] == "Backend"
