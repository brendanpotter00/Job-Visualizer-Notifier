"""EV-7 / EV-8 / EV-9: the facet-generic pre-label -> review -> apply pipeline.

The load-bearing assertions here are the ones a runbook cannot enforce: the
independence refusal, the byte-identical seeded draw, and the promotion switch.
"""

import argparse
import json

import pytest

from job_enricher import cli
from job_enricher.eval import prelabel as pl


class _FakeEngine:
    """Records the prompts it was given and replies from a canned table."""

    def __init__(self, replies=None, garble=False):
        self.prompts: list[str] = []
        self.replies = replies or {}
        self.garble = garble

    def _call_with_repair(self, chunk, build_prompt, latency_field):
        self.prompts.append(build_prompt(chunk))
        out = []
        for row in chunk:
            if self.garble:
                out.append({"job_listing_id": row["job_listing_id"],
                            "source_id": row["source_id"],
                            "prelabel": {"not": "a slug"}, "confidence": "high"})
                continue
            r = self.replies.get(row["job_listing_id"], {})
            out.append({
                "job_listing_id": row["job_listing_id"],
                "source_id": row["source_id"],
                "prelabel": r.get("prelabel"),
                "confidence": r.get("confidence", 0.8),
                "reasoning": r.get("reasoning", "because"),
                latency_field: 123,
            })
        return out


def _row(jid, cat="software_engineering", label_source="draft", **kw):
    base = {
        "job_listing_id": jid, "source_id": "greenhouse", "title": f"Engineer {jid}",
        "company": "acme", "raw_location": "SF", "description_html": "<p>work</p>",
        "clean_description": "work work", "label_source": label_source,
        "category": cat, "level": "mid", "tags": ["THE-GOLD-TAG"],
        "subcategories": None,
    }
    base.update(kw)
    return base


# --- independence ----------------------------------------------------------


def test_check_independence_refuses_a_model_labelling_itself():
    with pytest.raises(pl.IndependenceError) as exc:
        pl.check_independence("ollama", "qwen3:32b", "ollama:qwen3:32b")
    assert "independence rule a" in str(exc.value)
    # a genuinely different model is fine
    pl.check_independence("claude-code", "opus", "ollama:qwen3:32b")


def test_cli_prelabel_exits_2_on_the_independence_refusal(capsys):
    args = argparse.Namespace(
        facet="category", engine="ollama", model="qwen3:32b",
        under_test="ollama:qwen3:32b", seed=1, draw=None, batch=5, out=None,
    )
    assert cli._cmd_prelabel(args) == 2
    assert "independence rule a" in capsys.readouterr().err


# --- pools -----------------------------------------------------------------


def test_the_subcategory_pool_excludes_human_swe_rows_and_every_non_swe_row():
    """⚠ 11 of the 126 SWE rows are already human, so the workload is 115."""
    rows = [
        _row("1"),                                    # draft SWE, unlabelled -> in
        _row("2", label_source="human"),              # already human -> out
        _row("3", cat="business_ops"),                # not SWE -> out
        _row("4", subcategories=["backend"]),         # already has a label -> out
    ]
    assert [r["job_listing_id"] for r in pl.subcategory_pool(rows)] == ["1"]


def test_the_category_pool_excludes_human_rows():
    rows = [_row("1"), _row("2", label_source="human")]
    assert [r["job_listing_id"] for r in pl.category_pool(rows)] == ["1"]


def test_the_category_draw_is_seeded_and_byte_identical_across_two_runs():
    rows = (
        [_row(f"s{i}", cat="software_engineering") for i in range(40)]
        + [_row(f"b{i}", cat="business_ops") for i in range(20)]
        + [_row(f"g{i}", cat="growth") for i in range(6)]
    )
    a = pl.draw_pool("category", rows, 20, 20260820)
    b = pl.draw_pool("category", rows, 20, 20260820)
    assert [r["job_listing_id"] for r in a] == [r["job_listing_id"] for r in b]
    assert len(a) == 20


