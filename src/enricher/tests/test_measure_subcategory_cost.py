"""P0-5 — the sampler and the injection-boundary regression.

⚠ The MEASUREMENT itself is a RUN and is not performed here: it needs a live
model. These tests pin the two things that would silently corrupt it.
"""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import measure_subcategory_cost as msc  # noqa: E402

from job_enricher.store import ScopeUnavailableError, now_iso  # noqa: E402


def _swe(store, jid, title="Staff Engineer", clean="A LONG UNTRUSTED DESCRIPTION"):
    with store.connect() as c:
        c.execute(
            "INSERT INTO inbox (job_listing_id, source_id, title, company, "
            "raw_location, content_hash, claimed_at, status, clean_description, "
            "first_seen_at) VALUES (?, 'gh', ?, 'Acme', 'SF', ?, ?, 'sent', ?, ?)",
            (jid, title, f"h-{jid}", now_iso(), clean, "2026-08-01T00:00:00+00:00"),
        )
        c.execute(
            "INSERT INTO enrichments (job_listing_id, source_id, category, tags, "
            "enriched_at, sent_at) VALUES (?, 'gh', 'software_engineering', "
            "'[\"python\"]', ?, ?)",
            (jid, now_iso(), now_iso()),
        )


def test_the_sampler_never_selects_a_row_outside_the_scope(store):
    for i in range(10):
        _swe(store, f"j{i}")
    store.import_backfill_scope([("gh", "j0"), ("gh", "j1"), ("gh", "j2")])
    rows = msc.sample_scope_rows(store, n=10, seed=1)
    assert {r["job_listing_id"] for r in rows} <= {"j0", "j1", "j2"}
    assert len(rows) == 3


def test_the_sampler_refuses_rather_than_measuring_the_wrong_cohort(store):
    _swe(store, "j0")
    with pytest.raises(ScopeUnavailableError):
        msc.sample_scope_rows(store, n=5)


def test_the_prompt_renderer_never_includes_clean_description(store):
    """⚠ THE INJECTION-BOUNDARY REGRESSION. Assert the substring is absent from
    every rendered prompt."""
    for i in range(5):
        _swe(store, f"j{i}", clean=f"SECRET-PAYLOAD-{i}")
    store.import_backfill_scope([("gh", f"j{i}") for i in range(5)])
    rows = msc.sample_scope_rows(store, n=5, seed=0)
    for prompt in msc.render_prompts(rows):
        assert "SECRET-PAYLOAD" not in prompt
        assert "clean_description" not in prompt


def test_the_decision_rule_rejects_a_tier_over_the_parse_failure_ceiling():
    cells = [
        {"tier": "haiku", "seconds_per_row_p95": 1.0, "parse_failure_rate": 0.10,
         "tier_agreement": 0.95},
        {"tier": "sonnet", "seconds_per_row_p95": 4.0, "parse_failure_rate": 0.01,
         "tier_agreement": 0.95},
    ]
    assert msc.decide(cells)["tier"] == "sonnet"


def test_below_85_percent_agreement_sonnet_wins_even_though_haiku_is_faster():
    cells = [
        {"tier": "haiku", "seconds_per_row_p95": 1.0, "parse_failure_rate": 0.0,
         "tier_agreement": 0.70},
        {"tier": "sonnet", "seconds_per_row_p95": 9.0, "parse_failure_rate": 0.0,
         "tier_agreement": None},
    ]
    assert msc.decide(cells)["tier"] == "sonnet"


def test_at_or_above_the_floor_the_cheapest_eligible_cell_wins():
    cells = [
        {"tier": "haiku", "seconds_per_row_p95": 1.0, "parse_failure_rate": 0.0,
         "tier_agreement": 0.90},
        {"tier": "sonnet", "seconds_per_row_p95": 9.0, "parse_failure_rate": 0.0,
         "tier_agreement": None},
    ]
    assert msc.decide(cells)["tier"] == "haiku"


