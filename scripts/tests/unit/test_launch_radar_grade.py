"""``radar.py grade-export`` / ``grade-apply``: the AI Talent grade's plumbing, against the fake backend.

Covers: the export writes only what the rubric reads (no URLs, no team member names), clears
its directory, skips cards with no people data and, with ``--ungraded``, cards already graded
under the current rubric; a grade is validated against the rubric's output contract before
anything is written; ``apply`` makes ``talent`` the grade and keeps the rule blend as
``talent_rules`` (also across a re-grade); missing and invalid grades leave the card alone;
``--dry-run`` writes nothing; ``rescore`` keeps a grade and stays idempotent; and the rubric
file's version is the one the code writes. No Parallel client is ever built.
"""

import json
import re
from pathlib import Path

import pytest
from launch_radar import radar
from launch_radar.grade import RUBRIC_VERSION, ExportOptions, GradeError, apply, export, parse_grade
from launch_radar.pipeline import EXIT_ERROR, EXIT_OK
from tests.unit.test_launch_radar_rescore import Env, blended_payload

ROOT = Path(__file__).resolve().parents[3]


def grade(card_id: int, **over) -> dict:
    g = {"card_id": card_id, "industry": "CRM software",
         "parts": {"leaders": 30, "industry": 18, "team": 17, "track_record": 7}, "score": 72,
         "confidence": "high", "reasons": ["Founder sold Ledgerline to Northwind", "Team: Google x6, Stripe x3"]}
    g.update(over)
    return g


def write_grade(dir_: Path, card_id: int, body) -> None:
    (dir_ / "grades" / f"{card_id}.json").write_text(body if isinstance(body, str) else json.dumps(body))


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.add("light.ai", 7, blended_payload("light.ai"))
    e.add("dark.ai", 8, blended_payload("dark.ai"), status="saved")
    e.add("quiet.ai", 9, blended_payload("quiet.ai", team=None, leaders=False))  # no people data
    e.add("gone.ai", 10, blended_payload("gone.ai"), status="archived")
    return e


def run_export(env, dir_, **opts):
    return export(ExportOptions(dir=dir_, **opts), env.deps())


class TestExport:
    def test_writes_only_what_the_rubric_reads(self, env, tmp_path):
        d = tmp_path / "g"
        assert run_export(env, d, all_cards=True) == EXIT_OK
        assert sorted(p.name for p in (d / "inputs").iterdir()) == ["10.json", "7.json", "8.json"]  # not quiet.ai
        inp = json.loads((d / "inputs" / "7.json").read_text())
        assert inp["card_id"] == 7 and inp["rubric_version"] == RUBRIC_VERSION and inp["domain"] == "light.ai"
        assert set(inp["team_stats"]) == {"profiles_found", "team_size_estimate", "schools", "prior_employers"}
        assert "sample_names" not in json.dumps(inp)  # no team member names
        assert not re.search(r"https?://", json.dumps(inp))  # no URLs (no profile links)
        assert any("skip card 9 Quiet: no people data" in line for line in env.logs)
        env.assert_free()

    def test_clears_the_directory_first(self, env, tmp_path):
        d = tmp_path / "g"
        (d / "grades").mkdir(parents=True)
        write_grade(d, 7, grade(7))  # a stale grade from an earlier export
        assert run_export(env, d, domains=frozenset({"light.ai"})) == EXIT_OK
        assert list((d / "grades").iterdir()) == []

    def test_ungraded_skips_current_grades_and_archived_cards(self, env, tmp_path):
        d = tmp_path / "g"
        run_export(env, d, domains=frozenset({"light.ai", "dark.ai"}))
        write_grade(d, 7, grade(7))
        write_grade(d, 8, grade(8))
        assert apply(d, env.deps(), dry_run=False, graded_at="2026-10-08T00:00:00Z") == EXIT_OK
        env.fb.cards["dark.ai"]["payload"]["scores"]["talent_ai"]["rubric_version"] = "v0"  # an older rubric
        assert run_export(env, d, ungraded=True) == EXIT_OK
        assert sorted(p.name for p in (d / "inputs").iterdir()) == ["8.json"]  # gone.ai is archived

    def test_needs_exactly_one_selector(self, env, tmp_path):
        assert run_export(env, tmp_path / "g", all_cards=True, ungraded=True) == EXIT_ERROR


class TestParseGrade:
    def test_valid_grade_round_trips_and_cleans_text(self):
        g = parse_grade("```json\n" + json.dumps(grade(7, reasons=["AT&amp;T  veteran\nCTO"])) + "\n```", 7)
        assert g["score"] == 72 and g["reasons"] == ["AT&T veteran CTO"]
        assert set(g) == {"score", "parts", "confidence", "industry", "reasons"}

    @pytest.mark.parametrize("bad, why", [
        ("not json", "not JSON"),
        ("[1, 2]", "not a JSON object"),
        (grade(8), "card_id"),
        (grade(7, score=71), "sum of the parts"),
        (grade(7, score=True), "sum of the parts"),
        (grade(7, parts={"leaders": 41, "industry": 18, "team": 17, "track_record": 7}, score=83), "parts.leaders"),
        (grade(7, parts={"leaders": 30, "industry": 18, "team": 17}), "exactly"),
        (grade(7, parts={"leaders": 30.0, "industry": 18, "team": 17, "track_record": 7}), "parts.leaders"),
        (grade(7, confidence="certain"), "confidence"),
        (grade(7, reasons=[]), "reasons"),
        (grade(7, reasons=["x"] * 7), "reasons"),
        (grade(7, reasons=["x" * 301]), "longer than 300"),
        (grade(7, industry=""), "industry"),
    ])
    def test_rejects_what_breaks_the_contract(self, bad, why):
        with pytest.raises(GradeError, match=why):
            parse_grade(bad if isinstance(bad, str) else json.dumps(bad), 7)


