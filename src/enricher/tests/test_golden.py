"""EV-3: the golden-seed loader/merger seam.

The four assertions that matter here are all against SILENT failures:
  * `build_golden_set` used to DESTROY four live seed keys with no error;
  * `load_truth`'s base predicate made a subcategory-only correction invisible;
  * contract rows would clear GATE_MIN_N on a pool carrying zero information;
  * a missing audit file used to have no defined meaning.
"""

import json

import pytest

import job_enricher.eval.golden as golden
from job_enricher.eval.golden import (
    load_truth,
    merge_corrections,
    stamp_contract_rows,
)


def _row(jid, **kw):
    base = {
        "job_listing_id": jid, "source_id": "greenhouse", "title": f"T{jid}",
        "company": "acme", "raw_location": "SF", "description_html": "<p>x</p>",
        "label_source": "draft", "category": "software_engineering", "level": "mid",
        "level_includes": ["mid"], "tags": [], "locations": None,
    }
    base.update(kw)
    return base


@pytest.fixture
def seed(monkeypatch, tmp_path):
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    seed_file = seed_dir / "golden.json"
    monkeypatch.setattr(golden, "SEED_DIR", seed_dir)
    monkeypatch.setattr(golden, "SEED_FILE", seed_file)

    def write(rows):
        seed_file.write_text(json.dumps(rows))

    write.dir = seed_dir
    write.file = seed_file
    return write


# --- (a) the landmine ------------------------------------------------------


def test_build_golden_set_roundtrip_destroys_no_keys(seed, monkeypatch):
    """⚠ THE LANDMINE TEST, on all four keys the 12-key literal destroyed."""
    seed([
        _row("1", clean_description="already clean", department="Platform",
             hard_case=True, human_decision="kept as SWE",
             subcategories=["backend"], gold_subcategory_provenance="human",
             split="train", label_source="human"),
    ])

    class _FakeClient:
        def sample(self, n=150, stratify="company"):
            # JVN returns ONLY the six sourced fields — a refreshed title, even.
            return [{
                "job_listing_id": "1", "source_id": "greenhouse",
                "title": "Senior Backend Engineer", "company": "acme",
                "raw_location": "NYC", "description_html": "<p>new</p>",
            }]

    monkeypatch.setattr("job_enricher.jvn_client.JVNClient", lambda *a, **k: _FakeClient())
    golden.build_golden_set(n=1)
    out = golden.load_seed()[0]

    # the four keys the old rebuild destroyed
    assert out["clean_description"] == "already clean"
    assert out["department"] == "Platform"
    assert out["hard_case"] is True
    assert out["human_decision"] == "kept as SWE"
    # and the new facet keys
    assert out["subcategories"] == ["backend"]
    assert out["gold_subcategory_provenance"] == "human"
    assert out["split"] == "train"
    assert out["label_source"] == "human"
    # the JVN-sourced half IS refreshed
    assert out["title"] == "Senior Backend Engineer"
    assert out["raw_location"] == "NYC"


def test_build_golden_set_gives_a_brand_new_row_blank_labels(seed, monkeypatch):
    seed([])

    class _FakeClient:
        def sample(self, n=150, stratify="company"):
            return [{
                "job_listing_id": "9", "source_id": "lever", "title": "SWE",
                "company": "beta", "raw_location": "SF", "description_html": "<p>x</p>",
            }]

    monkeypatch.setattr("job_enricher.jvn_client.JVNClient", lambda *a, **k: _FakeClient())
    golden.build_golden_set(n=1)
    out = golden.load_seed()[0]
    assert out["label_source"] == ""
    assert out["category"] is None
    assert out["subcategories"] is None
    assert out["gold_subcategory_provenance"] is None
    assert out["split"] is None


# --- (c) the facet-aware loader -------------------------------------------


def test_load_truth_sees_a_subcategory_only_correction(seed):
    """⚠ The old base predicate (`category or level`) dropped this row."""
    seed([_row("1", category=None, level=None, subcategories=["backend"],
               label_source="human", gold_subcategory_provenance="human")])
    assert len(load_truth(human_only=True)) == 1