def test_no_seconds_per_row_constant_is_baked_in():
    """⚠ The only measured figure on this machine is 137.9 s/item for the FULL
    classify prompt on qwen3:32b — a different model, prompt and engine."""
    assert msc.SECONDS_PER_ROW_P50 is None
    assert msc.SECONDS_PER_ROW_P95 is None
    assert msc.MODEL_TIER is None
    assert msc.CHUNK_SIZE is None
    assert msc.CLAUDE_TIMEOUT_SECONDS is None


def test_agreement_is_computed_on_the_primary_slug():
    assert msc.agreement([["backend"], ["frontend"]], [["backend"], ["mobile"]]) == 0.5
    assert msc.agreement([], []) == 0.0


# ---------------------------------------------------------------------------
# The agreement half of the decision rule — computed, not hand-waved
# ---------------------------------------------------------------------------
def _probe(*labels):
    return {"row_labels": [
        {"source_id": "gh", "job_listing_id": jid, "slugs": list(slugs),
         "source": source}
        for jid, slugs, source in labels
    ]}


def test_model_labels_from_a_probe_exclude_the_rule_pass():
    """⚠ The rule pass is DETERMINISTIC and tier-independent — counting it would
    drive agreement toward 100% on rows no model ever saw."""
    probe = _probe(("j0", ["backend"], "model"), ("j1", ["backend"], "rule"))
    assert msc.model_labels_from_probe(probe) == {("gh", "j0"): ["backend"]}


def test_agreement_by_row_uses_only_the_rows_both_tiers_labelled():
    a = {("gh", "j0"): ["backend"], ("gh", "j1"): ["frontend"],
         ("gh", "j2"): ["mobile"]}
    b = {("gh", "j0"): ["backend"], ("gh", "j1"): ["mobile"]}
    assert msc.agreement_by_row(a, b) == 0.5
    # ⚠ NO OVERLAP IS A MISSING MEASUREMENT, NOT TOTAL DISAGREEMENT: returning
    # 0.0 here would fire 'SONNET WINS' off an empty probe.
    assert msc.agreement_by_row(a, {}) is None


def test_a_cheap_tier_that_disagrees_with_sonnet_loses_end_to_end():
    """⚠ THE FINDING THIS CLOSES. `tier_agreement` used to be hardcoded None on
    every cell, so the '< 85%, SONNET WINS' branch could never fire and the rule
    collapsed to 'lowest p95'. A haiku that disagrees on half the rows would have
    been selected."""
    labels = {
        "haiku": msc.model_labels_from_probe(
            _probe(("j0", ["backend"], "model"), ("j1", ["frontend"], "model"),
                   ("j2", ["backend"], "rule"))
        ),
        "sonnet": msc.model_labels_from_probe(
            _probe(("j0", ["backend"], "model"), ("j1", ["mobile"], "model"),
                   ("j2", ["backend"], "rule"))
        ),
    }
    cells = [
        {"tier": "haiku", "seconds_per_row_p95": 1.0, "parse_failure_rate": 0.0,
         "tier_agreement": None},
        {"tier": "sonnet", "seconds_per_row_p95": 9.0, "parse_failure_rate": 0.0,
         "tier_agreement": None},
    ]
    msc.fill_tier_agreement(cells, labels)
    # 1 of the 2 MODEL rows agree — the rule row is not counted either way
    assert cells[0]["tier_agreement"] == 0.5
    assert cells[1]["tier_agreement"] is None       # the baseline is not judged
    assert msc.decide(cells)["tier"] == "sonnet"


def test_an_agreeing_cheap_tier_still_wins():
    labels = {
        "haiku": msc.model_labels_from_probe(
            _probe(("j0", ["backend"], "model"), ("j1", ["frontend"], "model"))
        ),
        "sonnet": msc.model_labels_from_probe(
            _probe(("j0", ["backend"], "model"), ("j1", ["frontend"], "model"))
        ),
    }
    cells = [
        {"tier": "haiku", "seconds_per_row_p95": 1.0, "parse_failure_rate": 0.0,
         "tier_agreement": None},
        {"tier": "sonnet", "seconds_per_row_p95": 9.0, "parse_failure_rate": 0.0,
         "tier_agreement": None},
    ]
    msc.fill_tier_agreement(cells, labels)
    assert cells[0]["tier_agreement"] == 1.0
    assert msc.decide(cells)["tier"] == "haiku"
