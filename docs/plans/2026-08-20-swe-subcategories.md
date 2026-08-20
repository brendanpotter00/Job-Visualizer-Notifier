# Software Engineering subcategories — implementation plan

**Status:** reviewed, all decisions made, not yet implemented.
**Branches:** `feat/swe-subcategories` in this repo and in `job-enricher`.
**Rich version:** [`2026-08-20-swe-subcategories-plan.html`](./2026-08-20-swe-subcategories-plan.html) — open in a browser. It carries the full revision log of all 41 review comments across 11 rounds, plus a UI mock and the risk-ranked reading guide. This markdown is the reviewable-in-a-diff companion.

---

## 1. What this does

Four things, spanning two repos:

1. **Rename** the recent-jobs filter label from "Job title" to **"Job category"**.
2. **Add subcategories** under `software_engineering` — a nested MUI checkbox tree, alphabetical, multi-valued.
3. **Teach the enricher** to label the new facet, and **write new evals** for it.
4. **Backfill** existing software-engineering jobs without starving the live pipeline.

The rename is already sanctioned in the code. `RecentJobsFilters.tsx:131` says the label stays "Job title" only *until* the categories subdivide — "e.g. Software Engineering → Frontend SWE / Backend SWE, at which point they read as categories again." This feature is that trigger. The label is UI-only; `category` remains the data model all the way down.

## 2. Measured baseline

Every figure below was queried from prod Postgres and the live enricher SQLite on 2026-08-19/20, and re-verified directly rather than taken from an agent summary.

| Metric | Value |
|---|---|
| Job listings | 76,023 |
| `software_engineering` | 11,139 (8,126 OPEN) |
| Never enriched | 56,656 (74.5%) |
| New SWE jobs/day | ~230 |
| Classified/day | **485** (38/tick × 12.76 ticks) |
| Arrivals/day | **495–552** |
| SWE titles with no specialty | 41.2% (4,584 rows) |
| Human golden labels | 21 total, **11** software-engineering |

**The constraint that shaped everything:** the enricher classifies 485/day against 495–552 arriving. The last 100 ticks all hit the 38-row cap and the next tick starts 62 seconds after the previous ends — ~100% duty cycle. There is no idle capacity, so a backfill cannot be scheduled *inside* the existing lane. 282 rows have been stuck in `cleaned` since 2026-07-13.

## 3. The taxonomy — 15 subcategories

Multi-valued: an **ordered array of 0–2 slugs**, primary first. Forced by measurement — 9.0% of SWE jobs name two specialties in the title alone, while 3-or-more is only 0.65%.

Applies **only** under `software_engineering`. A subcategory is evaluated *after* §1 has already returned that category, so it partitions an existing set and structurally cannot re-route a job. That single fact dissolves every "collision with a top-level category" concern.

| Label | Slug | Measured | Rule |
|---|---|---|---|
| AI Engineering | `ai_engineering` | 4.76% (530) | Calls a model they did not train — LLM features, agents, RAG, evals |
| Backend | `backend` | 4.1%–47.6% | Server-side code consumed by the product's own users/clients |
| Data Engineering | `data_engineering` | 1.8%–10.8% | The deliverable is movement and shaping of data |
| DevOps & Site Reliability | `devops_sre` | 2.3%–14.3% | Keeps *other* teams running and shipping |
| Embedded & Low-Level Systems | `embedded_systems` | 2.9%–4.3% | Compiled against hardware or a kernel |
| Forward Deployed | `forward_deployed` | 2.8% | Ships production code inside a named customer's environment |
| Frontend | `frontend` | 1.2%–5.3% | Owns browser/desktop UI, does not also own the server |
| Full Stack | `full_stack` | 4.6%–7.9% | Explicitly requires both client and server. Exclusive |
| Infrastructure & Platform | `infrastructure_platform` | 14.1%–37.9% | Consumers are other engineers or other services |
| Machine Learning | `ml_engineering` | 4.74% (528) | Changes the model's weights, or the systems producing/serving them |
| Mobile | `mobile` | 2.4%–5.5% | Native or cross-platform app binary |
| QA & Testing | `qa_testing` | 2.0%–3.5% | Test coverage/infrastructure is the deliverable |
| Quantitative & Trading Systems | `quantitative` | 1.57% (175) | Correctness measured in money and microseconds |
| Robotics & Autonomy | `robotics_autonomy` | 2.4%–5.0% | Senses, plans, or actuates in the physical world |
| Security | `security` | 4.7%–11.0% | Subject matter is security; deliverable is code, not policy |

