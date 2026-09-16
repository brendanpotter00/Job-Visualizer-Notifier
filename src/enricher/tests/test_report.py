"""run_eval seam: --allow-draft advisory mode (banner, gold_quality stamp,
always-exit-0), judge_lift/judge_kappa_prejudge wiring, and the human-only
default gate."""

import json

import job_enricher.eval.golden as golden
import job_enricher.eval.report as report
from job_enricher.eval.report import run_eval


def _seed_row(jid, cat="software_engineering", lvl="mid", label_source="draft"):
    return {
        "job_listing_id": jid, "source_id": "greenhouse", "title": "SWE",
        "company": "acme", "raw_location": "SF", "description_html": "<p>x</p>",
        "label_source": label_source, "category": cat, "level": lvl,
        "level_includes": [lvl], "tags": [], "locations": None,
    }


def _pred_row(jid, cat="software_engineering", lvl="mid", jp=True):
    return {"job_listing_id": jid, "category": cat, "level": lvl, "tags": [],
            "judge_pass": jp}


def _setup(monkeypatch, tmp_path, label_source="draft", with_judge_off=True):
    seed = tmp_path / "golden.json"
    seed.write_text(json.dumps([
        _seed_row("1", label_source=label_source),
        _seed_row("2", cat="business_ops", label_source=label_source),
    ]))
    scorecards = tmp_path / "scorecards"
    scorecards.mkdir()
    (scorecards / "predictions.json").write_text(json.dumps([
        _pred_row("1"), _pred_row("2", cat="business_ops", jp=False),
    ]))
    if with_judge_off:
        (scorecards / "predictions.judge_off.json").write_text(json.dumps([
            _pred_row("1"), _pred_row("2", cat="growth"),  # pre-judge got #2 wrong
        ]))
    monkeypatch.setattr(golden, "SEED_FILE", seed)
    monkeypatch.setattr(golden, "SCORECARD_DIR", scorecards)
    monkeypatch.setattr(report, "SCORECARD_DIR", scorecards)
    return scorecards


def test_allow_draft_scores_draft_rows_with_banner_and_stamp(monkeypatch, tmp_path, capsys):
    scorecards = _setup(monkeypatch, tmp_path)
    rc = run_eval(allow_draft=True)
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRAFT-GOLD ADVISORY (not a gate)" in out
    card = json.loads((scorecards / "scorecard.json").read_text())
    assert card["gold_quality"] == "draft"
    assert card["n"] == 2
    # judge metrics wired from the judge-off file
    assert card["judge_lift"]["category_accuracy"] == 0.5
    assert card["judge_kappa_prejudge"] is not None


def test_allow_draft_gate_is_advisory_exit_zero(monkeypatch, tmp_path, capsys):
    scorecards = _setup(monkeypatch, tmp_path)
    # a baseline the tiny run must "regress" against (and n=2 < min_n anyway)
    (scorecards / "baseline.json").write_text(json.dumps({"category_accuracy": 1.0}))
    rc = run_eval(gate=True, allow_draft=True)
    assert rc == 0  # NEVER gates on draft gold
    out = capsys.readouterr().out
    assert "ADVISORY" in out


def test_default_gate_requires_human_rows(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, label_source="draft")
    rc = run_eval(gate=True)  # human_only filter finds nothing
    assert rc == 1
    assert "no human-labeled golden rows" in capsys.readouterr().out


def test_human_rows_gate_enforced(monkeypatch, tmp_path, capsys):
    scorecards = _setup(monkeypatch, tmp_path, label_source="human")
    (scorecards / "baseline.json").write_text(json.dumps({"category_accuracy": 0.5}))
    rc = run_eval(gate=True)  # n=2 < min_n=50 -> gate refuses -> regression exit
    assert rc == 1
    out = capsys.readouterr().out
    assert "REGRESSION" in out and "min_n" in out
    card = json.loads((scorecards / "scorecard.json").read_text())
    assert card["gold_quality"] == "human"


