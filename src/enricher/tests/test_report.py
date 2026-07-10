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