def test_load_truth_subcategory_facet_ignores_category_label_source(seed):
    seed([
        # draft category label, but a HUMAN subcategory label -> admitted
        _row("1", label_source="draft", subcategories=["backend"],
             gold_subcategory_provenance="human"),
        # human category label, but no subcategory label -> not admitted
        _row("2", label_source="human"),
    ])
    pool = load_truth(facet="subcategory")
    assert [r["job_listing_id"] for r in pool] == ["1"]


def test_load_truth_subcategory_facet_excludes_contract_rows(seed):
    """⚠ THE FAKE-N TRAP. 150 of 285 real rows are contract rows."""
    seed([
        _row("1", category="business_ops", subcategories=[],
             gold_subcategory_provenance="contract"),
        _row("2", category="product_manager", subcategories=[],
             gold_subcategory_provenance="contract"),
    ])
    assert load_truth(facet="subcategory") == []


def test_load_truth_subcategory_facet_excludes_non_swe_parents(seed):
    seed([_row("1", category="data_scientist", subcategories=["ml_engineering"],
               gold_subcategory_provenance="human")])
    assert load_truth(facet="subcategory") == []


@pytest.mark.parametrize("audit,expected", [
    (None, []),                      # ⚠ MISSING FILE == NOT PASSED
    ({"passed": False}, []),
    ({"passed": True}, ["1"]),
])
def test_prelabel_agreed_rows_need_a_passing_audit(seed, audit, expected):
    seed([_row("1", subcategories=["backend"],
               gold_subcategory_provenance="prelabel_agreed")])
    if audit is not None:
        (seed.dir / "subcategory_audit.json").write_text(json.dumps(audit))
    assert [r["job_listing_id"] for r in load_truth(facet="subcategory")] == expected


def test_train_split_rows_are_excluded_from_both_pools(seed):
    seed([
        _row("1", label_source="human", subcategories=["backend"],
             gold_subcategory_provenance="human", split="train"),
        _row("2", label_source="human", subcategories=["frontend"],
             gold_subcategory_provenance="human", split="test"),
    ])
    assert [r["job_listing_id"] for r in load_truth(human_only=True)] == ["2"]
    assert [r["job_listing_id"] for r in load_truth(facet="subcategory")] == ["2"]


# --- (d) stamp_contract_rows ----------------------------------------------


def test_stamp_contract_rows_marks_only_non_swe_and_is_idempotent(seed):
    seed([
        _row("1", category="software_engineering"),
        _row("2", category="business_ops"),
        _row("3", category="growth"),
    ])
    assert stamp_contract_rows() == 2
    rows = {r["job_listing_id"]: r for r in golden.load_seed()}
    assert rows["1"].get("subcategories") is None
    assert rows["2"] == dict(rows["2"], subcategories=[],
                             gold_subcategory_provenance="contract")
    assert rows["3"]["gold_subcategory_provenance"] == "contract"
    assert stamp_contract_rows() == 0  # idempotent


# --- (e) merge_corrections -------------------------------------------------


def test_merge_corrections_folds_subcategories(seed):
    seed([_row("1", subcategories=None)])
    report = merge_corrections([{
        "source_id": "greenhouse", "job_listing_id": "1",
        "category": "software_engineering", "subcategories": ["infrastructure_platform"],
    }])
    assert report == {"matched": 1, "upgraded": 1, "unmatched": 0, "parked": 0,
                      "subcategory_upgraded": 1}
    row = golden.load_seed()[0]
    assert row["subcategories"] == ["infrastructure_platform"]
    assert row["gold_subcategory_provenance"] == "human"
    assert [r["job_listing_id"] for r in load_truth(facet="subcategory")] == ["1"]


def test_a_correction_moving_category_off_swe_nulls_subcategories(seed):
    seed([_row("1", subcategories=["backend"], gold_subcategory_provenance="human")])
    merge_corrections([{
        "source_id": "greenhouse", "job_listing_id": "1", "category": "data_scientist",
    }])
    row = golden.load_seed()[0]
    assert row["subcategories"] == []
    assert row["gold_subcategory_provenance"] == "contract"
    assert load_truth(facet="subcategory") == []