def test_missing_predictions_file(monkeypatch, tmp_path, capsys):
    scorecards = _setup(monkeypatch, tmp_path)
    (scorecards / "predictions.json").unlink()
    rc = run_eval(allow_draft=True)
    assert rc == 1
    assert "not found" in capsys.readouterr().out


# --- EV-1: artifact namespacing (--tag), the ungated-facet WARN, draft relabel


def _setup_tagged(monkeypatch, tmp_path, tag, label_source="draft"):
    """Same fixture as `_setup` but writing TAG-namespaced prediction files."""
    seed = tmp_path / "golden.json"
    seed.write_text(json.dumps([
        _seed_row("1", label_source=label_source),
        _seed_row("2", cat="business_ops", label_source=label_source),
    ]))
    scorecards = tmp_path / "scorecards"
    scorecards.mkdir(exist_ok=True)
    (scorecards / f"predictions.{tag}.ollama.judge_off.json").write_text(json.dumps([
        _pred_row("1"), _pred_row("2", cat="business_ops"),
    ]))
    monkeypatch.setattr(golden, "SEED_FILE", seed)
    monkeypatch.setattr(golden, "SCORECARD_DIR", scorecards)
    monkeypatch.setattr(report, "SCORECARD_DIR", scorecards)
    return scorecards


def test_predictions_path_orders_tag_then_engine_then_judge(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "SCORECARD_DIR", tmp_path)
    assert report._predictions_path("off", "ollama", "v6").name == \
        "predictions.v6.ollama.judge_off.json"
    assert report._predictions_path(None, "ollama", "v7").name == \
        "predictions.v7.ollama.json"
    # backwards compatible: no tag == today's names
    assert report._predictions_path("off", "ollama").name == \
        "predictions.ollama.judge_off.json"
    assert report._predictions_path(None).name == "predictions.json"


def test_tag_namespaces_predictions_and_scorecard(monkeypatch, tmp_path, capsys):
    scorecards = _setup_tagged(monkeypatch, tmp_path, "v6")
    rc = run_eval(judge="off", engine="ollama", tag="v6", allow_draft=True)
    capsys.readouterr()
    assert rc == 0
    card = json.loads((scorecards / "scorecard.v6.ollama.judge_off.json").read_text())
    assert card["tag"] == "v6"
    assert not (scorecards / "scorecard.ollama.judge_off.json").exists()


def test_v7_run_leaves_the_v6_artifact_byte_identical(monkeypatch, tmp_path, capsys):
    """⚠ THE REASON --tag EXISTS. Files are namespaced by engine only today, so
    a second arm of the A/B silently destroys the first arm's irreproducible run."""
    scorecards = _setup_tagged(monkeypatch, tmp_path, "v6")
    v6_preds = scorecards / "predictions.v6.ollama.judge_off.json"
    before = v6_preds.read_bytes()
    run_eval(judge="off", engine="ollama", tag="v6", allow_draft=True)
    v6_card = (scorecards / "scorecard.v6.ollama.judge_off.json").read_bytes()

    # the v7 arm writes its OWN prediction artifact and scores it
    (scorecards / "predictions.v7.ollama.judge_off.json").write_text(json.dumps([
        _pred_row("1", cat="growth"), _pred_row("2", cat="growth"),
    ]))
    run_eval(judge="off", engine="ollama", tag="v7", allow_draft=True)
    capsys.readouterr()

    assert v6_preds.read_bytes() == before
    assert (scorecards / "scorecard.v6.ollama.judge_off.json").read_bytes() == v6_card
    assert (scorecards / "scorecard.v7.ollama.judge_off.json").exists()


