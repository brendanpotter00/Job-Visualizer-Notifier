# EVAL — the v6 baseline arm

**Status: THE RUN HAS NOT BEEN PERFORMED.** This document is the runbook plus
the one irreplaceable fact the run depends on. Everything below the "Recorded
after the run" heading is a blank to be filled in by whoever executes it.

---

## ⚠ 1. The one fact that makes v6 recoverable

```
SKILL_MD_V6_GIT_SHA = 8ff1eb1401bf19b9d879678262c389e4f45b8cc1
```

That is the **git blob SHA** of `.claude/skills/taxonomy/SKILL.md` immediately
before the v7 edit. Verified 2026-08-20:

```
$ git cat-file -t 8ff1eb1401bf19b9d879678262c389e4f45b8cc1
blob
$ git show 8ff1eb1401bf19b9d879678262c389e4f45b8cc1 | sed -n '4p'
version: v6
```

and the blob hashes to the taxonomy version the whole design record quotes:

```
declared_version = v6
content_hash     = 2bf741ee8ea1      ->  v6+2bf741ee8ea1
```

**⚠ THE ONE-WAY DOOR HAS ALREADY BEEN WALKED THROUGH.** PR-C bumped
`version: v6` -> `v7` and added `SUBCATEGORIES.md`, so the working tree today
reports `v7+0b4cfdceca9e` and `read_skill()` no longer returns the v6 text. The
v6 arm is now reachable **only** through that blob SHA:

```bash
git show 8ff1eb1401bf19b9d879678262c389e4f45b8cc1 > /tmp/SKILL.v6.md
```

This is Open Risk #1 in the build plan, and it is realized rather than
hypothetical. The SHA above is the entire mitigation. **Do not delete this file
and do not rewrite this section.**

Note also that `taxonomy_version()` widened to `combined_hash()` over BOTH
taxonomy files in v7, while `content_hash()` stayed SKILL.md-only precisely so
the v6 number above stays reproducible from one blob.

---

## 2. What the run captures, and why it cannot be repeated later

A full-seed classify pass on the **production engine** over all 273 golden rows,
producing the v6 prediction artifact. Scoring it is pure and re-runnable;
**producing it is not** — once the rubric moves, the only way back is the blob
SHA above plus another ~2 hours of local model time.

⚠ **IT MUST BE `ollama`.** The 71.8% / 73.5% confidence figures in circulation
come from `predictions.judge_off.json`, a **2026-07-08 claude-code artifact**,
not the production engine. Building a cost model or a calibration comparison on
the wrong engine's distribution is how this goes quietly wrong.

---

## 3. The procedure

### 3.0 Restore the v6 rubric into the working tree

```bash
git show 8ff1eb1401bf19b9d879678262c389e4f45b8cc1 \
  > .claude/skills/taxonomy/SKILL.md
job-enricher taxonomy-version        # MUST print v6+2bf741ee8ea1
```

⚠ `taxonomy_version()` now folds `SUBCATEGORIES.md` in, so it will NOT print
`v6+2bf741ee8ea1` while that file exists. Move it aside for the v6 arm:

```bash
mv .claude/skills/taxonomy/SUBCATEGORIES.md /tmp/SUBCATEGORIES.md
job-enricher taxonomy-version        # now v6+2bf741ee8ea1
```

### 3.1 Pilot 20 rows FIRST

⚠ **Publish p50/p95 before committing to the full run.** The only measured
figure on this machine is **137.9 s/item** for the full classify prompt on
qwen3:32b, from which "~2 h per version at batch 4" is an **ESTIMATE, not a
measurement**. The pilot is what decides whether the A/B fits in one sitting.

```bash
job-enricher eval-run --engine ollama --judge off --limit 20 --batch <B> --tag v6-pilot
```

### 3.2 The full run — IN A SINGLE PROCESS

```bash
job-enricher eval-run --engine ollama --judge off --batch <B> --tag v6
```

⚠ `prompts._taxonomy_text` is `lru_cache(maxsize=1)`, so a mid-process rubric
edit is invisible and a same-process rerun after an edit silently scores the
OLD rubric. `_cmd_eval_run` calls `reset_taxonomy_cache()` on entry, but a fresh
process is still the safe form.

⚠ **Record the batch size. The v7 run must use the IDENTICAL batch size or the
comparison is void** — at batch > 1 dropped chunks are skipped silently and only
a covered/total line is printed.

