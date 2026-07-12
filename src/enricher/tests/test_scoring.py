from job_enricher.eval.scoring import (
    cohens_kappa, judge_kappa_prejudge, judge_lift, regression_gate, score,
    _filter_consistent,
)
from job_enricher.taxonomy import CATEGORIES, LEVELS, validate_facets


def _row(jid, cat, lvl, tags=None, locs=None, conf=None, jp=None):
    r = {"job_listing_id": jid, "category": cat, "level": lvl, "tags": tags or []}
    if locs is not None:
        r["locations"] = locs
    if conf is not None:
        r["confidence"] = conf
    if jp is not None:
        r["judge_pass"] = jp
    return r


def test_category_and_level_exact():
    truth = [_row("1", "software_engineering", "senior"), _row("2", "business_ops", "new_grad")]
    preds = [_row("1", "software_engineering", "senior"), _row("2", "business_ops", "entry")]
    sc = score(preds, truth).to_dict()
    assert sc["category_accuracy"] == 1.0
    assert sc["level_exact_accuracy"] == 0.5
    assert sc["level_filter_consistent_accuracy"] == 1.0


def test_filter_consistency_rules():
    assert _filter_consistent("entry", "new_grad") is True
    assert _filter_consistent("new_grad", "entry") is False
    assert _filter_consistent("senior", "senior") is True
    assert _filter_consistent("mid", "senior") is False


def test_intern_is_a_valid_standalone_level():
    """intern is a first-class tier and, being standalone, is filter-consistent
    only with itself — it must NOT cross-credit with new_grad/entry either way."""
    assert "intern" in LEVELS
    assert _filter_consistent("intern", "intern") is True
    assert _filter_consistent("new_grad", "intern") is False
    assert _filter_consistent("intern", "new_grad") is False
    assert _filter_consistent("entry", "intern") is False
    assert _filter_consistent("intern", "entry") is False


def test_tags_prf():
    truth = [_row("1", "x", "mid", tags=["a", "b", "c"])]
    preds = [_row("1", "x", "mid", tags=["a", "b", "d"])]
    sc = score(preds, truth).to_dict()
    assert round(sc["tags_f1"], 3) == round(2 / 3, 3)


def test_tags_hyphen_token_credit():
    # gold splits a compound skill into two tags; pred keeps it hyphenated.
    # Exact set-match scores zero, but token-level F1 recognizes both tokens.
    truth = [_row("1", "x", "mid", tags=["motion", "planning"])]
    preds = [_row("1", "x", "mid", tags=["motion-planning"])]
    sc = score(preds, truth).to_dict()
    assert sc["tags_token_f1"] == 1.0
    assert sc["tags_jaccard"] == 0.0
    assert sc["tags_f1"] == 0.0


def test_tags_overlap_and_recall():
    # pred is a superset of gold: perfect recall/overlap, half Jaccard.
    truth = [_row("1", "x", "mid", tags=["a", "b"])]
    preds = [_row("1", "x", "mid", tags=["a", "b", "c", "d"])]
    sc = score(preds, truth).to_dict()
    assert sc["tags_recall"] == 1.0
    assert sc["tags_overlap"] == 1.0
    assert sc["tags_jaccard"] == 0.5


def test_location_primary():
    loc = [{"canonical_name": "San Francisco, CA, US", "is_primary": True}]
    other = [{"canonical_name": "Remote", "is_primary": True}]
    truth = [_row("1", "x", "mid", locs=loc)]
    assert score([_row("1", "x", "mid", locs=other)], truth).to_dict()["location_primary_accuracy"] == 0.0
    assert score([_row("1", "x", "mid", locs=loc)], truth).to_dict()["location_primary_accuracy"] == 1.0


def test_calibration_split():
    truth = [_row("1", "a", "mid"), _row("2", "a", "mid")]
    preds = [_row("1", "b", "mid", conf=0.5), _row("2", "a", "mid", conf=0.95)]
    sc = score(preds, truth).to_dict()
    assert sc["calibration_error_rate_below"] == 1.0
    assert sc["calibration_error_rate_above"] == 0.0


def test_kappa():
    assert cohens_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert round(cohens_kappa([1, 0, 1, 0], [0, 1, 0, 1]), 3) == -1.0


def test_macro_f1_skips_zero_support_classes():
    """Zero-support taxonomy classes must not dilute macro-F1: two perfectly
    predicted classes score 1.0, not 2/6."""
    truth = [_row("1", "software_engineering", "mid"), _row("2", "business_ops", "mid")]
    preds = [_row("1", "software_engineering", "mid"), _row("2", "business_ops", "mid")]
    sc = score(preds, truth).to_dict()
    assert sc["category_f1_macro"] == 1.0


