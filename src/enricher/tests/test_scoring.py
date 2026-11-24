import pytest

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


# ===========================================================================
# EV-5: the subcategory metric block — scored ONLY under an SWE parent, on its
# own denominator and its own min-n.
# ===========================================================================

from job_enricher.eval.scoring import (  # noqa: E402
    _FACET_GROUPS, GATE_MIN_N, gated_facets, group_denominator,
)
from job_enricher.taxonomy import SUBCATEGORIES  # noqa: E402


def _srow(jid, cat="software_engineering", subs=None, lvl="mid", sub_conf=None):
    r = {"job_listing_id": jid, "category": cat, "level": lvl, "tags": [],
         "subcategories": subs}
    if sub_conf is not None:
        r["subcategory_confidence"] = sub_conf
    return r


def test_subcategories_are_disjoint_from_categories_and_number_seventeen():
    assert len(SUBCATEGORIES) == 17
    assert not (SUBCATEGORIES & CATEGORIES)


def test_a_non_swe_gold_row_is_skipped_not_wrong():
    """⚠ A non-SWE row has no subcategory answer, so it must not enter the
    denominator. Counting it wrong would report a facet failing on rows it
    does not apply to."""
    truth = [_srow("1", cat="business_ops", subs=None)]
    preds = [_srow("1", cat="business_ops", subs=None)]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_n"] == 0


def test_a_gold_swe_row_with_null_subcategories_is_skipped():
    sc = score([_srow("1", subs=["backend"])], [_srow("1", subs=None)]).to_dict()
    assert sc["subcategory_n"] == 0


def test_contract_rows_never_enter_the_subcategory_denominator():
    """⚠ THE FAKE-N TRAP. Contract rows are non-SWE rows stamped `[]`; they are
    leak-measurement rows, not gold subcategory rows."""
    truth = [_srow(str(i), cat="business_ops", subs=[]) for i in range(60)]
    preds = [_srow(str(i), cat="business_ops", subs=[]) for i in range(60)]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_n"] == 0
    assert sc["subcategory_nonswe_n"] == 60


def test_primary_uses_element_zero_and_both_empty_counts_correct():
    truth = [_srow("1", subs=["backend", "frontend"]), _srow("2", subs=[])]
    preds = [_srow("1", subs=["backend", "security"]), _srow("2", subs=[])]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_primary_accuracy"] == 1.0        # both rows
    assert sc["subcategory_primary_accuracy_nonempty"] == 1.0  # only row 1


def test_nonempty_variant_excludes_the_free_both_empty_hit():
    """⚠ Abstention must not inflate the GATED headline."""
    truth = [_srow("1", subs=["backend"]), _srow("2", subs=[])]
    preds = [_srow("1", subs=["frontend"]), _srow("2", subs=[])]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_primary_accuracy"] == 0.5
    assert sc["subcategory_primary_accuracy_nonempty"] == 0.0


def test_set_f1_is_order_insensitive():
    a = score([_srow("1", subs=["backend", "security"])],
              [_srow("1", subs=["security", "backend"])]).to_dict()
    assert a["subcategory_set_f1"] == 1.0
    assert a["subcategory_jaccard"] == 1.0


def test_jaccard_both_empty_is_one():
    sc = score([_srow("1", subs=[])], [_srow("1", subs=[])]).to_dict()
    assert sc["subcategory_jaccard"] == 1.0


def test_macro_f1_ignores_zero_support_classes():
    sc = score([_srow("1", subs=["backend"])], [_srow("1", subs=["backend"])]).to_dict()
    assert sc["subcategory_f1_macro"] == 1.0
    assert set(sc["subcategory_f1_per_class"]) == {"backend"}
    assert isinstance(sc["subcategory_f1_per_class"]["backend"], float)


def test_coverage_counts_abstentions_as_uncovered():
    truth = [_srow("1", subs=["backend"]), _srow("2", subs=["frontend"])]
    preds = [_srow("1", subs=["backend"]), _srow("2", subs=[])]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_coverage"] == 0.5


def test_nulled_rate_counts_never_evaluated_predictions():
    truth = [_srow("1", subs=["backend"]), _srow("2", subs=["frontend"])]
    preds = [_srow("1", subs=["backend"]), _srow("2", subs=None)]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_nulled_rate"] == 0.5
    assert sc["subcategory_coverage"] == 0.5


def test_leak_rate_fires_on_a_prediction_over_a_non_swe_gold_row():
    truth = [_srow("1", cat="business_ops", subs=[]),
             _srow("2", cat="growth", subs=[])]
    preds = [_srow("1", cat="business_ops", subs=["backend"]),
             _srow("2", cat="growth", subs=[])]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_nonswe_n"] == 2
    assert sc["subcategory_leak_rate"] == 0.5


