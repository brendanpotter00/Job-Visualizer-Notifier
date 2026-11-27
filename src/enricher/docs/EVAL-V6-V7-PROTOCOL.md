# EVAL — the v6 → v7 A/B protocol and the ship gate

**Status: THE A/B HAS NOT BEEN RUN. No gate arm has a verdict.**
Everything here is executable; nothing here has been executed. This is the long
pole and the decision point of the whole project.

⚠ **Every arm that cannot run must be NAMED below with the reason. An arm that
is simply omitted reads as an arm that passed.**

---

## 0. Preconditions

| # | precondition | status |
|---|---|---|
| P1 | `SKILL_MD_V6_GIT_SHA` recorded | ✔ `8ff1eb1401bf19b9d879678262c389e4f45b8cc1`, verified v6 / `v6+2bf741ee8ea1` |
| P2 | v6 predictions captured (`EV-2`) | ✘ NOT RUN |
| P3 | category pool ≥ 55 (`EV-2b`) | ✔ by count only — `load_truth(human_only=True)` = **57**, but **not** via the stratified `EV-2b` review: 36 of the 57 are the human-reviewed forward-deployed rows from the FDE correction (`golden/review/forward-deployed-labels.md`), so the pool is FDE-heavy and `data_scientist` still has **0** human rows. `EV-2b` is still owed for a balanced gate |
| P4 | subcategory pool ≥ 55 (`EV-9b`) | ✘ NOT RUN — `load_truth(facet='subcategory')` = **0** |
| P5 | weak-rule baseline committed (`EV-11`) | ✔ artifact committed (156 rows, 118 typed); scored card covers only the **25** human `forward_deployed` rows (set_f1 0.906, a title-regex-friendly slug) until P4 |
| P6 | latency go/no-go (`ENR-LAT-1`) | ✘ NOT RUN (PR-C) |

---

## 1. The procedure

### (1) Confirm the v6 hash out of git

The working tree is **already v7**, so read the old rubric from the blob:

```bash
git show 8ff1eb1401bf19b9d879678262c389e4f45b8cc1:.claude/skills/taxonomy/SKILL.md
```

### (2) Run v7 over the SAME 273 rows, in a FRESH PROCESS

```bash
job-enricher eval-run --engine ollama --judge off --batch <B, IDENTICAL TO EV-2> --tag v7
cp golden/scorecards/predictions.v7.ollama.judge_off.json \
   golden/baselines/v7/predictions.ollama.judge_off.json
```

⚠ **FRESH PROCESS.** `prompts._taxonomy_text` is `lru_cache(maxsize=1)`, so a
same-process rerun silently scores the FIRST rubric and reports a delta of zero.
`_cmd_eval_run` calls `reset_taxonomy_cache()` on entry, but a new process is the
form to trust.

⚠ **THE BATCH SIZE MUST MATCH `EV-2`'s** or the comparison is void.

### (3) ⚠ BEFORE COMPARING: assert identical row coverage

At batch > 1 dropped chunks are skipped silently and `_cmd_eval_run` only prints
a covered/total line. **The paired test in G1b is meaningless if the two arms
cover different rows.** `tests/test_eval_artifacts.py` asserts this in CI once
both artifacts are committed.

### (4) Score twice, commit both

```bash
job-enricher eval --engine ollama --judge off --tag v7 --model qwen3:32b            # -> the GATE card, n>=55
job-enricher eval --engine ollama --judge off --tag v7 --model qwen3:32b --allow-draft   # advisory, n~273
```

⚠ **`--model` IS NOT OPTIONAL ON ANY RUN THAT GATES THE SUBCATEGORY GROUP.** It
is the only thing that tells the independence rail what the model under test is,
and the rail compares it against the pool's stamped `subcategory_prelabel_model`.
Omit it on a pre-labelled pool and the gate **REFUSES** (`subcategory gate
refused: pool pre-labelled by '<m>' and the model under test is unknown — pass
--model`) rather than passing on a rail it could not check. Carry it on every
command in this file so no copy-paste loses it.

Committed as `golden/scorecards/baseline.v7.{human,draft}.json`, mirroring
`baseline.v6.{human,draft}.json` from `EV-2c`.

