# Handoff — cut the enricher over to a fully-local Ollama worker

**Date:** 2026-07-12 · **Branch:** `fix-local-engine-row-drops` → **PR #10** (stacked on
`worktree-opencode-engine`, so it lands in **PR #9** when #10 merges) · **Taxonomy:** `v5 → v6+f2e477ef1e4b`
· **Status:** code complete, tests green (222); **not yet deployed** — deploy runbook below.

Related: `docs/ENGINE-COMPARISON.md` (§7 post-fix), `docs/OLLAMA-VS-OPENCODE.md`, `docs/ENVIRONMENTS.md`
(prod/dev + deploy), `docs/LOCAL-OPEN-MODEL.md`.

---

## TL;DR

Make the enricher **free and fully local**: classify **and** judge default to `ollama` (qwen3:32b),
running as a **continuous worker** instead of the 10-minute Claude tick. This trades throughput and a few
points of accuracy for **$0 marginal cost**. Two supporting changes shipped in the same PR: the
**silent-row-drop fix** (local engines now cover 21/21, was 19/21), and a **taxonomy cleanup** removing the
`project_manager` category (it was the main source of the local judge's bad "corrections").

**This is a real throughput downgrade** — a single local GPU serializes (~90 s/job, no fan-out) vs Claude's
12-wide sub-agent fan-out. It clears the current 26.7k backlog in **~7 weeks at 24/7** and only keeps up with
the ~333 new jobs/day if it runs most of the day. Accepted deliberately for the $0 cost. See §Throughput.

---

## Decisions locked (this session)

1. **Engine = ollama for both stages, judge ON.** `classify:engine` and `judge:engine` default → `ollama`;
   `judge:enabled` stays on. (Earlier analysis recommended judge *off* because the local judge degrades
   accuracy; the user kept it on because removing `project_manager` — see #3 — eliminates the main churn.)
2. **Continuous worker.** Not the 10-min poll — run "always working" via a **60-second** launchd interval
   (the single-flight lock makes fires during a running tick cheap no-ops). No lock/tick-lifecycle rewrite.
3. **Remove the `project_manager` category** (taxonomy `v5 → v6`). Only `product_manager` (owns product
   direction — the *what & why*) and `business_ops` (coordination/ops — the *how & when*, incl. TPM /
   Program Manager / Scrum Master / PMO) remain. The confusing 3-way split was where the local judge
   over-reasoned (it flipped a correct `business_ops` to `project_manager` in the eval — see §Verification).

## What changed in code (this PR)

| Area | Change |
|---|---|
| `engines/base.py` | Row-drop fix: `_call_with_repair` (retry-once + positional id-recovery); usable-dict gating; reorder-safe stamping; re-raise contract. |
| `cli.py` | batch=1 for non-`claude-code` engines at both queue sites; eval-run classify coverage/drops print. |
| `enrich_config.py` | `CLASSIFY_ENGINE_DEFAULT` / `JUDGE_ENGINE_DEFAULT` → `ollama`. |
| `taxonomy.py` | `project_manager` removed from `CATEGORIES` (6 categories now). |
| `.claude/skills/taxonomy/SKILL.md` | `project_manager` removed; TPM/PM/Scrum-Master folded into `business_ops`; `v5 → v6`. |
| `scripts/install_launchagents.sh` | Default `StartInterval` `600 → 60` (continuous). Override with `ENRICH_INTERVAL_SECS`. |
| tests | New engine + cli coverage; two batch tests pinned to `claude-code`; metrics version → `v6+`. |

## Production data snapshot (prod JVN Postgres, 2026-07-12)

| Metric | Value |
|---|---|
| Total listings | 57,840 |
| OPEN listings | 28,706 |
| Already enriched | 1,967 |
| **OPEN + unenriched (backlog to classify)** | **26,767** |
| New listings / day (30-day avg) | ~333 |
| Rows currently labeled `project_manager` | **79** |

## Throughput (the real "cost" — dollars are $0)

Single `ollama` stream, classify-only path, ~90–120 s/job, **no fan-out** → **~865 jobs/day at 24/7**
(range 730–940). Inflow ~333/day, so it only makes net progress on the backlog if run most of the day:

| Duty cycle | Net backlog progress/day | 26,767 backlog cleared in |
|---|---|---|
| 24/7 | ~530 | **~7 weeks** |
| 16 h/day | ~245 | ~3.5 months |
| 12 h/day | ~100 | ~9 months |
| < ~9 h/day | ≤ 0 | never — backlog grows |

Judge ON roughly **doubles** per-job wall time (classify + judge), so halve the throughput numbers if the
judge stays on for the whole backlog. (Claude's fan-out clears the same backlog in ~2–3 days — that's what's
being traded away.)

## Deploy runbook — "turn it on"

"Turned on when the PR merges" really means **on the next deploy after merge**. Steps (all on the **prod**
checkout `~/developer/personal/app` unless noted — see `docs/ENVIRONMENTS.md`):

1. **Merge** PR #10 → `worktree-opencode-engine`, then PR #9 → `main`.
2. `scripts/deploy.sh` on the prod checkout (pulls the new code + taxonomy `v6`).
3. **Point the knobs at the new defaults** (a pre-existing explicit knob would otherwise pin the old engine):
   ```sh
   uv run python -m job_enricher.cli reset-knob classify:engine   # follow the ollama default
   uv run python -m job_enricher.cli reset-knob judge:engine
   uv run python -m job_enricher.cli health                       # confirm classify/judge engine = ollama
   ```
4. **Confirm the local model is present:** `ollama list` shows `qwen3:32b`; `ollama` daemon on `:11434`.
5. **Switch to the continuous worker:** re-run the installer so the launchd plist uses the 60 s interval:
   ```sh
   ENRICH_INTERVAL_SECS=60 scripts/install_launchagents.sh
   ```
   (Or keep 600 for a gentler cadence. The single-flight lock makes overlapping fires no-ops either way.)
6. **Watch the first ticks:** `~/Library/Logs/job-enricher.log`; `cli health` for counts; JVN metrics push.

**Rollback:** `cli set-classify-engine claude-code` + `cli set-judge-engine claude-code` (or reset-knob to a
committed claude-code default), and re-install the agent with `ENRICH_INTERVAL_SECS=600`. No schema change to
revert. (Confirm the exact setter names with `cli --help`; the dashboard can also flip the engine knobs.)

## Taxonomy migration — the 79 `project_manager` rows

Removing the category makes those 79 rows' label stale (JVN still *renders* `project_manager`, so nothing
breaks — but the enricher will no longer produce it). Re-enrichment is **manual** and re-classifies them to
`product_manager` / `business_ops`:

```sh
# ALWAYS COUNT FIRST. --dry-run mutates nothing.
uv run python -m job_enricher.cli reenrich --taxonomy-below v6+f2e477ef1e4b --dry-run
uv run python -m job_enricher.cli reenrich --taxonomy-below v6+f2e477ef1e4b --limit 100
```

> ⚠️ **2026-08-20 (ENR-REN-1) — this command is now guarded, and the warning below understated it.**
> `reenrich` DELETEs the enrichment and flips the inbox row back to `cleaned`, with no undo. It now:
> counts first; supports `--dry-run` (mutates nothing); **REFUSES above `REENRICH_CONFIRM_THRESHOLD = 500`
> matched rows unless you pass `--yes-i-mean-all`**; and accepts `--limit`.
> **At v7 `--taxonomy-below v7+<hash>` matches EVERY v6 row — the whole ~19.4k corpus, roughly 40 days of
> worker time.** Never paste the unguarded form. Same guard shape and flag name as `subcategory-reset`.
> Note also: from v7 the hash covers `SUBCATEGORIES.md` too, so a **rubric-only edit moves the hash but not
> the declared N — and same-N-different-hash is NOT below, so `reenrich` will never pick it up.**

⚠️ `--taxonomy-below v6` resets **every** pre-v6 row (all 1,967 existing enrichments are < v6), not just the
79 — a full re-enrichment under the cleaner taxonomy. At ollama speed that's ~1,967 × ~90 s ≈ **~2 days** of
compute on top of the backlog. Not urgent (JVN keeps showing the old labels until re-done); schedule it into
the continuous worker's queue. JVN's `job_categories` enum still lists `project_manager` (harmless; drop it
JVN-side later once these rows are migrated).

## Verification (evidence)

- **Row drops fixed:** `ollama` & `opencode` eval-run both **21/21 (drops=0)** (was 19/21); the 3 hard rows
  recovered. `claude-code` smoke 3/3 (stamping is a no-op). Full suite **222 passing**, `base.py` 100%.
- **Local judge (why project_manager was cut):** fresh judged ollama run — category **16/21 → 15/21** after
  judge (0 fixes, 1 churn). The churn: `greenhouse_api/7851742` "Escalation Manager", correctly
  `business_ops`, the judge "corrected" it to `project_manager` ("functions as a technical program
  manager…"). Removing `project_manager` closes that failure mode; keeping the judge on is then reasonable.
- **ollama vs opencode:** identical accuracy, ollama ~3.2× faster → use `ollama`. (`docs/OLLAMA-VS-OPENCODE.md`.)

## Risks / open items

- **Throughput** is the headline risk — see the table. If the machine isn't on ~most of the day, the backlog
  grows. Consider a smaller tier (`qwen3:14b`, a settable `opencode:model`) for more speed at some accuracy cost.
- **Local judge still net-negative on accuracy** even after the taxonomy cleanup (it was −1 on the 21-row set;
  the churn is gone but it made 0 net improvements). Re-measure after a batch of real production rows; if it's
  still not adding value, revisit `judge:enabled=off` (fully free either way).
- **Re-enrichment scope:** `reenrich --taxonomy-below v6` re-does all 1,967 rows, not only the 79. If that's
  undesirable, add a category-scoped reenrich path (not built).
- **n=21** golden set — all accuracy figures are advisory (< the 50-row gate). Grow human labels via
  `cli golden-merge` to make the comparison gated.
- **JVN-side:** drop `project_manager` from JVN's category enum/filters once the 79 rows are migrated.