def test_the_draw_is_stratified_with_a_floor_on_small_strata():
    rows = (
        [_row(f"s{i}", cat="software_engineering") for i in range(100)]
        + [_row(f"g{i}", cat="growth") for i in range(6)]
    )
    drawn = pl.draw_pool("category", rows, 30, 20260820)
    by_cat = {}
    for r in drawn:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
    assert by_cat["growth"] >= pl.PARAM_STRATUM_FLOOR
    assert by_cat["software_engineering"] > by_cat["growth"]
    assert sum(by_cat.values()) == 30


def test_a_different_seed_draws_a_different_pool():
    rows = [_row(f"s{i}") for i in range(60)]
    a = [r["job_listing_id"] for r in pl.draw_pool("category", rows, 10, 1)]
    b = [r["job_listing_id"] for r in pl.draw_pool("category", rows, 10, 2)]
    assert a != b


# --- prompt ----------------------------------------------------------------


def test_the_built_prompt_contains_no_gold_tag_value(tmp_path):
    """⚠ golden.json's `tags` is a GOLD LABEL — it is what score() compares
    predictions against. Putting it in the prompt feeds the answer back in."""
    prompt = pl.build_prelabel_prompt("category", "RUBRIC", [_row("1")])
    assert "THE-GOLD-TAG" not in prompt
    block = prompt.split("<job_data>\n")[-1].split("\n</job_data>")[0].strip()
    assert "tags" not in json.loads(block)[0]
    # the four fields it SHOULD carry
    assert "Engineer 1" in prompt and "acme" in prompt and "work work" in prompt


def test_project_row_carries_exactly_the_six_input_fields():
    assert set(pl.project_row(_row("1"))) == set(pl._PRELABEL_ROW_FIELDS)


# --- run -------------------------------------------------------------------


def _run(facet, tmp_path, rows, engine, **kw):
    out = tmp_path / f"{facet}-prelabel.json"
    pl.run_prelabel(
        facet=facet, engine="claude-code", model="opus",
        under_test="ollama:qwen3:32b", seed=20260820, out=out, rows=rows,
        engine_factory=lambda kind, model=None: engine, **kw,
    )
    return json.loads(out.read_text())


def test_the_artifact_header_carries_full_model_provenance(tmp_path):
    eng = _FakeEngine({"1": {"prelabel": "software_engineering"}})
    art = _run("category", tmp_path, [_row("1")], eng)
    assert art["facet"] == "category"
    assert art["prelabel_engine"] == "claude-code"
    assert art["prelabel_model"] == "opus"
    assert art["under_test"] == "ollama:qwen3:32b"
    assert art["seed"] == 20260820
    assert art["pool_size"] == 1
    assert art["entries"][0]["prelabel"] == "software_engineering"
    assert art["entries"][0]["prelabel_confidence"] == 0.8


def test_a_garbled_reply_yields_null_and_does_not_raise(tmp_path):
    art = _run("category", tmp_path, [_row("1")], _FakeEngine(garble=True))
    assert art["entries"][0]["prelabel"] is None
    assert art["entries"][0]["prelabel_confidence"] is None


def test_an_out_of_enum_slug_is_dropped_rather_than_recorded(tmp_path):
    eng = _FakeEngine({"1": {"prelabel": "ai_ml"}})  # ai_ml died in r2
    art = _run("subcategory", tmp_path, [_row("1")], eng)
    assert art["entries"][0]["prelabel"] == []


def test_subcategory_prelabels_are_capped_at_two(tmp_path):
    eng = _FakeEngine({"1": {"prelabel": ["backend", "frontend", "security"]}})
    art = _run("subcategory", tmp_path, [_row("1")], eng)
    assert art["entries"][0]["prelabel"] == ["backend", "frontend"]


def test_facet_category_runs_with_the_subcategory_rubric_absent(tmp_path, monkeypatch):
    """⚠ The rubric is resolved LAZILY per facet. The category pool has to be
    buildable BEFORE SKILL.md is touched and before SUBCATEGORIES.md exists."""
    monkeypatch.setattr(
        "job_enricher.taxonomy.SUBCATEGORY_RUBRIC_PATH", tmp_path / "nope.md"
    )
    art = _run("category", tmp_path, [_row("1")],
               _FakeEngine({"1": {"prelabel": "growth"}}))
    assert art["entries"][0]["prelabel"] == "growth"
    with pytest.raises(FileNotFoundError):
        pl.read_rubric("subcategory")