def test_cardinality_and_over_cap():
    truth = [_srow("1", subs=["backend"]), _srow("2", subs=["backend"])]
    preds = [_srow("1", subs=["backend", "security", "mobile"]),
             _srow("2", subs=["backend"])]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_cardinality_mean"] == 2.0
    assert sc["subcategory_over_cap"] == 1


def test_exclusivity_fires_on_full_stack_beside_a_half():
    truth = [_srow("1", subs=["full_stack"])]
    preds = [_srow("1", subs=["full_stack", "backend"])]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_exclusivity_violations"] == 1


def test_accuracy_given_parent_correct_conditions_on_the_category():
    truth = [_srow("1", subs=["backend"]), _srow("2", subs=["frontend"])]
    preds = [
        _srow("1", subs=["backend"]),
        # category wrong -> the subcategory never had a chance; excluded from
        # the conditional metric but still in the unconditional one
        _srow("2", cat="business_ops", subs=["frontend"]),
    ]
    sc = score(preds, truth).to_dict()
    assert sc["subcategory_accuracy_given_parent_correct"] == 1.0
    assert sc["subcategory_primary_accuracy"] == 1.0


def test_subcategory_calibration_uses_its_own_confidence_field():
    """⚠ NEVER the shared `confidence` — that is what routes the judge."""
    truth = [_srow("1", subs=["backend"]), _srow("2", subs=["frontend"])]
    preds = [
        dict(_srow("1", subs=["security"], sub_conf=0.4), confidence=0.99),
        dict(_srow("2", subs=["frontend"], sub_conf=0.4), confidence=0.99),
    ]
    sc = score(preds, truth).to_dict()
    assert sc["calibration_error_rate_below_sub"] == 0.5
    # the shared-confidence pair is untouched by subcategory outcomes
    assert sc["calibration_error_rate_below"] is None


# --- the comparability guard ----------------------------------------------


def _comparability_fixture():
    truth = [
        _row("1", "software_engineering", "senior", tags=["python"], conf=0.9),
        _row("2", "business_ops", "new_grad", tags=["excel"], conf=0.9),
        _row("3", "data_scientist", "mid", tags=["sql"], conf=0.9),
    ]
    preds = [
        _row("1", "software_engineering", "senior", tags=["python"], conf=0.9, jp=True),
        _row("2", "business_ops", "new_grad", tags=["excel"], conf=0.5, jp=True),
        _row("3", "growth", "mid", tags=["sql"], conf=0.4, jp=False),
    ]
    return preds, truth


def test_preexisting_metrics_are_byte_identical_after_the_subcategory_additions():
    """⚠ THE COMPARABILITY GUARD. `baseline.json` commits 0.4937 / 0.1702 /
    0.0319 for the calibration and κ values; redefining `row_error` or the κ
    correctness definition destroys before/after comparability with every
    committed baseline. These are the values the additions must not move."""
    preds, truth = _comparability_fixture()
    sc = score(preds, truth, prejudge_predictions=preds).to_dict()
    assert sc["category_accuracy"] == 0.6667
    assert sc["level_exact_accuracy"] == 1.0
    assert sc["level_filter_consistent_accuracy"] == 1.0
    assert sc["tags_token_f1"] == 1.0
    assert sc["calibration_error_rate_below"] == 0.5
    assert sc["calibration_error_rate_above"] == 0.0
    assert sc["judge_kappa_prejudge"] == 1.0
    assert sc["n"] == 3


def test_the_subcategory_calibration_keys_exist_alongside_the_originals():
    preds, truth = _comparability_fixture()
    sc = score(preds, truth).to_dict()
    assert "calibration_error_rate_below_sub" in sc
    assert "calibration_error_rate_below" in sc
    assert sc["calibration_error_rate_below_sub"] is None  # no sub confidences


# --- the gate groups -------------------------------------------------------


def test_a_thin_category_pool_does_not_suppress_the_subcategory_group():
    """⚠ The old gate RETURNED on the min-n refusal, so a thin category pool
    kept the subcategory gate permanently inert."""
    truth = [_srow(str(i), subs=["backend"]) for i in range(GATE_MIN_N + 5)]
    preds = [_srow(str(i), subs=["frontend"]) for i in range(GATE_MIN_N + 5)]
    sc = score(preds, truth)
    # force a thin CATEGORY denominator while the subcategory pool is fat
    sc.category.n = 3
    fails = regression_gate(
        sc,
        {"category_accuracy": 0.9, "subcategory_set_f1": 0.9},
        groups=("category", "subcategory"),
    )
    assert any("category gate refused" in f for f in fails)
    assert any(f.startswith("subcategory_set_f1:") for f in fails)