def test_a_correction_lacking_a_facet_leaves_that_facet_intact(seed):
    """⚠ The tolerant parse. A pre-v7 correction carries NO `subcategories` key."""
    seed([_row("1", subcategories=["backend"], gold_subcategory_provenance="human",
               tags=["python"])])
    merge_corrections([{
        "source_id": "greenhouse", "job_listing_id": "1", "level": "senior",
        "category": "software_engineering",
    }])
    row = golden.load_seed()[0]
    assert row["subcategories"] == ["backend"]
    assert row["gold_subcategory_provenance"] == "human"
    assert row["tags"] == ["python"]
    assert row["level"] == "senior"


# --- EV-16: NO-APPEND, and the parked worklist ----------------------------


def test_an_unmatched_correction_is_parked_and_the_seed_does_not_grow(seed, monkeypatch, tmp_path):
    """⚠ THE DECISION, PINNED. The seed does not grow from the correction feed.
    Three verified reasons live in merge_corrections' docstring; this test is
    what stops the behaviour drifting back."""
    worklist = tmp_path / "unmatched-corrections.json"
    monkeypatch.setattr(golden, "UNMATCHED_WORKLIST", worklist)
    seed([_row("1")])
    report = merge_corrections([
        {"source_id": "greenhouse", "job_listing_id": "1", "level": "senior"},
        {"source_id": "lever", "job_listing_id": "999", "category": "growth"},
    ])
    assert report["unmatched"] == 1 and report["parked"] == 1
    assert len(golden.load_seed()) == 1
    parked = json.loads(worklist.read_text())
    assert [p["job_listing_id"] for p in parked] == ["999"]


def test_the_parked_worklist_is_append_only_and_deduped(seed, monkeypatch, tmp_path):
    worklist = tmp_path / "unmatched-corrections.json"
    monkeypatch.setattr(golden, "UNMATCHED_WORKLIST", worklist)
    seed([_row("1")])
    c = {"source_id": "lever", "job_listing_id": "999", "category": "growth"}
    assert merge_corrections([c])["parked"] == 1
    assert merge_corrections([c])["parked"] == 0          # deduped
    assert merge_corrections([dict(c, job_listing_id="1000")])["parked"] == 1
    assert len(json.loads(worklist.read_text())) == 2      # append-only


def test_a_pre_v7_confirmed_correct_row_yields_no_subcategory_label(seed):
    """A correction from before ADM-5 carries no `subcategories` key at all."""
    seed([_row("1", subcategories=None, gold_subcategory_provenance=None)])
    merge_corrections([{
        "source_id": "greenhouse", "job_listing_id": "1", "decision": "confirmed_correct",
        "category": "software_engineering", "level": "mid", "tags": [],
    }])
    row = golden.load_seed()[0]
    assert row["subcategories"] is None
    assert row["gold_subcategory_provenance"] is None
    assert load_truth(facet="subcategory") == []


def test_the_v7_correction_contract_is_asserted_loudly():
    """⚠ THE CONTRACT TEST. If ADM-5 slips, `subcategories` and
    `taxonomy_version` are simply absent — golden-merge then runs GREEN and
    writes no subcategory gold at all. This is what makes that a red build
    instead of a silent no-op."""
    from job_enricher.jvn_client import CORRECTION_V7_KEYS, missing_v7_correction_keys

    pre_v7 = {"job_listing_id": "1", "source_id": "greenhouse",
              "category": "software_engineering", "level": "mid", "tags": []}
    assert missing_v7_correction_keys(pre_v7) == ["subcategories", "taxonomy_version"]

    partial = dict(pre_v7, subcategories=["backend"])
    assert missing_v7_correction_keys(partial) == ["taxonomy_version"]

    full = dict(partial, taxonomy_version="v7+abc123def456")
    assert missing_v7_correction_keys(full) == []
    assert CORRECTION_V7_KEYS == {"subcategories", "taxonomy_version"}