# ===========================================================================
# EV-8 — review-build
# ===========================================================================


def _prelabel_artifact(facet, entries, **hdr):
    base = {
        "facet": facet, "prelabel_engine": "claude-code", "prelabel_model": "opus",
        "under_test": "ollama:qwen3:32b", "seed": 20260820,
        "taxonomy_version": "v7+abc123def456", "entries": entries,
    }
    base.update(hdr)
    return base


def _entry(jid, prelabel, conf=0.8):
    return {"job_listing_id": jid, "source_id": "greenhouse",
            "title": f"Engineer {jid}", "company": "acme",
            "prelabel": prelabel, "prelabel_confidence": conf,
            "prelabel_reasoning": "because"}


def _build(tmp_path, facet, entries, rows, **kw):
    src = tmp_path / "pre.json"
    src.write_text(json.dumps(_prelabel_artifact(facet, entries)))
    r, a, header = pl.build_review(
        facet=facet, prelabel_file=src, rows=rows,
        out=tmp_path / "review.json", agreements_out=tmp_path / "agree.json", **kw,
    )
    return json.loads(r.read_text()), json.loads(a.read_text()), header


def test_tier_assignment_on_a_crafted_fixture(tmp_path):
    rows = [
        # A: the regex cannot type "Software Engineer"
        _row("1", title="Software Engineer"),
        # B: regex says backend, the model says frontend
        _row("2", title="Backend Engineer"),
        # C: both say backend
        _row("3", title="Backend Engineer"),
    ]
    entries = [_entry("1", ["backend"]), _entry("2", ["frontend"]),
               _entry("3", ["backend"])]
    review, agree, header = _build(tmp_path, "subcategory", entries, rows)
    tiers = {e["job_listing_id"]: e["tier"] for e in review["entries"]}
    assert tiers["1"] == "A" and tiers["2"] == "B"
    assert header["tier_counts"] == {"A": 1, "B": 1, "C": 1}
    # tier C row 3 was audited (only one value present in C -> floor of 1)
    assert tiers.get("3") == "C"
    assert agree["entries"] == []


def test_a_row_can_never_land_in_two_tiers(tmp_path):
    rows = [_row(str(i), title="Backend Engineer") for i in range(6)]
    entries = [_entry(str(i), ["backend"] if i % 2 else ["frontend"]) for i in range(6)]
    review, agree, header = _build(tmp_path, "subcategory", entries, rows)
    ids = [e["job_listing_id"] for e in review["entries"]] + \
          [e["job_listing_id"] for e in agree["entries"]]
    assert len(ids) == len(set(ids)) == 6
    assert sum(header["tier_counts"].values()) == 6


def test_the_audit_sample_is_byte_identical_across_two_runs(tmp_path):
    rows = [_row(str(i), title="Backend Engineer") for i in range(40)]
    entries = [_entry(str(i), ["backend"]) for i in range(40)]
    a1, _, _ = _build(tmp_path, "subcategory", entries, rows)
    a2, _, _ = _build(tmp_path, "subcategory", entries, rows)
    strip = lambda d: [dict(e) for e in d["entries"]]  # noqa: E731
    assert strip(a1) == strip(a2)
    # ceil(0.15 * 40) == 6, and there is a single stratum so the floor is moot
    assert len(a1["entries"]) == 6


def test_a_value_appearing_once_in_c_still_gets_an_audit_slot(tmp_path):
    """⚠ An unstratified sample of a pool dominated by backend would audit
    almost none of the rare slugs — and the rare slugs are where a pre-labeller
    is most likely to be wrong."""
    rows = [_row(str(i), title="Backend Engineer") for i in range(30)]
    rows.append(_row("rare", title="Forward Deployed Engineer"))
    entries = [_entry(str(i), ["backend"]) for i in range(30)]
    entries.append(_entry("rare", ["forward_deployed"]))
    review, _, _ = _build(tmp_path, "subcategory", entries, rows)
    assert "rare" in {e["job_listing_id"] for e in review["entries"]}


