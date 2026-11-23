# golden/baselines/

⚠ **Prediction artifacts live HERE, not in `golden/scorecards/`.**

`.gitignore` excludes `golden/scorecards/predictions*.json` and
`golden/scorecards/scorecard*.json`, so an artifact left in `scorecards/` is
uncommittable — and EV-12's row-set-identity check and EV-5b's paired test both
read committed artifacts. This directory is matched by no ignore rule.

| path | produced by | status |
|---|---|---|
| `v6/predictions.ollama.judge_off.json` | `EV-2` (a RUN) | not yet captured |
| `v6/confidence_histogram.json` | `EV-2` (a RUN) | not yet captured |
| `v7/predictions.ollama.judge_off.json` | `EV-12` (a RUN) | not yet captured |
| `weak_rule/predictions.weak_rule.json` | `cli subcategory-weak-baseline` | committed (135 rows, 98 typed) |

⚠ **The committed `baseline.weak_rule.json` scorecard is a PLACEHOLDER, not a
gate.** It was scored against `load_truth(facet='subcategory')`, which returns
**0 rows** until `EV-9b`, so every metric on it is `0.0` and it carries
`gate_ready: false` plus a `gate_blocked_reason`. G2 must refuse a card that is
not `gate_ready` — beating `subcategory_set_f1: 0.0` by 0.10 measures nothing.
Re-run `cli subcategory-weak-baseline` and commit the result the day the pool
exists; a test fails until you do.

Scored SCORECARDS (`baseline.*.json`) stay in `golden/scorecards/` — the ignore
rule there covers `scorecard*.json` and `predictions*.json` only, which is why
`baseline.json` is committed today.