def test_gate_warns_on_facets_absent_from_the_baseline(monkeypatch, tmp_path, capsys):
    """⚠ regression_gate `continue`s past a facet the baseline lacks, so it
    prints PASS while checking nothing. The WARN makes that visible."""
    scorecards = _setup(monkeypatch, tmp_path, label_source="human")
    (scorecards / "baseline.json").write_text(json.dumps({"category_accuracy": 0.5}))
    run_eval(gate=True)
    out = capsys.readouterr().out
    assert "eval --gate: WARN category_f1_macro absent from baseline — NOT checked" in out
    assert "eval --gate: WARN tags_token_f1 absent from baseline — NOT checked" in out
    # the facet the baseline DOES carry is not warned about
    assert "WARN category_accuracy" not in out


def test_gate_provenance_line_precedes_the_verdict(monkeypatch, tmp_path, capsys):
    scorecards = _setup(monkeypatch, tmp_path, label_source="human")
    (scorecards / "baseline.json").write_text(json.dumps({"category_accuracy": 0.5}))
    run_eval(gate=True)
    out = capsys.readouterr().out
    prov = "eval --gate: pool=human n=2 groups=category allow_draft=False"
    assert prov in out
    assert out.index(prov) < out.index("eval --gate: REGRESSION")


def test_gate_provenance_reports_draft_pool_under_allow_draft(monkeypatch, tmp_path, capsys):
    scorecards = _setup(monkeypatch, tmp_path)
    (scorecards / "baseline.json").write_text(json.dumps({"category_accuracy": 0.5}))
    run_eval(gate=True, allow_draft=True)
    out = capsys.readouterr().out
    assert "eval --gate: pool=draft n=2 groups=category allow_draft=True" in out


def test_draft_headline_says_agreement_not_accuracy(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path)
    run_eval(allow_draft=True)
    out = capsys.readouterr().out
    assert "agreement vs draft gold (NOT accuracy)" in out
    assert "  category            acc=" not in out
    assert "genuinely BETTER v7 scores WORSE" in out


def test_human_headline_still_says_acc(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path, label_source="human")
    run_eval()
    out = capsys.readouterr().out
    assert "  category            acc=" in out
    assert "agreement vs draft gold" not in out


# --- EV-10: the subcategory headline, provenance stamps, --facet, --gate-group
#     and the two independence rails


def _sub_seed_row(jid, subs, prov="human", model=None, cat="software_engineering"):
    r = _seed_row(jid, cat=cat, label_source="human")
    r["subcategories"] = subs
    r["gold_subcategory_provenance"] = prov
    if model:
        r["subcategory_prelabel_model"] = model
    return r


def _setup_sub(monkeypatch, tmp_path, seed_rows, preds, audit=None, tag=None):
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir(exist_ok=True)
    seed = seed_dir / "golden.json"
    seed.write_text(json.dumps(seed_rows))
    if audit is not None:
        (seed_dir / "subcategory_audit.json").write_text(json.dumps(audit))
    scorecards = tmp_path / "scorecards"
    scorecards.mkdir(exist_ok=True)
    name = ".".join(["predictions"] + ([tag] if tag else []) + ["ollama", "judge_off"])
    (scorecards / f"{name}.json").write_text(json.dumps(preds))
    monkeypatch.setattr(golden, "SEED_DIR", seed_dir)
    monkeypatch.setattr(golden, "SEED_FILE", seed)
    monkeypatch.setattr(golden, "SCORECARD_DIR", scorecards)
    monkeypatch.setattr(report, "SCORECARD_DIR", scorecards)
    return scorecards


def _sub_pred(jid, subs, cat="software_engineering"):
    return {"job_listing_id": jid, "category": cat, "level": "mid", "tags": [],
            "subcategories": subs}