⚠ `.gitignore` excludes `predictions*.json` and `scorecard*.json` under
`golden/scorecards/` — **NOT `baseline*.json`**, which is why `baseline.json` is
committed today.

---

## 2. THE SHIP GATE — all required before the backfill knob leaves 0

| arm | test | threshold | verdict |
|---|---|---|---|
| **G0 POOL** | `load_truth(human_only=True) >= 50` AND `load_truth(facet='subcategory') >= 50` | 50 / 50 | **CANNOT RUN** — 21 / 0 |
| **G1 CATEGORY (unpaired)** | `regression_gate(v7_human, baseline.v6.human.json, groups=('category',))` returns `[]` | eps 0.02 | **CANNOT RUN** — needs P2 + P3 |
| **G1b CATEGORY (paired)** | `paired_facet_deltas(v7, v6, human_truth)` for `category` and `level` | FAIL when `b - c >= PARAM_PAIRED_MIN_NET` **AND** exact-binomial p ≤ 0.05 | **CANNOT RUN** |
| **G1c MACRO** | `category_f1_macro_supported` (min_support=5) drop | ≤ 0.02, with `category_f1_macro_excluded_classes` printed | **CANNOT RUN** |
| **G1d SWE CONFUSION** | `data_scientist` recall drop | ≤ 0.05 | **CANNOT RUN** |
| **G2 WEAK BASELINE** | beat `baseline.weak_rule.json` on `subcategory_set_f1` | ≥ +0.10 | **CANNOT RUN** — needs P4 (needs zero HUMAN labels, but needs a scored pool) |
| **G3 SUBCATEGORY** | `subcategory_primary_accuracy_nonempty` and `subcategory_f1_macro` | ≥ 0.65 / ≥ 0.50 — ⚠ **OPINION, not derived** | **CANNOT RUN** |
| **G7 LATENCY** | `ENR-LAT-1`'s prompt-length and p50-delta budgets | see PR-C | **CANNOT RUN** |
| **G9 LANE ATTRIBUTION** | the doc names which scorecard governs which lane | — | ✔ see §4 |

### G1b — why the paired arm is not optional

At n ≈ 67 the standard error on an accuracy near 0.80 is
`sqrt(0.8·0.2/67) ≈ 0.049`, so `regression_gate`'s `epsilon = 0.02` sits **well
inside the noise floor**. G1 alone would both false-alarm on noise and
false-clear a real regression. v6 and v7 score the SAME rows, so the correct
statistic is the paired one.

⚠ **BOTH conditions are required.** `PARAM_PAIRED_MIN_NET = 4` exists so a 2-vs-0
flip (exact two-sided p = 0.5) cannot fail the gate on its own.

### G1c — why a support floor exists

Measured on the seed, `growth` and `hardware_engineer` have exactly **2 rows
each and BOTH are already human, with zero draft rows available to draw more**.
On the human pool each therefore carries a full 1/6 of a GATED facet off two
rows, where one flip moves the macro by 0.083 — **four times the gate epsilon**.
`category_f1_macro` keeps its unfloored definition for comparability;
`category_f1_macro_supported` is the gated one.

### G1d — the specific v7 failure mode

Section 1b's language is ML-adjacent, and the risk is that it pulls
ML-adjacent rows INTO `software_engineering` and away from `data_scientist`.
That is not visible in overall accuracy on a pool where SWE is the largest
class, so it is checked on its own.

### G3 — ⚠ these two numbers are OPINION

0.65 primary-nonempty and 0.50 macro-F1 across **15 classes** are judgment
calls, not derived from any measurement. They are labelled as opinion here
deliberately. Whoever runs the A/B may argue them up or down with evidence; what
must not happen is quoting them as if a measurement produced them.

---

## 3. Calibration and judge volume (EV-14)

Two channels, both measured, plus one decision that stays closed.

* **(a) `conf_below_ceiling_share`** — the share of rows below
  `judge:confidence_ceiling` (0.85). The direct driver of `_needs_judge`.
  Verdict against `PARAM_CAL_DELTA` (5pp).
