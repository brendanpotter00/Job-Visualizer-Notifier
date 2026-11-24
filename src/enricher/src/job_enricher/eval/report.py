"""Run an eval + print a scorecard; optionally enforce the regression gate.

Separation of concerns: the agentic clean->classify->judge is driven by the
/enrich-eval Claude Code workflow, which writes predictions to
golden/scorecards/predictions[.judge_off].json. `cli eval` then SCORES those
predictions with the pure scorer — no keys, deterministic, CI-safe.

Gold quality: the GATE only ever runs against human labels
(label_source='human'). `--allow-draft` scores against draft labels too, but
is loudly ADVISORY — it stamps `gold_quality: "draft"` into the scorecard,
prints an unmissable banner, and always exits 0 (a draft self-agreement number
must never block or bless a prompt change).
"""

from __future__ import annotations

import json
from pathlib import Path

from job_enricher.eval.golden import SCORECARD_DIR, load_truth
from job_enricher.eval.scoring import (
    gated_facets,
    judge_lift,
    missing_baseline_facets,
    regression_gate,
    score,
)

_DRAFT_BANNER = "\n".join(
    [
        "############################################################",
        "##  DRAFT-GOLD ADVISORY (not a gate)                      ##",
        "##  These scores are measured against DRAFT labels — the  ##",
        "##  pipeline agreeing with its own drafts, NOT accuracy.  ##",
        "##  Draft labels are judge-bootstrapped v6 OUTPUT, so a   ##",
        "##  genuinely BETTER v7 scores WORSE against them.        ##",
        "##  Nothing here passes or fails anything. Exit code: 0.  ##",
        "############################################################",
    ]
)


def _predictions_path(
    judge: str | None, engine: str | None = None, tag: str | None = None
) -> Path:
    """Prediction artifact path: ``predictions[.<tag>][.<engine>][.judge_off].json``.

    ⚠ THE `tag` SEGMENT IS WHAT MAKES AN A/B POSSIBLE. Without it files are
    namespaced by ENGINE ONLY, so a v7 run over the same engine silently
    OVERWRITES the v6 artifact — and the v6 arm of a taxonomy A/B is a model run
    that cannot be repeated once the rubric has moved. Always pass `--tag` on
    both arms.
    """
    parts = ["predictions"]
    if tag:
        parts.append(tag)
    if engine:
        parts.append(engine)
    if judge == "off":
        parts.append("judge_off")
    return SCORECARD_DIR / (".".join(parts) + ".json")


