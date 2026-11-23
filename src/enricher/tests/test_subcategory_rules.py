"""EV-4: the deterministic title+tag subcategory labeler.

This is the weak baseline a v7 model must beat AND the backfill's free layers,
so its hard rules are pinned here rather than left to the docstring.
"""

import pytest

from job_enricher import subcategory_rules as sr
from job_enricher.taxonomy import SUBCATEGORIES


# --- the arbiter -----------------------------------------------------------


def test_every_canonical_slug_has_at_least_one_title_pattern():
    """⚠ taxonomy.SUBCATEGORIES is the single arbiter: an 18th slug added there
    must fail HERE, not go quietly unlabelled forever."""
    assert set(sr._TITLE_PATTERNS) == set(SUBCATEGORIES)
    assert set(sr._PRIORITY) == set(SUBCATEGORIES)
    assert len(SUBCATEGORIES) == 17


def test_every_slug_is_reachable_from_some_title():
    """Each pattern actually fires on a plausible title — a pattern that can
    never match is the same as no coverage at all."""
    probes = {
        "ai_engineering": "AI Engineer, Agents",
        "backend": "Backend Engineer",
        "data_engineering": "Data Engineer",
        "devops_sre": "Site Reliability Engineer",
        "embedded_systems": "Firmware Engineer",
        "forward_deployed": "Forward Deployed Engineer",
        "frontend": "Frontend Engineer",
        "full_stack": "Full Stack Engineer",
        "growth_engineering": "Growth Engineer",
        "infrastructure_platform": "Platform Engineer",
        "ml_engineering": "Machine Learning Engineer",
        "mobile": "iOS Engineer",
        "product_engineering": "Product Engineer",
        "qa_testing": "QA Engineer",
        "quantitative": "Quantitative Developer",
        "robotics_autonomy": "Robotics Software Engineer",
        "security": "Security Engineer",
    }
    assert set(probes) == set(SUBCATEGORIES)
    for slug, title in probes.items():
        assert slug in sr.label_from_title(title), (slug, title)


# --- title layer -----------------------------------------------------------


def test_a_title_naming_one_specialty_yields_that_slug():
    assert sr.label_from_title("Senior Backend Engineer") == ["backend"]


def test_seniority_words_are_stripped_before_matching():
    assert sr.strip_seniority("Senior Staff Backend Engineer II") == "Backend Engineer"
    assert sr.label_from_title("Principal Frontend Engineer") == ["frontend"]


def test_a_multi_hit_title_yields_at_most_two_in_priority_order():
    slugs = sr.label_from_title("Backend Engineer, Robotics Perception Platform")
    assert len(slugs) <= 2
    # robotics_autonomy outranks infrastructure_platform and backend
    assert slugs[0] == "robotics_autonomy"


def test_a_no_specialty_title_yields_nothing():
    assert sr.label_from_title("Software Engineer") == []
    assert sr.label_from_title("Member of Technical Staff") == []
    assert sr.label_from_title("") == []
    assert sr.label_from_title(None) == []


def test_silicon_validation_is_embedded_not_qa():
    """⚠ "validation" in a hardware posting is silicon bring-up. Reading it as
    QA is the single most common mislabel in this corpus."""
    assert sr.label_from_title("Silicon Validation Software Engineer — GPU IP") == [
        "embedded_systems"
    ]


def test_qa_carries_no_bare_validation_pattern():
    assert "validation" not in sr._TITLE_PATTERNS["qa_testing"]


def test_full_stack_never_co_occurs_with_frontend_or_backend():
    for title in (
        "Full Stack Engineer, Frontend Platform",
        "Full-Stack Backend Engineer",
        "Fullstack Web Engineer",
    ):
        slugs = sr.label_from_title(title)
        assert "full_stack" in slugs
        assert "frontend" not in slugs and "backend" not in slugs


# --- tag layer -------------------------------------------------------------


@pytest.mark.parametrize("variant,canonical", [
    ("c-plus-plus", "c++"),
    ("cplusplus", "c++"),
    ("csharp", "c-sharp"),
    ("c#", "c-sharp"),
    ("cloud", "cloud"),
    ("cloud-computing", "cloud"),
    ("cloud-infrastructure", "cloud"),
    ("cloud-native", "cloud"),
    ("embedded", "embedded"),
    ("embedded-systems", "embedded"),
])
def test_synonym_collapse(variant, canonical):
    assert sr.normalize_tag(variant) == canonical
    assert sr.normalize_tag(variant.upper()) == canonical


