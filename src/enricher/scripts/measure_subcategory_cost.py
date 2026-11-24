#!/usr/bin/env python3
"""P0-5 — real seconds/row for the SUBCATEGORY-ONLY prompt: haiku vs sonnet.

    uv run python scripts/measure_subcategory_cost.py --n 20 --tiers haiku,sonnet \\
        --batches 1,4,10

⚠ IT CONSUMES `BF-9`'s `--dry-run` HARNESS RATHER THAN SHIPPING A SECOND PROBE.
The plan's edge is `BF-9 -> P0-5`, not the reverse: contract decision 18's
`BF-9.dependsOn += P0-5` would have been a CYCLE, and a second probe could
diverge from the real run, which is exactly what a cost measurement must not do.

⚠ THE INJECTION BOUNDARY. Every prompt is built from TITLE + `enrichments.tags`
ONLY, never `clean_description`. That is enforceable because 10,792 of the 11,150
local SWE rows carry non-empty tags — and it is enforced STRUCTURALLY, because
`backfill.chunk_rows` raises on a row that even CARRIES a description key.

⚠ REQUIRED DISCLOSURE, and it must also appear in the runbook and the morning
report: those tags are the ENRICHER'S OWN v6-generated tags, NOT company tags.
JVN's `_JOB_PROJECTION` has never shipped `details->'tags'`. So layer-2 tag
agreement is **NOT independent evidence** — it is v6 grading its own homework.

DECISION RULE (write the chosen cell into the runbook):

    lowest p95 s/row, subject to  parse-failure rate <= 2%
                            and   haiku-vs-sonnet agreement >= 85%
    below 85% agreement, SONNET WINS.

⚠ BOTH HALVES OF THAT RULE ARE COMPUTED HERE. `tier_agreement` is derived from
the dry-run probe's own `row_labels` (`fill_tier_agreement`), over the rows both
tiers labelled and over MODEL-labelled rows only — the rule pass is deterministic
and tier-independent, so including it would inflate agreement toward 100%. It was
previously hardcoded None with a note saying an operator would fill it in, which
made the '<85%, SONNET WINS' branch unreachable and quietly reduced the rule to
'lowest p95'.

⚠ CONCURRENCY ARITHMETIC, written down rather than assumed:
`ChunkEngine._call_with_repair` is STRICTLY SEQUENTIAL — one `subprocess.run` per
chunk, plus one more on the repair path. So

    wall_seconds  =  ceil(rows / batch) * T_chunk(batch)
    seconds_per_row = T_chunk(batch) / batch

and the ONLY levers are `batch` and the model tier. There is no concurrency term
because there is no concurrency.

⚠ THIS SCRIPT IS NOT RUN BY PR-E. It needs a live model and Brendan's
subscription; running it is the measurement step itself.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# ⚠ 2% — the parse-failure ceiling a tier must stay under to be eligible at all.
PARSE_FAILURE_CEILING = 0.02

# ⚠ 85% — below this, haiku and sonnet do not agree enough for the cheaper tier
# to be trusted on 8,000 rows nobody will read, so SONNET WINS regardless of cost.
TIER_AGREEMENT_FLOOR = 0.85

# UNMEASURED — placeholder; set by P0-5
#   ⚠ The ONLY measured figure on this machine is 137.9 s/item for the FULL
#   CLASSIFY prompt on qwen3:32b — a different model, a different prompt and a
#   different engine. Do NOT reuse the plan's 60 s/row or 20 s/row placeholders,
#   and repeat NO night-length claim until this script's table exists.
SECONDS_PER_ROW_P50 = None
SECONDS_PER_ROW_P95 = None

# UNMEASURED — placeholder; set by P0-5
MODEL_TIER = None       # 'haiku' | 'sonnet'
CHUNK_SIZE = None
CLAUDE_TIMEOUT_SECONDS = None


def sample_scope_rows(store, n: int, seed: int = 0) -> list:
    """Uniform sample of `n` rows from `P0-4`'s scope.

    ⚠ NEVER selects a row outside `backfill_scope`: `open_only=True` is the whole
    point of the sampler, and it REFUSES on an empty or stale scope rather than
    quietly measuring the wrong cohort."""
    rows = store.rows_needing_subcategory(limit=None, open_only=True)
    rng = random.Random(seed)
    return rng.sample(rows, min(n, len(rows)))


def render_prompts(rows) -> list[str]:
    """One rendered prompt per chunk, through the SAME builder the night uses."""
    from job_enricher.backfill import chunk_rows
    from job_enricher.engines.prompts import build_subcategory_prompt

    return [build_subcategory_prompt(chunk_rows(rows))]


def agreement(a: list, b: list) -> float:
    """Fraction of rows on which two tiers produced the same primary slug."""
    if not a or len(a) != len(b):
        return 0.0
    same = sum(
        1 for x, y in zip(a, b)
        if (x or [None])[0] == (y or [None])[0]
    )
    return same / len(a)


def model_labels_from_probe(probe: dict) -> dict[tuple[str, str], list]:
    """The MODEL-produced labels in a `--dry-run` probe, keyed by row.

    ⚠ RULE-LABELLED ROWS ARE EXCLUDED, and that is the whole point. The
    title/tag rule pass is deterministic and tier-independent, so counting those
    rows would drive agreement toward 100% on rows no model ever saw — a number
    that would then wave a cheap tier through the 85% floor."""
    labels: dict[tuple[str, str], list] = {}
    for entry in probe.get("row_labels") or []:
        if entry.get("source") != "model":
            continue
        labels[(entry["source_id"], entry["job_listing_id"])] = entry.get("slugs") or []
    return labels


def agreement_by_row(
    a: dict[tuple[str, str], list], b: dict[tuple[str, str], list]
) -> float | None:
    """Primary-slug agreement over the rows BOTH tiers actually labelled.

    ⚠ Returns None — not 0.0 — when there is no overlap. A missing measurement
    and total disagreement are different facts, and conflating them would fire
    the 'SONNET WINS' branch on an empty probe, which teaches an operator to
    ignore it."""
    shared = set(a) & set(b)
    if not shared:
        return None
    same = sum(
        1 for pair in shared if (a[pair] or [None])[0] == (b[pair] or [None])[0]
    )
    return same / len(shared)


BASELINE_TIER = "sonnet"


def fill_tier_agreement(
    cells: list[dict], labels_by_tier: dict[str, dict[tuple[str, str], list]]
) -> list[dict]:
    """Stamp each CHALLENGER tier's agreement against `sonnet` onto its cells.

    ⚠ THE HALF OF THE DECISION RULE THAT USED TO BE INERT. `tier_agreement` was
    hardcoded None on every cell with a comment saying the operator would fill it
    in, but the probe emitted no per-row labels, so there was nothing to fill it
    in FROM — and `decide` therefore collapsed to 'lowest p95 subject to
    parse-failure <= 2%'. The baseline keeps None: it is the tier the others are
    measured against, and it wins by construction when they fall short."""
    baseline = labels_by_tier.get(BASELINE_TIER)
    for cell in cells:
        if cell["tier"] == BASELINE_TIER or not baseline:
            continue
        cell["tier_agreement"] = agreement_by_row(
            labels_by_tier.get(cell["tier"]) or {}, baseline
        )
    return cells


def decide(cells: list[dict]) -> dict | None:
    """Apply the decision rule to the measured cells and return the winner."""
    # ⚠ `or 1.0` would be WRONG here: 0.0 is falsy, and a ZERO parse-failure
    # rate is the best possible outcome, not a missing measurement.
    eligible = [
        c for c in cells
        if c.get("parse_failure_rate") is not None
        and c["parse_failure_rate"] <= PARSE_FAILURE_CEILING
    ]
    if not eligible:
        return None
    haiku_vs_sonnet = next(
        (c["tier_agreement"] for c in cells if c.get("tier_agreement") is not None),
        None,
    )
    if haiku_vs_sonnet is not None and haiku_vs_sonnet < TIER_AGREEMENT_FLOOR:
        # ⚠ BELOW 85% AGREEMENT, SONNET WINS — cost does not get a vote.
        eligible = [c for c in eligible if c["tier"] == "sonnet"] or eligible
    return min(eligible, key=lambda c: c.get("seconds_per_row_p95") or float("inf"))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - a RUN
    from job_enricher import backfill as bfl
    from job_enricher.engines import build_engine
    from job_enricher.store import Store

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--tiers", default="haiku,sonnet")
    ap.add_argument("--batches", default="1,4,10")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    store = Store()
    cells = []
    labels_by_tier: dict[str, dict] = {}
    for tier in args.tiers.split(","):
        for batch in (int(b) for b in args.batches.split(",")):
            engine = build_engine("claude-code", model=tier)
            outcome = bfl.run_backfill(
                store, engine, limit=args.n, batch=batch, open_only=True,
                dry_run=True, model=tier, engine_name="claude-code",
            )
            probe = outcome.probe or {}
            attempted = probe.get("model_attempted_rows") or 0
            # ⚠ MERGED ACROSS BATCHES, last write wins: a dry run writes nothing,
            # so every batch size for a tier sees the SAME rows in the same order.
            labels_by_tier.setdefault(tier, {}).update(model_labels_from_probe(probe))
            cells.append({
                "tier": tier,
                "batch": batch,
                "seconds_per_row_p50": probe.get("seconds_per_row"),
                "seconds_per_row_p95": (probe.get("chunk_latency_s") or {}).get("p95"),
                "parse_failure_rate": (
                    (probe.get("counters", {}).get("parse_errors", 0) / attempted)
                    if attempted else None
                ),
                # ⚠ BF-7's per-layer [] measurement, folded in: BF-9's empty-rate
                # breaker threshold must be THIS number plus a stated band, never
                # the placeholder.
                "empty_array_rate": probe.get("empty_array_rate"),
                "rule_pass": probe.get("rule_pass"),
                "echo_mismatch_rate": probe.get("echo_mismatch_rate"),
                # computed below by `fill_tier_agreement`, from the probe's own
                # per-row labels — NOT hand-filled, and never left inert.
                "tier_agreement": None,
            })
    fill_tier_agreement(cells, labels_by_tier)
    report = {
        "cells": cells,
        "decision_rule": {
            "parse_failure_ceiling": PARSE_FAILURE_CEILING,
            "tier_agreement_floor": TIER_AGREEMENT_FLOOR,
        },
        "chosen": decide(cells),
        # ⚠ so the operator can see the agreement was computed on MODEL rows only
        # and how many rows it had to work with.
        "agreement_basis": {
            "baseline_tier": BASELINE_TIER,
            "model_labelled_rows_per_tier": {
                tier: len(labels) for tier, labels in labels_by_tier.items()
            },
            "note": (
                "rule-labelled rows are EXCLUDED: the rule pass is deterministic "
                "and tier-independent, so including it would inflate agreement"
            ),
        },
        "disclosure": (
            "the tags in these prompts are the ENRICHER'S OWN v6 output, not "
            "company tags — layer-2 tag agreement is NOT independent evidence"
        ),
    }
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
