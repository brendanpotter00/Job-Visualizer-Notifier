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
from job_enricher.eval.scoring import judge_lift, regression_gate, score

_DRAFT_BANNER = "\n".join(
    [
        "############################################################",
        "##  DRAFT-GOLD ADVISORY (not a gate)                      ##",
        "##  These scores are measured against DRAFT labels — the  ##",
        "##  pipeline agreeing with its own drafts, NOT accuracy.  ##",
        "##  Nothing here passes or fails anything. Exit code: 0.  ##",
        "############################################################",
    ]
)


def _predictions_path(judge: str | None, engine: str | None = None) -> Path:
    """Prediction artifact path. With `engine`, files are namespaced
    (predictions.<engine>[.judge_off].json) so multiple engines coexist and
    `cli eval --engine ollama` scores the right run."""
    prefix = f"predictions.{engine}" if engine else "predictions"
    suffix = ".judge_off" if judge == "off" else ""
    return SCORECARD_DIR / f"{prefix}{suffix}.json"


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
    granularity-tolerant metrics next to the strict exact-match numbers."""
    g = card.get
    return "\n".join(
        [
            "── eval scorecard ─────────────────────────────────────────",
            f"  category            acc={_fmt(g('category_accuracy'))}  macro_f1={_fmt(g('category_f1_macro'))}",
            f"  level [PRIMARY]     filter_consistent={_fmt(g('level_filter_consistent_accuracy'))}",
            f"  level (secondary)  exact={_fmt(g('level_exact_accuracy'))}",
            f"  tags [fair]        jaccard={_fmt(g('tags_jaccard'))}  overlap={_fmt(g('tags_overlap'))}  recall={_fmt(g('tags_recall'))}  token_f1={_fmt(g('tags_token_f1'))}",
            f"  tags (strict)      exact_f1={_fmt(g('tags_f1'))}  precision={_fmt(g('tags_precision'))}  recall_micro={_fmt(g('tags_recall_micro'))}",
            f"  location primary   acc={_fmt(g('location_primary_accuracy'))}",
            f"  judge_kappa_prejudge {_fmt(g('judge_kappa_prejudge'))}",
            f"  latency (ms)       classify={_fmt_latency(g('classify_latency_ms'))}  judge={_fmt_latency(g('judge_latency_ms'))}",
            f"  gold_quality       {_fmt(g('gold_quality'))}",
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
) -> int:
    truth = load_truth(human_only=not allow_draft)
    if not truth:
        print("eval: no human-labeled golden rows found (golden/seed/golden.json).")
        print("      Run `cli build-golden-set` then label rows with label_source='human',")
        print("      or use `cli golden-merge` to pull JVN admin corrections in.")
        print("      (`--allow-draft` scores draft labels — advisory only, never a gate.)")
        return 1
    gold_quality = "human" if all(r.get("label_source") == "human" for r in truth) else "draft"

    pred_path = _predictions_path(judge, engine)
    predictions = _load_predictions(pred_path)
    if predictions is None:
        print(f"eval: predictions file {pred_path} not found.")
        if engine:
            print(f"      Produce it with `cli eval-run --engine {engine}` (headless).")
        else:
            print("      Produce it with the /enrich-eval workflow or `cli eval-run`.")
        return 1

    # The judge-off predictions are the PRE-judge labels: when scoring the
    # judged run they unlock the honest judge metrics (κ vs pre-judge
    # correctness + per-facet lift). Same engine namespace as the judged run.
    prejudge = None
    if judge != "off":
        prejudge = _load_predictions(_predictions_path("off", engine))

    sc = score(predictions, truth, prejudge_predictions=prejudge)
    card = sc.to_dict()
    card["gold_quality"] = gold_quality
    if engine:
        card["engine"] = engine
    if prejudge is not None:
        card["judge_lift"] = judge_lift(sc, score(prejudge, truth))
    if allow_draft and gold_quality == "draft":
        print(_DRAFT_BANNER)
    print(_headline(card))
    if reasoning:
        print(_reasoning_dump(predictions, truth))
    print(json.dumps(card, indent=2))

    SCORECARD_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"scorecard.{engine}" if engine else "scorecard"
    out = SCORECARD_DIR / (f"{stem}.judge_{judge}.json" if judge else f"{stem}.json")
    out.write_text(json.dumps(card, indent=2), encoding="utf-8")

    if gate:
        baseline_path = Path(baseline) if baseline else (SCORECARD_DIR / "baseline.json")
        if not baseline_path.exists():
            print(f"eval --gate: baseline {baseline_path} not found; run once and commit it.")
            return 0 if allow_draft else 1
        base = json.loads(baseline_path.read_text(encoding="utf-8"))
        failures = regression_gate(sc, base)
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
