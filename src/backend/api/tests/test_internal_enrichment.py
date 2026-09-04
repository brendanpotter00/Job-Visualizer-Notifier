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
``_enrichment_isolation`` fixture does exactly that, and also truncates the
enrichment-side tables listed in ``_ENRICHMENT_TABLES``.
"""

import json
from datetime import datetime, timedelta, timezone

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

# Enrichment-side tables this module truncates itself so writer state never leaks
# between tests. locations + its alias cache are included so the one location test
# starts from a clean slate. Most of these are tables conftest's clean_tables does
# not touch; ``job_categories`` / ``job_levels`` are the exception — clean_tables
# truncates those too, and the overlap is deliberate and harmless because
# ``_seed_taxonomy`` re-seeds them and is ON CONFLICT DO NOTHING. Dropping them
# here would couple this module's per-test isolation to clean_tables' table list.
_ENRICHMENT_TABLES = (
    "enrichment_ticks",
    "job_tags",
    "job_enrichment",
    "job_locations",
    "alias_locations",
    "location_aliases",
    "locations",
    # BEFORE job_categories: job_subcategories.parent_slug is a real FK onto it,
    # so the child has to truncate first (TRUNCATE ... CASCADE would otherwise
    # take a different path through the graph than the one intended).
    "job_subcategories",
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
        "enrichment_claimed_at, normalization_status, enrichment_subcategories, "
        "enrichment_subcategory_source FROM job_listings WHERE id = %s",
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

    def test_custom_share_defaults(self):
        """The fairness brake ships ON at 10% with a 500-row per-company window —
        these two numbers are the whole policy, so pin them."""
        s = Settings(_env_file=None)
        assert s.enrichment_custom_share_pct == 10
        assert s.enrichment_custom_per_company_cap == 500

    @pytest.mark.parametrize("bad", [-1, 101])
    def test_custom_share_pct_rejects_out_of_range(self, bad):
        """A share outside 0-100 is nonsense (negative budget / over-subscribed
        batch) and must fail at boot, not silently clamp at request time."""
        with pytest.raises(ValueError):
            Settings(_env_file=None, enrichment_custom_share_pct=bad)


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


class TestApplySubcategories:
    """SCHEMA-3: the `_UNSET` tri-state, the parent rule, and the per-field lock.

    The whole point of these is that the failures they catch are SILENT: the
    endpoint returns 200 and reports `written: N` in every one of them.
    """

    def _base(self, job_id, **extra):
        result = {
            "job_listing_id": job_id,
            "source_id": "google_scraper",
            "category": "software_engineering",
            "level": "senior",
            "tags": [],
            "locations": [],
        }
        result.update(extra)
        return result

    def _seed(self, db_conn, job_id, subcats=None, source=None, confidence=None):
        _insert_job(db_conn, _make_job({"id": job_id}))
        if subcats is not None or source is not None:
            cur = db_conn.cursor()
            cur.execute(
                "UPDATE job_listings SET enrichment_subcategories = %s::text[], "
                "enrichment_subcategory_source = %s WHERE id = %s",
                (subcats, source, job_id),
            )
        if confidence is not None:
            cur = db_conn.cursor()
            cur.execute(
                "INSERT INTO job_enrichment (source_id, job_listing_id, "
                "subcategory_confidence) VALUES ('google_scraper', %s, %s) "
                "ON CONFLICT (source_id, job_listing_id) DO UPDATE SET "
                "subcategory_confidence = EXCLUDED.subcategory_confidence",
                (job_id, confidence),
            )
        db_conn.commit()

    def test_a_v6_payload_leaves_an_existing_array_source_AND_confidence_alone(
        self, db_conn
    ):
        """THE SINGLE MOST IMPORTANT TEST IN THIS STEP.

        An enricher that has not shipped subcategories yet posts ordinary ticks
        with no `subcategories` key. If that NULLed the column, every ordinary
        tick would wipe the backfill's work — and the response would still say
        `written: 1`. This is what makes the enricher-side knob a reversible
        deploy ORDER instead of a code push.
        """
        self._seed(db_conn, "v6-coexist", subcats=["backend", "full_stack"],
                   source="backfill", confidence=0.77)

        apply_result(db_conn, self._base("v6-coexist"), require_judge_pass=False)
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "v6-coexist")
        assert facets["enrichment_subcategories"] == ["backend", "full_stack"]
        assert facets["enrichment_subcategory_source"] == "backfill"
        audit = _fetch_job_enrichment(db_conn, "v6-coexist")
        assert audit["subcategory_confidence"] == 0.77

    def test_a_FRESH_row_with_a_confidence_and_NO_array_stores_no_confidence(
        self, db_conn
    ):
        """⚠ `_UNSET` IS TRUTHY, AND THE PLAIN-INSERT ARM HAS NO `CASE` GUARD.

        `subcategory_confidence = None if not subcategories else ...` lets the
        sentinel straight through, because `object()` is truthy. The ON CONFLICT
        arm is protected by `CASE WHEN <subcategories is not _UNSET>`; the
        first-time INSERT is not. So a payload carrying `subcategoryConfidence`
        with no `subcategories` key seeded a brand-new row with a score beside a
        NULL array — the pairing §1.2 forbids, with no error anywhere.

        Deliberately NO `_seed(..., confidence=...)`: this row must have no
        `job_enrichment` row at all, or the upsert takes the UPDATE arm and the
        bug hides.
        """
        self._seed(db_conn, "sub-fresh-conf")
        apply_result(
            db_conn,
            self._base("sub-fresh-conf", subcategory_confidence=0.73),
            require_judge_pass=False,
        )
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "sub-fresh-conf")
        assert facets["enrichment_subcategories"] is None
        assert _fetch_job_enrichment(db_conn, "sub-fresh-conf")[
            "subcategory_confidence"
        ] is None

    def test_a_v6_RECLASSIFY_AWAY_from_swe_clears_the_stale_array(self, db_conn):
        """⚠ THE PARENT CHECK RUNS FIRST, AHEAD OF THE `_UNSET` CHECK.

        §1's SCHEMA-3 step words it "resolved category ≠ software_engineering →
        None + warn, UNCONDITIONAL AND FIRST". Check `_UNSET` first instead and
        a v6 tick that RECLASSIFIES a job away from `software_engineering` sets
        the new category and leaves the old array behind: a non-SWE row carrying
        subcategories, no DB constraint to catch it, no warning, `written: 1`.

        It is not exotic — the epic's own deploy order has the bulk drain
        writing arrays while the classify tick is still v6 and sends no key.
        """
        self._seed(db_conn, "sub-reclass", subcats=["backend"], source="backfill",
                   confidence=0.81)
        # A v6-shaped payload: NO `subcategories` key, new non-SWE category.
        apply_result(
            db_conn,
            self._base("sub-reclass", category="growth"),
            require_judge_pass=False,
        )
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "sub-reclass")
        assert facets["enrichment_category"] == "growth"
        assert facets["enrichment_subcategories"] is None, (
            "a non-SWE row kept subcategories the parent rule forbids"
        )
        assert facets["enrichment_subcategory_source"] is None
        assert _fetch_job_enrichment(db_conn, "sub-reclass")[
            "subcategory_confidence"
        ] is None

    def test_a_v6_reclassify_away_from_swe_emits_NO_spurious_warning(self, db_conn):
        """The parent branch must not fire its "dropped" warning on a payload
        that sent nothing to drop — `_UNSET` is truthy, so a bare `if value:`
        would put that line in the /results echo for every non-SWE row of every
        ordinary tick."""
        self._seed(db_conn, "sub-reclass-quiet")
        warnings = apply_result(
            db_conn,
            self._base("sub-reclass-quiet", category="growth"),
            require_judge_pass=False,
        )
        db_conn.commit()
        assert not any("subcategories dropped" in w for w in warnings), warnings

    def test_explicit_null_clears_the_column_and_its_source(self, db_conn):
        self._seed(db_conn, "sub-null", subcats=["backend"], source="classify")
        apply_result(
            db_conn, self._base("sub-null", subcategories=None),
            require_judge_pass=False,
        )
        db_conn.commit()
        facets = _fetch_listing_facets(db_conn, "sub-null")
        assert facets["enrichment_subcategories"] is None
        assert facets["enrichment_subcategory_source"] is None

    def test_empty_list_is_terminal_and_carries_a_source(self, db_conn):
        """`[]` means "evaluated, nothing applies" — it LEAVES the queue."""
        self._seed(db_conn, "sub-empty")
        apply_result(
            db_conn,
            self._base("sub-empty", subcategories=[], subcategory_source="backfill"),
            require_judge_pass=False,
        )
        db_conn.commit()
        facets = _fetch_listing_facets(db_conn, "sub-empty")
        assert facets["enrichment_subcategories"] == []
        assert facets["enrichment_subcategory_source"] == "backfill"

    def test_unknown_slug_is_dropped_with_a_warning_never_a_raise(self, db_conn):
        self._seed(db_conn, "sub-bad")
        warnings = apply_result(
            db_conn,
            self._base("sub-bad", subcategories=["backend", "ai_ml"]),
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_listing_facets(db_conn, "sub-bad")["enrichment_subcategories"] == [
            "backend"
        ]
        assert any("ai_ml" in w for w in warnings)

    def test_all_slugs_invalid_yields_empty_NOT_null(self, db_conn):
        """The enricher DID evaluate the row; it just produced nothing this
        taxonomy recognizes. Returning null would silently re-queue it forever."""
        self._seed(db_conn, "sub-allbad")
        apply_result(
            db_conn,
            self._base("sub-allbad", subcategories=["ai_ml", "nonsense"]),
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_listing_facets(db_conn, "sub-allbad")[
            "enrichment_subcategories"
        ] == []

    def test_non_swe_with_a_non_empty_array_is_forced_to_null_with_a_warning(
        self, db_conn
    ):
        self._seed(db_conn, "sub-nonswe")
        warnings = apply_result(
            db_conn,
            self._base("sub-nonswe", category="growth", subcategories=["backend"]),
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_listing_facets(db_conn, "sub-nonswe")[
            "enrichment_subcategories"
        ] is None
        assert any("not 'software_engineering'" in w for w in warnings)

    def test_full_stack_suppresses_frontend_and_backend(self, db_conn):
        self._seed(db_conn, "sub-fs")
        apply_result(
            db_conn,
            self._base("sub-fs", subcategories=["full_stack", "backend"]),
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_listing_facets(db_conn, "sub-fs")[
            "enrichment_subcategories"
        ] == ["full_stack"]

    def test_order_is_preserved_and_truncated_at_two(self, db_conn):
        self._seed(db_conn, "sub-order")
        apply_result(
            db_conn,
            self._base(
                "sub-order",
                subcategories=["security", "mobile", "quantitative"],
            ),
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_listing_facets(db_conn, "sub-order")[
            "enrichment_subcategories"
        ] == ["security", "mobile"]

    def test_a_scalar_is_promoted_not_rejected(self, db_conn):
        self._seed(db_conn, "sub-scalar")
        apply_result(
            db_conn,
            self._base("sub-scalar", subcategories="backend"),
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_listing_facets(db_conn, "sub-scalar")[
            "enrichment_subcategories"
        ] == ["backend"]

    def test_invalid_source_soft_nulls_to_the_default(self, db_conn):
        self._seed(db_conn, "sub-src")
        warnings = apply_result(
            db_conn,
            self._base(
                "sub-src", subcategories=["backend"],
                subcategory_source="backfill_failed",
            ),
            require_judge_pass=False,
        )
        db_conn.commit()
        assert _fetch_listing_facets(db_conn, "sub-src")[
            "enrichment_subcategory_source"
        ] == "classify"
        assert any("backfill_failed" in w for w in warnings)

    # --- the per-field human unlock ---------------------------------------

    def _lock(self, db_conn, job_id):
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id, human_corrected_at) "
            "VALUES ('google_scraper', %s, now()) "
            "ON CONFLICT (source_id, job_listing_id) DO UPDATE SET "
            "human_corrected_at = now()",
            (job_id,),
        )
        db_conn.commit()

    def test_a_human_locked_row_with_a_NULL_array_IS_written(self, db_conn):
        """The human corrected this row BEFORE subcategories existed, so a NULL
        array is provably not a human decision — there was nothing to decide.
        Refusing here would permanently exclude the human-labelled pool from the
        backfill, and that pool is exactly what the eval gate is built on."""
        self._seed(db_conn, "lock-null")
        self._lock(db_conn, "lock-null")

        warnings = apply_result(
            db_conn,
            self._base(
                # The payload's own resolved category has to be SWE — the parent
                # rule is checked against what THIS payload claims, not against
                # whatever the locked row happens to hold.
                "lock-null", category="software_engineering", level="senior",
                subcategories=["backend"], subcategory_source="backfill",
                subcategory_confidence=0.9,
            ),
            require_judge_pass=False,
        )
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "lock-null")
        assert facets["enrichment_subcategories"] == ["backend"]
        assert facets["enrichment_subcategory_source"] == "backfill"
        assert _fetch_job_enrichment(db_conn, "lock-null")["subcategory_confidence"] == 0.9
        # EVERYTHING ELSE stays refused — the lock is still absolute for the
        # facets a human actually decided.
        assert facets["enrichment_category"] is None
        assert facets["enrichment_level"] is None
        assert any("human-corrected" in w for w in warnings)

    def test_a_human_locked_row_with_a_NON_NULL_array_is_NOT_written(self, db_conn):
        self._seed(db_conn, "lock-set", subcats=["frontend"], source="human")
        self._lock(db_conn, "lock-set")

        warnings = apply_result(
            db_conn,
            self._base("lock-set", subcategories=["backend"]),
            require_judge_pass=False,
        )
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "lock-set")
        assert facets["enrichment_subcategories"] == ["frontend"]
        assert facets["enrichment_subcategory_source"] == "human"
        assert any("skipped: human-corrected" in w for w in warnings)

    def test_a_human_locked_row_with_no_subcategories_key_is_still_refused(
        self, db_conn
    ):
        self._seed(db_conn, "lock-v6")
        self._lock(db_conn, "lock-v6")
        warnings = apply_result(
            db_conn, self._base("lock-v6"), require_judge_pass=False
        )
        db_conn.commit()
        assert _fetch_listing_facets(db_conn, "lock-v6")["enrichment_category"] is None
        assert any("skipped: human-corrected" in w for w in warnings)

    def test_demote_nulls_the_array_unconditionally(self, db_conn):
        """A row re-flagged for a human must not keep stale published labels."""
        self._seed(db_conn, "sub-demote", subcats=["backend"], source="classify")
        apply_result(
            db_conn,
            self._base("sub-demote", judge={"judged": True, "needs_human": True}),
            require_judge_pass=True,
        )
        db_conn.commit()
        facets = _fetch_listing_facets(db_conn, "sub-demote")
        assert facets["enrichment_subcategories"] is None
        assert facets["enrichment_subcategory_source"] is None
        assert facets["enrichment_status"] == "needs_human"


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
        # details is the trimmed jsonb projection (experience_level only).
        assert job["details"] == {"experience_level": "Senior"}

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

    def test_entry_level_titles_claimed_before_newer_misc(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """Title-priority tiers: an entry-level/intern title is claimed ahead of a
        newer non-matching ("everything else") title. Tier beats recency."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        # OLD intern (tier 0) vs NEW misc (tier 2).
        _insert_job(db_conn, _make_job({
            "id": "t-intern-old", "status": "OPEN", "title": "Software Engineer Intern",
            "first_seen_at": "2025-01-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "t-misc-new", "status": "OPEN", "title": "Marketing Manager",
            "first_seen_at": "2026-07-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 1}
        )
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        # The older intern wins over the newer non-matching role.
        assert ids == {"t-intern-old"}
        assert _fetch_listing_facets(db_conn, "t-misc-new")["enrichment_status"] is None

    def test_tier_order_is_entry_then_swe_then_rest(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """Full tier sequence: entry-level (tier 0) -> software-engineering (tier 1)
        -> everything else (tier 2), even when the lower tiers were first seen more
        recently. Drained one at a time across successive /pending calls."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        # Deliberately inverted recency: the LOWER-priority tiers are NEWER, so only
        # the tier CASE (not first_seen_at) can produce the intern -> swe -> misc order.
        _insert_job(db_conn, _make_job({
            "id": "t-intern", "status": "OPEN", "title": "Data Science Intern",
            "first_seen_at": "2025-01-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "t-swe", "status": "OPEN", "title": "Senior Software Engineer",
            "first_seen_at": "2025-06-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "t-misc", "status": "OPEN", "title": "Account Executive",
            "first_seen_at": "2026-07-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))

        def claim_one() -> set[str]:
            resp = enrichment_client.get(
                "/api/internal/enrichment/pending", params={"limit": 1}
            )
            assert resp.status_code == 200
            return {j["job_id"] for j in resp.json()["jobs"]}

        assert claim_one() == {"t-intern"}   # tier 0 first (oldest, but top tier)
        assert claim_one() == {"t-swe"}      # tier 1 next (before the newer misc)
        assert claim_one() == {"t-misc"}     # tier 2 last

    def test_within_tier_orders_by_first_seen_desc(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """Recency is the WITHIN-tier tie-breaker: among two entry-level roles, the
        one we first saw most recently is claimed first."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "t-intern-older", "status": "OPEN", "title": "Software Intern",
            "first_seen_at": "2025-01-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "t-intern-newer", "status": "OPEN", "title": "Machine Learning Intern",
            "first_seen_at": "2026-07-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 1}
        )
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        assert ids == {"t-intern-newer"}
        assert _fetch_listing_facets(db_conn, "t-intern-older")["enrichment_status"] is None

    def test_intern_false_friend_not_prioritized(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """Whole-word (\\y) matching: 'International' / 'Internal' titles must NOT be
        treated as intern (tier 0). A NEWER false-friend must not be claimed ahead of
        an OLDER real intern — which only holds if the false-friend falls to tier 2."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "t-real-intern", "status": "OPEN", "title": "Backend Intern",
            "first_seen_at": "2025-01-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        # Newer, but NOT intern — 'International'/'Internal' must not false-match.
        _insert_job(db_conn, _make_job({
            "id": "t-intl", "status": "OPEN", "title": "International Operations Lead",
            "first_seen_at": "2026-07-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "t-internal", "status": "OPEN", "title": "Internal Communications Manager",
            "first_seen_at": "2026-07-02T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 1}
        )
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        # The older REAL intern wins; the newer false-friends are tier 2.
        assert ids == {"t-real-intern"}
        for ff in ("t-intl", "t-internal"):
            assert _fetch_listing_facets(db_conn, ff)["enrichment_status"] is None

    def test_new_grad_and_junior_are_entry_tier(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """'New Grad' and 'Junior' titles are entry-level (tier 0), claimed ahead of a
        newer non-matching role."""
        monkeypatch.setattr(settings, "enrichment_use_external", True)
        _insert_job(db_conn, _make_job({
            "id": "t-newgrad", "status": "OPEN", "title": "New Grad Software Engineer",
            "first_seen_at": "2025-02-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "t-junior", "status": "OPEN", "title": "Junior Developer",
            "first_seen_at": "2025-01-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        _insert_job(db_conn, _make_job({
            "id": "t-mgr-new", "status": "OPEN", "title": "Product Manager",
            "first_seen_at": "2026-07-01T00:00:00Z",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 2}
        )
        assert resp.status_code == 200
        ids = {j["job_id"] for j in resp.json()["jobs"]}
        # Both entry-level roles beat the newer non-matching manager role.
        assert ids == {"t-newgrad", "t-junior"}
        assert _fetch_listing_facets(db_conn, "t-mgr-new")["enrichment_status"] is None

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


# --------------------------------------------------------------------------- #
# 3b. Router: /pending — the custom-company fairness brake                     #
# --------------------------------------------------------------------------- #

# Every fixture below seeds custom rows STRICTLY NEWER than every published row.
# That is the real-world shape (a board added today produces the newest rows in
# the table) and it is what makes these tests meaningful: under the pre-brake
# claim — ORDER BY tier, first_seen_at DESC with no source_id filter — the custom
# rows would sweep 100% of every batch. Any assertion here that a published row
# was claimed is therefore also an assertion that the brake engaged.
_PUBLISHED_EPOCH = datetime(2026, 7, 1, tzinfo=timezone.utc)
_CUSTOM_EPOCH = datetime(2026, 8, 1, tzinfo=timezone.utc)
# The wire contract, spelled out literally rather than imported from
# scripts.shared.constants: these tests pin the `custom:` prefix itself, so a
# change to the constant has to be a deliberate, visible test edit.
_CUSTOM_PREFIX = "custom:"
_DESC = json.dumps({"description_html": "<p>x</p>"})


def _bulk_insert_jobs(db_conn, jobs: list[dict]) -> None:
    """Insert many job rows in ONE transaction.

    conftest's ``_insert_job`` commits per row and mirrors ``job_freshness``;
    the claim reads neither, and these tests seed up to ~90 rows each, so the
    per-row round trips would be pure overhead. Column names come from
    ``_make_job``'s fixed literal dict — no user input reaches the SQL text.
    """
    cur = db_conn.cursor()
    cols = [k for k in jobs[0] if k not in ("last_seen_at", "consecutive_misses")]
    cur.executemany(
        f"INSERT INTO job_listings ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))})",
        [[j[c] for c in cols] for j in jobs],
    )
    db_conn.commit()


def _custom_jobs(company_id: str, n: int, *, title: str = "Account Executive",
                 offset: int = 0) -> list[dict]:
    """`n` OPEN rows for one custom company, oldest first (index 0 = oldest)."""
    return [
        _make_job({
            "id": f"{company_id}-{offset + i}",
            "source_id": f"{_CUSTOM_PREFIX}{company_id}",
            "company": company_id,
            "title": title,
            "status": "OPEN",
            "first_seen_at": (
                _CUSTOM_EPOCH + timedelta(minutes=offset + i)
            ).isoformat(),
            "details": _DESC,
        })
        for i in range(n)
    ]


def _published_jobs(n: int, *, title: str = "Account Executive") -> list[dict]:
    return [
        _make_job({
            "id": f"pub-{i}",
            "source_id": "greenhouse_api",
            "company": "stripe",
            "title": title,
            "status": "OPEN",
            "first_seen_at": (_PUBLISHED_EPOCH + timedelta(minutes=i)).isoformat(),
            "details": _DESC,
        })
        for i in range(n)
    ]


def _split_slices(body: dict) -> tuple[list[dict], list[dict]]:
    custom = [j for j in body["jobs"] if j["source_id"].startswith(_CUSTOM_PREFIX)]
    published = [
        j for j in body["jobs"] if not j["source_id"].startswith(_CUSTOM_PREFIX)
    ]
    return custom, published


class TestPendingCustomShare:
    """The fairness brake: custom (user-added) companies get a reserved SHARE of
    each claim — not the whole queue, and not zero."""

    @pytest.fixture(autouse=True)
    def _enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "enrichment_use_external", True)

    def test_split_holds_under_mixed_load(self, enrichment_client, db_conn):
        """With both slices deeper than one batch, a 60-row claim is 6 custom /
        54 published — the configured 10% share, exactly."""
        for company in ("u-aaa", "u-bbb", "u-ccc"):
            _bulk_insert_jobs(db_conn, _custom_jobs(company, 10))
        _bulk_insert_jobs(db_conn, _published_jobs(60))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 60}
        )
        assert resp.status_code == 200
        custom, published = _split_slices(resp.json())
        assert len(custom) == 6
        assert len(published) == 54

    def test_one_huge_custom_board_cannot_exceed_its_share(
        self, enrichment_client, db_conn
    ):
        """The 47k-board scenario in miniature: one custom company with more rows
        than the whole batch still gets only its 10%."""
        _bulk_insert_jobs(db_conn, _custom_jobs("u-huge", 80))
        _bulk_insert_jobs(db_conn, _published_jobs(80))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 60}
        )
        assert resp.status_code == 200
        custom, published = _split_slices(resp.json())
        assert len(custom) == 6
        assert len(published) == 54

    def test_custom_slice_round_robins_across_companies(
        self, enrichment_client, db_conn
    ):
        """Within the custom slice the 6 slots are dealt one-per-company before
        anyone gets a second — three equally deep boards get 2 each.

        The per-company `offset` stagger is load-bearing, not decoration: it makes
        u-aaa's rows strictly NEWER than u-bbb's and u-ccc's, so plain
        recency ordering would hand all 6 slots to u-aaa. Without it every board
        shares the same timestamps and recency alone reproduces 2/2/2, leaving the
        test unable to fail when the round-robin is removed.
        """
        for offset, company in enumerate(("u-ccc", "u-bbb", "u-aaa")):
            _bulk_insert_jobs(db_conn, _custom_jobs(company, 10, offset=offset * 10))
        _bulk_insert_jobs(db_conn, _published_jobs(60))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 60}
        )
        assert resp.status_code == 200
        custom, _ = _split_slices(resp.json())
        per_company: dict[str, int] = {}
        for job in custom:
            per_company[job["source_id"]] = per_company.get(job["source_id"], 0) + 1
        assert per_company == {
            f"{_CUSTOM_PREFIX}u-aaa": 2,
            f"{_CUSTOM_PREFIX}u-bbb": 2,
            f"{_CUSTOM_PREFIX}u-ccc": 2,
        }

    def test_busy_custom_board_cannot_crowd_out_a_quiet_one(
        self, enrichment_client, db_conn
    ):
        """Round-robin, not proportional: a 50-row board and two 1-row boards
        share the slice — the small boards are served FIRST, and the big one only
        absorbs what they leave."""
        _bulk_insert_jobs(db_conn, _custom_jobs("u-big", 50))
        _bulk_insert_jobs(db_conn, _custom_jobs("u-tiny1", 1))
        _bulk_insert_jobs(db_conn, _custom_jobs("u-tiny2", 1))
        _bulk_insert_jobs(db_conn, _published_jobs(60))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 60}
        )
        assert resp.status_code == 200
        custom, _ = _split_slices(resp.json())
        by_source: dict[str, int] = {}
        for job in custom:
            by_source[job["source_id"]] = by_source.get(job["source_id"], 0) + 1
        assert by_source[f"{_CUSTOM_PREFIX}u-tiny1"] == 1
        assert by_source[f"{_CUSTOM_PREFIX}u-tiny2"] == 1
        assert by_source[f"{_CUSTOM_PREFIX}u-big"] == 4  # the rest of the 6 slots

    def test_published_claim_order_is_unchanged_by_the_custom_slice(
        self, enrichment_client, db_conn
    ):
        """The brake changes WHICH rows the published pass sees (custom rows are
        gone from it), never the order it sees them in.

        Drains the same published fixture twice — once alone, once alongside a
        deep custom board — one published row per tick, and asserts the two claim
        SEQUENCES are identical (tier 0 -> 1 -> 2, recency within tier). The two
        phases use different limits only to isolate one published row per tick
        (`limit` never appears in the ORDER BY): phase 1 has no custom rows so
        limit=1 is all published; phase 2 reserves 1 slot for custom, so limit=2
        yields 1 custom + 1 published.
        """
        published = [
            _make_job({
                "id": jid, "source_id": "greenhouse_api", "company": "stripe",
                "title": title, "status": "OPEN", "first_seen_at": ts,
                "details": _DESC,
            })
            for jid, title, ts in [
                ("o-intern", "Data Science Intern", "2026-07-01T00:00:00Z"),
                ("o-swe", "Senior Software Engineer", "2026-07-02T00:00:00Z"),
                ("o-misc-new", "Account Executive", "2026-07-04T00:00:00Z"),
                ("o-misc-old", "Account Executive", "2026-07-03T00:00:00Z"),
            ]
        ]
        _bulk_insert_jobs(db_conn, published)

        def drain(limit: int) -> list[str]:
            seen: list[str] = []
            for _ in range(len(published)):
                resp = enrichment_client.get(
                    "/api/internal/enrichment/pending", params={"limit": limit}
                )
                assert resp.status_code == 200
                _, pub = _split_slices(resp.json())
                seen.extend(j["job_id"] for j in pub)
            return seen

        baseline = drain(1)
        assert baseline == ["o-intern", "o-swe", "o-misc-new", "o-misc-old"]

        # Reset the published rows and re-run WITH a deep custom board present.
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_status = NULL, "
            "enrichment_claimed_at = NULL"
        )
        db_conn.commit()
        _bulk_insert_jobs(db_conn, _custom_jobs("u-noisy", 20))

        assert drain(2) == baseline

    def test_empty_custom_slice_falls_back_to_published(
        self, enrichment_client, db_conn
    ):
        """The reservation is a CEILING on custom, not a floor: with no custom
        rows waiting, the published pass gets 100% of the batch — no idle slot,
        no short tick."""
        _bulk_insert_jobs(db_conn, _published_jobs(20))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 6}
        )
        assert resp.status_code == 200
        custom, publishedjobs = _split_slices(resp.json())
        assert custom == []
        assert len(publishedjobs) == 6

    def test_short_custom_slice_spills_back_to_published_same_tick(
        self, enrichment_client, db_conn
    ):
        """The share is a CEILING on custom, never a floor on the tick. With 4
        slots reserved and only 1 custom row eligible, the batch is still FULL —
        1 custom + 39 published — not 1 + 36 with three slots wasted.

        This is the throughput bug that would ship silently: a naive `LIMIT
        share` / `LIMIT total - share` split under-fills every tick where custom
        is short, and the only symptom is a queue that drains slower.
        """
        _bulk_insert_jobs(db_conn, _custom_jobs("u-quiet", 1))
        _bulk_insert_jobs(db_conn, _published_jobs(60))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 40}
        )
        assert resp.status_code == 200
        custom, publishedjobs = _split_slices(resp.json())
        assert len(custom) == 1
        assert len(publishedjobs) == 39
        assert len(resp.json()["jobs"]) == 40  # the tick is full

    def test_custom_takes_the_leftovers_when_published_is_dry(
        self, enrichment_client, db_conn
    ):
        """Mirror image of the fallback: an empty published backlog must not leave
        the enricher idling at 10% — custom absorbs the unused budget."""
        _bulk_insert_jobs(db_conn, _custom_jobs("u-only", 20))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 6}
        )
        assert resp.status_code == 200
        custom, publishedjobs = _split_slices(resp.json())
        assert len(custom) == 6
        assert publishedjobs == []

    def test_per_company_cap_bounds_eligibility(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """Only a custom company's newest N unclaimed OPEN rows compete. With the
        cap at 2, the board's two NEWEST (tier-2 "Account Executive") rows are
        claimed and its older tier-0 interns are not — the cap is applied before
        the tier ordering, so a mega-board's deep tier-0 history cannot outrank
        everyone else's fresh postings."""
        monkeypatch.setattr(settings, "enrichment_custom_per_company_cap", 2)
        # index 0/1 = oldest = interns (tier 0); index 2/3 = newest (tier 2).
        _bulk_insert_jobs(db_conn, _custom_jobs("u-cap", 2, title="Data Science Intern"))
        _bulk_insert_jobs(db_conn, _custom_jobs("u-cap", 2, offset=2))
        # Published rows soak the leftover budget so the top-up pass can't slide
        # the window forward within this same tick.
        _bulk_insert_jobs(db_conn, _published_jobs(20))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 20}
        )
        assert resp.status_code == 200
        custom, _ = _split_slices(resp.json())
        assert {j["job_id"] for j in custom} == {"u-cap-2", "u-cap-3"}
        for interned in ("u-cap-0", "u-cap-1"):
            assert _fetch_listing_facets(db_conn, interned)["enrichment_status"] is None

    def test_per_company_cap_window_slides_so_the_tail_is_never_stranded(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """The cap ranks UNCLAIMED rows, so it defers a board's tail rather than
        walling it off: once the newest rows are claimed, the next tick's window
        slides onto the older ones. (share=100 keeps this tick pure custom.)"""
        monkeypatch.setattr(settings, "enrichment_custom_per_company_cap", 2)
        monkeypatch.setattr(settings, "enrichment_custom_share_pct", 100)
        _bulk_insert_jobs(db_conn, _custom_jobs("u-slide", 4))

        first = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 2}
        )
        assert {j["job_id"] for j in first.json()["jobs"]} == {"u-slide-2", "u-slide-3"}
        second = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 2}
        )
        assert {j["job_id"] for j in second.json()["jobs"]} == {"u-slide-0", "u-slide-1"}

    def test_share_pct_zero_never_claims_custom_rows(
        self, enrichment_client, db_conn, monkeypatch
    ):
        """0% is the kill switch. It also proves custom rows are EXCLUDED from the
        published pass rather than merely deprioritized — they are the newest rows
        in the table, so a published pass that could see them would take all 5."""
        monkeypatch.setattr(settings, "enrichment_custom_share_pct", 0)
        _bulk_insert_jobs(db_conn, _custom_jobs("u-off", 20))
        _bulk_insert_jobs(db_conn, _published_jobs(20))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 5}
        )
        assert resp.status_code == 200
        custom, publishedjobs = _split_slices(resp.json())
        assert custom == []
        assert len(publishedjobs) == 5

    def test_small_limit_still_reserves_one_custom_slot(
        self, enrichment_client, db_conn
    ):
        """A limit below 10 must not round the share down to zero — that would
        block custom rows forever on a worker polling small batches."""
        _bulk_insert_jobs(db_conn, _custom_jobs("u-small", 5))
        _bulk_insert_jobs(db_conn, _published_jobs(20))

        resp = enrichment_client.get(
            "/api/internal/enrichment/pending", params={"limit": 4}
        )
        assert resp.status_code == 200
        custom, publishedjobs = _split_slices(resp.json())
        assert len(custom) == 1
        assert len(publishedjobs) == 3

    def test_description_guard_still_applies_to_custom_rows(
        self, enrichment_client, db_conn
    ):
        """The brake changes WHICH rows are handed out, never the eligibility
        rules: a description-less custom row stays unclaimable while
        enrichment_claim_without_description is off."""
        _bulk_insert_jobs(db_conn, [
            _make_job({
                "id": "u-nodesc-0", "source_id": f"{_CUSTOM_PREFIX}u-nodesc",
                "company": "u-nodesc", "status": "OPEN",
                "first_seen_at": _CUSTOM_EPOCH.isoformat(),
                "details": json.dumps({}),
            })
        ])
        resp = enrichment_client.get("/api/internal/enrichment/pending")
        assert resp.status_code == 200
        assert resp.json()["jobs"] == []
        assert _fetch_listing_facets(db_conn, "u-nodesc-0")["enrichment_status"] is None


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

    # --- SCHEMA-3: the `_UNSET` distinction AT THE HTTP BOUNDARY ------------- #
    #
    # TestApplySubcategories proves the writer honours `_UNSET`, but it calls
    # `apply_result` directly, where `_UNSET` comes from the CALLER omitting the
    # dict key — something the route never does. On the wire the key arrives
    # absent and `model_dump()` flattens absent and null into the same `None`;
    # only the router's `model_fields_set` pop carries the distinction into the
    # writer. These two tests are the only coverage of those lines.

    def _seed_subcategorised(
        self, db_conn, job_id, subcats, source, confidence, src_id="google_scraper"
    ):
        _insert_job(db_conn, _make_job({"id": job_id, "source_id": src_id}))
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_subcategories = %s::text[], "
            "enrichment_subcategory_source = %s WHERE source_id = %s AND id = %s",
            (subcats, source, src_id, job_id),
        )
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id, "
            "subcategory_confidence) VALUES (%s, %s, %s)",
            (src_id, job_id, confidence),
        )
        db_conn.commit()

    def _v6_item(self, job_id, **extra):
        """Exactly what a v6 enricher posts: no `subcategories` key at all."""
        item = {
            "job_listing_id": job_id,
            "source_id": "google_scraper",
            "category": "software_engineering",
            "level": "senior",
            "tags": [],
            "locations": [],
        }
        item.update(extra)
        return item

    def test_a_v6_shaped_REQUEST_leaves_the_array_source_AND_confidence_alone(
        self, enrichment_client, db_conn
    ):
        """⚠ THE SILENT FAILURE, PROVEN THROUGH HTTP.

        Delete the two `model_fields_set` pop lines in the route and every
        ordinary tick of a v6 enricher wipes the backfill's labels — while the
        response still says `200 {"written": 1}`. Nothing else in the suite
        fails when those lines go, because the writer-level test constructs
        `_UNSET` by omitting a dict key, which no HTTP request can do.
        """
        self._seed_subcategorised(
            db_conn, "r-v6", ["backend", "full_stack"], "backfill", 0.77
        )

        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [self._v6_item("r-v6")]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["written"] == 1
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "r-v6")
        assert facets["enrichment_subcategories"] == ["backend", "full_stack"]
        assert facets["enrichment_subcategory_source"] == "backfill"
        assert _fetch_job_enrichment(db_conn, "r-v6")["subcategory_confidence"] == 0.77

    def test_an_explicit_null_over_the_wire_STILL_requeues_the_row(
        self, enrichment_client, db_conn
    ):
        """The other half of the boundary: absent and null must NOT collapse.

        A route that popped the key unconditionally (or dropped `None` values
        wholesale) would pass the test above and silently make the explicit
        re-queue signal unreachable — `null` means "never evaluated", and it is
        how a row gets BACK into the backfill queue.
        """
        self._seed_subcategorised(
            db_conn, "r-null", ["backend"], "classify", 0.55
        )

        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [self._v6_item("r-null", subcategories=None)]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["written"] == 1
        db_conn.commit()

        facets = _fetch_listing_facets(db_conn, "r-null")
        assert facets["enrichment_subcategories"] is None
        assert facets["enrichment_subcategory_source"] is None


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
        retire_mig = _load_enrichment_migration(
            "*retire_project_manager_category*.py"
        )
        # Categories = the base seed MINUS every later migration's
        # REMOVED_CATEGORIES — the mirror image of the ADDED_LEVELS union below,
        # so a retired slug stays in lock-step with the code constants instead
        # of tripping this guard.
        seed_categories = {slug for slug, _label, _order in mig.CATEGORY_SEED}
        seed_categories -= set(retire_mig.REMOVED_CATEGORIES)
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

    def test_subcategory_slug_set_shape(self):
        """Fifteen slugs, lowercase, no whitespace, no duplicates."""
        from api.services.enrichment_writer import SUBCATEGORY_SLUGS

        assert len(SUBCATEGORY_SLUGS) == 15
        for slug in SUBCATEGORY_SLUGS:
            assert slug == slug.strip().lower()
            assert " " not in slug
            assert slug.replace("_", "").isalnum()

    def test_subcategory_slugs_are_disjoint_from_categories(self):
        """The arrow never runs backwards.

        A slug that means both a category and a subcategory would make every
        expansion, every facet lookup and every filter ambiguous, and the
        ambiguity would only show up as wrong results, never as an error.
        """
        from api.services.enrichment_writer import (
            CATEGORY_SLUGS,
            LEVEL_SLUGS,
            SUBCATEGORY_SLUGS,
        )

        assert SUBCATEGORY_SLUGS.isdisjoint(CATEGORY_SLUGS)
        assert SUBCATEGORY_SLUGS.isdisjoint(LEVEL_SLUGS)

    def test_subcategory_parent_is_a_real_category(self, db_conn):
        from api.services.enrichment_writer import CATEGORY_SLUGS, SUBCATEGORY_PARENT

        assert SUBCATEGORY_PARENT in CATEGORY_SLUGS
        cur = db_conn.cursor()
        cur.execute(
            "SELECT 1 FROM job_categories WHERE slug = %s", (SUBCATEGORY_PARENT,)
        )
        assert cur.fetchone() is not None, (
            f"{SUBCATEGORY_PARENT!r} is not a seeded category — the subcategory "
            "dimension's FK target does not exist"
        )

    def test_seeded_subcategory_rows_are_a_subset_of_code(self, db_conn):
        """SUBSET + SHAPE, not equality — and that is deliberate.

        Phase 1 ships `job_subcategories` EMPTY in prod, so an equality
        assertion here would be a FALSE GREEN: it would pass only against a
        fixture that seeds the table, i.e. against a state production is not in.
        `<=` holds both while the table is empty and after SCHEMA-7 seeds it;
        SCHEMA-9 tightens it to `==` in the phase-2 PR, once prod actually
        carries the rows.
        """
        from api.services.enrichment_writer import (
            SUBCATEGORY_PARENT,
            SUBCATEGORY_SLUGS,
        )

        cur = db_conn.cursor()
        cur.execute("SELECT slug, parent_slug FROM job_subcategories")
        rows = cur.fetchall()
        seeded = {r["slug"] for r in rows}
        assert seeded <= set(SUBCATEGORY_SLUGS), (
            f"seeded subcategories not present in code: {sorted(seeded - set(SUBCATEGORY_SLUGS))}"
        )
        for r in rows:
            assert r["parent_slug"] == SUBCATEGORY_PARENT

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

    def test_a_retired_category_is_nulled_and_warned(self, enrichment_client, db_conn):
        """``project_manager`` is RETIRED (SCHEMA-11), not legacy-accepted.

        It used to ride the accept-and-warn path: written, with a "legacy" warning,
        because the seeded dimension and the frontend dropdown both still knew the
        slug. This PR retires it — dropped from ``CATEGORY_SLUGS``, from the
        ``job_categories`` seed and from the frontend fallback — so accepting it
        would now WRITE a value whose FK target row no longer exists. It takes the
        ordinary invalid-facet path instead: the row is still written, the category
        is NULLed, and the enricher is told over ``warnings[]``.
        """
        self._seed_job(db_conn)
        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [{
                "job_listing_id": "fb-1", "source_id": "src-a",
                "category": "project_manager", "level": "mid",
            }]},
        )
        body = resp.json()
        assert body["written"] == 1
        msgs = [
            m
            for entry in body["warnings"]
            for m in (entry["warnings"] if isinstance(entry, dict) else [entry])
        ]
        assert any("project_manager" in m for m in msgs), body["warnings"]
        assert not any("legacy" in m for m in msgs), (
            "a retired slug must not take the legacy accept-and-warn path — its FK "
            "target row is deleted by SCHEMA-11"
        )

    def test_an_in_taxonomy_category_warns_about_nothing(self, enrichment_client, db_conn):
        """The tripwire must stay quiet on the 6 categories actually in use, or the
        warnings channel becomes noise and stops being read."""
        self._seed_job(db_conn)
        resp = enrichment_client.post(
            "/api/internal/enrichment/results",
            json={"results": [{
                "job_listing_id": "fb-1", "source_id": "src-a",
                "category": "software_engineering", "level": "mid",
            }]},
        )
        body = resp.json()
        assert body["written"] == 1
        assert body["warnings"] == []

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


    def test_feed_carries_subcategories_and_taxonomy_version(
        self, enrichment_client, db_conn
    ):
        """Both fields, and `taxonomy_version` is the load-bearing one.

        Without it the consumer cannot tell a PRE-v7 `confirmed_correct` row —
        a human validating a label set that had no subcategory field in it — from
        a real subcategory confirmation, and every such row becomes a false
        `subcategories: []` gold label.
        """
        from api.services.enrichment_monitor import apply_correction

        _insert_job(db_conn, _make_job({
            "id": "corr-sub", "source_id": "src-a",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id, taxonomy_version) "
            "VALUES ('src-a', 'corr-sub', 'v7+abc123def456')"
        )
        db_conn.commit()
        apply_correction(
            db_conn, source_id="src-a", job_listing_id="corr-sub",
            category="software_engineering", level="mid", tags=[],
            note=None, admin_email="admin@test",
            subcategories=["backend", "full_stack"], subcategories_provided=True,
        )
        body = enrichment_client.get("/api/internal/enrichment/corrections").json()
        c = body["corrections"][0]
        assert c["subcategories"] == ["backend", "full_stack"]
        assert c["taxonomy_version"] == "v7+abc123def456"

    def test_feed_reports_an_unevaluated_row_as_null_not_empty(
        self, enrichment_client, db_conn
    ):
        """Tri-state survives the feed: null != []."""
        from api.services.enrichment_monitor import apply_correction

        _insert_job(db_conn, _make_job({
            "id": "corr-null", "source_id": "src-a",
            "details": json.dumps({"description_html": "<p>x</p>"}),
        }))
        apply_correction(
            db_conn, source_id="src-a", job_listing_id="corr-null",
            category="software_engineering", level="mid", tags=[],
            note=None, admin_email="admin@test",
        )
        body = enrichment_client.get("/api/internal/enrichment/corrections").json()
        c = body["corrections"][0]
        assert c["subcategories"] is None
        assert c["taxonomy_version"] is None

    def test_feed_stays_ordered_ascending_by_correction_time(
        self, enrichment_client, db_conn
    ):
        """`cli golden-merge --since` walks this feed forward and relies on it."""
        from api.services.enrichment_monitor import apply_correction

        for job_id in ("ord-1", "ord-2", "ord-3"):
            _insert_job(db_conn, _make_job({
                "id": job_id, "source_id": "src-a",
                "details": json.dumps({"description_html": "<p>x</p>"}),
            }))
            apply_correction(
                db_conn, source_id="src-a", job_listing_id=job_id,
                category="growth", level="mid", tags=[],
                note=None, admin_email="admin@test",
            )
        body = enrichment_client.get("/api/internal/enrichment/corrections").json()
        stamps = [c["corrected_at"] for c in body["corrections"]]
        assert stamps == sorted(stamps)


class TestSubcategoryResults:
    """SCHEMA-14: POST /subcategories — the only PARTIAL write path.

    What these actually guard is that the endpoint stays CHEAP and NARROW. The
    moment it touches anything besides the subcategory triple it stops being a
    drain and becomes a second way to clobber enrichment state.
    """

    URL = "/api/internal/enrichment/subcategories"

    def _seed(self, db_conn, job_id, source="google_scraper", **enrich):
        _insert_job(db_conn, _make_job({"id": job_id, "source_id": source}))
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_category='software_engineering', "
            "enrichment_level='senior', enrichment_status='done' "
            "WHERE source_id=%s AND id=%s",
            (source, job_id),
        )
        cur.execute(
            "INSERT INTO job_enrichment (source_id, job_listing_id, clean_description, "
            "classify_confidence, taxonomy_version, human_corrected_at) "
            "VALUES (%s, %s, 'the original description', 0.9, 'v6+aaa', %s)",
            (source, job_id, enrich.get("human_corrected_at")),
        )
        cur.execute(
            "INSERT INTO job_tags (source_id, job_listing_id, tag) VALUES (%s, %s, 'go')",
            (source, job_id),
        )
        if enrich.get("subcategory_source"):
            cur.execute(
                "UPDATE job_listings SET enrichment_subcategory_source=%s "
                "WHERE source_id=%s AND id=%s",
                (enrich["subcategory_source"], source, job_id),
            )
        db_conn.commit()

    def _snapshot(self, db_conn, job_id, source="google_scraper"):
        cur = db_conn.cursor()
        cur.execute(
            "SELECT jl.enrichment_category, jl.enrichment_level, "
            "jl.enrichment_status, je.clean_description, je.enriched_at, "
            "je.classify_confidence, "
            "COALESCE((SELECT json_agg(tag ORDER BY tag) FROM job_tags "
            "  WHERE source_id=jl.source_id AND job_listing_id=jl.id), '[]'::json) AS tags "
            "FROM job_listings jl JOIN job_enrichment je "
            "  ON je.source_id=jl.source_id AND je.job_listing_id=jl.id "
            "WHERE jl.source_id=%s AND jl.id=%s",
            (source, job_id),
        )
        return dict(cur.fetchone())

    def test_a_batch_writes_the_arrays_AND_TOUCHES_NOTHING_ELSE(
        self, enrichment_client, db_conn
    ):
        """The cheapness assertion, byte-for-byte.

        If this endpoint ever starts writing `clean_description` or bumping
        `enriched_at`, it is no longer a partial write path — it is `/results`
        with extra steps, and the whole reason it exists is gone.
        """
        self._seed(db_conn, "sr-1")
        self._seed(db_conn, "sr-2")
        before = {j: self._snapshot(db_conn, j) for j in ("sr-1", "sr-2")}

        resp = enrichment_client.post(
            self.URL,
            json={
                "items": [
                    {
                        "jobListingId": "sr-1", "sourceId": "google_scraper",
                        "subcategories": ["infrastructure_platform", "backend"],
                        "subcategoryConfidence": 0.82,
                        "subcategorySource": "backfill",
                        "taxonomyVersion": "v7+abc123abc123",
                    },
                    {
                        "jobListingId": "sr-2", "sourceId": "google_scraper",
                        "subcategories": [], "subcategorySource": "backfill",
                        "taxonomyVersion": "v7+abc123abc123",
                    },
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["written"] == 2
        db_conn.commit()

        cur = db_conn.cursor()
        cur.execute(
            "SELECT id, enrichment_subcategories AS s, enrichment_subcategory_source "
            "AS src FROM job_listings WHERE id IN ('sr-1','sr-2') ORDER BY id"
        )
        rows = {r["id"]: r for r in cur.fetchall()}
        # ORDER preserved: index 0 is the primary.
        assert rows["sr-1"]["s"] == ["infrastructure_platform", "backend"]
        assert rows["sr-1"]["src"] == "backfill"
        assert rows["sr-2"]["s"] == []

        for job_id in ("sr-1", "sr-2"):
            after = self._snapshot(db_conn, job_id)
            for field in ("enrichment_category", "enrichment_level",
                          "enrichment_status", "clean_description",
                          "enriched_at", "classify_confidence", "tags"):
                assert after[field] == before[job_id][field], (
                    f"{job_id}.{field} changed — this endpoint must touch ONLY "
                    "the subcategory triple"
                )

        cur.execute(
            "SELECT subcategory_confidence AS c, taxonomy_version AS v "
            "FROM job_enrichment WHERE job_listing_id='sr-1'"
        )
        audit = cur.fetchone()
        assert audit["c"] == 0.82
        assert audit["v"] == "v7+abc123abc123"

    def test_a_human_LOCKED_row_is_skipped_and_reported(
        self, enrichment_client, db_conn
    ):
        self._seed(db_conn, "sr-human", subcategory_source="human")
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_subcategories='{frontend}'::text[] "
            "WHERE id='sr-human'"
        )
        db_conn.commit()

        resp = enrichment_client.post(
            self.URL,
            json={"items": [{"jobListingId": "sr-human",
                             "sourceId": "google_scraper",
                             "subcategories": ["backend"],
                             "subcategorySource": "backfill"}]},
        )
        body = resp.json()
        assert body["written"] == 0
        assert body["skipped"][0]["job_listing_id"] == "sr-human"
        db_conn.commit()
        cur.execute("SELECT enrichment_subcategories AS s FROM job_listings "
                    "WHERE id='sr-human'")
        assert cur.fetchone()["s"] == ["frontend"]

    def test_human_corrected_at_ALONE_does_NOT_block_the_write(
        self, enrichment_client, db_conn
    ):
        """THE PER-FIELD FIX.

        `human_corrected_at` means a human fixed the category or level — usually
        before subcategories existed at all. Treating it as a subcategory lock
        would make the backfill permanently miss exactly the human-labelled pool
        the eval gate is built on.
        """
        self._seed(db_conn, "sr-hc", human_corrected_at="2026-01-01T00:00:00Z")

        resp = enrichment_client.post(
            self.URL,
            json={"items": [{"jobListingId": "sr-hc", "sourceId": "google_scraper",
                             "subcategories": ["backend"],
                             "subcategorySource": "backfill"}]},
        )
        assert resp.json()["written"] == 1, resp.text
        db_conn.commit()
        cur = db_conn.cursor()
        cur.execute("SELECT enrichment_subcategories AS s FROM job_listings "
                    "WHERE id='sr-hc'")
        assert cur.fetchone()["s"] == ["backend"]

    def test_out_of_enum_slug_is_dropped_with_a_warning_never_a_422(
        self, enrichment_client, db_conn
    ):
        self._seed(db_conn, "sr-bad")
        resp = enrichment_client.post(
            self.URL,
            json={"items": [{"jobListingId": "sr-bad", "sourceId": "google_scraper",
                             "subcategories": ["backend", "ai_ml"],
                             "subcategorySource": "backfill"}]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["written"] == 1
        assert any("ai_ml" in w for w in body["warnings"][0]["warnings"])

    def test_an_unknown_key_422s_LOUDLY(self, enrichment_client, db_conn):
        """One client, no legacy fleet. An accidental `category` key must fail
        loudly rather than read as "wrote nothing, reported success"."""
        self._seed(db_conn, "sr-extra")
        resp = enrichment_client.post(
            self.URL,
            json={"items": [{"jobListingId": "sr-extra", "sourceId": "google_scraper",
                             "subcategories": ["backend"], "category": "growth"}]},
        )
        assert resp.status_code == 200
        # The ELEMENT fails (per-row isolation), not the batch.
        body = resp.json()
        assert body["written"] == 0
        assert body["failed"][0]["job_listing_id"] == "sr-extra"
        assert "category" in body["failed"][0]["error"]

    def test_a_mis_keyed_envelope_422s_up_front(self, enrichment_client):
        resp = enrichment_client.post(
            self.URL, json={"results": [{"jobListingId": "x", "sourceId": "y"}]}
        )
        assert resp.status_code == 422

    def test_over_500_items_422s(self, enrichment_client):
        items = [
            {"jobListingId": f"j{i}", "sourceId": "s", "subcategories": []}
            for i in range(501)
        ]
        resp = enrichment_client.post(self.URL, json={"items": items})
        assert resp.status_code == 422

    def test_an_unknown_job_lands_in_failed_not_written(
        self, enrichment_client, db_conn
    ):
        resp = enrichment_client.post(
            self.URL,
            json={"items": [{"jobListingId": "ghost", "sourceId": "nowhere",
                             "subcategories": ["backend"]}]},
        )
        body = resp.json()
        assert body["written"] == 0
        assert body["failed"][0]["job_listing_id"] == "ghost"

    def test_an_item_with_NO_subcategories_key_FAILS_and_writes_nothing(
        self, enrichment_client, db_conn
    ):
        """⚠ §1.2(B): the key may NOT be absent on this endpoint.

        There is nothing else in a subcategory item, so an item without the key
        said nothing at all — and the value it would otherwise be read as (null)
        NULLs an existing label array AND its source. The writer raises for the
        `_UNSET` case, but `model_dump()` flattens absent into `None`, so that
        guard is only reachable because the route pops the key when Pydantic
        reports it unset. Without the pop this returns `written: 1` and quietly
        destroys the backfill's work.
        """
        self._seed(db_conn, "sr-absent")
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_subcategories='{backend}'::text[], "
            "enrichment_subcategory_source='backfill' WHERE id='sr-absent'"
        )
        db_conn.commit()

        resp = enrichment_client.post(
            self.URL,
            json={"items": [{"jobListingId": "sr-absent",
                             "sourceId": "google_scraper",
                             "taxonomyVersion": "v7+abc123abc123"}]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["written"] == 0
        assert body["failed"][0]["job_listing_id"] == "sr-absent"
        assert "missing subcategories" in body["failed"][0]["error"]
        db_conn.commit()

        cur.execute(
            "SELECT enrichment_subcategories AS s, enrichment_subcategory_source "
            "AS src FROM job_listings WHERE id='sr-absent'"
        )
        row = cur.fetchone()
        assert row["s"] == ["backend"]
        assert row["src"] == "backfill"

    def test_an_EXPLICIT_null_is_accepted_and_requeues_the_row(
        self, enrichment_client, db_conn
    ):
        """The counterpart: absent is a client bug, null is a real instruction.

        Popping the key unconditionally would pass the test above while making
        the "never evaluated, re-queue me" state unsendable on the one endpoint
        the backfill uses.
        """
        self._seed(db_conn, "sr-null")
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_subcategories='{backend}'::text[], "
            "enrichment_subcategory_source='backfill' WHERE id='sr-null'"
        )
        db_conn.commit()

        resp = enrichment_client.post(
            self.URL,
            json={"items": [{"jobListingId": "sr-null",
                             "sourceId": "google_scraper",
                             "subcategories": None}]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["written"] == 1
        db_conn.commit()

        cur.execute(
            "SELECT enrichment_subcategories AS s, enrichment_subcategory_source "
            "AS src FROM job_listings WHERE id='sr-null'"
        )
        row = cur.fetchone()
        assert row["s"] is None
        assert row["src"] is None

    def test_a_non_swe_row_is_forced_to_null_with_a_warning(
        self, enrichment_client, db_conn
    ):
        self._seed(db_conn, "sr-growth")
        cur = db_conn.cursor()
        cur.execute(
            "UPDATE job_listings SET enrichment_category='growth' WHERE id='sr-growth'"
        )
        db_conn.commit()
        resp = enrichment_client.post(
            self.URL,
            json={"items": [{"jobListingId": "sr-growth", "sourceId": "google_scraper",
                             "subcategories": ["backend"]}]},
        )
        assert resp.status_code == 200, resp.text
        db_conn.commit()
        cur.execute("SELECT enrichment_subcategories AS s FROM job_listings "
                    "WHERE id='sr-growth'")
        assert cur.fetchone()["s"] is None


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