def test_one_bucket_yields_that_slug():
    assert sr.label_from_tags(["react", "css", "tailwind"]) == ["frontend"]
    assert sr.label_from_tags(["cloud-native"]) == ["infrastructure_platform"]
    assert sr.label_from_tags(["embedded-systems"]) == ["embedded_systems"]


def test_zero_or_two_or_more_buckets_yield_nothing():
    assert sr.label_from_tags([]) == []
    assert sr.label_from_tags(["python", "typescript"]) == []      # zero buckets
    assert sr.label_from_tags(["react", "kubernetes"]) == []       # two buckets
    assert sr.label_from_tags(None) == []


def test_a_bare_ai_tag_yields_nothing():
    """⚠ 22% of SWE rows carry an ai/ml-family tag while being ordinary backend
    or full-stack work. The tag is marketing vocabulary, not a role signal."""
    assert sr.label_from_tags(["ai"]) == []
    assert sr.label_from_tags(["ai", "machine-learning", "llm"]) == []
    assert sr.label_from_tags(["ai", "django"]) == ["backend"]  # the ai tag is inert


def test_the_ai_ml_family_has_no_tag_bucket_at_all():
    assert "ai_engineering" not in sr._TAG_BUCKETS.values()
    assert "ml_engineering" not in sr._TAG_BUCKETS.values()


def test_forward_deployed_and_quantitative_have_no_tag_mapping():
    """⚠ Measured: ZERO tag coverage in the corpus. Stated explicitly so a
    reader does not assume the tag layer reaches them."""
    assert "forward_deployed" not in sr._TAG_BUCKETS.values()
    assert "quantitative" not in sr._TAG_BUCKETS.values()
    assert {"forward_deployed", "quantitative"} <= sr._UNCOVERED_BY_TAGS


def test_the_two_newest_slugs_are_title_only_too():
    """⚠ DELIBERATE, not an oversight. A `growth` tag is an ORG name that sits on
    marketing-adjacent rows too, and there is no technology tag that means "owns
    what ships" — a tag mapping for `product_engineering` would be the ownership-
    boilerplate trap in tag form (SUBCATEGORIES.md tie-breaker 14)."""
    assert "growth_engineering" not in sr._TAG_BUCKETS.values()
    assert "product_engineering" not in sr._TAG_BUCKETS.values()
    assert {"growth_engineering", "product_engineering"} <= sr._UNCOVERED_BY_TAGS


def test_a_growth_MARKETER_is_never_typed_here():
    """⚠ THE CATEGORY TRAP, pinned. A marketer is category `growth` and never
    reaches this module — but the regex must not type one either, or a
    mis-categorised row gets a confident engineering label on top."""
    assert sr.label_from_title("Growth Marketing Engineer") == []
    assert sr.label_from_title("Growth Marketing Manager") == []
    assert sr.label_from_title("Lifecycle Marketing Lead") == []


def test_product_engineering_outranks_full_stack_when_both_are_explicit():
    """SUBCATEGORIES.md tie-breaker 14: they CAN co-occur, and the scope claim
    is the narrower one, so it leads."""
    assert sr.label_from_title("Full Stack Product Engineer") == [
        "product_engineering", "full_stack"
    ]
    assert sr.label_from_title("Full Stack Engineer") == ["full_stack"]


def test_ownership_boilerplate_is_not_a_product_engineering_signal():
    """⚠ The rail that stops `product_engineering` becoming the catch-all. Every
    startup posting is written this way."""
    for title in (
        "Software Engineer (high agency)",
        "Software Engineer - wear many hats",
        "Software Engineer, 0 to 1",
        "Software Engineer, end-to-end ownership",
    ):
        assert "product_engineering" not in sr.label_from_title(title), title


def test_an_experimentation_platform_is_infrastructure_not_growth():
    """SUBCATEGORIES.md tie-breaker 13 — build the platform other teams run
    experiments on, or run the experiments. The regex declines to guess: it
    carries no `experimentation` pattern for `growth_engineering` at all."""
    assert sr.label_from_title("Experimentation Platform Engineer") == [
        "infrastructure_platform"
    ]