def test_the_headline_carries_the_subcategory_line_and_n_sub(monkeypatch, tmp_path, capsys):
    _setup_sub(
        monkeypatch, tmp_path,
        [_sub_seed_row("1", ["backend"]), _sub_seed_row("2", ["frontend"])],
        [_sub_pred("1", ["backend"]), _sub_pred("2", ["frontend"])],
    )
    assert run_eval(judge="off", engine="ollama", facet="subcategory") == 0
    out = capsys.readouterr().out
    assert "subcategory [SWE only]" in out
    assert "n_sub=2" in out
    assert "set_f1=1.0000" in out
    assert "subcategory_gold_quality=human" in out


def test_facet_subcategory_writes_its_own_scorecard_and_leaves_scorecard_json_alone(
    monkeypatch, tmp_path, capsys
):
    """⚠ scorecard.json is the exact filename metrics.py ships to JVN."""
    scorecards = _setup_sub(
        monkeypatch, tmp_path, [_sub_seed_row("1", ["backend"])],
        [_sub_pred("1", ["backend"])],
    )
    (scorecards / "scorecard.judge_off.json").write_text('{"sentinel": true}')
    run_eval(judge="off", engine="ollama", facet="subcategory")
    capsys.readouterr()
    assert (scorecards / "scorecard.subcategory.ollama.judge_off.json").exists()
    assert json.loads((scorecards / "scorecard.judge_off.json").read_text()) == {
        "sentinel": True
    }


def test_the_independence_rail_fires_with_its_exact_message(monkeypatch, tmp_path, capsys):
    scorecards = _setup_sub(
        monkeypatch, tmp_path,
        [_sub_seed_row("1", ["backend"], model="ollama:qwen3:32b")],
        [_sub_pred("1", ["backend"])],
    )
    (scorecards / "baseline.json").write_text(json.dumps({"subcategory_set_f1": 0.5}))
    rc = run_eval(judge="off", engine="ollama", facet="subcategory", gate=True,
                  model="ollama:qwen3:32b")
    out = capsys.readouterr().out
    assert rc == 1
    assert (
        "subcategory gate refused: prelabel model 'ollama:qwen3:32b' == "
        "model under test 'ollama:qwen3:32b' (independence rule a)" in out
    )


def test_the_independence_rail_refuses_when_the_model_under_test_is_unknown(
    monkeypatch, tmp_path, capsys
):
    """⚠ `--model` is OPTIONAL, and the runbook's gate command used to omit it.

    With no `--model` the identity set is empty, so the equality check can never
    be true: the rail was SILENTLY INERT and the gate reported PASS while being
    scored against labels the model under test had produced. An unknown model
    under test is a REFUSAL.
    """
    scorecards = _setup_sub(
        monkeypatch, tmp_path,
        [_sub_seed_row("1", ["backend"], model="qwen3:32b")],
        [_sub_pred("1", ["backend"])],
    )
    (scorecards / "baseline.json").write_text(json.dumps({"subcategory_set_f1": 0.5}))
    rc = run_eval(judge="off", engine="ollama", facet="subcategory", gate=True)
    out = capsys.readouterr().out
    assert rc == 1
    assert (
        "subcategory gate refused: pool pre-labelled by 'qwen3:32b' and the "
        "model under test is unknown — pass --model (independence rule a)" in out
    )
    assert "eval --gate: PASS" not in out


def test_an_unlabelled_pool_needs_no_model_and_an_independent_one_passes():
    """The refusal is scoped: no pre-labeller means nothing to be independent of."""
    truth = [{"gold_subcategory_provenance": "human"}]
    assert report._subcategory_gate_rails(
        ("subcategory",), {"subcategory_prelabel_model": None}, truth, "ollama", None
    ) == []
    assert report._subcategory_gate_rails(
        ("subcategory",), {"subcategory_prelabel_model": "opus"}, truth,
        "ollama", "qwen3:32b",
    ) == []