def _fmt(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _headline(card: dict) -> str:
    """Human-readable summary. Level headline is `filter_consistent` (the fair
    metric under the new_grad⊂entry contract); `exact` is shown as secondary
    because the draft gold under-levels some rows. Tags show the fair,
    granularity-tolerant metrics next to the strict exact-match numbers.

    ⚠ UNDER DRAFT GOLD THE CATEGORY/LEVEL LINES SAY "agreement", NOT "acc".
    `--allow-draft` scores against `label_source='draft'` labels, which
    golden.py's module docstring defines as judge-bootstrapped — i.e. v6's OWN
    OUTPUT. Those numbers measure AGREEMENT WITH v6, so a genuinely better v7
    scores WORSE. Printing them under the word "acc" is how a real improvement
    gets read as a regression in a pasted scrollback.
    """
    g = card.get
    draft = card.get("gold_quality") == "draft"
    cat_label = "agreement vs draft gold (NOT accuracy)" if draft else "acc"
    lvl_note = " [agreement vs draft gold, NOT accuracy]" if draft else ""
    return "\n".join(
        [
            "── eval scorecard ─────────────────────────────────────────",
            f"  category            {cat_label}={_fmt(g('category_accuracy'))}  macro_f1={_fmt(g('category_f1_macro'))}",
            f"  level [PRIMARY]     filter_consistent={_fmt(g('level_filter_consistent_accuracy'))}{lvl_note}",
            f"  level (secondary)  exact={_fmt(g('level_exact_accuracy'))}",
            f"  tags [fair]        jaccard={_fmt(g('tags_jaccard'))}  overlap={_fmt(g('tags_overlap'))}  recall={_fmt(g('tags_recall'))}  token_f1={_fmt(g('tags_token_f1'))}",
            f"  tags (strict)      exact_f1={_fmt(g('tags_f1'))}  precision={_fmt(g('tags_precision'))}  recall_micro={_fmt(g('tags_recall_micro'))}",
            f"  location primary   acc={_fmt(g('location_primary_accuracy'))}",
            # ⚠ n_sub IS PRINTED EXPLICITLY. A reader who sees only an accuracy
            # number on a thin pool will over-trust it, and this facet's pool
            # is a strict subset of every other facet's.
            f"  subcategory [SWE only] primary_ne={_fmt(g('subcategory_primary_accuracy_nonempty'))}"
            f"  set_f1={_fmt(g('subcategory_set_f1'))}"
            f"  macro_f1={_fmt(g('subcategory_f1_macro'))}"
            f"  coverage={_fmt(g('subcategory_coverage'))}"
            f"  leak={_fmt(g('subcategory_leak_rate'))}"
            f"  card={_fmt(g('subcategory_cardinality_mean'))}"
            f"  excl={_fmt(g('subcategory_exclusivity_violations'))}"
            f"  n_sub={_fmt(g('subcategory_n'))}",
            f"  judge_kappa_prejudge {_fmt(g('judge_kappa_prejudge'))}",
            f"  latency (ms)       classify={_fmt_latency(g('classify_latency_ms'))}  judge={_fmt_latency(g('judge_latency_ms'))}",
            f"  gold_quality       {_fmt(g('gold_quality'))}"
            f"   subcategory_gold_quality={_fmt(g('subcategory_gold_quality'))}"
            f"  audit_passed={_fmt(g('subcategory_audit_passed'))}",
            f"  n={_fmt(g('n'))}",
            "────────────────────────────────────────────────────────────",
        ]
    )


def _fmt_latency(stats: object) -> str:
    if not isinstance(stats, dict):
        return "n/a"
    return f"mean={stats.get('mean')} p50={stats.get('p50')} p95={stats.get('p95')} (n={stats.get('n')})"


def _reasoning_dump(predictions: list[dict], truth: list[dict], limit: int = 60) -> str:
    """Per-row 'why' block: predicted vs gold category/level + the classify and
    judge rationales. This is the `--reasoning` view — it explains WHY each row
    landed where it did (the model's own stated signal), which the numeric
    scorecard can't show."""
    tby = {t["job_listing_id"]: t for t in truth}
    lines = ["── reasoning (predicted vs gold + rationale) ──────────────"]
    shown = 0
    for p in predictions:
        g = tby.get(p["job_listing_id"])
        if g is None:
            continue
        if shown >= limit:
            lines.append(f"  … ({len(predictions) - shown} more rows omitted; raise --reasoning-limit)")
            break
        shown += 1
        cat_ok = "✓" if p.get("category") == g.get("category") else "✗"
        lvl_ok = "✓" if p.get("level") == g.get("level") else "✗"
        lines.append(
            f"\n  [{p['job_listing_id']}] cat {cat_ok} {p.get('category')} (gold {g.get('category')})"
            f"  |  level {lvl_ok} {p.get('level')} (gold {g.get('level')})"
        )
        cr = (p.get("reasoning") or "").strip()
        if cr:
            lines.append(f"    classify: {cr}")
        if "judge_pass" in p:
            verdict = "PASS" if p.get("judge_pass") else "CORRECTED/FAIL"
            lines.append(f"    judge [{verdict}]: {(p.get('judge_reasoning') or '').strip() or '(no rationale)'}")
    lines.append("────────────────────────────────────────────────────────────")
    return "\n".join(lines)


# Re-exported from the scorer so there is exactly ONE definition of the
# production judge ceiling in the eval harness.
from job_enricher.eval.scoring import JUDGE_CONFIDENCE_CEILING  # noqa: E402


def _subcategory_provenance(truth: list[dict]) -> dict:
    """Provenance stamps for the SUBCATEGORY pool.

    ⚠ It carries DIFFERENT provenance than the category pool — the two are
    gated on different columns with disjoint vocabularies — so a single
    `gold_quality` stamp cannot describe both."""
    from job_enricher.eval.golden import audit_passed

    labelled = [r for r in truth if r.get("subcategories") is not None]
    provs = [r.get("gold_subcategory_provenance") for r in labelled]
    models = [
        r.get("subcategory_prelabel_model") for r in labelled
        if r.get("subcategory_prelabel_model")
    ]
    return {
        "subcategory_gold_quality": _modal(provs),
        "subcategory_prelabel_model": _modal(models),
        "subcategory_audit_passed": audit_passed("subcategory"),
    }


def _modal(values: list) -> object:
    seen: dict = {}
    for v in values:
        if v is None:
            continue
        seen[v] = seen.get(v, 0) + 1
    if not seen:
        return None
    return max(sorted(seen), key=lambda k: seen[k])


def _subcategory_gate_rails(
    gate_groups: tuple[str, ...], card: dict, truth: list[dict],
    engine: str | None, model: str | None,
) -> list[str]:
    """The two refusals that must fire BEFORE any subcategory verdict is printed.

    Both exist because the failure they catch is invisible in the numbers: a
    gate scored against labels the model under test produced (or agreed with)
    reports a comfortable pass while measuring nothing but self-consistency.
    """
    if "subcategory" not in gate_groups:
        return []
    out: list[str] = []

    # (1) INDEPENDENCE
    #
    # ⚠ FAIL CLOSED WHEN THE MODEL UNDER TEST IS UNKNOWN. `--model` is optional
    # (cli.py's eval parser defaults it to None) and the runbooks' gate commands
    # used to omit it, which made this rail SILENTLY INERT: with no identity to
    # compare against, `prelabel_model in identities` is never true, nothing is
    # printed, and a gate scored against labels the model under test produced
    # itself reports PASS. An unknown identity is therefore a refusal, not a
    # pass — the pool is only exempt when NOTHING in it was pre-labelled.
    prelabel_model = card.get("subcategory_prelabel_model")
    identities = {i for i in (model, f"{engine}:{model}" if engine and model else None) if i}
    if prelabel_model and not identities:
        out.append(
            f"subcategory gate refused: pool pre-labelled by '{prelabel_model}' "
            "and the model under test is unknown — pass --model "
            "(independence rule a)"
        )
    elif prelabel_model and prelabel_model in identities:
        out.append(
            f"subcategory gate refused: prelabel model '{prelabel_model}' == "
            f"model under test '{prelabel_model}' (independence rule a)"
        )

    # (2) AUDIT
    has_agreed = any(
        r.get("gold_subcategory_provenance") == "prelabel_agreed" for r in truth
    )
    if has_agreed and card.get("subcategory_audit_passed") is not True:
        out.append("subcategory gate refused: agreement audit not passed")
    return out


def _gate_group_names(gate_groups: tuple[str, ...] | None) -> tuple[str, ...]:
    return tuple(gate_groups) if gate_groups else ("category",)


def _gated_facets_for(gate_groups: tuple[str, ...] | None) -> tuple[str, ...]:
    """The facet keys the gate will actually compare, for this run's groups."""
    return gated_facets(gate_groups)


def _load_predictions(path: Path) -> list[dict] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_eval(
    golden_set: str = "golden",
    judge: str | None = None,
    gate: bool = False,
    baseline: str | None = None,
    allow_draft: bool = False,
    engine: str | None = None,
    reasoning: bool = False,
    tag: str | None = None,
    facet: str = "all",
    gate_groups: tuple[str, ...] | None = None,
    model: str | None = None,
    conf_threshold: float = 0.80,
) -> int:
    # ⚠ EACH FACET IS SCORED AGAINST ITS OWN POOL, in its own run. Merging the
    # two truth lists would inflate `category.n` with rows that have no
    # category gold and silently move every committed category baseline.
    subcategory_only = facet == "subcategory"
    if gate_groups is None:
        gate_groups = ("subcategory",) if subcategory_only else ("category",)
    gate_groups = tuple(gate_groups)
    truth = (
        load_truth(facet="subcategory") if subcategory_only
        else load_truth(human_only=not allow_draft)
    )
    if not truth and subcategory_only:
        print("eval: no gold subcategory rows (golden/seed/golden.json).")
        print("      Build the pool with `cli prelabel --facet subcategory`,")
        print("      `cli review-build`, `cli review-render`, `cli review-apply`.")
        return 1
    if not truth:
        print("eval: no human-labeled golden rows found (golden/seed/golden.json).")
        print("      Run `cli build-golden-set` then label rows with label_source='human',")
        print("      or use `cli golden-merge` to pull JVN admin corrections in.")
        print("      (`--allow-draft` scores draft labels — advisory only, never a gate.)")
        return 1
    gold_quality = "human" if all(r.get("label_source") == "human" for r in truth) else "draft"

    pred_path = _predictions_path(judge, engine, tag)
    predictions = _load_predictions(pred_path)
    if predictions is None:
        print(f"eval: predictions file {pred_path} not found.")
        if engine:
            tag_hint = f" --tag {tag}" if tag else ""
            print(f"      Produce it with `cli eval-run --engine {engine}{tag_hint}` (headless).")
        else:
            print("      Produce it with the /enrich-eval workflow or `cli eval-run`.")
        return 1

    # The judge-off predictions are the PRE-judge labels: when scoring the
    # judged run they unlock the honest judge metrics (κ vs pre-judge
    # correctness + per-facet lift). Same engine namespace as the judged run.
    prejudge = None
    if judge != "off":
        prejudge = _load_predictions(_predictions_path("off", engine, tag))

    sc = score(predictions, truth, conf_threshold=conf_threshold,
               prejudge_predictions=prejudge)
    card = sc.to_dict()
    card["gold_quality"] = gold_quality
    # ⚠ A LIVE INCONSISTENCY, CORRECTED WITHOUT BREAKING COMPARABILITY.
    # Calibration splits at the scorer's 0.80 default while production routes
    # the judge at 0.85 (`JUDGE_CONFIDENCE_CEILING_DEFAULT`). Threading the live
    # ceiling through would silently invalidate baseline.json's committed
    # 0.4937 / 0.1702, so the default stays 0.80 and the at-ceiling number is a
    # SECOND key. Both are documented; neither replaces the other.
    card["calibration_error_rate_below_at_ceiling"] = score(
        predictions, truth, conf_threshold=JUDGE_CONFIDENCE_CEILING
    ).to_dict()["calibration_error_rate_below"]
    card["conf_threshold"] = conf_threshold
    card["conf_ceiling"] = JUDGE_CONFIDENCE_CEILING
    card.update(_subcategory_provenance(truth))
    if engine:
        card["engine"] = engine
    if tag:
        card["tag"] = tag
    if prejudge is not None:
        card["judge_lift"] = judge_lift(sc, score(prejudge, truth))
    if allow_draft and gold_quality == "draft":
        print(_DRAFT_BANNER)
    print(_headline(card))
    if reasoning:
        print(_reasoning_dump(predictions, truth))
    print(json.dumps(card, indent=2))

    SCORECARD_DIR.mkdir(parents=True, exist_ok=True)
    # Same namespacing as the prediction artifact: scorecard[.tag][.engine][.judge_x]
    # ⚠ `--facet subcategory` gets its OWN filename. `scorecard.json` is the
    # exact name `metrics.py:_fresh_scorecard` ships to JVN, so a
    # subcategory-only run must not overwrite it — otherwise `metrics-push`
    # re-ships a card whose category numbers came from a different pool.
    parts = ["scorecard"]
    if subcategory_only:
        parts.append("subcategory")
    if tag:
        parts.append(tag)
    if engine:
        parts.append(engine)
    if judge:
        parts.append(f"judge_{judge}")
    out = SCORECARD_DIR / (".".join(parts) + ".json")
    out.write_text(json.dumps(card, indent=2), encoding="utf-8")

    if gate:
        baseline_path = Path(baseline) if baseline else (SCORECARD_DIR / "baseline.json")
        if not baseline_path.exists():
            print(f"eval --gate: baseline {baseline_path} not found; run once and commit it.")
            return 0 if allow_draft else 1
        base = json.loads(baseline_path.read_text(encoding="utf-8"))
        rails = _subcategory_gate_rails(gate_groups, card, truth, engine, model)
        if rails:
            for r in rails:
                print(r)
            return 0 if allow_draft else 1
        # ⚠ (c) PROVENANCE FIRST, before any verdict. An `--allow-draft` run
        # prints "PASS" too, and in a terminal scrollback or a pasted handoff
        # that line is indistinguishable from a real gate. This says, on the
        # line above the verdict, exactly which pool produced it.
        print(
            f"eval --gate: pool={gold_quality} n={sc.category.n} "
            f"groups={','.join(_gate_group_names(gate_groups))} allow_draft={bool(allow_draft)}"
        )
        # ⚠ (b) Then name every facet the gate is about to NOT check.
        for facet in missing_baseline_facets(base, _gated_facets_for(gate_groups)):
            print(f"eval --gate: WARN {facet} absent from baseline — NOT checked")
        failures = regression_gate(sc, base, groups=gate_groups)
        if failures:
            print("eval --gate: REGRESSION" + (" (ADVISORY — draft gold, not enforced)" if allow_draft else ""))
            for f in failures:
                print(f"  - {f}")
            if allow_draft:
                print(_DRAFT_BANNER)
                return 0
            return 1
        print("eval --gate: PASS" + (" (ADVISORY — draft gold, not a real gate)" if allow_draft else ""))
    if allow_draft and gold_quality == "draft":
        print(_DRAFT_BANNER)
    return 0