def test_growth_engineering_reads_the_metric_wherever_it_sits_in_the_title():
    assert sr.label_from_title("Software Engineer, Growth") == ["growth_engineering"]
    assert sr.label_from_title("Software Engineer - Growth") == ["growth_engineering"]
    assert sr.label_from_title("Engineer, Consumer Growth") == ["growth_engineering"]
    assert sr.label_from_title("Monetization Engineer") == ["growth_engineering"]


def test_ambiguous_language_tags_stay_unmapped():
    assert sr.label_from_tags(["c-plus-plus"]) == []
    assert sr.label_from_tags(["csharp"]) == []


# --- rule_label ------------------------------------------------------------


def test_rule_label_prefers_the_title_and_reports_its_source():
    assert sr.rule_label("Backend Engineer", ["react"]) == (["backend"], "title")
    assert sr.rule_label("Software Engineer", ["django"]) == (["backend"], "tag")
    assert sr.rule_label("Software Engineer", ["python"]) == ([], "")
    assert sr.rule_label(None, None) == ([], "")


def test_rule_label_never_reads_a_description():
    """Structural: the signature has nowhere to put one."""
    import inspect

    params = set(inspect.signature(sr.rule_label).parameters)
    assert params == {"title", "tags"}
    for fn in (sr.label_from_title, sr.label_from_tags):
        assert "description" not in inspect.signature(fn).parameters


def test_regex_coverage_counts_only_gold_swe_titles():
    rows = [
        {"category": "software_engineering", "title": "Backend Engineer"},
        {"category": "software_engineering", "title": "Software Engineer"},
        {"category": "business_ops", "title": "Frontend Engineer"},
    ]
    assert sr.regex_coverage(rows) == (1, 2)


def test_the_recorded_regex_coverage_matches_the_live_seed():
    """⚠ PARAM_REGEX_COVERAGE is a MEASURED number that sizes EV-9b's review
    cost. If the seed or the patterns move, the recorded value must move with
    them — a stale figure silently under- or over-books human review time."""
    from job_enricher.eval.golden import load_seed

    rows = load_seed()
    if not rows:
        pytest.skip("no golden seed committed")
    assert sr.regex_coverage(rows) == (
        sr.PARAM_REGEX_COVERAGE_TYPED, sr.PARAM_REGEX_COVERAGE_TOTAL
    )


# --- EV-11: the committed weak-rule baseline ------------------------------


def _weak_artifact():
    import json
    from job_enricher.store import REPO_ROOT

    path = REPO_ROOT / "golden" / "baselines" / "weak_rule" / "predictions.weak_rule.json"
    if not path.exists():
        pytest.skip("weak-rule artifact not committed")
    return json.loads(path.read_text())


def test_the_committed_weak_artifact_is_title_only():
    """⚠ Stamped so nobody mistakes it for the PRODUCTION rule layer, which
    also runs the tag layer. Scoring the tag layer against the seed's `tags`
    would be label leakage — that field is a GOLD LABEL."""
    art = _weak_artifact()
    assert art["input_mode"] == "title_only"
    assert art["generated_by"].endswith("label_from_title")


def test_the_committed_weak_artifact_row_set_equals_the_gold_swe_pool():
    from job_enricher.eval.golden import load_seed

    art = _weak_artifact()
    swe = {
        (r["source_id"], r["job_listing_id"]) for r in load_seed()
        if r.get("category") == "software_engineering"
    }
    got = {(p["source_id"], p["job_listing_id"]) for p in art["predictions"]}
    assert got == swe
    assert art["n"] == len(swe) == 135


def test_the_committed_weak_artifact_reproduces_from_the_current_rules():
    """The golden-file check: re-deriving it from the seed must be byte-equal,
    so a change to the regex cannot silently move the number the gate compares
    against."""
    from job_enricher.eval.golden import load_seed

    art = _weak_artifact()
    expected = {
        (r["source_id"], r["job_listing_id"]): sr.label_from_title(r.get("title"))
        for r in load_seed() if r.get("category") == "software_engineering"
    }
    got = {
        (p["source_id"], p["job_listing_id"]): p["subcategories"]
        for p in art["predictions"]
    }
    assert got == expected


