"""Tests for the external-enrichment pull integration.

Covers three layers of the PR:

* ``api.config.Settings`` — the new enrichment flags + allowlist property.
* ``api.services.enrichment_writer.apply_result`` — the per-row writer that
  lands facets on ``job_listings``, tags in ``job_tags``, the audit payload in
  ``job_enrichment``, and locations via the shared Tier-2 writer.
* ``api.routers.internal_enrichment`` — the ``/pending``, ``/results`` and
  ``/health`` endpoints, driven through a FastAPI ``TestClient``.

The ``db_conn`` fixture (see conftest) materializes the ORM schema then *stamps*
Alembic — it does NOT run the migration's ``upgrade()`` body, so the seeded
``job_categories`` / ``job_levels`` dimension rows are absent. Because
``enrichment_category`` / ``enrichment_level`` are real FKs to those dimensions,
every test that writes a facet must seed the taxonomy first: the autouse
``_enrichment_isolation`` fixture does exactly that (and truncates the
enrichment-side tables, which conftest's ``clean_tables`` does not touch).
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.config import Settings, settings
from api.dependencies import get_db
from api.routers import internal_enrichment
from api.services.enrichment_writer import apply_result

from .conftest import _insert_job, _make_job

# Mirrors the migration's CATEGORY_SEED / LEVEL_SEED. Parents (parent_slug None)
# must be inserted before children for the job_levels self-FK (new_grad -> entry).
_CATEGORY_SEED = [
    ("software_engineering", "Software Engineering", 0),
    ("product_manager", "Product Manager", 1),
    ("data_scientist", "Data Scientist", 2),
    ("data_engineer", "Data Engineer", 3),
    ("business", "Business", 4),
]
_LEVEL_SEED = [
    ("entry", "Entry", 1, None),
    ("mid", "Mid", 2, None),
    ("senior", "Senior", 3, None),
    ("senior_plus", "Staff / Principal", 4, None),
    ("manager", "Manager", 5, None),
    ("new_grad", "New Grad", 0, "entry"),  # child last (self-FK)
]

# Enrichment-side tables that conftest's clean_tables does NOT truncate. Truncate
# them ourselves so writer state never leaks between tests. locations + its alias
# cache are included so the one location test starts from a clean slate.
_ENRICHMENT_TABLES = (
    "job_tags",
    "job_enrichment",
    "job_locations",
    "alias_locations",
    "location_aliases",
    "locations",
    "job_categories",
    "job_levels",
)


@pytest.fixture(autouse=True)
def _enrichment_isolation(db_conn, clean_tables):
    """Truncate the enrichment-side tables and seed the taxonomy dimensions.

    Depends on conftest's ``clean_tables`` (listed as a param) so it runs AFTER
    job_listings has been truncated — that ordering lets us safely truncate the
    FK-target dimension tables without dangling references.
    """
    cur = db_conn.cursor()
    cur.execute(
        "TRUNCATE " + ", ".join(_ENRICHMENT_TABLES) + " CASCADE"
    )
    cur.executemany(
        "INSERT INTO job_categories (slug, label, sort_order) VALUES (%s, %s, %s) "
        "ON CONFLICT (slug) DO NOTHING",
        _CATEGORY_SEED,
    )
    cur.executemany(
        "INSERT INTO job_levels (slug, label, rank, parent_slug) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (slug) DO NOTHING",
        _LEVEL_SEED,
    )
    db_conn.commit()
    yield


@pytest.fixture
def enrichment_client(db_conn):
    """A TestClient mounting only the internal-enrichment router.

    Mirrors conftest's ``test_app``: overrides ``get_db`` to hand back the test
    connection and does NOT install the internal-key middleware (that gate has
    its own dedicated test, and test_jobs_router exercises routers the same way).
    """
    app = FastAPI()
    app.include_router(
        internal_enrichment.router, prefix="/api/internal/enrichment"
    )

    def override_get_db():
        yield db_conn

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _fetch_job_enrichment(db_conn, job_id: str) -> dict | None:
    cur = db_conn.cursor()
    cur.execute("SELECT * FROM job_enrichment WHERE job_listing_id = %s", (job_id,))
    return cur.fetchone()


def _fetch_listing_facets(db_conn, job_id: str) -> dict:
    cur = db_conn.cursor()
    cur.execute(
        "SELECT enrichment_category, enrichment_level, enrichment_status, "
        "enrichment_claimed_at, normalization_status FROM job_listings WHERE id = %s",
        (job_id,),
    )
    return cur.fetchone()


def _fetch_tags(db_conn, job_id: str) -> set[str]:
    cur = db_conn.cursor()
    cur.execute("SELECT tag FROM job_tags WHERE job_listing_id = %s", (job_id,))
    return {r["tag"] for r in cur.fetchall()}


# --------------------------------------------------------------------------- #
# 1. Config                                                                    #
# --------------------------------------------------------------------------- #


class TestConfig:
    def test_enrichment_use_external_defaults_false(self):
        # _env_file=None so a stray local .env can't flip the default.
        assert Settings(_env_file=None).enrichment_use_external is False

    def test_allowlist_parses_csv_trimming_and_dropping_blanks(self):
        s = Settings(_env_file=None, enrichment_company_allowlist="google, apple ,,microsoft")
        assert s.enrichment_company_allowlist_list == ["google", "apple", "microsoft"]

    def test_allowlist_empty_string_is_empty_list(self):
        s = Settings(_env_file=None, enrichment_company_allowlist="")
        assert s.enrichment_company_allowlist_list == []


# --------------------------------------------------------------------------- #
# 2. apply_result (writer)                                                     #
# --------------------------------------------------------------------------- #


class TestApplyResult:
    def test_writes_facets_tags_and_audit_row(self, db_conn):
        _insert_job(db_conn, _make_job({"id": "enr-basic"}))
        result = {
            "job_listing_id": "enr-basic",
            "category": "software_engineering",
            "level": "senior",
            "tags": ["Python", "AWS", "python"],  # dup + mixed case
            "clean_description": "clean text",
            "classify_confidence": 0.91,
            "taxonomy_version": "v1",
            "locations": [],
        }
        apply_result(db_conn, result, require_judge_pass=False)
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "enr-basic")
        assert facets["enrichment_category"] == "software_engineering"
        assert facets["enrichment_level"] == "senior"
        assert facets["enrichment_status"] == "done"
        assert facets["enrichment_claimed_at"] is None

        # Tags are lowercased + deduped.
        assert _fetch_tags(db_conn, "enr-basic") == {"python", "aws"}

        audit = _fetch_job_enrichment(db_conn, "enr-basic")
        assert audit is not None
        assert audit["clean_description"] == "clean text"
        assert audit["taxonomy_version"] == "v1"
        assert audit["needs_human"] is False

    def test_invalid_category_is_nulled_not_raised(self, db_conn):
        _insert_job(db_conn, _make_job({"id": "enr-bad-cat"}))
        result = {
            "job_listing_id": "enr-bad-cat",
            "category": "nonsense",  # not in CATEGORY_SLUGS -> nulled
            "level": "mid",
            "tags": [],
            "locations": [],
        }
        # Must not raise.
        apply_result(db_conn, result, require_judge_pass=False)
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "enr-bad-cat")
        assert facets["enrichment_category"] is None  # dropped
        assert facets["enrichment_level"] == "mid"    # valid, kept
        assert facets["enrichment_status"] == "done"

    def test_reapply_replaces_tags(self, db_conn):
        _insert_job(db_conn, _make_job({"id": "enr-idem"}))
        apply_result(
            db_conn,
            {"job_listing_id": "enr-idem", "category": "business",
             "level": "entry", "tags": ["alpha", "beta"], "locations": []},
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_tags(db_conn, "enr-idem") == {"alpha", "beta"}

        # Re-apply with a different tag set: old tags must be gone (replaced).
        apply_result(
            db_conn,
            {"job_listing_id": "enr-idem", "category": "data_scientist",
             "level": "mid", "tags": ["beta", "gamma"], "locations": []},
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_tags(db_conn, "enr-idem") == {"beta", "gamma"}
        facets = _fetch_listing_facets(db_conn, "enr-idem")
        assert facets["enrichment_category"] == "data_scientist"
        assert facets["enrichment_level"] == "mid"

    def test_needs_human_gate_holds_back_facets(self, db_conn):
        _insert_job(db_conn, _make_job({"id": "enr-human"}))
        result = {
            "job_listing_id": "enr-human",
            "category": "data_scientist",
            "level": "senior",
            "tags": ["ml"],
            "judge": {"judged": True, "needs_human": True, "passed": False},
            "locations": [],
        }
        apply_result(db_conn, result, require_judge_pass=True)
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "enr-human")
        assert facets["enrichment_status"] == "needs_human"
        # Category/level NOT published while flagged for a human.
        assert facets["enrichment_category"] is None
        assert facets["enrichment_level"] is None
        assert _fetch_tags(db_conn, "enr-human") == set()

        # The audit row still records the judge verdict.
        audit = _fetch_job_enrichment(db_conn, "enr-human")
        assert audit["needs_human"] is True
        assert audit["judged"] is True

    def test_needs_human_publishes_when_gate_off(self, db_conn):
        """With require_judge_pass=False, a needs_human flag does NOT gate: the
        facets publish anyway (JVN trusts the laptop's own judge corrections)."""
        _insert_job(db_conn, _make_job({"id": "enr-nogate"}))
        result = {
            "job_listing_id": "enr-nogate",
            "category": "product_manager",
            "level": "mid",
            "tags": ["roadmap"],
            "judge": {"judged": True, "needs_human": True},
            "locations": [],
        }
        apply_result(db_conn, result, require_judge_pass=False)
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "enr-nogate")
        assert facets["enrichment_status"] == "done"
        assert facets["enrichment_category"] == "product_manager"

    def test_locations_path_persists_via_shared_writer(self, db_conn):
        """One case exercises the persist_llm_result path: a valid location dict
        lands job_locations rows and flips normalization_status to 'done'."""
        _insert_job(db_conn, _make_job({"id": "enr-loc"}))
        result = {
            "job_listing_id": "enr-loc",
            "category": "software_engineering",
            "level": "entry",
            "tags": [],
            "raw_location": "Austin, TX",
            "locations": [
                {
                    "canonical_name": "Austin, TX, US",
                    "kind": "city",
                    "city": "Austin",
                    "region": "TX",
                    "country": "US",
                    "confidence": 0.95,
                }
            ],
        }
        apply_result(db_conn, result, require_judge_pass=False)
        db_conn.commit()

        cur = db_conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS n FROM job_locations WHERE job_listing_id = %s",
            ("enr-loc",),
        )
        assert cur.fetchone()["n"] == 1
        facets = _fetch_listing_facets(db_conn, "enr-loc")
        assert facets["normalization_status"] == "done"
        assert facets["enrichment_status"] == "done"