def test_the_subcategory_group_uses_its_own_denominator():
    sc = score([_srow("1", subs=["backend"])], [_srow("1", subs=["backend"])])
    sc.category.n = 500
    fails = regression_gate(sc, {"subcategory_set_f1": 0.9}, groups=("subcategory",))
    assert len(fails) == 1 and "subcategory gate refused" in fails[0]
    assert group_denominator(sc, "subcategory") == 1
    assert group_denominator(sc, "category") == 500


def test_leak_rate_gates_with_an_inverted_comparison():
    truth = [_srow(str(i), cat="business_ops", subs=[]) for i in range(GATE_MIN_N)]
    truth += [_srow("swe" + str(i), subs=["backend"]) for i in range(GATE_MIN_N)]
    preds = [_srow(str(i), cat="business_ops", subs=["backend"]) for i in range(GATE_MIN_N)]
    preds += [_srow("swe" + str(i), subs=["backend"]) for i in range(GATE_MIN_N)]
    sc = score(preds, truth)
    fails = regression_gate(sc, {"subcategory_leak_rate": 0.0}, groups=("subcategory",))
    assert any("higher is worse" in f for f in fails)


def test_the_category_group_is_byte_identical_to_the_pre_change_tuple():
    assert _FACET_GROUPS["category"] == (
        "category_accuracy", "category_f1_macro", "level_exact_accuracy",
        "level_filter_consistent_accuracy", "tags_token_f1", "location_primary_accuracy",
    )
    assert gated_facets() == _FACET_GROUPS["category"]
    assert gated_facets(("category", "subcategory")) == (
        _FACET_GROUPS["category"] + _FACET_GROUPS["subcategory"]
    )


def test_judge_lift_covers_the_subcategory_set_f1():
    from job_enricher.eval.scoring import judge_lift as _jl
    on = score([_srow("1", subs=["backend"])], [_srow("1", subs=["backend"])])
    off = score([_srow("1", subs=["frontend"])], [_srow("1", subs=["backend"])])
    assert _jl(on, off)["subcategory_set_f1"] == 1.0


# ===========================================================================
# EV-5b: making the category gate SENSITIVE at n~=67
# ===========================================================================

from job_enricher.eval.scoring import (  # noqa: E402
    exact_binomial_two_sided, paired_facet_deltas,
)
from job_enricher.eval.params import PARAM_MIN_CLASS_SUPPORT  # noqa: E402


def _paired_fixture(fixes, breaks, agree=0):
    """v6 vs v7 over the same rows: `fixes` rows v7 gets right that v6 got
    wrong, `breaks` rows the other way round, `agree` rows both get right."""
    truth, v6, v7 = [], [], []
    n = 0
    for _ in range(fixes):
        n += 1
        jid = str(n)
        truth.append(_row(jid, "software_engineering", "mid"))
        v6.append(_row(jid, "business_ops", "mid"))
        v7.append(_row(jid, "software_engineering", "mid"))
    for _ in range(breaks):
        n += 1
        jid = str(n)
        truth.append(_row(jid, "software_engineering", "mid"))
        v6.append(_row(jid, "software_engineering", "mid"))
        v7.append(_row(jid, "business_ops", "mid"))
    for _ in range(agree):
        n += 1
        jid = str(n)
        truth.append(_row(jid, "growth", "mid"))
        v6.append(_row(jid, "growth", "mid"))
        v7.append(_row(jid, "growth", "mid"))
    return v7, v6, truth


def test_paired_deltas_count_regressions_and_fixes_separately():
    v7, v6, truth = _paired_fixture(fixes=5, breaks=1)
    d = paired_facet_deltas(v7, v6, truth)["category"]
    assert (d["b"], d["c"], d["net"]) == (1, 5, 4)
    assert d["n_paired"] == 6
    # exact TWO-SIDED binomial on (min(b,c)=1, n=6): 2 * (C(6,0)+C(6,1)) / 2^6
    assert d["p_value"] == pytest.approx(14 / 64)


def test_a_symmetric_fixture_has_zero_net_and_p_one():
    v7, v6, truth = _paired_fixture(fixes=3, breaks=3)
    d = paired_facet_deltas(v7, v6, truth)["category"]
    assert d["net"] == 0
    assert d["p_value"] == 1.0


def test_two_versus_zero_yields_p_one_half():
    """⚠ THE CASE PARAM_PAIRED_MIN_NET EXISTS TO LET THROUGH. Two flips in one
    direction is not evidence, and a gate keyed on p alone would fail on it."""
    v7, v6, truth = _paired_fixture(fixes=0, breaks=2)
    d = paired_facet_deltas(v7, v6, truth)["category"]
    assert (d["b"], d["c"], d["net"]) == (2, 0, -2)
    assert d["p_value"] == 0.5