def test_the_committed_weak_scorecard_is_HONEST_about_whether_it_can_gate():
    """⚠ THE ALL-ZEROS TRAP. `load_truth(facet='subcategory')` returns 0 rows
    until the EV-9b pool run lands, so scoring the weak artifact today yields a
    full card of 0.0s. "Beat `subcategory_set_f1: 0.0` by 0.10" is a FREE PASS,
    not a gate — the card must say so on its face.

    This also forces the card to be RE-SCORED the day the pool appears: the
    moment `load_truth(facet='subcategory')` is non-empty, a committed
    all-zeros card fails here instead of quietly under-setting G2's bar."""
    import json

    from job_enricher.eval.golden import SCORECARD_DIR, load_truth

    path = SCORECARD_DIR / "baseline.weak_rule.json"
    if not path.exists():
        pytest.skip("weak-rule scorecard not committed")
    committed = json.loads(path.read_text())
    pool_n = len(load_truth(facet="subcategory"))
    assert committed["subcategory_n"] == pool_n, (
        "the committed weak card was scored against a pool of "
        f"{committed['subcategory_n']} rows but the pool now holds {pool_n} — "
        "re-run `cli subcategory-weak-baseline` and commit the result"
    )
    assert committed["gate_ready"] is (pool_n > 0)
    if pool_n == 0:
        assert "EMPTY" in committed["gate_blocked_reason"]
        assert committed["subcategory_set_f1"] == 0.0
    else:
        assert committed["gate_blocked_reason"] is None


def test_the_committed_weak_scorecard_scores_reproducibly():
    """The golden-file half: re-scoring the committed artifact against the
    current pool must reproduce the committed numbers exactly."""
    import json

    from job_enricher.eval.golden import SCORECARD_DIR, load_truth
    from job_enricher.eval.scoring import score

    path = SCORECARD_DIR / "baseline.weak_rule.json"
    if not path.exists():
        pytest.skip("weak-rule scorecard not committed")
    committed = json.loads(path.read_text())
    assert committed["input_mode"] == "title_only"
    rescored = score(_weak_artifact()["predictions"], load_truth(facet="subcategory"))
    assert rescored.to_dict()["subcategory_set_f1"] == committed["subcategory_set_f1"]
    assert rescored.to_dict()["subcategory_n"] == committed["subcategory_n"]


def _typed_predictions(k):
    """The first k committed weak predictions that the title layer actually
    typed (a prediction of `[]` scores nothing interesting)."""
    typed = [p for p in _weak_artifact()["predictions"] if p["subcategories"]]
    if len(typed) < k:
        pytest.skip("not enough typed rows in the committed artifact")
    return typed[:k]


def test_the_scorer_actually_measures_the_weak_predictions():
    """⚠ WITHOUT THIS THE REPRODUCIBILITY TEST ABOVE IS A TAUTOLOGY. With an
    empty gold pool it compares 0.0 against 0.0 and would pass with the scorer
    DELETED. Here the same `score()` call runs over a NON-empty synthetic pool
    built from the committed artifact, with hand-computed expectations."""
    from job_enricher.eval.scoring import score

    preds = _typed_predictions(3)
    # (a) gold == the rule's own answer -> a perfect card over exactly 3 rows
    perfect = [
        {"job_listing_id": p["job_listing_id"], "source_id": p["source_id"],
         "category": "software_engineering", "subcategories": list(p["subcategories"])}
        for p in preds
    ]
    card = score(preds, perfect).to_dict()
    assert card["subcategory_n"] == 3
    assert card["subcategory_set_f1"] == 1.0
    assert card["subcategory_primary_accuracy"] == 1.0
    assert card["subcategory_coverage"] == 1.0

    # (b) one row's gold flipped to a slug the rule did NOT emit -> the card
    #     must MOVE. A scorer that always answers 0.0 fails (a); one that
    #     always answers 1.0 fails (b).
    wrong_slug = next(
        s for s in ("security", "mobile", "qa_testing")
        if s not in preds[0]["subcategories"]
    )
    mixed = [dict(perfect[0], subcategories=[wrong_slug])] + perfect[1:]
    mixed_card = score(preds, mixed).to_dict()
    assert mixed_card["subcategory_n"] == 3
    assert 0.0 < mixed_card["subcategory_set_f1"] < 1.0
    assert mixed_card["subcategory_primary_accuracy"] == pytest.approx(2 / 3, abs=1e-4)

    # (c) an EMPTY pool scores 0.0 over n=0 — which is exactly why the
    #     committed card cannot gate today.
    empty_card = score(preds, []).to_dict()
    assert empty_card["subcategory_n"] == 0
    assert empty_card["subcategory_set_f1"] == 0.0
