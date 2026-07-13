"""Tests for the external-enrichment pull integration.

Covers three layers of the PR:

* ``api.config.Settings`` — the enrichment flags.
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
    ("hardware_engineer", "Hardware Engineer", 1),
    ("product_manager", "Product Manager", 2),
    ("project_manager", "Project Manager", 3),
    ("data_scientist", "Data Scientist", 4),
    ("growth", "Growth", 5),
    ("business_ops", "Business Ops", 6),
]
# Mirrors the post-migration DB state (0fa33aca5bda seed + the 0b61e444ea25
# intern migration, which adds `intern` at rank 0 and renumbers the rest +1).
_LEVEL_SEED = [
    ("intern", "Intern", 0, None),
    ("entry", "Entry", 2, None),
    ("mid", "Mid", 3, None),
    ("senior", "Senior", 4, None),
    ("senior_plus", "Staff / Principal", 5, None),
    ("manager", "Manager", 6, None),
    ("new_grad", "New Grad", 1, "entry"),  # child last (self-FK)
]

# Enrichment-side tables that conftest's clean_tables does NOT truncate. Truncate
# them ourselves so writer state never leaks between tests. locations + its alias
# cache are included so the one location test starts from a clean slate.
_ENRICHMENT_TABLES = (
    "enrichment_ticks",
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


def _fetch_facets_by_pk(db_conn, source_id: str, job_id: str) -> dict:
    """Facets for one row keyed on the FULL composite PK (source_id, id) — needed
    when two rows share the same `id` under different source_ids (F1)."""
    cur = db_conn.cursor()
    cur.execute(
        "SELECT enrichment_category, enrichment_level, enrichment_status, "
        "enrichment_claimed_at, normalization_status FROM job_listings "
        "WHERE source_id = %s AND id = %s",
        (source_id, job_id),
    )
    return cur.fetchone()


def _count_job_locations(db_conn, job_id: str) -> int:
    cur = db_conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS n FROM job_locations WHERE job_listing_id = %s", (job_id,)
    )
    return cur.fetchone()["n"]


def _fetch_tags(db_conn, job_id: str) -> set[str]:
    cur = db_conn.cursor()
    cur.execute("SELECT tag FROM job_tags WHERE job_listing_id = %s", (job_id,))
    return {r["tag"] for r in cur.fetchall()}


def _fetch_tags_by_pk(db_conn, source_id: str, job_id: str) -> set[str]:
    """Tags for one row keyed on the FULL side-table composite (source_id,
    job_listing_id) — needed when two sources share the same `id` (F8)."""
    cur = db_conn.cursor()
    cur.execute(
        "SELECT tag FROM job_tags WHERE source_id = %s AND job_listing_id = %s",
        (source_id, job_id),
    )
    return {r["tag"] for r in cur.fetchall()}


def _fetch_job_enrichment_by_pk(db_conn, source_id: str, job_id: str) -> dict | None:
    """Audit row keyed on the composite (source_id, job_listing_id) (F8)."""
    cur = db_conn.cursor()
    cur.execute(
        "SELECT * FROM job_enrichment WHERE source_id = %s AND job_listing_id = %s",
        (source_id, job_id),
    )
    return cur.fetchone()


# --------------------------------------------------------------------------- #
# 1. Config                                                                    #
# --------------------------------------------------------------------------- #


class TestConfig:
    def test_enrichment_use_external_defaults_false(self):
        # _env_file=None so a stray local .env can't flip the default.
        assert Settings(_env_file=None).enrichment_use_external is False


# --------------------------------------------------------------------------- #
# 2. apply_result (writer)                                                     #
# --------------------------------------------------------------------------- #


class TestApplyResult:
    def test_writes_facets_tags_and_audit_row(self, db_conn):
        _insert_job(db_conn, _make_job({"id": "enr-basic"}))
        result = {
            "job_listing_id": "enr-basic",
            "source_id": "google_scraper",
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
            "source_id": "google_scraper",
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

    def test_intern_level_is_accepted_not_nulled(self, db_conn):
        """`intern` is a first-class level: it must be in LEVEL_SLUGS AND seeded
        in job_levels (the FK target), so an incoming intern result persists
        instead of being soft-nulled or FK-rejected."""
        _insert_job(db_conn, _make_job({"id": "enr-intern"}))
        result = {
            "job_listing_id": "enr-intern",
            "source_id": "google_scraper",
            "category": "software_engineering",
            "level": "intern",
            "tags": [],
            "locations": [],
        }
        warnings = apply_result(db_conn, result, require_judge_pass=False)
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "enr-intern")
        assert facets["enrichment_level"] == "intern"   # accepted, not nulled
        assert facets["enrichment_status"] == "done"
        assert not any("level" in w for w in warnings)   # no soft-null warning

    def test_reapply_replaces_tags(self, db_conn):
        _insert_job(db_conn, _make_job({"id": "enr-idem"}))
        apply_result(
            db_conn,
            {"job_listing_id": "enr-idem", "source_id": "google_scraper",
             "category": "business_ops", "level": "entry",
             "tags": ["alpha", "beta"], "locations": []},
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_tags(db_conn, "enr-idem") == {"alpha", "beta"}

        # Re-apply with a different tag set: old tags must be gone (replaced).
        apply_result(
            db_conn,
            {"job_listing_id": "enr-idem", "source_id": "google_scraper",
             "category": "hardware_engineer", "level": "mid",
             "tags": ["beta", "gamma"], "locations": []},
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_tags(db_conn, "enr-idem") == {"beta", "gamma"}
        facets = _fetch_listing_facets(db_conn, "enr-idem")
        assert facets["enrichment_category"] == "hardware_engineer"
        assert facets["enrichment_level"] == "mid"

    def test_needs_human_gate_holds_back_facets(self, db_conn):
        _insert_job(db_conn, _make_job({"id": "enr-human"}))
        result = {
            "job_listing_id": "enr-human",
            "source_id": "google_scraper",
            "category": "hardware_engineer",
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
            "source_id": "google_scraper",
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
            "source_id": "google_scraper",
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

    # --- F1: composite-key write --------------------------------------------- #

    def test_updates_only_the_matching_source_id(self, db_conn):
        """Two rows share id='dup' under different source_ids (the PK is the
        composite (source_id, id)). A result for source_id='src-a' must update
        ONLY that row and leave the src-b row completely untouched."""
        _insert_job(db_conn, _make_job({"id": "dup", "source_id": "src-a"}))
        _insert_job(db_conn, _make_job({"id": "dup", "source_id": "src-b"}))

        apply_result(
            db_conn,
            {"job_listing_id": "dup", "source_id": "src-a",
             "category": "business_ops", "level": "mid", "tags": [], "locations": []},
            require_judge_pass=False,
        )
        db_conn.commit()

        a = _fetch_facets_by_pk(db_conn, "src-a", "dup")
        assert a["enrichment_status"] == "done"
        assert a["enrichment_category"] == "business_ops"
        # The other source's row with the SAME id is untouched.
        b = _fetch_facets_by_pk(db_conn, "src-b", "dup")
        assert b["enrichment_status"] is None
        assert b["enrichment_category"] is None

    def test_missing_source_id_raises(self, db_conn):
        """A result without source_id can't be keyed to a row — it must raise so
        the caller's SAVEPOINT rolls it into failed[] (never a guessed write)."""
        _insert_job(db_conn, _make_job({"id": "enr-nosrc"}))
        with pytest.raises(ValueError, match="source_id"):
            apply_result(
                db_conn,
                {"job_listing_id": "enr-nosrc", "category": "business_ops",
                 "level": "mid", "tags": [], "locations": []},
                require_judge_pass=False,
            )
        db_conn.rollback()

    # --- F2: location poison-pill degrades, never nukes labels --------------- #

    def test_bad_location_degrades_labels_persist(self, db_conn, caplog):
        """A malformed locations[] element (kind not in the allowed set) must NOT
        roll back the good category/level/tags: the row stays 'done', the
        location is skipped, and a warning is logged."""
        import logging as _logging

        _insert_job(db_conn, _make_job({"id": "enr-badloc"}))
        result = {
            "job_listing_id": "enr-badloc",
            "source_id": "google_scraper",
            "category": "software_engineering",
            "level": "senior",
            "tags": ["python"],
            "raw_location": "Nowhere",
            "locations": [{"canonical_name": "X", "kind": "planet", "confidence": 0.5}],
        }
        with caplog.at_level(_logging.WARNING, logger="api.services.enrichment_writer"):
            apply_result(db_conn, result, require_judge_pass=False)  # must NOT raise
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "enr-badloc")
        assert facets["enrichment_status"] == "done"          # labels landed
        assert facets["enrichment_category"] == "software_engineering"
        assert facets["normalization_status"] is None         # location skipped
        assert _fetch_tags(db_conn, "enr-badloc") == {"python"}
        assert _count_job_locations(db_conn, "enr-badloc") == 0
        assert any("skipping locations" in r.message for r in caplog.records)

    def test_partial_location_one_of_two_warns(self, db_conn, caplog):
        """raw_location present but locations[] empty (or vice-versa): can't
        persist without both, so skip + warn; the row is still 'done'."""
        import logging as _logging

        _insert_job(db_conn, _make_job({"id": "enr-partial"}))
        result = {
            "job_listing_id": "enr-partial",
            "source_id": "google_scraper",
            "category": "business_ops",
            "level": "mid",
            "tags": [],
            "raw_location": "Austin, TX",   # set, but no locations[]
            "locations": [],
        }
        with caplog.at_level(_logging.WARNING, logger="api.services.enrichment_writer"):
            apply_result(db_conn, result, require_judge_pass=False)
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "enr-partial")
        assert facets["enrichment_status"] == "done"
        assert facets["normalization_status"] is None
        assert _count_job_locations(db_conn, "enr-partial") == 0
        assert any("partial location" in r.message for r in caplog.records)

    # --- F3: needs_human demote nulls stale facets --------------------------- #

    def test_needs_human_demote_nulls_previously_published_facets(self, db_conn):
        """A row first published 'done' (with facets + tags), then re-POSTed as
        needs_human, must NOT keep its stale published facets/tags."""
        _insert_job(db_conn, _make_job({"id": "enr-demote"}))
        # 1. Publish it 'done' with facets + tags.
        apply_result(
            db_conn,
            {"job_listing_id": "enr-demote", "source_id": "google_scraper",
             "category": "hardware_engineer", "level": "senior",
             "tags": ["ml", "python"], "locations": []},
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_listing_facets(db_conn, "enr-demote")["enrichment_category"] == "hardware_engineer"
        assert _fetch_tags(db_conn, "enr-demote") == {"ml", "python"}

        # 2. Re-apply the SAME row flagged needs_human with the gate on.
        apply_result(
            db_conn,
            {"job_listing_id": "enr-demote", "source_id": "google_scraper",
             "category": "hardware_engineer", "level": "senior", "tags": ["ml"],
             "judge": {"judged": True, "needs_human": True}, "locations": []},
            require_judge_pass=True,
        )
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "enr-demote")
        assert facets["enrichment_status"] == "needs_human"
        assert facets["enrichment_category"] is None      # stale facet nulled
        assert facets["enrichment_level"] is None
        assert _fetch_tags(db_conn, "enr-demote") == set()  # stale tags dropped

    # --- F8: side tables keyed by (source_id, job_listing_id[, tag]) --------- #

    def test_side_tables_isolated_by_source_id(self, db_conn):
        """Two rows share id='dup' under src-a/src-b. Each must get its OWN
        job_tags + job_enrichment rows keyed on the composite (source_id,
        job_listing_id) — one source's write must never clobber the other's."""
        _insert_job(db_conn, _make_job({"id": "dup", "source_id": "src-a"}))
        _insert_job(db_conn, _make_job({"id": "dup", "source_id": "src-b"}))

        apply_result(
            db_conn,
            {"job_listing_id": "dup", "source_id": "src-a",
             "category": "business_ops", "level": "mid",
             "tags": ["a-only"], "clean_description": "A desc", "locations": []},
            require_judge_pass=False,
        )
        apply_result(
            db_conn,
            {"job_listing_id": "dup", "source_id": "src-b",
             "category": "hardware_engineer", "level": "senior",
             "tags": ["b-only"], "clean_description": "B desc", "locations": []},
            require_judge_pass=False,
        )
        db_conn.commit()

        # Each source keeps its own tags — no collision, no union.
        assert _fetch_tags_by_pk(db_conn, "src-a", "dup") == {"a-only"}
        assert _fetch_tags_by_pk(db_conn, "src-b", "dup") == {"b-only"}
        # Each source keeps its own audit row.
        assert _fetch_job_enrichment_by_pk(db_conn, "src-a", "dup")["clean_description"] == "A desc"
        assert _fetch_job_enrichment_by_pk(db_conn, "src-b", "dup")["clean_description"] == "B desc"

    def test_demote_one_source_does_not_delete_other_source_tags(self, db_conn):
        """Re-POSTing src-a as needs_human (which DELETEs its tags) must NOT touch
        src-b's tags/enrichment for the same shared id='dup'."""
        _insert_job(db_conn, _make_job({"id": "dup", "source_id": "src-a"}))
        _insert_job(db_conn, _make_job({"id": "dup", "source_id": "src-b"}))
        for src in ("src-a", "src-b"):
            apply_result(
                db_conn,
                {"job_listing_id": "dup", "source_id": src,
                 "category": "business_ops", "level": "mid",
                 "tags": [f"{src}-tag"], "locations": []},
                require_judge_pass=False,
            )
        db_conn.commit()
        assert _fetch_tags_by_pk(db_conn, "src-a", "dup") == {"src-a-tag"}
        assert _fetch_tags_by_pk(db_conn, "src-b", "dup") == {"src-b-tag"}

        # Demote src-a: its tags are DELETEd, facets nulled.
        apply_result(
            db_conn,
            {"job_listing_id": "dup", "source_id": "src-a",
             "category": "business_ops", "level": "mid", "tags": ["src-a-tag"],
             "judge": {"judged": True, "needs_human": True}, "locations": []},
            require_judge_pass=True,
        )
        db_conn.commit()

        assert _fetch_tags_by_pk(db_conn, "src-a", "dup") == set()   # src-a dropped
        assert _fetch_tags_by_pk(db_conn, "src-b", "dup") == {"src-b-tag"}  # UNTOUCHED
        b = _fetch_facets_by_pk(db_conn, "src-b", "dup")
        assert b["enrichment_status"] == "done"       # src-b still published
        assert b["enrichment_category"] == "business_ops"

    # --- F14: writer guards the job_listings UPDATE rowcount ----------------- #

    def test_nonexistent_row_demote_branch_raises_no_orphan(self, db_conn):
        """F14 (needs_human/demote branch): a judge-flagged result for a
        nonexistent (source_id, id) matches 0 job_listings rows, so the demote
        UPDATE's rowcount==0 guard raises. The caller's SAVEPOINT then rolls back
        the already-inserted job_enrichment audit row → no orphan, no false write."""
        with pytest.raises(ValueError, match="nothing updated"):
            apply_result(
                db_conn,
                {"job_listing_id": "ghost-demote", "source_id": "ghost-src2",
                 "category": "business_ops", "level": "mid", "tags": [],
                 "judge": {"judged": True, "needs_human": True}, "locations": []},
                require_judge_pass=True,
            )
        db_conn.rollback()
        assert _fetch_job_enrichment_by_pk(db_conn, "ghost-src2", "ghost-demote") is None


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

    def test_claims_most_recently_first_seen_first(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """The claim prioritizes the jobs we saw most recently (ORDER BY
        first_seen_at DESC). With a backlog deeper than the limit, the newest
        arrivals win."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        first_seen = {
            "f-old": "2025-01-01T00:00:00Z",
            "f-mid": "2025-06-01T00:00:00Z",
            "f-new": "2026-06-01T00:00:00Z",
            "f-newest": "2026-07-01T00:00:00Z",
        }
        for jid, ts in first_seen.items():
            _insert_job(db_conn, _make_job({
                "id": jid, "status": "OPEN", "first_seen_at": ts,
                "details": json.dumps({"description_html": "<p>x</p>"}),
            }))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 2}
        )
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        # The two most recently first-seen are claimed; the two older ones are not.
        assert ids == {"f-newest", "f-new"}
        for stale in ("f-old", "f-mid"):
            assert _fetch_listing_facets(db_conn, stale)["enrichment_status"] is None

    def test_ordering_ignores_posted_on(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """posted_on is an unreliable recency signal (companies repost old
        listings), so it must NOT drive the claim order. A job seen recently but
        with an OLD posted_on (a re-listed role) is claimed BEFORE a job with a
        brand-new posted_on we first saw long ago."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        rows = [
            # Recently first-seen, but ATS reports a 2-year-old posted_on (re-list).
            {"id": "r-freshseen-oldpost", "first_seen_at": "2026-07-11T00:00:00Z",
             "posted_on": "2024-01-01T00:00:00Z"},
            # Brand-new posted_on, but we first saw it long ago.
            {"id": "r-oldseen-freshpost", "first_seen_at": "2025-01-01T00:00:00Z",
             "posted_on": "2026-07-12T00:00:00Z"},
        ]
        for r in rows:
            _insert_job(db_conn, _make_job({
                **r, "status": "OPEN",
                "details": json.dumps({"description_html": "<p>x</p>"}),
            }))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 1}
        )
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        # The recently-seen re-listing wins despite its stale posted_on.
        assert ids == {"r-freshseen-oldpost"}
        assert _fetch_listing_facets(db_conn, "r-oldseen-freshpost")["enrichment_status"] is None

    def test_skips_description_null_rows(self, enrichment_client, db_conn, monkeypatch):
        """F7 / CR-5: a row whose details has no description_html can't be
        classified, so /pending must NOT claim it (mirrors /sample's guard)."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "p-desc", "status": "OPEN",
            "details": json.dumps({"description_html": "<p>real</p>"}),
        }))
        # No description_html key at all (default _make_job details is {}).
        _insert_job(db_conn, _make_job({"id": "p-nodesc", "status": "OPEN"}))

        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert ids == {"p-desc"}
        # The description-less row was never claimed.
        assert _fetch_listing_facets(db_conn, "p-nodesc")["enrichment_status"] is None

    def test_gem_and_google_description_shapes_are_claimable(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """gem_api stores the description under 'content_html' and google_scraper
        under 'about_the_job' — the extended COALESCE must now find both and return
        them as description_html (regression for the ~826 permanently-stuck rows)."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "gem", "status": "OPEN", "source_id": "gem_api",
            "details": json.dumps({"content_html": "<p>gem body</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "goog", "status": "OPEN", "source_id": "google_scraper",
            "details": json.dumps({"about_the_job": "About this Google role"}),
        }))
        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        by_id = {j["job_id"]: j for j in resp.json()["jobs"]}
        assert set(by_id) == {"gem", "goog"}
        assert by_id["gem"]["description_html"] == "<p>gem body</p>"
        assert by_id["goog"]["description_html"] == "About this Google role"

    def test_empty_about_the_job_not_claimable_when_flag_off(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """NULLIF(...,''): an empty about_the_job is not a usable description, so
        the row stays unclaimable while the title-only flag is off (falls through
        to the title-only path only when that flag is on)."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "goog-empty", "status": "OPEN", "source_id": "google_scraper",
            "details": json.dumps({"about_the_job": ""}),
        }))
        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []
        assert _fetch_listing_facets(db_conn, "goog-empty")["enrichment_status"] is None

    def test_pending_echoes_first_seen_at(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """The claim echoes first_seen_at (ISO) so the enricher can order its own
        local classify queue newest-first instead of re-FIFOing by local arrival."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "fs", "status": "OPEN", "first_seen_at": "2026-07-12T18:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        job = resp.json()["jobs"][0]
        assert job["first_seen_at"] is not None
        assert job["first_seen_at"].startswith("2026-07-12T18:00:00")

    def test_claims_description_less_rows_when_titleonly_flag_on(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """With enrichment_claim_without_description ON, a row with no description
        under any key IS claimed (title-only interim path) and its description
        projects to null; the default OFF still skips it (see
        test_skips_description_null_rows)."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        monkeypatch.setattr(settings, "enrichment_claim_without_description", True)
        _insert_job(db_conn, _make_job({
            "id": "wd-nodesc", "status": "OPEN", "source_id": "workday_api",
            "details": json.dumps({"description_html": None, "team": "Risk"}),
        }))
        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        job = next(j for j in resp.json()["jobs"] if j["job_id"] == "wd-nodesc")
        assert job["description_html"] is None  # enricher will classify title-only
        assert _fetch_listing_facets(db_conn, "wd-nodesc")["enrichment_status"] == "claimed"

    def test_stale_claim_is_reclaimed_and_rehanded(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """S3 / CR-6: a claim older than the TTL is reclaimed, then re-handed out
        in the same /pending call (it is OPEN + has a description)."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "p-stale", "status": "OPEN", "enrichment_status": "claimed",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        # Backdate the claim well past the TTL.
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_claimed_at = "
            "now() - make_interval(mins => %s) WHERE id = %s",
            (settings.enrichment_claim_ttl_minutes + 5, "p-stale"),
        )
        db_conn.commit()

        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert "p-stale" in ids
        facets = _fetch_listing_facets(db_conn, "p-stale")
        assert facets["enrichment_status"] == "claimed"       # re-claimed
        assert facets["enrichment_claimed_at"] is not None

    def test_fresh_claim_not_reclaimed(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """A claim within the TTL must NOT be reclaimed or re-handed out."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "p-fresh", "status": "OPEN", "enrichment_status": "claimed",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_claimed_at = now() WHERE id = %s",
            ("p-fresh",),
        )
        db_conn.commit()

        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert "p-fresh" not in ids
        assert _fetch_listing_facets(db_conn, "p-fresh")["enrichment_status"] == "claimed"


class TestResults:
    def test_bad_location_row_still_written_with_warning(
        self, enrichment_client, db_conn
    ):
        """F2 at the route: a row with a malformed locations[] element is NOT a
        failed row — its labels persist, it is 'done', the location is skipped."""
        _insert_job(db_conn, _make_job({"id": "r-good"}))
        _insert_job(db_conn, _make_job({"id": "r-badloc"}))
        payload = {
            "results": [
                {
                    "job_listing_id": "r-good",
                    "source_id": "google_scraper",
                    "category": "business_ops",
                    "level": "mid",
                    "tags": ["ops"],
                    "locations": [],
                },
                # raw_location + an invalid location dict (kind not allowed):
                # CanonicalLocation validation raises INSIDE the location savepoint,
                # so the labels still land and the row is 'done'.
                {
                    "job_listing_id": "r-badloc",
                    "source_id": "google_scraper",
                    "category": "software_engineering",
                    "level": "senior",
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
        assert body["written"] == 2       # BOTH rows written; bad location degraded
        assert body["failed"] == []

        assert _fetch_listing_facets(db_conn, "r-good")["enrichment_status"] == "done"
        badloc = _fetch_listing_facets(db_conn, "r-badloc")
        assert badloc["enrichment_status"] == "done"
        assert badloc["enrichment_category"] == "software_engineering"
        assert badloc["normalization_status"] is None    # location skipped
        assert _count_job_locations(db_conn, "r-badloc") == 0

    def test_null_and_non_dict_items_are_per_row_failures(
        self, enrichment_client, db_conn
    ):
        """F4/F6: a null element, a non-dict element, and a dict missing the
        required source_id must EACH land in failed[] — the batch returns 200,
        not a 422/500 — while a valid item in the same batch still writes."""
        _insert_job(db_conn, _make_job({"id": "r-ok"}))
        payload = {
            "results": [
                None,                                   # null element
                "not-a-dict",                           # wrong type
                {"job_listing_id": "r-nosrc"},          # missing required source_id
                {
                    "job_listing_id": "r-ok",
                    "source_id": "google_scraper",
                    "category": "business_ops",
                    "level": "mid",
                    "tags": [],
                    "locations": [],
                },
            ]
        }
        resp = enrichment_client.post(
            "/api/internal/enrichment/results", json=payload
        )
        assert resp.status_code == 200                  # NOT 422/500 for the batch
        body = resp.json()
        assert body["written"] == 1
        assert len(body["failed"]) == 3
        # The dict-with-missing-source_id still reports its id.
        failed_ids = [f["job_listing_id"] for f in body["failed"]]
        assert "r-nosrc" in failed_ids

        # The one valid item landed despite the three bad siblings.
        assert _fetch_listing_facets(db_conn, "r-ok")["enrichment_status"] == "done"
        # A bad item wrote nothing.
        assert _fetch_job_enrichment(db_conn, "r-nosrc") is None

    def test_needs_human_demote_through_route(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """F3 at the route: a row published 'done', then re-POSTed needs_human
        with the gate on, loses its stale facets + tags."""
        monkeypatch.setattr(settings, "enrichment_require_judge_pass", True)
        _insert_job(db_conn, _make_job({"id": "r-demote"}))

        # Publish (judge not flagged) -> done with facets.
        enrichment_client.post("/api/internal/enrichment/results", json={"results": [{
            "job_listing_id": "r-demote", "source_id": "google_scraper",
            "category": "hardware_engineer", "level": "senior", "tags": ["ml"],
            "locations": [],
        }]})
        assert _fetch_listing_facets(db_conn, "r-demote")["enrichment_category"] == "hardware_engineer"

        # Re-POST flagged needs_human -> facets nulled, tags gone.
        enrichment_client.post("/api/internal/enrichment/results", json={"results": [{
            "job_listing_id": "r-demote", "source_id": "google_scraper",
            "category": "hardware_engineer", "level": "senior", "tags": ["ml"],
            "judge": {"judged": True, "needs_human": True}, "locations": [],
        }]})
        facets = _fetch_listing_facets(db_conn, "r-demote")
        assert facets["enrichment_status"] == "needs_human"
        assert facets["enrichment_category"] is None
        assert _fetch_tags(db_conn, "r-demote") == set()

    def test_require_judge_pass_holds_row_through_route(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """require_judge_pass=True routes a judge-flagged row to needs_human
        instead of publishing it."""
        monkeypatch.setattr(settings, "enrichment_require_judge_pass", True)
        _insert_job(db_conn, _make_job({"id": "r-hold"}))
        enrichment_client.post("/api/internal/enrichment/results", json={"results": [{
            "job_listing_id": "r-hold", "source_id": "google_scraper",
            "category": "business_ops", "level": "mid", "tags": ["x"],
            "judge": {"judged": True, "needs_human": True}, "locations": [],
        }]})
        facets = _fetch_listing_facets(db_conn, "r-hold")
        assert facets["enrichment_status"] == "needs_human"
        assert facets["enrichment_category"] is None
        assert _fetch_tags(db_conn, "r-hold") == set()
        # Audit row still records the verdict.
        assert _fetch_job_enrichment(db_conn, "r-hold")["needs_human"] is True

    def test_empty_batch_is_noop(self, enrichment_client):
        resp = enrichment_client.post(
            "/api/internal/enrichment/results", json={"results": []}
        )
        assert resp.status_code == 200
        assert resp.json() == {"written": 0, "failed": [], "warnings": []}

    # --- F9: empty job_listing_id fails at the boundary, no orphan rows ------ #

    def test_empty_job_listing_id_is_a_failure_no_orphans(
        self, enrichment_client, db_conn
    ):
        """job_listing_id="" (valid source_id) updates ZERO job_listings yet would
        insert orphan side-table rows and count as `written`. min_length=1 must
        fail it at validation → failed[], and the DB must hold NO orphan rows."""
        resp = enrichment_client.post("/api/internal/enrichment/results", json={"results": [
            {
                "job_listing_id": "",
                "source_id": "src-empty",
                "category": "business_ops",
                "level": "mid",
                "tags": ["ghost"],
                "locations": [],
            }
        ]})
        assert resp.status_code == 200            # per-row isolation, NOT a batch 422
        body = resp.json()
        assert body["written"] == 0
        assert len(body["failed"]) == 1
        # No orphan side-table rows were written.
        assert _fetch_job_enrichment_by_pk(db_conn, "src-empty", "") is None
        cur = db_conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM job_tags WHERE source_id = %s", ("src-empty",))
        assert cur.fetchone()["n"] == 0

    # --- F10: type-malformed location degrades, does NOT fail the item ------- #

    def test_type_malformed_location_degrades_row_still_written(
        self, enrichment_client, db_conn
    ):
        """A value-TYPE-malformed location (confidence:"high" — a str where a float
        is required) is carried through item validation (locations is
        list[dict[str, Any]]) and degraded by CanonicalLocation in the enr_loc
        savepoint: the row is still written/'done', labels persist, the location is
        skipped + warned — NOT routed to failed[]."""
        _insert_job(db_conn, _make_job({"id": "r-typeloc"}))
        resp = enrichment_client.post("/api/internal/enrichment/results", json={"results": [
            {
                "job_listing_id": "r-typeloc",
                "source_id": "google_scraper",
                "category": "software_engineering",
                "level": "senior",
                "tags": ["python"],
                "raw_location": "Austin, TX",
                "locations": [
                    {
                        "canonical_name": "Austin, TX, US",
                        "kind": "city",
                        "city": "Austin",
                        "region": "TX",
                        "country": "US",
                        "confidence": "high",   # str, not a float -> degrades
                    }
                ],
            }
        ]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["written"] == 1           # NOT a failed row
        assert body["failed"] == []

        facets = _fetch_listing_facets(db_conn, "r-typeloc")
        assert facets["enrichment_status"] == "done"                 # labels landed
        assert facets["enrichment_category"] == "software_engineering"
        assert facets["normalization_status"] is None                # location skipped
        assert _fetch_tags(db_conn, "r-typeloc") == {"python"}
        assert _count_job_locations(db_conn, "r-typeloc") == 0

    # --- F12: a NON-DICT location element degrades, does NOT fail the item --- #

    def test_non_dict_location_degrades_row_still_written(
        self, enrichment_client, db_conn, caplog
    ):
        """F12 (supersedes Ledger #12): a NON-DICT locations[] element (e.g.
        "Berlin") must be carried through item validation (locations is
        list[Any], NOT list[dict[str, Any]] which would raise Pydantic dict_type
        at model_validate and route the WHOLE item to failed[]) and degraded by
        CanonicalLocation(**loc) in the enr_loc savepoint — the non-dict splat
        raises TypeError there, so the row is still written/'done', labels
        persist, the location is skipped + warned, and it is NOT in failed[]."""
        import logging as _logging

        _insert_job(db_conn, _make_job({"id": "r-nondictloc"}))
        with caplog.at_level(_logging.WARNING, logger="api.services.enrichment_writer"):
            resp = enrichment_client.post(
                "/api/internal/enrichment/results",
                json={"results": [
                    {
                        "job_listing_id": "r-nondictloc",
                        "source_id": "google_scraper",
                        "category": "software_engineering",
                        "level": "senior",
                        "tags": ["python"],
                        "raw_location": "Berlin",
                        "locations": ["Berlin"],   # a bare string, not a dict
                    }
                ]},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["written"] == 1            # NOT a failed row
        assert body["failed"] == []

        facets = _fetch_listing_facets(db_conn, "r-nondictloc")
        assert facets["enrichment_status"] == "done"                 # labels landed
        assert facets["enrichment_category"] == "software_engineering"
        assert facets["normalization_status"] is None                # location skipped
        assert _fetch_tags(db_conn, "r-nondictloc") == {"python"}
        assert _count_job_locations(db_conn, "r-nondictloc") == 0
        assert any("skipping locations" in r.message for r in caplog.records)

    # --- F13: whitespace-only ids are stripped -> min_length fail -> failed[] - #

    def test_whitespace_only_ids_fail_no_orphans(self, enrichment_client, db_conn):
        """F13: a whitespace-only id ("   ") is stripped to "" (strip_whitespace=
        True) → min_length violation → per-row failed[], not a false-success
        orphan write. Covers BOTH source_id and job_listing_id."""
        _insert_job(db_conn, _make_job({"id": "r-ws", "source_id": "google_scraper"}))
        resp = enrichment_client.post("/api/internal/enrichment/results", json={"results": [
            {   # whitespace-only source_id
                "job_listing_id": "r-ws", "source_id": "   ",
                "category": "business_ops", "level": "mid", "tags": ["ghost"], "locations": [],
            },
            {   # whitespace-only job_listing_id
                "job_listing_id": "  ", "source_id": "google_scraper",
                "category": "business_ops", "level": "mid", "tags": ["ghost"], "locations": [],
            },
        ]})
        assert resp.status_code == 200            # per-row isolation, NOT a batch 422
        body = resp.json()
        assert body["written"] == 0
        assert len(body["failed"]) == 2
        # Neither wrote anything: the seeded row keeps no facets, no orphan side rows.
        assert _fetch_listing_facets(db_conn, "r-ws")["enrichment_status"] is None
        assert _fetch_job_enrichment(db_conn, "r-ws") is None
        cur = db_conn.cursor()
        cur.execute("SELECT COUNT(*) AS n FROM job_tags WHERE job_listing_id IN ('r-ws', '  ')")
        assert cur.fetchone()["n"] == 0

    # --- F14: nonexistent (source_id, id) -> rowcount==0 guard -> failed[] ---- #

    def test_nonexistent_source_id_id_is_a_failure_no_orphans(
        self, enrichment_client, db_conn
    ):
        """F14 (publish branch): a well-formed but nonexistent (source_id, id)
        matches 0 job_listings rows. The writer's rowcount==0 guard raises → the
        SAVEPOINT rolls back the already-inserted job_enrichment audit row (+ any
        tags) → written==0, one failed[], and ZERO orphan job_enrichment/job_tags
        rows. (Deliberately does NOT seed the row.)"""
        resp = enrichment_client.post("/api/internal/enrichment/results", json={"results": [
            {
                "job_listing_id": "ghost-id", "source_id": "ghost-src",
                "category": "business_ops", "level": "mid", "tags": ["ghost"], "locations": [],
            }
        ]})
        assert resp.status_code == 200
        body = resp.json()
        assert body["written"] == 0
        assert len(body["failed"]) == 1
        assert body["failed"][0]["job_listing_id"] == "ghost-id"
        # The audit insert + tags were rolled back by the SAVEPOINT — no orphans.
        assert _fetch_job_enrichment_by_pk(db_conn, "ghost-src", "ghost-id") is None
        assert _fetch_tags_by_pk(db_conn, "ghost-src", "ghost-id") == set()

    # --- F11: envelope `results` required (mis-keyed body -> 422) ------------ #

    def test_miskeyed_body_returns_422(self, enrichment_client):
        """A body missing `results` (`{}` or a mis-keyed `{"items": [...]}`) must
        422 up front, not silently return 200 {"written": 0}."""
        for bad_body in ({}, {"items": [{"job_listing_id": "x", "source_id": "s"}]}):
            resp = enrichment_client.post(
                "/api/internal/enrichment/results", json=bad_body
            )
            assert resp.status_code == 422, bad_body

    def test_explicit_empty_results_still_accepted(self, enrichment_client):
        """An explicit {"results": []} is a valid no-op poll (200), even though the
        field is now required."""
        resp = enrichment_client.post(
            "/api/internal/enrichment/results", json={"results": []}
        )
        assert resp.status_code == 200
        assert resp.json() == {"written": 0, "failed": [], "warnings": []}


class TestHealth:
    def test_reports_status_counts(self, enrichment_client, db_conn, monkeypatch):
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({"id": "h-null", "status": "OPEN"}))
        _insert_job(db_conn, _make_job({
            "id": "h-done", "status": "OPEN", "enrichment_status": "done",
        }))
        # A needs_human audit row so the counter is non-zero. source_id is part of
        # the composite PK (source_id, job_listing_id) and NOT NULL — use the job's
        # default source_id ('google_scraper').
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id, needs_human) "
            "VALUES (%s, %s, true)",
            ("google_scraper", "h-done"),
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


class TestSample:
    def test_excludes_null_description_rows(self, enrichment_client, db_conn):
        """/sample must never return a row without a description_html (it exists
        for the golden eval set and description-less rows can't be classified).
        Runs REGARDLESS of the enrichment flag (only /pending is gated)."""
        _insert_job(db_conn, _make_job({
            "id": "s-desc", "status": "OPEN",
            "details": json.dumps({"description_html": "<p>real</p>"}),
        }))
        _insert_job(db_conn, _make_job({"id": "s-nodesc", "status": "OPEN"}))

        for stratify in ("company", "none"):
            resp = enrichment_client.get(
                "/api/internal/enrichment/sample", params={"stratify": stratify}
            )
            assert resp.status_code == 200
            ids = {j["job_id"] for j in resp.json()["jobs"]}
            assert ids == {"s-desc"}, f"stratify={stratify}"

    def test_stratify_company_caps_per_company(self, enrichment_client, db_conn):
        """stratify=company caps ~3 rows per company so one company can't
        dominate the sample."""
        for i in range(6):
            _insert_job(db_conn, _make_job({
                "id": f"s-cap-{i}", "company": "google", "status": "OPEN",
                "details": json.dumps({"description_html": "<p>x</p>"}),
            }))
        resp = enrichment_client.get(
            "/api/internal/enrichment/sample", params={"stratify": "company"}
        )
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) <= 3


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
        _seed_facet_job(db_conn, "f-ds", "hardware_engineer", "senior")
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
        _seed_facet_job(db_conn, "f-c2", "business_ops", "entry")
        _seed_facet_job(db_conn, "f-c3", "software_engineering", "senior")
        resp = client.get(
            "/api/jobs", params={"category": "software_engineering", "level": "entry"}
        )
        ids = {j["id"] for j in resp.json()}
        assert ids == {"f-c1"}

    def test_jobs_response_tags_isolated_by_source_id(self, client, db_conn):
        """F8 read-side: two rows share id='dup' under src-a/src-b. Each job in the
        /api/jobs response must carry ONLY its own tags (the tags subquery joins on
        the composite (source_id, id), not id alone)."""
        _insert_job(db_conn, _make_job({"id": "dup", "source_id": "src-a"}))
        _insert_job(db_conn, _make_job({"id": "dup", "source_id": "src-b"}))
        apply_result(
            db_conn,
            {"job_listing_id": "dup", "source_id": "src-a",
             "category": "business_ops", "level": "mid", "tags": ["a-only"], "locations": []},
            require_judge_pass=False,
        )
        apply_result(
            db_conn,
            {"job_listing_id": "dup", "source_id": "src-b",
             "category": "business_ops", "level": "mid", "tags": ["b-only"], "locations": []},
            require_judge_pass=False,
        )
        db_conn.commit()

        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        tags_by_source = {
            j["sourceId"]: set(j["tags"]) for j in resp.json() if j["id"] == "dup"
        }
        assert tags_by_source == {"src-a": {"a-only"}, "src-b": {"b-only"}}


# --------------------------------------------------------------------------- #
# 5. Taxonomy parity (S1): the slug sets + hierarchy are triple-encoded        #
#    (enrichment_writer constants, services.database expansion, migration seed  #
#    + DB rows). This test fails CI the moment any of them drifts apart.        #
# --------------------------------------------------------------------------- #


def _load_enrichment_migration(pattern: str = "*0fa33aca5bda*.py"):
    """Import a frozen enrichment migration module by filename glob, without
    depending on Alembic's runtime, to read its seed constants (CATEGORY_SEED /
    LEVEL_SEED on the base migration, ADDED_LEVELS on later ones)."""
    import importlib.util
    from pathlib import Path

    versions_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    path = next(versions_dir.glob(pattern))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTaxonomyParity:
    def test_code_slug_sets_match_migration_seed(self):
        from api.services.enrichment_writer import CATEGORY_SLUGS, LEVEL_SLUGS

        mig = _load_enrichment_migration()
        intern_mig = _load_enrichment_migration("*add_intern_level*.py")
        seed_categories = {slug for slug, _label, _order in mig.CATEGORY_SEED}
        # Levels = the base seed UNION every later migration's ADDED_LEVELS, so a
        # tier added by a follow-up migration (e.g. `intern`) stays in lock-step
        # with the code constants instead of tripping this parity guard.
        seed_levels = {slug for slug, _label, _rank, _parent in mig.LEVEL_SEED}
        seed_levels |= {slug for slug, _label, _rank, _parent in intern_mig.ADDED_LEVELS}

        assert CATEGORY_SLUGS == seed_categories
        assert LEVEL_SLUGS == seed_levels

    def test_level_filter_expansion_matches_seed_hierarchy(self):
        from api.services.database import _LEVEL_FILTER_EXPANSION

        mig = _load_enrichment_migration()
        # Derive the expected read-side expansion from the seed's parent_slug
        # edges: every parent expands to itself + each child pointing at it.
        expected: dict[str, set[str]] = {}
        for slug, _label, _rank, parent in mig.LEVEL_SEED:
            if parent is not None:
                expected.setdefault(parent, {parent}).add(slug)

        actual = {k: set(v) for k, v in _LEVEL_FILTER_EXPANSION.items()}
        assert actual == expected  # {'entry': {'entry', 'new_grad'}}

    def test_seeded_db_rows_match_code_slug_sets(self, db_conn):
        """The taxonomy the fixture seeds into job_categories/job_levels (a copy
        of the migration seed) must equal the code constants — closes the loop so
        a drift in EITHER the seed or the code fails here."""
        from api.services.enrichment_writer import CATEGORY_SLUGS, LEVEL_SLUGS

        cur = db_conn.cursor()
        cur.execute("SELECT slug FROM job_categories")
        assert {r["slug"] for r in cur.fetchall()} == CATEGORY_SLUGS
        cur.execute("SELECT slug FROM job_levels")
        assert {r["slug"] for r in cur.fetchall()} == LEVEL_SLUGS


class TestDescriptionCoalesce:
    """/pending + /sample must see descriptions under ALL real per-ATS keys
    (verified against prod 2026-07-08: Ashby/Lever use description_html,
    Greenhouse uses content, custom scrapers use description, Workday carries a
    JSON-null description_html). Without the COALESCE only ~17% of OPEN rows
    were claimable."""

    def _seed(self, db_conn):
        _insert_job(db_conn, _make_job({
            "id": "desc-html", "source_id": "ashby_api",
            "details": json.dumps({"description_html": "<p>ashby</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "desc-content", "source_id": "greenhouse_api",
            "details": json.dumps({"content": "<p>greenhouse</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "desc-plain", "source_id": "google_scraper",
            "details": json.dumps({"description": "plain scraper text"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "desc-null", "source_id": "workday_api",
            # The Workday shape: the KEY exists but its VALUE is JSON null.
            "details": json.dumps({"description_html": None}),
        }))

    def test_pending_claims_all_description_shapes(self, enrichment_client, db_conn, monkeypatch):
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        self._seed(db_conn)
        resp = enrichment_client.get("/api/internal/enrichment/pending?limit=10")
        assert resp.status_code == 200
        jobs = {j["job_id"]: j for j in resp.json()["jobs"]}
        assert set(jobs) == {"desc-html", "desc-content", "desc-plain"}
        # The projection presents whichever key matched AS description_html.
        assert jobs["desc-content"]["description_html"] == "<p>greenhouse</p>"
        assert jobs["desc-plain"]["description_html"] == "plain scraper text"

    def test_sample_sees_all_description_shapes(self, enrichment_client, db_conn):
        self._seed(db_conn)
        resp = enrichment_client.get("/api/internal/enrichment/sample?n=10&stratify=none")
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert ids == {"desc-html", "desc-content", "desc-plain"}


class TestKillSwitchReclaim:
    """The stale-claim reclaim must run even with the flag OFF — flipping the
    kill switch is exactly when in-flight 'claimed' rows must drain back to
    NULL (previously they stranded at 'claimed' forever)."""

    def test_flag_off_still_reclaims_stale_claims(self, enrichment_client, db_conn, monkeypatch):
        monkeypatch.setattr(settings, "enrichment_use_external", False)
        _insert_job(db_conn, _make_job({
            "id": "stale-1", "source_id": "src",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_status='claimed', "
            "enrichment_claimed_at = now() - interval '10 hours' WHERE id='stale-1'"
        )
        db_conn.commit()

        resp = enrichment_client.get("/api/internal/enrichment/pending?limit=10")
        assert resp.status_code == 200
        assert resp.json() == {"jobs": [], "enabled": False}

        cur.execute("SELECT enrichment_status FROM job_listings WHERE id='stale-1'")
        assert cur.fetchone()["enrichment_status"] is None


class TestResultsFeedback:
    """The /results response's warnings channel + failed[].source_id + batch cap."""

    def _seed_job(self, db_conn, job_id="fb-1", source_id="src-a"):
        _insert_job(db_conn, _make_job({
            "id": job_id, "source_id": source_id,
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))

    def test_invalid_category_warns_and_nulls(self, enrichment_client, db_conn):
        self._seed_job(db_conn)
        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [{
                "job_listing_id": "fb-1", "source_id": "src-a",
                "category": "underwater_basket_weaving", "level": "mid",
            }]},
        )
        body = resp.json()
        assert body["written"] == 1
        assert len(body["warnings"]) == 1
        w = body["warnings"][0]
        assert w["job_listing_id"] == "fb-1" and w["source_id"] == "src-a"
        assert any("underwater_basket_weaving" in msg for msg in w["warnings"])
        cur = db_conn.cursor()
        cur.execute("SELECT enrichment_category, enrichment_level FROM job_listings WHERE id='fb-1'")
        row = cur.fetchone()
        assert row["enrichment_category"] is None and row["enrichment_level"] == "mid"

    def test_failed_rows_carry_source_id(self, enrichment_client, db_conn):
        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [{
                "job_listing_id": "ghost", "source_id": "src-ghost", "level": "mid",
            }]},
        )
        body = resp.json()
        assert body["written"] == 0
        assert body["failed"][0]["job_listing_id"] == "ghost"
        assert body["failed"][0]["source_id"] == "src-ghost"

    def test_tags_truncated_with_warning(self, enrichment_client, db_conn):
        from api.services.enrichment_writer import MAX_TAGS_PER_JOB

        self._seed_job(db_conn)
        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [{
                "job_listing_id": "fb-1", "source_id": "src-a",
                "tags": [f"tag-{i}" for i in range(MAX_TAGS_PER_JOB + 5)],
            }]},
        )
        body = resp.json()
        assert body["written"] == 1
        assert any("truncated" in msg for msg in body["warnings"][0]["warnings"])
        cur = db_conn.cursor()
        cur.execute(
            "SELECT count(*) AS n FROM job_tags WHERE source_id='src-a' AND job_listing_id='fb-1'"
        )
        assert cur.fetchone()["n"] == MAX_TAGS_PER_JOB

    def test_overlong_tag_dropped_with_warning(self, enrichment_client, db_conn):
        self._seed_job(db_conn)
        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [{
                "job_listing_id": "fb-1", "source_id": "src-a",
                "tags": ["ok-tag", "x" * 61],
            }]},
        )
        body = resp.json()
        assert body["written"] == 1
        assert any("dropped" in msg for msg in body["warnings"][0]["warnings"])
        cur = db_conn.cursor()
        cur.execute(
            "SELECT tag FROM job_tags WHERE source_id='src-a' AND job_listing_id='fb-1'"
        )
        assert [r["tag"] for r in cur.fetchall()] == ["ok-tag"]

    def test_batch_over_cap_returns_413(self, enrichment_client):
        from api.routers.internal_enrichment import MAX_RESULTS_PER_BATCH

        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [{}] * (MAX_RESULTS_PER_BATCH + 1)},
        )
        assert resp.status_code == 413

    def test_human_corrected_row_is_locked(self, enrichment_client, db_conn):
        """A row an admin corrected must survive a later agent write untouched:
        the item counts as written (so the enricher stops retrying) but carries
        the skip warning, and the facets keep the human's values."""
        self._seed_job(db_conn)
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_category='growth', "
            "enrichment_level='senior', enrichment_status='done' WHERE id='fb-1'"
        )
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id, needs_human, "
            "human_corrected_at, human_corrected_by) "
            "VALUES ('src-a', 'fb-1', false, now(), 'admin@test')"
        )
        db_conn.commit()

        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [{
                "job_listing_id": "fb-1", "source_id": "src-a",
                "category": "software_engineering", "level": "entry",
                "tags": ["should-not-land"],
            }]},
        )
        body = resp.json()
        assert body["written"] == 1
        assert any("human-corrected" in msg for msg in body["warnings"][0]["warnings"])
        cur.execute(
            "SELECT enrichment_category, enrichment_level FROM job_listings WHERE id='fb-1'"
        )
        row = cur.fetchone()
        assert row["enrichment_category"] == "growth"
        assert row["enrichment_level"] == "senior"
        cur.execute(
            "SELECT count(*) AS n FROM job_tags WHERE job_listing_id='fb-1'"
        )
        assert cur.fetchone()["n"] == 0


