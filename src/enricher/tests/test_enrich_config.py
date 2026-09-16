import pytest

from job_enricher import enrich_config as ec


def test_classify_defaults(store):
    assert ec.get_classify_model(store) == "haiku"
    assert ec.get_classify_batch_size(store) == 3
    assert ec.get_classify_fan_out(store) == 12


def test_judge_defaults(store):
    assert ec.get_judge_enabled(store) is True
    assert ec.get_judge_model(store) == "sonnet"
    assert ec.get_judge_human_floor(store) == 0.60


def test_set_and_clamp(store):
    assert ec.set_classify_batch_size(store, 999) == 10
    assert ec.get_classify_batch_size(store) == 10
    assert ec.set_classify_fan_out(store, 0) == 1
    ec.set_judge_enabled(store, False)
    assert ec.get_judge_enabled(store) is False
    assert ec.set_judge_human_floor(store, 0.75) == 0.75
    assert ec.get_judge_human_floor(store) == 0.75
    assert ec.set_judge_human_floor(store, 5.0) == 1.0  # clamped


def test_invalid_model_rejected(store):
    with pytest.raises(ValueError):
        ec.set_classify_model(store, "gpt")


def test_bad_meta_values_fall_back(store):
    store.set_meta("classify:batch_size", "not-an-int")
    assert ec.get_classify_batch_size(store) == 3
    store.set_meta("judge:human_floor", "9.9")
    assert ec.get_judge_human_floor(store) == 0.60


def test_snapshot(store):
    snap = ec.config_snapshot(store)
    assert snap["classify_model"] == "haiku" and snap["judge_enabled"] is True
    assert snap["judge_scope"] == "low_confidence"
    assert snap["judge_confidence_ceiling"] == 0.85


def test_judge_scope_defaults_and_setters(store):
    assert ec.get_judge_scope(store) == "low_confidence"
    assert ec.set_judge_scope(store, "all") == "all"
    assert ec.get_judge_scope(store) == "all"
    with pytest.raises(ValueError):
        ec.set_judge_scope(store, "everything")
    store.set_meta("judge:scope", "garbage")
    assert ec.get_judge_scope(store) == "low_confidence"  # bad meta -> default


def test_judge_ceiling_defaults_and_clamping(store):
    assert ec.get_judge_confidence_ceiling(store) == 0.85
    assert ec.set_judge_confidence_ceiling(store, 0.7) == 0.7
    assert ec.get_judge_confidence_ceiling(store) == 0.7
    assert ec.set_judge_confidence_ceiling(store, 7.0) == 1.0  # clamped
    store.set_meta("judge:confidence_ceiling", "not-a-float")
    assert ec.get_judge_confidence_ceiling(store) == 0.85


def test_reset_knob_clears_override_to_committed_default(store):
    ec.set_classify_model(store, "sonnet")
    assert ec.get_classify_model(store) == "sonnet"
    assert ec.reset_knob(store, ec.CLASSIFY_MODEL_META_KEY) == ec.CLASSIFY_MODEL_META_KEY
    assert ec.get_classify_model(store) == "haiku"  # falls back to the committed default


def test_reset_knob_rejects_unknown_key(store):
    with pytest.raises(ValueError):
        ec.reset_knob(store, "bogus:key")


def test_knob_meta_keys_cover_all_setters():
    assert ec.KNOB_META_KEYS == {
        ec.CLASSIFY_ENGINE_META_KEY,
        ec.CLASSIFY_MODEL_META_KEY,
        ec.CLASSIFY_BATCH_META_KEY,
        ec.CLASSIFY_FANOUT_META_KEY,
        ec.JUDGE_ENABLED_META_KEY,
        ec.JUDGE_ENGINE_META_KEY,
        ec.JUDGE_MODEL_META_KEY,
        ec.JUDGE_HUMAN_FLOOR_META_KEY,
        ec.JUDGE_SCOPE_META_KEY,
        ec.JUDGE_CONFIDENCE_CEILING_META_KEY,
        ec.JUDGE_SUBCATEGORY_CORRECTIONS_META_KEY,
        ec.WRITEBACK_SEND_SUBCATEGORIES_META_KEY,
        ec.OPENCODE_MODEL_META_KEY,
        ec.ENRICH_PER_TICK_LIMIT_META_KEY,
    }


def test_enrich_per_tick_limit_default_set_clamp_and_bad_meta(store):
    assert ec.get_enrich_per_tick_limit(store) == 40           # committed default
    assert ec.set_enrich_per_tick_limit(store, 25) == 25
    assert ec.get_enrich_per_tick_limit(store) == 25
    assert ec.set_enrich_per_tick_limit(store, 0) == 1         # clamped to lower bound
    assert ec.set_enrich_per_tick_limit(store, 9999) == 500    # clamped to upper bound
    store.set_meta(ec.ENRICH_PER_TICK_LIMIT_META_KEY, "not-an-int")
    assert ec.get_enrich_per_tick_limit(store) == 40           # bad meta -> default
    assert ec.reset_knob(store, ec.ENRICH_PER_TICK_LIMIT_META_KEY)
    assert ec.get_enrich_per_tick_limit(store) == 40
    assert ec.config_snapshot(store)["enrich_per_tick_limit"] == 40


def test_judge_subcategory_corrections_defaults_true_and_toggles(store):
    """ENR-CLS-2's knob. Default TRUE — the judge MAY correct subcategories under
    four code-enforced rails — but the knob exists so the lift can be MEASURED
    and killed in one command."""
    assert ec.get_judge_subcategory_corrections(store) is True
    ec.set_judge_subcategory_corrections(store, False)
    assert ec.get_judge_subcategory_corrections(store) is False
    ec.reset_knob(store, ec.JUDGE_SUBCATEGORY_CORRECTIONS_META_KEY)
    assert ec.get_judge_subcategory_corrections(store) is True


def test_writeback_send_subcategories_defaults_FALSE(store):
    """⚠ ENR-WB-1 SHIPS DARK. It may only be flipped ON after JVN's
    EnrichmentResultItem has the field (SCHEMA-4) AND enrichment_writer has
    SUBCATEGORY_SLUGS + the column write — otherwise Pydantic's default `ignore`
    drops it silently while the row still counts as written."""
    assert ec.get_writeback_send_subcategories(store) is False
    ec.set_writeback_send_subcategories(store, True)
    assert ec.get_writeback_send_subcategories(store) is True
    ec.reset_knob(store, ec.WRITEBACK_SEND_SUBCATEGORIES_META_KEY)
    assert ec.get_writeback_send_subcategories(store) is False