### Two rules the measurement forced

- **"Inference / serving" belongs to Machine Learning, not AI Engineering.** That token alone caused ~90% of the measured overlap between the two. Building an inference stack is ML; *calling* one is AI Engineering.
- **Never route on the `ai` tag or on AI mentions in the description.** 2,462 SWE rows (22% of the corpus) carry an ai/ml family tag while being ordinary backend jobs. Keying off mentions would drag ~1,243 plain rows into AI Engineering.

Tie-breaker for the case that bites — an engineer building an LLM feature at a company that also trains frontier models: *route on what the person in this role changes, not what the company builds.*

### Deliberate exclusions

- **No "Other" / "General" bucket.** 41.2% of titles carry no specialty; a General box would instantly become the model's lazy default *and* the largest option. Unlabelled is `[]`, an explicitly correct answer.
- **Engineering Management** — `level=manager` already covers 660 SWE rows. Double-encoding invites disagreement.
- **Networking** — clears the floor at 2.1% but fragments Infrastructure & Platform. Revisit only if Infrastructure measures >25% on the first 500 labelled rows.
- **iOS/Android split** — two ~1.5% boxes near the dead-checkbox floor.

### Storage

`job_listings.enrichment_subcategories TEXT[]` plus a `job_subcategories` dimension table. The tri-state is load-bearing:

- `NULL` — never evaluated. **This is the backfill queue**, and it is what makes the backfill resumable for free.
- `'{}'` — evaluated, no specialty applies.
- `['backend','ai_engineering']` — labelled, primary first.

### Filter semantics

- **OR within the facet**, AND across facets, matching existing behavior.
- Checking any child auto-checks and locks the `software_engineering` parent.
- One expansion rule, mirroring the shipped `new_grad ⊂ entry` contract: **`full_stack ⊂ {frontend, backend}`**. Checking Backend returns `backend OR full_stack`; checking Full Stack returns only full-stack. The classifier never litigates the boundary — the query widens.
- Unlabelled rows are **hidden** when a subcategory box is checked, consistent with how category and level already behave.

## 4. Decisions (all made)

| # | Decision |
|---|---|
| 1 | Backfill runs on **Claude Code** off-GPU, keeping the free title/tag pre-passes, with a **title+tags-only** prompt |
| 2 | Ship all **15** subcategories |
| 3 | Frontend **feature-flagged**; reveal at 90% coverage — computed and displayed, flipped manually |
| 4 | Golden set: **LLM pre-labels, human reviews disagreements** (plus independence rules, below) |
| 5 | Backfill scope: **OPEN only** (8,126 rows) |
| 6 | Unlabelled rows **hidden** under an active filter |
| 7 | Saved filters **do** persist a subcategory — adds a `subcategory JSONB` column |
| 8 | Seven smaller defaults accepted (chips, sort order, `subcategory_source` audit column, separate `subcategory_confidence`, cap-of-2 as a code constant, orphan `project_manager` cleanup) |
| — | `department` chip **removed** (done, on `feat/swe-subcategories`) |
| — | Title-regex pre-sort **declined** |

## 5. Backfill

The Claude Code engine (`ClaudeCodeEngine`) is already registered, takes a model tier, and runs on the **subscription** via `claude -p` — not the metered API. Critically it is a *subprocess, not the local GPU*, so it does not contend with the ollama worker. The live tick keeps running at full rate while the backfill runs beside it.