def test_the_audit_rail_fires_with_its_exact_message(monkeypatch, tmp_path, capsys):
    scorecards = _setup_sub(
        monkeypatch, tmp_path,
        [_sub_seed_row("1", ["backend"], prov="prelabel_agreed")],
        [_sub_pred("1", ["backend"])],
        audit={"passed": True},   # load_truth admits the row...
    )
    (scorecards / "baseline.json").write_text(json.dumps({"subcategory_set_f1": 0.5}))
    # ...but the stamped verdict is then flipped, which the rail must catch
    (tmp_path / "seed" / "subcategory_audit.json").write_text(json.dumps({"passed": True}))
    truth = golden.load_truth(facet="subcategory")
    assert len(truth) == 1

    card = {"subcategory_audit_passed": False, "subcategory_prelabel_model": None}
    rails = report._subcategory_gate_rails(("subcategory",), card, truth, "ollama", None)
    assert rails == ["subcategory gate refused: agreement audit not passed"]


def test_the_rails_do_not_fire_for_the_category_group():
    card = {"subcategory_audit_passed": False, "subcategory_prelabel_model": "opus"}
    truth = [{"gold_subcategory_provenance": "prelabel_agreed"}]
    assert report._subcategory_gate_rails(("category",), card, truth, "claude-code", "opus") == []


def test_a_below_min_n_subcategory_group_refuses_only_itself(monkeypatch, tmp_path, capsys):
    """⚠ The category group must still evaluate."""
    rows = [_sub_seed_row(str(i), ["backend"]) for i in range(60)]
    preds = [_sub_pred(str(i), ["backend"]) for i in range(60)]
    # only 2 rows carry a subcategory gold label
    for r in rows[2:]:
        r["subcategories"] = None
        r["gold_subcategory_provenance"] = None
    scorecards = _setup_sub(monkeypatch, tmp_path, rows, preds)
    (scorecards / "baseline.json").write_text(json.dumps({
        "category_accuracy": 0.5, "subcategory_set_f1": 0.9,
    }))
    run_eval(judge="off", engine="ollama", gate=True,
             gate_groups=("category", "subcategory"))
    out = capsys.readouterr().out
    assert "subcategory gate refused: only 2 scored row(s)" in out
    # NB: "subcategory gate refused" CONTAINS "category gate refused", so the
    # category-group check has to look at the whole failure line.
    assert not any(
        line.strip().startswith("- category gate refused") for line in out.splitlines()
    )
    # the category group DID evaluate: its six facets produced no failure, so
    # the refusal line is the ONLY entry in the failure list.
    failures = [l for l in out.splitlines() if l.strip().startswith("- ")]
    assert len(failures) == 1
    assert "groups=category,subcategory" in out


def test_the_default_conf_threshold_is_080_and_the_at_ceiling_key_is_present(
    monkeypatch, tmp_path, capsys
):
    scorecards = _setup(monkeypatch, tmp_path, label_source="human")
    run_eval()
    capsys.readouterr()
    card = json.loads((scorecards / "scorecard.json").read_text())
    assert card["conf_threshold"] == 0.80
    assert card["conf_ceiling"] == 0.85
    assert "calibration_error_rate_below_at_ceiling" in card


def test_the_at_ceiling_key_differs_from_the_default_when_it_should(
    monkeypatch, tmp_path, capsys
):
    rows = [_sub_seed_row("1", None), _sub_seed_row("2", None)]
    preds = [
        dict(_sub_pred("1", None), confidence=0.82),           # right, conf 0.82
        dict(_sub_pred("2", None, cat="growth"), confidence=0.82),  # wrong, conf 0.82
    ]
    scorecards = _setup_sub(monkeypatch, tmp_path, rows, preds)
    run_eval(judge="off", engine="ollama")
    capsys.readouterr()
    card = json.loads((scorecards / "scorecard.ollama.judge_off.json").read_text())
    # at 0.80 both rows sit ABOVE the split, so the below-bucket is empty
    assert card["calibration_error_rate_below"] is None
    # at the 0.85 production ceiling both fall below it, and one is wrong
    assert card["calibration_error_rate_below_at_ceiling"] == 0.5