# --------------------------------------------------------------------------- #
# 3. Router: /pending, /results, /health                                       #
# --------------------------------------------------------------------------- #


class TestPending:
    def test_returns_empty_and_disabled_when_flag_off(self, enrichment_client, db_conn):
        # Default: enrichment_use_external is False.
        _insert_job(db_conn, _make_job({
            "id": "p-off", "status": "OPEN",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        assert resp.json() == {"jobs": [], "enabled": False}
        # The row was NOT claimed.
        assert _fetch_listing_facets(db_conn, "p-off")["enrichment_status"] is None

    def test_claims_open_null_rows_when_flag_on(
        self, enrichment_client, db_conn, monkeypatch
    ):
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "p-claim", "status": "OPEN", "details_scraped": True,
            "details": json.dumps({
                "description_html": "<h1>Role</h1>",
                "department": "Engineering",
                "experience_level": "Senior",
            }),
        }))
        # A CLOSED row must be ignored by the claim query.
        _insert_job(db_conn, _make_job({
            "id": "p-closed", "status": "CLOSED",
            "details": json.dumps({"description_html": "<p>nope</p>"}),
        }))

        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        ids = {j["job_id"] for j in body["jobs"]}
        assert ids == {"p-claim"}

        job = body["jobs"][0]
        assert job["description_html"] == "<h1>Role</h1>"
        # details is the trimmed jsonb projection (department + experience_level).
        assert job["details"]["department"] == "Engineering"

        # The claimed row is now marked 'claimed' with a claim timestamp.
        facets = _fetch_listing_facets(db_conn, "p-claim")
        assert facets["enrichment_status"] == "claimed"
        assert facets["enrichment_claimed_at"] is not None
        # CLOSED row untouched.
        assert _fetch_listing_facets(db_conn, "p-closed")["enrichment_status"] is None

    def test_respects_limit(self, enrichment_client, db_conn, monkeypatch):
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        for i in range(3):
            _insert_job(db_conn, _make_job({
                "id": f"p-lim-{i}", "status": "OPEN",
                "details": json.dumps({"description_html": "<p>x</p>"}),
            }))
        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 2}
        )
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 2