### 3.3 Copy the artifact somewhere committable

```bash
cp golden/scorecards/predictions.v6.ollama.judge_off.json \
   golden/baselines/v6/predictions.ollama.judge_off.json
git add golden/baselines/v6/predictions.ollama.judge_off.json
```

⚠ `.gitignore` excludes `golden/scorecards/predictions*.json` and
`scorecard*.json`, so anything left in `scorecards/` is **uncommittable** and
EV-12's row-set-identity check and EV-5b's paired test would have nothing to
read. `golden/baselines/` is matched by no ignore rule.

### 3.4 Derive the confidence histogram

`golden/baselines/v6/confidence_histogram.json`, from that same artifact:

* counts by confidence value,
* share below 0.85 (`judge:confidence_ceiling`, the direct driver of
  `_needs_judge`),
* share below 0.85 **among predicted-SWE rows**.

### 3.5 Restore the working tree

```bash
git checkout .claude/skills/taxonomy/SKILL.md
mv /tmp/SUBCATEGORIES.md .claude/skills/taxonomy/SUBCATEGORIES.md
```

---

## 4. Recorded after the run — FILL THESE IN

| field | value |
|---|---|
| `cli taxonomy-version` at run time | _(must be `v6+2bf741ee8ea1`)_ |
| `SKILL_MD_V6_GIT_SHA` | `8ff1eb1401bf19b9d879678262c389e4f45b8cc1` ✔ recorded |
| engine / model | `ollama` / _TBD_ |
| batch size `B` | _TBD — the v7 run MUST match_ |
| rows in seed | 273 |
| classify coverage (`covered/total`) | _TBD_ |
| dropped `job_listing_id`s | _TBD — enumerate them, do not summarize_ |
| pilot p50 / p95 (20 rows) | _TBD_ |
| full-run wall clock | _TBD_ |

## 5. EV-2c — scoring the captured predictions into the committed baseline PAIR

**Status: NOT RUN** (it needs §3's artifact and `EV-2b`'s human pool).

Scoring is split out from the capture because **scoring is pure and re-runnable
while the run is not**, and because the human baseline must be scored against
the REAL pool `EV-2b` builds rather than today's useless n=21.

Score the SAME artifact TWICE and commit both:

```bash
# THE GATE BASELINE — no --allow-draft, now at n>=55 instead of n=21
job-enricher eval --engine ollama --judge off --tag v6
cp golden/scorecards/scorecard.v6.ollama.judge_off.json \
   golden/scorecards/baseline.v6.human.json

# ADVISORY — the same predictions at n~273
job-enricher eval --engine ollama --judge off --tag v6 --allow-draft
cp golden/scorecards/scorecard.v6.ollama.judge_off.json \
   golden/scorecards/baseline.v6.draft.json
```

⚠ **This sentence must appear verbatim in the committed doc**, because the
draft card is the one a reader will reach for and it is the one that misleads:

> `--allow-draft` scores against `label_source='draft'` labels, which
> `golden.py`'s module docstring defines as judge-bootstrapped **v6 output** —
> so those numbers measure **AGREEMENT WITH v6, not accuracy**, and a genuinely
> better v7 scores **WORSE** against them.

The draft card is kept anyway because n≈273 is the only n where a 2-point move
is outside the noise band.

Both files must carry `n`, `gold_quality`, `engine`, `model`, `tag` and the
`EV-5` / `EV-5b` keys (`category_f1_macro_supported`,
`category_f1_macro_excluded_classes`), so `EV-12`'s gate arms have a baseline
value to compare against and `EV-1`'s WARN does not fire on the real gate.
`tests/test_eval_artifacts.py` asserts exactly that once the files land.

⚠ `.gitignore` excludes `predictions*.json` and `scorecard*.json` under
`golden/scorecards/` — **NOT `baseline*.json`**, confirmed by `baseline.json`
being committed today.

**SANITY, not a gate:** note how `baseline.v6.draft.json`'s `category_accuracy`
compares to the committed `baseline.json`'s **0.7778**, and explain any gap —
`baseline.json` is an **n=252 claude-code** run, not an ollama one, so a gap is
expected and is not evidence of a regression.

Re-running the same scoring command must reproduce each file byte-for-byte.