def test_the_review_row_count_is_a_plus_b_plus_the_audit_sample(tmp_path):
    rows = [_row(str(i), title="Backend Engineer") for i in range(20)]
    rows += [_row("u" + str(i), title="Software Engineer") for i in range(3)]
    entries = [_entry(str(i), ["backend"]) for i in range(20)]
    entries += [_entry("u" + str(i), ["backend"]) for i in range(3)]
    review, agree, header = _build(tmp_path, "subcategory", entries, rows)
    tc = header["tier_counts"]
    assert len(review["entries"]) == tc["A"] + tc["B"] + header["audit_target"]
    assert len(agree["entries"]) == tc["C"] - header["audit_target"]


def test_facet_defaults_declare_independence_and_the_audit_rate(tmp_path):
    rows = [_row("1", title="Backend Engineer")]
    _r, _a, cat = _build(tmp_path, "category", [_entry("1", "software_engineering")], rows)
    assert cat["corroborator_independent"] is False
    assert cat["audit_rate"] == 1.0
    assert cat["promote_agreements"] is False
    assert cat["corroborator"] == "seed draft label"

    _r, _a, sub = _build(tmp_path, "subcategory", [_entry("1", ["backend"])], rows)
    assert sub["corroborator_independent"] is True
    assert sub["audit_rate"] == 0.15
    assert sub["promote_agreements"] is True
    assert sub["corroborator"] == "subcategory_rules.rule_label"


def test_review_render_emits_one_self_contained_page(tmp_path):
    rows = [_row("1", title="Backend Engineer")]
    review, _a, _h = _build(tmp_path, "subcategory", [_entry("1", ["backend"])], rows)
    html = pl.render_review_html(review)
    assert "<script>" in html and "<style>" in html
    assert "http://" not in html and "https://" not in html   # self-contained
    assert html.count("type='checkbox'") >= 17                # 17 slugs + touched
    cat_html = pl.render_review_html({**review, "facet": "category"})
    assert "type='radio'" in cat_html


# ===========================================================================
# EV-9 — review-apply
# ===========================================================================


def _apply(tmp_path, facet, review_entries, agreements, rows, threshold, **hdr):
    rfile = tmp_path / "review.json"
    afile = tmp_path / "agree.json"
    header = {
        "facet": facet, "prelabel_model": "opus", "under_test": "ollama:qwen3:32b",
        "seed": 20260820, "corroborator": "x", "corroborator_independent": True,
        "promote_agreements": True,
    }
    header.update(hdr)
    rfile.write_text(json.dumps({**header, "entries": review_entries}))
    afile.write_text(json.dumps({**header, "entries": agreements}))
    return pl.apply_review(
        facet=facet, threshold=threshold, review_file=rfile, agreements_file=afile,
        rows=rows, audit_out=tmp_path / "audit.json", write=False,
    )


def _rev(jid, prelabel, decision, audited=False, **kw):
    e = {"job_listing_id": jid, "source_id": "greenhouse", "prelabel": prelabel,
         "prelabel_confidence": 0.8, "decision": decision, "tier": "C"}
    if audited:
        e["audited"] = True
    e.update(kw)
    return e


def test_an_audit_at_or_below_threshold_promotes_the_agreements(tmp_path):
    rows = [_row("1"), _row("2"), _row("3"), _row("4")]
    review = [_rev("1", ["backend"], ["backend"], audited=True),
              _rev("2", ["backend"], ["backend"], audited=True)]
    agreements = [_rev("3", ["frontend"], None), _rev("4", ["mobile"], None)]
    res = _apply(tmp_path, "subcategory", review, agreements, rows, 0.05)
    assert res["verdict"]["error_rate"] == 0.0
    assert res["verdict"]["passed"] is True
    assert res["promoted"] == 2
    by = {r["job_listing_id"]: r for r in rows}
    assert by["3"]["gold_subcategory_provenance"] == "prelabel_agreed"
    assert by["1"]["gold_subcategory_provenance"] == "human_audited"