* **(b) `needs_human_rate`** — ⚠ **the channel nobody scoped.** The separate
  `subcategory_confidence` field keeps subcategory uncertainty out of the 0.85
  routing, but it does NOT protect the second path: `validate_subcategories`
  nulls a bad slug, the invalid-slug path flags `needs_human`, and
  `_needs_judge` returns True on `needs_human` **regardless of confidence**.
  Hallucinated slugs buy judge volume anyway.
* **(c) `subcategory_nulled_rate`** — verdict against `PARAM_NULL_RATE` (3%).

⚠ **THE CONTROL IS `EV-2`'s OLLAMA HISTOGRAM.** The 71.8% / 73.5% figures in
circulation come from `predictions.judge_off.json`, a **2026-07-08 CLAUDE-CODE
artifact** on a different engine. Building a cost model on the wrong engine's
distribution is how this goes quietly wrong.

### Cost translation

At the measured ollama judge median **~92 s/row** and `enrich:per_tick_limit =
40` per in-process stage, each extra judged row is ~92 s off a lane already at
~100% duty cycle. ⚠ And `docs/ENGINE-COMPARISON.md` §1 measured the local judge
as **NET-NEGATIVE on category accuracy** (−5.3 pts, macro-F1 0.73 → 0.55, judge
lift −0.053) — so any design routing more rows to it amplifies a stage already
known to hurt.

⚠ The confidence distribution's SHAPE matters: the model emits coarse
round-number confidences, so a shift moves rows across the ceiling in **discrete
clumps**. Expect a step change, not a smooth one.

If either budget is exceeded, the doc must name the mitigation taken — raise
`judge:confidence_ceiling` and re-measure calibration at the new threshold, or
tighten the slug validator.

### ⚠ THE DECISION THAT STAYS CLOSED

Do **NOT** add `category == 'software_engineering' AND subcategories IS NULL` to
`_needs_judge`'s OR-chain. 135 of 285 golden rows are SWE, so it would route
roughly half the corpus to the judge on its own — and `[]` is a legal EVALUATED
answer that must never be read as a nulled facet. A standing test asserts
`_needs_judge`'s body contains no subcategory clause at all.

---

## 4. G9 — which scorecard governs which lane

⚠ **ONE GATE CANNOT GOVERN TWO LANES.** They see different inputs and are
different tasks:

| lane | input | prompt | governing scorecard |
|---|---|---|---|
| **classify** (Tier 1, live tick) | title + company + raw_location + the FULL cleaned description | compact SKILL.md §1b | `scorecard.v7.ollama.judge_off.json` — G3 |
| **backfill** (Tier 2, ~8k rows) | title + company tags ONLY | long-form `SUBCATEGORIES.md` | `scorecard.v7-backfill.ollama.judge_off.json` — the backfill floor |

Classify-lane subcategory precision will be lower than backfill-lane precision
**BY CONSTRUCTION**, and `subcategory_source` (`'classify'` vs `'backfill'`) is
what lets you tell them apart after the fact.

Produce the backfill card with:

```bash
job-enricher eval-run --engine ollama --judge off --prompt backfill --tag v7-backfill
job-enricher eval --engine ollama --judge off --tag v7-backfill --facet subcategory --model qwen3:32b
```

⚠ **THE BACKFILL LANE'S FLOOR IS DERIVED, NOT INVENTED:**
`eval.params.derive_backfill_floor()` = G3's primary threshold − the margin
(placeholder 0.15, to be replaced by the first MEASURED title-only number).

⚠ **HONEST LIMITATION:** company tags are absent from the golden seed today (the
seed's `tags` field is a gold LABEL), so `--prompt backfill` is effectively
**TITLE-ONLY** and its score is a **LOWER BOUND** on the backfill's real quality.
Named follow-up, not blocking: expose `details->'tags'` in JVN's
`_JOB_PROJECTION` plus a `company_tags` seed field.

⚠ **If only one arm is gated, the compact rubric ships unmeasured.**

---

## 5. Verdicts

**None. The A/B has not been run.** When it is, every arm G0-G9 gets a written
PASS/FAIL here **with the actual numbers**, and any arm that could not run says
so and why.