class TestApply:
    def test_grade_becomes_talent_and_the_rule_blend_is_kept(self, env, tmp_path):
        d = tmp_path / "g"
        run_export(env, d, domains=frozenset({"light.ai"}))
        before = env.fb.cards["light.ai"]["payload"]
        rules = before["scores"]["talent"]
        write_grade(d, 7, grade(7))
        assert apply(d, env.deps(), dry_run=False, graded_at="2026-10-08T00:00:00Z") == EXIT_OK
        after = env.fb.cards["light.ai"]["payload"]
        s = after["scores"]
        assert s["talent"] == 72 and s["talent_rules"] == rules
        assert s["talent_ai"] == {"score": 72, "parts": grade(7)["parts"], "confidence": "high",
                                  "industry": "CRM software", "reasons": grade(7)["reasons"],
                                  "rubric_version": RUBRIC_VERSION, "graded_at": "2026-10-08T00:00:00Z"}
        # The rule breakdown and everything outside the scores are untouched.
        for k in ("talent_leaders", "talent_team", "talent_basis", "talent_reasons", "talent_team_reasons", "vc"):
            assert s[k] == before["scores"][k]
        assert {k: v for k, v in after.items() if k != "scores"} == {k: v for k, v in before.items() if k != "scores"}
        row = json.loads((d / "results.json").read_text())[0]
        assert (row["card_id"], row["talent_rules"], row["talent_ai"]) == (7, rules, 72)
        env.assert_free()

    def test_regrade_keeps_the_original_rule_score(self, env, tmp_path):
        d = tmp_path / "g"
        rules = env.fb.cards["light.ai"]["payload"]["scores"]["talent"]
        for score_parts in ({"leaders": 30, "industry": 18, "team": 17, "track_record": 7},
                            {"leaders": 20, "industry": 10, "team": 10, "track_record": 0}):
            run_export(env, d, domains=frozenset({"light.ai"}))
            write_grade(d, 7, grade(7, parts=score_parts, score=sum(score_parts.values())))
            apply(d, env.deps(), dry_run=False, graded_at="2026-10-08T00:00:00Z")
        s = env.fb.cards["light.ai"]["payload"]["scores"]
        assert (s["talent"], s["talent_rules"]) == (40, rules)

    def test_missing_and_invalid_grades_leave_the_card_alone(self, env, tmp_path):
        d = tmp_path / "g"
        run_export(env, d, domains=frozenset({"light.ai", "dark.ai"}))
        before = {dom: json.dumps(env.fb.cards[dom]["payload"]) for dom in ("light.ai", "dark.ai")}
        write_grade(d, 8, grade(8, score=1))  # invalid; 7 has no grade at all
        assert apply(d, env.deps(), dry_run=False, graded_at="x") == EXIT_OK
        assert env.puts() == []
        assert {dom: json.dumps(env.fb.cards[dom]["payload"]) for dom in before} == before
        assert env.logs[-1] == "grade-apply: applied 0, missing 1, invalid 1, gone 0, errors 0"

    def test_dry_run_writes_nothing(self, env, tmp_path):
        d = tmp_path / "g"
        run_export(env, d, domains=frozenset({"light.ai"}))
        write_grade(d, 7, grade(7))
        assert apply(d, env.deps(), dry_run=True, graded_at="x") == EXIT_OK
        assert env.puts() == [] and "talent_ai" not in env.fb.cards["light.ai"]["payload"]["scores"]
        assert any(line.startswith("would apply card 7 Light: talent") for line in env.logs)

    def test_a_backend_error_exits_1(self, env, tmp_path):
        d = tmp_path / "g"
        run_export(env, d, domains=frozenset({"light.ai"}))
        write_grade(d, 7, grade(7))
        env.put_status[7] = 422
        assert apply(d, env.deps(), dry_run=False, graded_at="x") == EXIT_ERROR


def test_rescore_keeps_a_grade_and_stays_idempotent(env, tmp_path):
    d = tmp_path / "g"
    run_export(env, d, domains=frozenset({"light.ai"}))
    write_grade(d, 7, grade(7))
    apply(d, env.deps(), dry_run=False, graded_at="2026-10-08T00:00:00Z")
    graded = json.loads(json.dumps(env.fb.cards["light.ai"]["payload"]["scores"]))
    puts = len(env.puts())
    assert env.rescore(domains=frozenset({"light.ai"})) == EXIT_OK
    assert env.fb.cards["light.ai"]["payload"]["scores"] == graded
    assert len(env.puts()) == puts  # unchanged: no PUT


def test_rubric_file_carries_the_code_version():
    rubric = (ROOT / ".claude" / "skills" / "launch-radar-grade" / "rubric.md").read_text()
    assert re.search(rf"^# Launch Radar Talent rubric — `{RUBRIC_VERSION}`$", rubric, re.MULTILINE)


def test_cli_wires_both_commands(env, tmp_path):
    d = tmp_path / "g"
    assert radar.main(["grade-export", "--domains", "light.ai", "--dir", str(d)], deps=env.deps()) == EXIT_OK
    write_grade(d, 7, grade(7))
    assert radar.main(["grade-apply", "--dir", str(d), "--dry-run"], deps=env.deps()) == EXIT_OK
    with pytest.raises(SystemExit):
        radar.main(["grade-export", "--dir", str(d)], deps=env.deps())  # needs a selector