def test_an_audit_above_threshold_promotes_nothing(tmp_path):
    rows = [_row("1"), _row("2"), _row("3")]
    review = [_rev("1", ["backend"], ["frontend"], audited=True),   # a miss
              _rev("2", ["backend"], ["backend"], audited=True)]
    agreements = [_rev("3", ["mobile"], None)]
    res = _apply(tmp_path, "subcategory", review, agreements, rows, 0.05)
    assert res["verdict"]["error_rate"] == 0.5
    assert res["verdict"]["passed"] is False
    assert res["promoted"] == 0
    assert rows[2].get("gold_subcategory_provenance") is None


def test_promote_agreements_false_promotes_nothing_regardless(tmp_path):
    """⚠ The honest consequence of a same-family corroborator: a perfect audit
    still promotes nothing."""
    rows = [_row("1"), _row("2")]
    review = [_rev("1", ["backend"], ["backend"], audited=True)]
    agreements = [_rev("2", ["mobile"], None)]
    res = _apply(tmp_path, "subcategory", review, agreements, rows, 0.05,
                 promote_agreements=False)
    assert res["verdict"]["error_rate"] == 0.0
    assert res["verdict"]["passed"] is True
    assert res["promoted"] == 0
    assert rows[1].get("gold_subcategory_provenance") is None


def test_contract_rows_are_never_promoted(tmp_path):
    rows = [_row("1"), _row("2", category="business_ops", subcategories=[],
                            gold_subcategory_provenance="contract")]
    review = [_rev("1", ["backend"], ["backend"], audited=True)]
    agreements = [_rev("2", ["mobile"], None)]
    res = _apply(tmp_path, "subcategory", review, agreements, rows, 0.05)
    assert res["promoted"] == 0
    assert rows[1]["gold_subcategory_provenance"] == "contract"


def test_applying_twice_is_idempotent(tmp_path):
    rows = [_row("1"), _row("2")]
    review = [_rev("1", ["backend"], ["backend"], audited=True)]
    agreements = [_rev("2", ["mobile"], None)]
    _apply(tmp_path, "subcategory", review, agreements, rows, 0.05)
    first = json.dumps(rows, sort_keys=True)
    _apply(tmp_path, "subcategory", review, agreements, rows, 0.05)
    assert json.dumps(rows, sort_keys=True) == first


def test_facet_category_never_writes_a_subcategories_key(tmp_path):
    """⚠ ONE FACET PER PASS. Level, tags and locations are untouched too."""
    rows = [_row("1", category="business_ops", level="mid", tags=["ops"])]
    review = [_rev("1", "software_engineering", "software_engineering", audited=True)]
    _apply(tmp_path, "category", review, [], rows, 0.05,
           promote_agreements=False, corroborator_independent=False)
    row = rows[0]
    assert row["category"] == "software_engineering"
    assert row["label_source"] == "human"
    assert row["category_prelabel_model"] == "opus"
    assert row["subcategories"] is None            # untouched (the _row default)
    assert row["level"] == "mid" and row["tags"] == ["ops"]


def test_an_undecided_row_is_reported_and_not_applied(tmp_path):
    rows = [_row("1")]
    res = _apply(tmp_path, "subcategory", [_rev("1", ["backend"], None)], [], rows, 0.05)
    assert res["undecided"] == ["1"]
    assert res["decided"] == 0
    assert rows[0]["subcategories"] is None


def test_a_split_train_decision_is_recorded_on_the_row(tmp_path):
    rows = [_row("1")]
    _apply(tmp_path, "subcategory",
           [_rev("1", ["backend"], ["backend"], audited=True, split="train")],
           [], rows, 0.05)
    assert rows[0]["split"] == "train"


def test_an_empty_audit_never_passes(tmp_path):
    """No audited rows means no measurement, and no measurement is not a pass."""
    rows = [_row("1"), _row("2")]
    res = _apply(tmp_path, "subcategory", [_rev("1", ["backend"], ["backend"])],
                 [_rev("2", ["mobile"], None)], rows, 0.05)
    assert res["verdict"]["error_rate"] is None
    assert res["verdict"]["passed"] is False
    assert res["promoted"] == 0


# --- EV-9: a malformed hand-edited decision is a REFUSAL, not a null label ---