def test_rows_absent_from_either_prediction_file_are_skipped_and_counted():
    v7, v6, truth = _paired_fixture(fixes=2, breaks=0)
    v7 = v7 + [_row("orphan", "growth", "mid")]     # not in truth or baseline
    v6 = v6[:1]                                     # drop one from the baseline
    d = paired_facet_deltas(v7, v6, truth)["category"]
    assert d["n_paired"] == 1
    assert d["skipped"] == 2                        # the orphan + the dropped row


def test_the_identity_check_returns_all_zeros_and_no_p_value():
    """⚠ ACCEPTANCE: an artifact compared AGAINST ITSELF must be perfectly
    concordant. A non-zero here means the alignment is broken, not the model."""
    v7, _v6, truth = _paired_fixture(fixes=3, breaks=2, agree=4)
    for facet, d in paired_facet_deltas(v7, v7, truth).items():
        assert (d["b"], d["c"], d["net"]) == (0, 0, 0), facet
        assert d["p_value"] is None, facet


def test_exact_binomial_edges():
    assert exact_binomial_two_sided(0, 0) is None
    assert exact_binomial_two_sided(0, 1) == 1.0
    assert exact_binomial_two_sided(0, 2) == 0.5


def test_macro_f1_with_no_argument_is_unchanged():
    """⚠ THE COMPARABILITY GUARD for the macro. baseline.json commits 0.679."""
    preds, truth = _comparability_fixture()
    sc = score(preds, truth)
    assert sc._macro_f1() == sc._macro_f1(1)
    assert sc.to_dict()["category_f1_macro"] == round(sc._macro_f1(), 4)


def test_the_support_floor_drops_a_thin_class_and_names_it():
    truth = (
        [_row(str(i), "software_engineering", "mid") for i in range(10)]
        + [_row("g1", "growth", "mid"), _row("g2", "growth", "mid")]
    )
    preds = list(truth)
    sc = score(preds, truth).to_dict()
    assert PARAM_MIN_CLASS_SUPPORT == 5
    assert sc["category_f1_macro_excluded_classes"] == ["growth"]
    # with growth dropped only software_engineering remains
    assert sc["category_f1_macro_supported"] == 1.0
    # the unfloored macro still counts growth
    assert sc["category_f1_macro"] == 1.0


def test_the_support_floor_reports_a_thin_class_rather_than_hiding_it():
    truth = (
        [_row(str(i), "software_engineering", "mid") for i in range(10)]
        + [_row("g1", "growth", "mid"), _row("g2", "growth", "mid")]
    )
    preds = (
        [_row(str(i), "software_engineering", "mid") for i in range(10)]
        + [_row("g1", "growth", "mid"), _row("g2", "business_ops", "mid")]
    )
    sc = score(preds, truth).to_dict()
    # one flipped row out of two moves the raw macro a long way...
    assert sc["category_f1_macro"] < 0.90
    # ...but the floored one excludes it and NAMES it
    assert sc["category_f1_macro_excluded_classes"] == ["business_ops", "growth"]


def test_regression_gate_does_not_call_the_paired_functions():
    """⚠ (c) Both are PURE functions. regression_gate's signature and default
    behaviour stay frozen against every committed baseline; EV-12 invokes the
    paired arms explicitly."""
    import inspect

    src = inspect.getsource(regression_gate)
    assert "paired_facet_deltas" not in src
    assert "_macro_f1(" not in src


# ===========================================================================
# EV-14: calibration and judge-volume — measure both channels
# ===========================================================================


def test_the_judge_volume_channels_are_emitted():
    truth = [_row("1", "software_engineering", "mid"),
             _row("2", "software_engineering", "mid")]
    preds = [dict(_row("1", "software_engineering", "mid"), confidence=0.82,
                  needs_human=True),
             dict(_row("2", "software_engineering", "mid"), confidence=0.95,
                  needs_human=False)]
    sc = score(preds, truth).to_dict()
    # one of two rows sits below the 0.85 production ceiling
    assert sc["conf_below_ceiling_share"] == 0.5
    assert sc["conf_ceiling"] == 0.85
    assert sc["needs_human_rate"] == 0.5
    assert "subcategory_nulled_rate" in sc


def test_conf_below_ceiling_is_independent_of_conf_threshold():
    """⚠ The calibration split stays at 0.80 for comparability; the judge-volume
    channel is measured at the 0.85 PRODUCTION ceiling regardless."""
    truth = [_row("1", "software_engineering", "mid")]
    preds = [dict(_row("1", "software_engineering", "mid"), confidence=0.82)]
    for threshold in (0.5, 0.8, 0.95):
        sc = score(preds, truth, conf_threshold=threshold).to_dict()
        assert sc["conf_below_ceiling_share"] == 1.0
