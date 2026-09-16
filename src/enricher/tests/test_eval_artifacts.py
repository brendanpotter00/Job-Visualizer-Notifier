"""EV-12: CI assertions over COMMITTED eval artifacts — not a run.

⚠ READ THIS BEFORE ADDING A SKIP. Most of the assertions below are gated on the
artifact existing, because the runs that produce them (`EV-2`, `EV-2b`, `EV-2c`,
`EV-9b`, `EV-12`) are deliberately NOT performed in this PR. `test_the_ship_gate_
preconditions_are_reported_honestly` is the one that always runs: it FAILS if
the protocol doc ever claims a precondition is met while the artifact backing it
is absent. That is what stops the skips below from quietly becoming permanent.
"""

import json
import subprocess

import pytest

from job_enricher.eval.golden import SCORECARD_DIR, audit_path, load_truth
from job_enricher.eval.scoring import _FACET_GROUPS, GATE_MIN_N
from job_enricher.store import REPO_ROOT

BASELINES = REPO_ROOT / "golden" / "baselines"
DOCS = REPO_ROOT / "docs"
SKILL_MD_V6_GIT_SHA = "8ff1eb1401bf19b9d879678262c389e4f45b8cc1"


def _json_or_skip(path, produced_by):
    if not path.exists():
        pytest.skip(f"{path.name} not committed yet — produced by {produced_by} (a RUN)")
    return json.loads(path.read_text(encoding="utf-8"))


# --- always-on: the guards that need no run --------------------------------


def test_the_v6_skill_md_blob_sha_still_resolves_to_a_v6_rubric():
    """⚠ OPEN RISK #1, MADE A TEST. The working tree is v7, so the v6 arm of the
    A/B is reachable ONLY through this blob. If the SHA stops resolving — a
    rewritten history, a pruned object — the v6 arm becomes unrecoverable and
    the whole comparison is dead. Better to learn that from a red build."""
    proc = subprocess.run(
        ["git", "cat-file", "-p", SKILL_MD_V6_GIT_SHA],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip("git object store unavailable in this environment")
    assert "version: v6" in proc.stdout.splitlines()[3]

    import hashlib

    assert hashlib.sha256(proc.stdout.encode()).hexdigest()[:12] == "2bf741ee8ea1"


def test_the_recorded_sha_appears_in_the_baseline_doc():
    doc = (DOCS / "EVAL-V6-BASELINE.md").read_text(encoding="utf-8")
    assert SKILL_MD_V6_GIT_SHA in doc


def test_the_protocol_gate_command_carries_no_allow_draft():
    """⚠ `--allow-draft` is `return 0 if allow_draft else 1` — a gate run with
    it can never fail. A protocol whose recorded command line carries it is
    documenting a gate that is not one."""
    proto = (DOCS / "EVAL-V6-V7-PROTOCOL.md").read_text(encoding="utf-8")
    gate_lines = [
        line for line in proto.splitlines()
        if "--gate" in line or "regression_gate(" in line
    ]
    assert gate_lines
    for line in gate_lines:
        assert "--allow-draft" not in line, line


def test_the_ship_gate_preconditions_are_reported_honestly():
    """⚠ THE ANTI-SKIP GUARD. Every precondition the protocol marks as MET must
    have its artifact on disk. This is what stops the doc drifting into
    claiming a gate arm ran when the artifact behind it was never produced."""
    proto = (DOCS / "EVAL-V6-V7-PROTOCOL.md").read_text(encoding="utf-8")
    backing = {
        "P2": BASELINES / "v6" / "predictions.ollama.judge_off.json",
        "P3": None,   # checked live below
        "P4": None,   # checked live below
    }
    for pid, path in backing.items():
        row = next(line for line in proto.splitlines() if line.startswith(f"| {pid} "))
        claims_met = "✔" in row
        if pid == "P3":
            actually = len(load_truth(human_only=True)) >= 55
        elif pid == "P4":
            actually = len(load_truth(facet="subcategory")) >= 55
        else:
            actually = path.exists()
        assert claims_met == actually, (
            f"{pid}: the protocol claims met={claims_met} but the evidence "
            f"says {actually}"
        )


def test_the_weak_rule_baseline_exists_and_carries_input_mode():
    card = _json_or_skip(SCORECARD_DIR / "baseline.weak_rule.json", "EV-11")
    assert card["input_mode"] == "title_only"
    art = _json_or_skip(
        BASELINES / "weak_rule" / "predictions.weak_rule.json", "EV-11"
    )
    assert art["input_mode"] == "title_only"
    # ⚠ The card must declare whether it can gate. An all-zeros card scored
    # against an EMPTY subcategory pool is a placeholder — G2's "beat
    # subcategory_set_f1 by 0.10" against 0.0 is a free pass.
    assert card["gate_ready"] is (card["subcategory_n"] > 0)
    assert (card["gate_blocked_reason"] is None) is card["gate_ready"]


# --- armed once the runs land ----------------------------------------------


def test_both_v6_baselines_exist_and_carry_n_and_gold_quality():
    human = _json_or_skip(SCORECARD_DIR / "baseline.v6.human.json", "EV-2c")
    draft = _json_or_skip(SCORECARD_DIR / "baseline.v6.draft.json", "EV-2c")
    assert human["gold_quality"] == "human"
    assert human["n"] >= GATE_MIN_N
    assert "n" in draft and "gold_quality" in draft


def test_the_v6_and_v7_prediction_artifacts_cover_identical_row_sets():
    """⚠ At batch > 1 dropped chunks are skipped SILENTLY and only a
    covered/total line is printed. The paired arm G1b is meaningless if the two
    arms do not cover the same rows."""
    v6 = _json_or_skip(BASELINES / "v6" / "predictions.ollama.judge_off.json", "EV-2")
    v7 = _json_or_skip(BASELINES / "v7" / "predictions.ollama.judge_off.json", "EV-12")
    assert {p["job_listing_id"] for p in v6} == {p["job_listing_id"] for p in v7}


def test_every_gated_category_facet_is_present_in_the_v6_human_baseline():
    """⚠ `regression_gate` skips a facet the baseline lacks while still printing
    PASS. EV-1's WARN makes that visible; this makes it fail."""
    card = _json_or_skip(SCORECARD_DIR / "baseline.v6.human.json", "EV-2c")
    for facet in _FACET_GROUPS["category"] + ("category_f1_macro_supported",):
        assert card.get(facet) is not None, facet


def test_the_category_audit_exists_and_did_not_promote():
    audit = _json_or_skip(audit_path("category"), "EV-2b")
    assert audit["promote_agreements"] is False
    assert audit["error_rate"] is not None


def test_the_subcategory_audit_exists_and_passed():
    audit = _json_or_skip(audit_path("subcategory"), "EV-9b")
    assert audit["passed"] is True


def test_the_category_pool_cleared_the_gate_floor():
    if len(load_truth(human_only=True)) < GATE_MIN_N:
        pytest.skip("EV-2b (a RUN + human review) has not been performed")
    assert len(load_truth(human_only=True)) >= GATE_MIN_N


def test_the_subcategory_pool_cleared_the_gate_floor_with_no_contract_rows():
    pool = load_truth(facet="subcategory")
    if len(pool) < GATE_MIN_N:
        pytest.skip("EV-9b (a RUN + human review) has not been performed")
    assert len(pool) >= GATE_MIN_N
    assert not any(
        r.get("gold_subcategory_provenance") == "contract" for r in pool
    ), "⚠ a contract row reached the subcategory gate pool — the fake-n trap"