def test_judge_kappa_prejudge_uses_pre_judge_labels():
    """κ compares the judge's verdict against the PRE-judge correctness: a row
    the judge failed AND fixed must count as agreement (the old post-merge
    computation counted it against the judge)."""
    truth = [_row("1", "software_engineering", "mid"), _row("2", "business_ops", "mid"),
             _row("3", "growth", "mid")]
    prejudge = [
        _row("1", "software_engineering", "mid"),  # correct pre-judge
        _row("2", "growth", "mid"),                # wrong pre-judge
        _row("3", "growth", "mid"),                # correct pre-judge
    ]
    judged = [
        _row("1", "software_engineering", "mid", jp=True),   # pass on correct -> agree
        _row("2", "business_ops", "mid", jp=False),          # fail on wrong (fixed!) -> agree
        _row("3", "growth", "mid", jp=True),                 # pass on correct -> agree
    ]
    truth_by_id = {t["job_listing_id"]: t for t in truth}
    k = judge_kappa_prejudge(judged, prejudge, truth_by_id)
    assert k == 1.0  # perfect agreement — including the successful correction
    # and the score() entry point wires it through
    sc = score(judged, truth, prejudge_predictions=prejudge)
    assert sc.to_dict()["judge_kappa_prejudge"] == 1.0
    # without the pre-judge file the metric is honestly absent
    assert score(judged, truth).to_dict()["judge_kappa_prejudge"] is None


def test_judge_lift_reports_per_facet_delta():
    truth = [_row("1", "software_engineering", "mid"), _row("2", "business_ops", "senior")]
    prejudge = [_row("1", "software_engineering", "mid"), _row("2", "growth", "senior")]
    judged = [_row("1", "software_engineering", "mid"), _row("2", "business_ops", "senior")]
    lift = judge_lift(score(judged, truth), score(prejudge, truth))
    assert lift["category_accuracy"] == 0.5  # judge fixed one of two categories
    assert lift["level_exact_accuracy"] == 0.0


def test_regression_gate_pass_and_fail():
    truth = [_row("1", "a", "mid"), _row("2", "a", "senior")]
    # perfect predictions (min_n lowered for the tiny fixture)
    good = score([_row("1", "a", "mid"), _row("2", "a", "senior")], truth)
    assert regression_gate(good, {"category_accuracy": 0.99, "level_exact_accuracy": 0.98}, min_n=2) == []
    # one category wrong -> accuracy 0.5, should regress vs a 0.99 baseline
    bad = score([_row("1", "b", "mid"), _row("2", "a", "senior")], truth)
    fails = regression_gate(bad, {"category_accuracy": 0.99}, min_n=2)
    assert any("category_accuracy" in f for f in fails)


def test_regression_gate_refuses_below_min_n():
    truth = [_row("1", "a", "mid")]
    tiny = score([_row("1", "a", "mid")], truth)
    fails = regression_gate(tiny, {"category_accuracy": 0.5})  # default min_n=50
    assert len(fails) == 1 and "min_n" in fails[0]


def test_project_manager_removed_and_scoring_tolerates_shrunk_categories():
    """v6 taxonomy dropped the project_manager category. It must be gone from
    CATEGORIES, treated as a hallucination by validate_facets, and the scorer
    (whose macro-F1 iterates CATEGORIES) must run cleanly over the shrunk set."""
    assert "project_manager" not in CATEGORIES
    assert "product_manager" in CATEGORIES  # the retained PM slug is unaffected
    # validate_facets nulls + flags the removed slug, and passes a valid one through
    cat, _lvl, bad = validate_facets("project_manager", "mid")
    assert cat is None and ("category", "project_manager") in bad
    assert validate_facets("product_manager", "mid") == ("product_manager", "mid", [])
    # category macro-F1 / accuracy compute over the current CATEGORIES without error
    truth = [_row("1", "product_manager", "mid"), _row("2", "business_ops", "senior")]
    preds = [_row("1", "product_manager", "mid"), _row("2", "business_ops", "senior")]
    sc = score(preds, truth).to_dict()
    assert sc["category_f1_macro"] == 1.0
    assert sc["category_accuracy"] == 1.0


def test_regression_gate_ignores_strict_tags_f1():
    """tags_f1 (strict exact set-match) is advisory — a collapse there alone
    must not fail the gate; tags_token_f1 is the gated tag metric."""
    truth = [_row(str(i), "a", "mid", tags=["motion", "planning"]) for i in range(60)]
    preds = [_row(str(i), "a", "mid", tags=["motion-planning"]) for i in range(60)]
    sc = score(preds, truth)
    assert sc.to_dict()["tags_f1"] == 0.0
    # baseline had perfect strict tags — but the gate no longer reads tags_f1
    fails = regression_gate(sc, {"tags_f1": 1.0, "category_accuracy": 0.9})
    assert fails == []
