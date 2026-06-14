# Location Normalization — Prod Monitor Findings — 2026-06-14 (UTC ~05:12)

- **Verdict:** ✅ **HEALTHY** (first post-merge run; pipeline mid initial-drain, draining cleanly)
- **Run by:** agent (Claude), on-demand, read-only via `mcp__postgres-prod__query` + `mcp__railway-mcp-server__get_logs`
- **Deployment:** Railway deploy `d9b23593-47bb-48a1-afca-d434f790961e` · commit `b8830a25` (PR #145 "Location Normalization") · SUCCESS at **2026-06-14 04:58:41 UTC** (~13 min before this run)
- **Key-state:** **SET** — inferred from repeated `normalized via Tier-2` deploy-log lines (a live Haiku call only emits that on success). The direct `ANTHROPIC_API_KEY` log grep was correctly blocked by the auto-mode classifier as a credential-targeted read; not needed — the Tier-2 success lines are stronger positive proof.

> **Method note:** at the time of this run the `monitor_prod.py` CLI and runbook did not
> exist, so this run executed the plan's §4-A..F SQL/log checks directly via the MCPs (the
> runbook's documented fallback for "no local DSN configured"). They have since been built —
> CLI `src/backend/api/eval/monitor_prod.py` (groups A–D) and runbook
> `src/backend/docs/location-normalization-monitoring.md`. Strictly read-only; no prod
> writes, no `prod_sample.json` edits, no re-normalize.

## A–D — Health table (plan §4)

| Check | Value | Threshold | Status |
|---|---|---|---|
| **A1** schema gate | `has_status_col=1`, `n_loc_tables=4` | =1 / =4 | ✅ ok |
| **A2** heartbeat age | 3.99 min | warn>10, crit>30 | ✅ ok |
| **B0** key-state | SET (Tier-2 success lines) | — | ✅ ok (not dormant) |
| **B1** null_backlog | 47,966 → 47,866 (2 reads) | — | ✅ draining (−100/tick) |
| **B1** done | 100 → 200 (2 reads) | climbing | ✅ ok |
| **B1** null_aged_1h | 47,966 | decreasing during drain | ✅ see note¹ |
| **B2** failed_blank | 0 | sanity only | ✅ ok² |
| **B2** failed_nonblank ratio | 0 / 200 = 0% | warn>2%, crit>5% | ✅ ok |
| **C1** done-without-locations | 0 | crit>0 | ✅ ok |
| **C2** alias-without-children | 0 | warn>0 | ✅ ok |
| **C3** id collisions | 0 | crit>0 | ✅ ok |
| **C4** orphan job_locations | 0 | warn>0 | ✅ ok |
| **C5** remote-with-city | 0 | warn>0 | ✅ ok |
| **C6** city-kind-null-city | 0 | warn>0 | ✅ ok |
| **C7** low-conf cached LLM alias | 0 (min LLM conf = **0.95**) | warn>0 | ✅ ok |
| **C8** geo populated (v1) | 0 | warn>0 | ✅ ok |
| **C9** multi-primary per job | 0 | warn>0 | ✅ ok |
| **D** normalize queue | succeeded 101→202, **failed 0**, no piled todo/doing | failures flat | ✅ ok |

¹ **`null_aged_1h` = full backlog is EXPECTED here, not a stall.** These 47,966 NULL rows
were scraped days/weeks ago (their `first_seen_at` predates the feature), so all are >1h
old. The real stall signal is the run-over-run trend, and the two readings 100 jobs apart
show backlog strictly decreasing + `done` strictly increasing → genuinely draining, not stuck.

² `failed_blank` is still 0 only because the drain hasn't yet reached the ~4,418 (9.2%)
blank-location rows that will legitimately fail as `no-location`. Expect `failed_blank` to
climb toward ~4.4k as drain completes — that is the **designed floor**, not an alarm.

**Cache state (warming):** locations=26, aliases=40 (all `source='llm'`, none manual),
alias_locations=54, job_locations=248. Min LLM confidence **0.95** (well above the 0.5 floor).

## E — Log-stream (plan §4-E)

- **Error-level deploy logs (last 24h): NONE.** No pool-exhaustion / `too many clients` /
  `connection` errors (the 2026-05-17 anti-pattern has **not** returned), no
  `permanently unparseable`, no `low-confidence`, no `alias cache invariant violated`,
  no `ALL … defer(s) FAILED`.
- **`scan_unnormalized` safety net ticking on `*/5`:** tick `1781413500` (05:06) → `deferred
  100/100 unnormalized (failed=0)`; tick `1781413800` (05:10) → `deferred 100/100 (failed=0)`.
  Each tick ~29s, defers exactly `SCAN_LIMIT=100`.
- **Tier-1 vs Tier-2:** Tier-1 cache HITs dominate the log window with a minority of
  `normalized via Tier-2` (3.0–3.6s each). ~40 distinct strings hit Tier-2 across 200 done
  jobs ⇒ **~80% Tier-1 HIT even in early warmup**, trending toward the >90% steady-state
  target. (info — healthy trajectory.)
- Worker booted clean on the new deploy; `normalize` queue + `normalize_location` /
  `scan_unnormalized` tasks registered and running; no crash-loop.

## F — Quality (plan §4-F)

- **Mapping-correctness audit (EXHAUSTIVE — entire distinct cache, not a sample): 0 errors.**
  Pulled all distinct `raw → canonical` mappings currently in prod (~50 distinct raw strings /
  76 raw→canonical rows) and ran an automated mismatch detector for four error classes —
  `city_not_in_raw` (canonical city name absent from the raw string = garble/reversal),
  `us_raw_nonus_country` (US-text raw → non-US country), `remote_with_city`, `city_kind_no_city`.
  **All four returned empty.** Manual review of every distinct mapping confirmed correctness,
  including the structurally tricky ones:
  - State-only → `kind=region`: `"Texas, United States"` → `Texas, US` (`region=TX`, `city=NULL`) ✅
  - Reversed order: `"United States, Washington, Redmond"` → `Redmond, WA, US` ✅
  - Remote w/ country scope: `"Remote - Canada"` → `Remote (Canada)` (`country=CA`, `remote_scope=ca`, `city=NULL`) ✅
  - Remote w/ region scope: `"US - NY - Remote"` → `Remote (NY, US)` (`remote_scope=us`, `region=NY`, `city=NULL`) ✅
  - City-state → `kind=country`: `"Singapore"` → `Singapore` (`country=SG`) ✅
  - Bare-city inference: `"Los Angeles"` → `Los Angeles, CA, US`; `"Memphis, TN"` → `Memphis, TN, US` ✅
  - Non-US cities: `"Vancouver, BC, Canada"` → `Vancouver, BC, CA`; `"Quito, Pichincha, Ecuador"` → `…, EC` ✅
  - Full-form normalization: `"…, United States of America"` → `US` ✅
  - Multi-city splits: primary is consistently the **first-listed** city; secondaries `is_primary=false` ✅

- **F1 live spot-check (80 most-recent `done` rows): CLEAN — zero systematic errors.**
  Verified the hard cases:
  - Reversed order: `"United States, Washington, Redmond"` → `Redmond, WA, US` ✅
  - Remote: `"US - NY - Remote"` → `Remote (NY, US)`, `kind=remote`, **`city=NULL`**,
    `region=NY`, `remote_scope=us` ✅ (C5 invariant holds on real data)
  - Country/city-state: `"Singapore"` → `Singapore` (`kind=country`, `country=SG`),
    `"Quito, Pichincha, Ecuador"` → `Quito, Pichincha, EC` ✅
  - Multi-city splits (e.g. `"New York, NY, USA; Sunnyvale, CA, USA"`,
    `"Sunnyvale, CA, USA; Kirkland, WA, USA"`) → 2 rows, **exactly one `is_primary=true`** ✅
  - Long-form US strings (`"Beaverton, Oregon, United States"`, `"Irvine, California,
    United States"`, `"Austin, Texas, United States"`) → correct `City, ST, US` ✅
  - **No** reversed/garbled/wrong-country/remote-as-city pairs found.
  - **Spot-check suspects (candidate eval cases): NONE this run.**
- **F2 Tier-2 eval: NOT RUN this session** — requires `ANTHROPIC_API_KEY` locally and spends
  model tokens. Recommended as the next follow-up (see below). Last known baseline: 100%
  gating accuracy (66/66), `--repeat 3`, captured 2026-06-13.

## Verdict & drain ETA

**HEALTHY.** PR #145 deployed cleanly, the migration applied, the worker is alive, the
`normalize` queue is draining at **~100 jobs / 5-min tick** with **zero** failures, **every
integrity invariant (C1–C9) is 0**, and the F1 quality spot-check is flawless. At the observed
~1,200 jobs/hr the ~48k initial backfill should fully drain in **~1.5 days (~2026-06-15/16)** —
consistent with the plan's estimate. This is the **expected initial-drain phase**, not a
steady state.

## Suggested follow-ups (NOT auto-applied — report-only)

- [ ] **Re-run this monitor once the drain completes (~2026-06-15/16)** to capture the
      **steady-state baseline**: confirm `null_aged_1h` near 0, `failed_blank ≈ 4,418`
      (~9.2%), `failed_nonblank` ratio low, Tier-1 HIT > 90%. Save that run's JSON as the
      `--baseline` reference and record the calibrated B1 / D thresholds (plan §8 leaves
      these as proposals until the first clean steady-state run).
- [ ] **Run the F2 Tier-2 eval** for the authoritative quality check (needs
      `ANTHROPIC_API_KEY` in `.env.local`):
      `PYTHONPATH=. python -m src.backend.api.eval.eval_locations --set all --repeat 3 --baseline src/backend/api/eval/eval-baseline.json`
- [x] Build the `monitor_prod.py` CLI + runbook from `MONITORING_PLAN.md` so future runs
      are one command instead of hand-run SQL. **Done** — CLI
      `src/backend/api/eval/monitor_prod.py` (groups A–D, read-only, exit 0/1/2), unit tests
      `src/backend/api/tests/test_monitor_prod.py`, runbook
      `src/backend/docs/location-normalization-monitoring.md`.
- [ ] No `prod_sample.json` additions warranted — F1 surfaced no suspect normalizations.