def test_a_list_category_decision_refuses_and_nulls_nothing(tmp_path):
    """⚠ THE SILENT-CORRUPTION CASE. A hand-edited review file carrying
    `decision: ["software_engineering"]` for the CATEGORY facet used to parse
    to None, be written onto the row as `category=None` with
    `label_source='human'`, and be counted `decided:1 undecided:[]`. The row
    then still entered load_truth's pool through its LEVEL and scored as a miss
    against every prediction. It must refuse instead, and write nothing."""
    rows = [_row("1", category="business_ops", level="mid")]
    review = [_rev("1", "software_engineering", ["software_engineering"], audited=True)]
    with pytest.raises(ValueError) as exc:
        _apply(tmp_path, "category", review, [], rows, 0.05,
               promote_agreements=False)
    msg = str(exc.value)
    assert "malformed" in msg and "NOTHING was written" in msg
    assert "greenhouse/1" in msg and "single slug string" in msg
    # the row is untouched — no null category, no 'human' stamp
    assert rows[0]["category"] == "business_ops"
    assert rows[0]["label_source"] == "draft"


def test_an_unknown_category_slug_refuses(tmp_path):
    rows = [_row("1", category="business_ops")]
    review = [_rev("1", "software_engineering", "softwareengineering", audited=True)]
    with pytest.raises(ValueError, match="unknown category slug"):
        _apply(tmp_path, "category", review, [], rows, 0.05,
               promote_agreements=False)
    assert rows[0]["category"] == "business_ops"


def test_a_subcategory_decision_with_a_non_string_element_refuses(tmp_path):
    """A silent DROP is as bad as a silent null: the reviewer is never told
    which of their choices was discarded."""
    rows = [_row("1")]
    review = [_rev("1", ["backend"], ["backend", 5], audited=True)]
    with pytest.raises(ValueError, match="non-string element"):
        _apply(tmp_path, "subcategory", review, [], rows, 0.05)
    assert rows[0]["subcategories"] is None


def test_a_subcategory_decision_over_the_cap_refuses_instead_of_truncating(tmp_path):
    rows = [_row("1")]
    review = [_rev("1", ["backend"], ["backend", "frontend", "mobile"], audited=True)]
    with pytest.raises(ValueError, match="the cap is 2"):
        _apply(tmp_path, "subcategory", review, [], rows, 0.05)
    assert rows[0]["subcategories"] is None


def test_an_out_of_taxonomy_subcategory_slug_refuses(tmp_path):
    rows = [_row("1")]
    review = [_rev("1", ["backend"], ["ai_ml"], audited=True)]
    with pytest.raises(ValueError, match="unknown subcategory slug"):
        _apply(tmp_path, "subcategory", review, [], rows, 0.05)
    assert rows[0]["subcategories"] is None


def test_a_malformed_agreement_prelabel_refuses_before_promotion(tmp_path):
    """Agreement prelabels are COPIED onto gold rows by the promotion branch,
    so they are held to the same shape contract as a decision."""
    rows = [_row("1"), _row("2")]
    review = [_rev("1", ["backend"], ["backend"], audited=True)]
    agreements = [_rev("2", ["not_a_real_slug"], None)]
    with pytest.raises(ValueError, match="unknown subcategory slug"):
        _apply(tmp_path, "subcategory", review, agreements, rows, 0.05)
    assert rows[1].get("gold_subcategory_provenance") is None


def test_the_legal_shapes_still_apply(tmp_path):
    """The guard must not reject the decisions the reviewer is meant to make:
    an empty list ('evaluated, none apply'), a bare slug string, and an
    undecided null."""
    rows = [_row("1"), _row("2"), _row("3")]
    review = [_rev("1", ["backend"], [], audited=True),
              _rev("2", ["backend"], "backend", audited=True),
              _rev("3", ["backend"], None)]
    res = _apply(tmp_path, "subcategory", review, [], rows, 0.6)
    assert res["decided"] == 2 and res["undecided"] == ["3"]
    assert rows[0]["subcategories"] == []
    assert rows[1]["subcategories"] == ["backend"]
    assert rows[2]["subcategories"] is None