class TestResults:
    def test_writes_good_rows_and_reports_bad_row(
        self, enrichment_client, db_conn
    ):
        _insert_job(db_conn, _make_job({"id": "r-good"}))
        payload = {
            "results": [
                {
                    "job_listing_id": "r-good",
                    "category": "business",
                    "level": "mid",
                    "tags": ["ops"],
                    "locations": [],
                },
                # Malformed: raw_location set but the location dict is invalid
                # (kind not in the allowed set) -> CanonicalLocation validation
                # raises inside the row's SAVEPOINT.
                {
                    "job_listing_id": "r-bad",
                    "raw_location": "Nowhere",
                    "locations": [
                        {"canonical_name": "X", "kind": "planet", "confidence": 0.5}
                    ],
                },
            ]
        }
        resp = enrichment_client.post(
            "/api/internal/enrichment/results", json=payload
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["written"] == 1
        assert len(body["failed"]) == 1
        assert body["failed"][0]["job_listing_id"] == "r-bad"
        assert body["failed"][0]["error"]

        # The good row landed despite the bad row in the same batch.
        facets = _fetch_listing_facets(db_conn, "r-good")
        assert facets["enrichment_status"] == "done"
        assert facets["enrichment_category"] == "business"
        # The bad row wrote nothing.
        assert _fetch_job_enrichment(db_conn, "r-bad") is None

    def test_empty_batch_is_noop(self, enrichment_client):
        resp = enrichment_client.post(
            "/api/internal/enrichment/results", json={"results": []}
        )
        assert resp.status_code == 200
        assert resp.json() == {"written": 0, "failed": []}


class TestHealth:
    def test_reports_status_counts(self, enrichment_client, db_conn, monkeypatch):
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({"id": "h-null", "status": "OPEN"}))
        _insert_job(db_conn, _make_job({
            "id": "h-done", "status": "OPEN", "enrichment_status": "done",
        }))
        # A needs_human audit row so the counter is non-zero.
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO job_enrichment (job_listing_id, needs_human) VALUES (%s, true)",
            ("h-done",),
        )
        db_conn.commit()

        resp = enrichment_client.get("/api/internal/enrichment/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled"] is True
        # NULL status COALESCEs to 'unenriched'.
        assert body["open_by_status"] == {"unenriched": 1, "done": 1}
        assert body["needs_human"] == 1
        assert body["claim_ttl_minutes"] == settings.enrichment_claim_ttl_minutes