class TestMetricsPush:
    """POST /metrics — the laptop's per-tick observability channel."""

    _PAYLOAD = {
        "tick_uuid": "tick-abc",
        "started_at": "2026-07-08T10:00:00Z",
        "ended_at": "2026-07-08T10:05:00Z",
        "status": "ok",
        "counters": {"claimed": 12, "classified": 12, "sent": 11, "errors": 1},
        "duration_s": 300.5,
        "taxonomy_version": "v2+abc123",
        "knobs": {"judge_scope": "low_confidence"},
        "stage_timings": [{"stage": "classify", "ms": 91000, "items": 12, "retries": 0}],
        "heartbeat_age_s": 12.5,
        "drift_suspected": False,
    }

    def test_push_inserts_tick(self, enrichment_client, db_conn):
        resp = enrichment_client.post(
            "/api/internal/enrichment/metrics", json=self._PAYLOAD
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        cur = db_conn.cursor()
        cur.execute("SELECT * FROM enrichment_ticks WHERE tick_uuid='tick-abc'")
        row = cur.fetchone()
        assert row["status"] == "ok"
        assert row["claimed"] == 12 and row["sent"] == 11 and row["errors"] == 1
        assert row["knobs"] == {"judge_scope": "low_confidence"}
        assert row["stage_timings"][0]["stage"] == "classify"

    def test_repush_same_uuid_upserts(self, enrichment_client, db_conn):
        running = dict(self._PAYLOAD, status="running", ended_at=None)
        enrichment_client.post("/api/internal/enrichment/metrics", json=running)
        enrichment_client.post("/api/internal/enrichment/metrics", json=self._PAYLOAD)
        cur = db_conn.cursor()
        cur.execute(
            "SELECT count(*) AS n, max(status) AS status FROM enrichment_ticks "
            "WHERE tick_uuid='tick-abc'"
        )
        row = cur.fetchone()
        assert row["n"] == 1 and row["status"] == "ok"

    def test_bad_status_422s(self, enrichment_client):
        resp = enrichment_client.post(
            "/api/internal/enrichment/metrics",
            json=dict(self._PAYLOAD, status="on-fire"),
        )
        assert resp.status_code == 422

    def test_oversized_scorecard_422s(self, enrichment_client):
        resp = enrichment_client.post(
            "/api/internal/enrichment/metrics",
            json=dict(self._PAYLOAD, scorecard={"pad": "x" * 17000}),
        )
        assert resp.status_code == 422


class TestCorrectionsFeed:
    """GET /corrections — human labels flowing back to the enricher's gold set."""

    def test_empty_feed(self, enrichment_client):
        resp = enrichment_client.get("/api/internal/enrichment/corrections")
        assert resp.status_code == 200
        assert resp.json() == {"corrections": [], "count": 0}

    def test_correction_appears_in_feed(self, enrichment_client, db_conn):
        from api.services.enrichment_monitor import apply_correction

        _insert_job(db_conn, _make_job({
            "id": "corr-1", "source_id": "src-a",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        apply_correction(
            db_conn, source_id="src-a", job_listing_id="corr-1",
            category="growth", level="mid", tags=["go", "sql"],
            note="was mislabelled", admin_email="admin@test",
        )
        resp = enrichment_client.get("/api/internal/enrichment/corrections")
        body = resp.json()
        assert body["count"] == 1
        c = body["corrections"][0]
        assert c["job_listing_id"] == "corr-1" and c["source_id"] == "src-a"
        assert c["category"] == "growth" and c["level"] == "mid"
        assert c["tags"] == ["go", "sql"]
        assert c["corrected_at"] is not None
        assert c["decision"] == "corrected"

        # since= strictly after the correction -> empty again
        resp = enrichment_client.get(
            "/api/internal/enrichment/corrections",
            params={"since": "2100-01-01T00:00:00Z"},
        )
        assert resp.json()["count"] == 0

    def test_confirmation_appears_in_feed_with_decision(self, enrichment_client, db_conn):
        """A confirmed-correct row also flows to the golden-merge feed, tagged
        so the enricher can weight a validated raise apart from a fix."""
        from api.services.enrichment_monitor import apply_confirmation

        _insert_job(db_conn, _make_job({
            "id": "conf-1", "source_id": "src-a",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        cur = db_conn.cursor()
        # Publish a proposal so there is something to confirm.
        cur.execute(
            "UPDATE job_listings SET enrichment_category='growth', "
            "enrichment_level='mid', enrichment_status='done' "
            "WHERE source_id='src-a' AND id='conf-1'"
        )
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id, needs_human) "
            "VALUES ('src-a', 'conf-1', true)"
        )
        db_conn.commit()
        apply_confirmation(
            db_conn, source_id="src-a", job_listing_id="conf-1", admin_email="admin@test",
        )
        body = enrichment_client.get("/api/internal/enrichment/corrections").json()
        assert body["count"] == 1
        c = body["corrections"][0]
        assert c["job_listing_id"] == "conf-1"
        assert c["decision"] == "confirmed_correct"
        assert c["category"] == "growth" and c["level"] == "mid"


class TestHealthAdditions:
    """eligible_unenriched + needs_human_open on the internal /health."""

    def test_eligible_counts_only_claimable_rows(self, enrichment_client, db_conn):
        _insert_job(db_conn, _make_job({
            "id": "el-1", "source_id": "s",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "el-2", "source_id": "s", "details": json.dumps({}),
        }))
        resp = enrichment_client.get("/api/internal/enrichment/health")
        body = resp.json()
        assert body["open_by_status"]["unenriched"] == 2
        assert body["eligible_unenriched"] == 1

    def test_eligible_includes_description_less_when_titleonly_flag_on(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """With title-only claiming ON, description-less rows ARE claimable, so
        eligible_unenriched must count them too — otherwise a title-only-draining
        pipeline reads as idle/starved. Keeps the metric equal to what /pending hands out."""
        _insert_job(db_conn, _make_job({
            "id": "el-desc", "source_id": "s",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "el-nodesc", "source_id": "s", "details": json.dumps({}),
        }))
        monkeypatch.setattr(settings, "enrichment_claim_without_description", True)
        resp = enrichment_client.get("/api/internal/enrichment/health")
        body = resp.json()
        assert body["open_by_status"]["unenriched"] == 2
        assert body["eligible_unenriched"] == 2  # both claimable under title-only

    def test_needs_human_open_excludes_corrected_and_closed(self, enrichment_client, db_conn):
        for jid, status in (("nh-open", "OPEN"), ("nh-closed", "CLOSED"), ("nh-fixed", "OPEN")):
            _insert_job(db_conn, _make_job({
                "id": jid, "source_id": "s", "status": status,
                "details": json.dumps({"description_html": "<p>x</p>"}),
            }))
        cur = db_conn.cursor()
        for jid, corrected in (("nh-open", False), ("nh-closed", False), ("nh-fixed", True)):
            cur.execute(
                "INSERT INTO job_enrichment (source_id, job_listing_id, needs_human, "
                "human_corrected_at) VALUES ('s', %s, true, %s)",
                (jid, "2026-01-01T00:00:00Z" if corrected else None),
            )
        db_conn.commit()
        resp = enrichment_client.get("/api/internal/enrichment/health")
        body = resp.json()
        assert body["needs_human"] == 3          # raw count (backward compat)
        assert body["needs_human_open"] == 1     # OPEN + uncorrected only