Four layers:

| Layer | What | Rows | Cost |
|---|---|---|---|
| 0 | Fix the 282-row poison cohort first | — | negative (returns capacity) |
| 1 | Deterministic title pass | ~4,780 (58.8%) | zero |
| 2 | Tag-assisted pass, single-bucket only | ~700 (8.6%) | zero |
| 3 | Claude Code on the remainder | ~2,650 (32.6%) | off-GPU |

**Run window:** one night, **hard stop 09:00 CT**. Needs a wall-clock deadline knob checked *between* chunks so it never dies mid-write. Resumability is free — the `NULL` tri-state *is* the queue. A morning report gives rows labelled, remaining, coverage %, and errors.

**Security boundary — do not cross silently.** `claude_code.py`'s docstring states that production deliberately keeps the sandboxed sub-agent fan-out as prompt-injection hardening for untrusted scraped text, and that headless `claude -p` is for trusted golden text only. Job descriptions are untrusted. The mitigation is the **title+tags-only prompt**; the alternative is routing through the sandboxed fan-out.

### Your three tiers, mapped

| Asked for | Where it lives | Added cost |
|---|---|---|
| Tier 1 — new SWE jobs | The existing tick, unchanged. The subcategory is an extra *field* on the classify call each new job already receives | zero |
| Tier 3 — general new jobs | The **same** unchanged tick | zero |
| Tier 2 — backfill | A separate Claude Code lane | off-GPU |

Tier 1 and Tier 3 are the same operation, so there is no queue to reorder: a new job gets one classify call, and subcategories ride along when the answer is software engineering. The three-tier scheme collapses to **one unchanged lane plus one backfill lane**.

## 6. Evals — new code, not an extension

The subcategory facet has **no scorer, no gold labels, and no gate entry** today. `Scorecard` has no subcategory field, `regression_gate` iterates a hardcoded facet tuple without it, and `golden.json` rows have no `subcategories` key. This is new eval code plus a new gold pool.

The gate **cannot currently fire**: `regression_gate` calls `load_truth(human_only=True)`, which filters 273 golden rows to 21, against `GATE_MIN_N = 50`. Only 11 of those are software-engineering.

Required:

- **Scoring semantics decided before labelling** — primary-exact (`pred[0]` vs `gold[0]`) *and* order-insensitive set P/R/F1, plus a `subcategory_leak_rate` for non-empty arrays on non-SWE rows.
- **Capture v6 baselines before touching `SKILL.md`** — the hash changes with the file, making the v6 baseline unreproducible afterward.
- **Reach n≥50 via pre-labelling, with two independence rules.** Agreement is only evidence if the labelers can fail independently. So: (1) the pre-labeler must be a **different model** than the one under test — Claude pre-labels, qwen3 is evaluated; (2) the review set is every disagreement **plus a random ~15% sample of the agreements**. Without both, agreement only proves the model is self-consistent, and shared blind spots become confirmed gold labels.
- **Fix the correction feedback loop** — `merge_corrections` iterates a hardcoded `("category","level","tags")`, and `load_truth` admits rows only `if r.get("category") or r.get("level")`, so a subcategory-only human correction never becomes a gold row.
- **A committed weak baseline** — the title+tag regex labeler, which the model must beat.

## 7. Live engineering obligations

None of these need a decision. The first three share a failure mode: **they do not crash, they succeed quietly and do nothing.**