# --------------------------------------------------------------------------- #
# 4. jobs /api/jobs?category=&level= filter params reach the query             #
# --------------------------------------------------------------------------- #


def _seed_facet_job(db_conn, job_id, category, level):
    _insert_job(db_conn, _make_job({
        "id": job_id, "company": "google", "status": "OPEN",
        "enrichment_category": category, "enrichment_level": level,
    }))


class TestJobsFilterParams:
    def test_category_param_filters(self, client, db_conn):
        _seed_facet_job(db_conn, "f-swe", "software_engineering", "senior")
        _seed_facet_job(db_conn, "f-ds", "data_scientist", "senior")
        resp = client.get("/api/jobs", params={"category": "software_engineering"})
        assert resp.status_code == 200
        ids = {j["id"] for j in resp.json()}
        assert ids == {"f-swe"}
        assert resp.json()[0]["category"] == "software_engineering"

    def test_level_entry_expands_to_new_grad(self, client, db_conn):
        _seed_facet_job(db_conn, "f-entry", "software_engineering", "entry")
        _seed_facet_job(db_conn, "f-ng", "software_engineering", "new_grad")
        _seed_facet_job(db_conn, "f-sr", "software_engineering", "senior")
        resp = client.get("/api/jobs", params={"level": "entry"})
        assert resp.status_code == 200
        ids = {j["id"] for j in resp.json()}
        assert ids == {"f-entry", "f-ng"}  # senior excluded

    def test_level_new_grad_is_exact(self, client, db_conn):
        _seed_facet_job(db_conn, "f-entry2", "software_engineering", "entry")
        _seed_facet_job(db_conn, "f-ng2", "software_engineering", "new_grad")
        resp = client.get("/api/jobs", params={"level": "new_grad"})
        ids = {j["id"] for j in resp.json()}
        assert ids == {"f-ng2"}

    def test_category_and_level_combined(self, client, db_conn):
        _seed_facet_job(db_conn, "f-c1", "software_engineering", "entry")
        _seed_facet_job(db_conn, "f-c2", "business", "entry")
        _seed_facet_job(db_conn, "f-c3", "software_engineering", "senior")
        resp = client.get(
            "/api/jobs", params={"category": "software_engineering", "level": "entry"}
        )
        ids = {j["id"] for j in resp.json()}
        assert ids == {"f-c1"}