| # | What breaks | Where |
|---|---|---|
| 1 | **The backfill can report success and persist nothing.** `EnrichmentResultItem` has no `extra='forbid'`, so a subcategory sent before JVN accepts the field is silently dropped while the run reports `written: N` | `models.py:886–926` |
| 2 | **A silently-failing backfill looks healthy.** `drift_suspected` only fires on `nulled_facets`; a run emitting `[]` for every row produces none, so the tick closes `status=ok` | `metrics.py:46–49` |
| 3 | **Admin corrections cause unrecoverable loss.** `apply_correction` issues an unconditional UPDATE then stamps `human_corrected_at`, locking the row against later automated writes. Two more paths orphan subcategories | `enrichment_monitor.py:379, :546`; `enrichment_writer.py:200` |
| 4 | **The 282-row poison cohort** trips any `classify_deferred > 0` guard permanently | live DB |
| 5 | **No rollback path** without `subcategory_source` | schema |
| 6 | **Cross-repo enum drift**, which has already happened: `job_categories` has 7 rows, the enricher frozenset 6, the frontend fallback 7 | 6 mirror points |
| 7 | **Production runs from a different checkout** — `~/developer/personal/app`, not the `job-enricher` repo. Merging to main deploys nothing | `/app/.checkout-role` |
| 8 | **Bump `version:` or the backfill is a silent no-op** — `_version_below` skips a same-version/new-hash file | `cli.py:1157` |
| 9 | **Write-back amplification** — backfill clears `sent_at` unconditionally | store / writeback |
| 10 | **PR #252 relocates the `full_stack` expansion** — on main both pages filter client-side; #252 moves Recent server-side | merge order |

> **Do not run `reenrich --taxonomy-below` after the v7 bump.** All 19,396 rows carry v6, so every row would match and the entire corpus re-queues (~40 days). It clears only the enricher's local SQLite labels, not this repo's data, and nothing runs it automatically — the trap is that the documented bump procedure tells you to. The subcategory pass leaves category, level and tags untouched instead.

## 8. Sequencing

| # | Phase | Why here |
|---|---|---|
| 0 | Diagnose the poison cohort; measure real seconds/row; resolve the alembic fork (main `1d2d6c17acfc` vs #252's `4b5d40dbc774`) | Every downstream estimate is fiction until these exist |
| 1 | Eval floor — pre-label to n≥50, capture v6 baselines, add the subcategory scorer and gate entry | Once `SKILL.md` changes, the v6 baseline is gone |
| 2 | JVN Phase 1 — migration (columns only, no seed), write-back tri-state, facets, admin tri-state fix, parity tests | Migrations run in-process at startup; the enricher must never write a slug the backend rejects |
| 3 | Enricher dark deploy — store v3→v4 rehearsed on a copy of the 240 MB DB, validators, hardened `reenrich`. **Deploy to `/app`** | Schema first, behavior later, so rollback is a knob flip |
| 4 | Taxonomy v7 — repeal the sub-specialty ban, add §1b, prompts, engines | Nothing user-visible; a bad rubric is a one-file revert |
| 5 | The v6→v7 gate. If top-level accuracy regressed, stop | The decision point of the project |
| 6 | Flip write-back — new SWE jobs start carrying subcategories | First step whose failure is user-visible |
| 7 | Backfill canary (200 rows, one tick, hand-check 30), then the sustained run | Cheapest place to catch a systematic rubric error |
| 8 | JVN Phase 2 + frontend — the filter, the tree, the rename, the changelog | Gated on measured coverage, not code readiness |

**The rename can jump the queue.** It has no dependency on any of this and ships standalone.

## 9. Feature flag

The reveal flag is a **DB-persisted admin toggle, not an env var** — an env var would need a Vercel redeploy to flip. This repo has no feature-flag mechanism today (`Feature`/`FeatureUpvote` are feature *voting*), so it needs a small `app_settings` key/value row plus a GET/PUT on the admin router, mirroring the enricher's existing knobs pattern. It sits next to the coverage tile. **Delete it in a follow-up PR** once permanently on.

> **Caching gotcha:** `GET /api/jobs/facets` is RTK-Query cached for an hour. A flag riding on that response appears not to work for up to an hour. Either serve it from a short-TTL endpoint or invalidate the facets tag on toggle.
