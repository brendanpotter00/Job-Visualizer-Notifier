# Runbook — SWE subcategory backfill

Operational runbook for the SWE-subcategories epic's enricher half (PR-C).
Everything here is a **procedure a human runs**, not something a tick does.

> **Read the destructive-command warnings before pasting anything.** Two
> commands in this repo can cost days of worker time:
> `reenrich --taxonomy-below` and `subcategory-reset`. Both count first, both
> refuse above 500 matched rows without `--yes-i-mean-all`.

---

## 0. Prod is `/Users/bpotter/developer/personal/app`, not this repo

Merging to `job-enricher` `main` **deploys nothing**. See
[`ENVIRONMENTS.md`](./ENVIRONMENTS.md) and the deploy procedure in §6 below.

---

## 1. Cross-repo taxonomy parity (`ENR-PAR-2`)

Every other guard in this epic is intra-repo. This is the only check that
compares the enricher's slug sets against JVN's live API — the drift it catches
is slow, silent and only observable in production (the current `project_manager`
6-vs-7 category drift is exactly this failure, and it survived for a year).

```sh
PARITY_CHECK=1 JVN_BASE_URL=https://onesecondswe.dev scripts/check_taxonomy_parity.sh
```

Exits 0 and prints `subcategories: 17/17 match, categories: 6/6 match` when
parity holds; exits 1, prints each problem, and texts via the `message-brendan`
skill otherwise. `--write-snapshot` refreshes
`golden/taxonomy-parity/jvn_facets.json`.

Installed as launchd `com.bp.jvn-taxonomy-parity` (daily 09:15), mirroring
`com.bp.jvn-health-watch`. The plist template is
`scripts/com.bp.jvn-taxonomy-parity.plist` — **this PR does not install it.**

### The two expected-red windows

| Window | What is red | What to do |
|---|---|---|
| **Before `SCHEMA-11` ships** (retire `project_manager`) | `categories: JVN-only ['project_manager']` | Expected. This non-zero exit **is the proof the check works.** Do not "fix" it here — SCHEMA-11 fixes it JVN-side. |
| **Before `SCHEMA-7` seeds the 17 rows** | `subcategories: enricher-only [all 17]` | Run with `ALLOW_EMPTY_SUBCATEGORIES=1` (the plist sets it). Remove that env var the day SCHEMA-7 lands, or the guard is armed against nothing. |

### The vendored snapshot

`golden/taxonomy-parity/jvn_facets.json` is **JVN's
`src/backend/taxonomy.json` (SCHEMA-15's artifact) copied verbatim**, with its
sha256 in `jvn_facets.sha256`. **Never re-derive the slug list in this repo** —
two independently-typed lists agree right up until one of them is edited, which
is the seam SCHEMA-15 exists to close.

**It is vendored** — from `origin/feat/swe-subcat-b-backend` (PR-B) commit
`b1356ca`, so half (a) is armed and green today. Provenance and the two refresh
recipes live in `golden/taxonomy-parity/README.md`; **refresh the `.json` and
the `.sha256` together** or the recorded-sha test goes red. ⚠ **Re-copy it once
PR-B merges to JVN `main`.**

⚠ **Third expected-red window, and it is live NOW.** The 15 → 17 widening
(`growth_engineering`, `product_engineering`) landed in the ENRICHER first, so
JVN's artifact is a slug set behind. The vendored `.json` therefore carries a
**locally regenerated** 17-slug `subcategories` block — the generator's exact
output shape — instead of a verbatim copy, and the LIVE half (b) will report
`subcategories: enricher-only ['growth_engineering', 'product_engineering']`
plus nine `sort_order` mismatches until JVN ships the new rows. That non-zero
exit **is the proof the check works**; do not silence it here. The fix is
JVN-side, then one `git show` re-copy. See
`golden/taxonomy-parity/README.md` → *"RIGHT NOW THIS COPY IS A FORECAST"*.

⚠ The snapshot tests **FAIL** if the file is missing. They used to `skip`, which
made the PR-blocking half report success while asserting nothing. Do not turn
them back into skips.

---

## 2. Diagnosing the stuck cohort (`P0-1`, `P0-2`)

### 2.1 Run the read-only harness (`P0-1`)

```sh
# From the DEV worktree. Read-only by construction: PRAGMA query_only=ON, and the
# script ABORTS if that pragma does not read back 1.
uv run python scripts/diagnose_stuck_cohort.py \
  --db /Users/bpotter/developer/personal/app/data/enricher.db
```

Why the connection recipe is not the obvious one:

| Approach | Why not |
|---|---|
| `file:...?mode=ro` URI | A **WAL** DB must attach `-shm`/`-wal`; a read-only URI raises `SQLITE_CANTOPEN` (err 14). |
| `immutable=1` | Returns a **stale main-file image** — silently wrong numbers instead of an error. |
| `Store(...)` | **`init_schema()` WRITES** (`store.py:219` journal-mode, `:232` the `user_version` stamp). Opening prod through the normal class mutates it. |

The report prints the count of `status='cleaned' AND first_seen_at IS NULL`.
**Reported, deliberately NOT repaired** — see §2.3.

### 2.2 The three hypotheses, and their verified status

| # | Hypothesis | Status | Evidence |
|---|---|---|---|
| **H1** | **Engine-timeout abandonment** | ⚠ **CONFIRMED** | `_cmd_classify_run` (`cli.py:707-711`) does `except EngineError as exc: logger.error(...); continue`. The chunk is **skipped**, `errors` is never bumped, `inbox.attempts` is never touched, and **the tick closes `status=ok / errors=0`.** Corroborated by 607 `ollama call failed (qwen3:32b): timed out` lines in `~/Library/Logs/job-enricher.err`, and by recent ticks recording `classified=38` against `enrich:per_tick_limit` = 40 (the meta key is at **`enrich_config.py:93`**, not 92). |
| **H2** | **Order starvation** | ⚠ **CONFIRMED** | `store.py:354-366`, `ORDER BY` at `:360`: NULL `first_seen_at` sorts LAST forever, so a NULL-recency row behind a queue longer than the per-tick limit is never reached. |
| **H3** | Unhashable-dict crash | **NOT reproduced** | Fixed by `bf3be25`; no current evidence. |

`h1_silent_abandonment_ticks` and `h1_rows_lost_estimate` in the report are the
measured rows-lost-per-tick. Convert to rows/day (`× ticks/day`) and
seconds/tick and record both here as the returned-capacity estimate.

### 2.3 ⚠ The decision rule — and where to STOP

If NULL-recency rows exceed **10%** of the cleaned cohort, the script prints a
STOP notice. **RECORD the count and BOTH candidate remedies here, and stop.**
Do not fold a remedy into `P0-3`.

| Candidate remedy | Why it is NOT applied |
|---|---|
| `UPDATE inbox SET first_seen_at = claimed_at WHERE first_seen_at IS NULL` | `first_seen_at` is documented at `store.py:68-71` as **"the job's posting-recency signal from JVN"**. Overwriting it with a local claim timestamp permanently **corrupts a provenance column to fix a sort symptom**, and makes those rows look freshly-posted to every future recency comparison. |
| `ORDER BY COALESCE(first_seen_at, claimed_at) DESC` | Non-mutating, but **still an order change**, and r11 explicitly declined an order change. Folding an order change into a migration is exactly how a declined decision ships anyway. |

Both need **an explicit yes from Brendan**, not a migration side effect.

### 2.4 Write the verdict here

After the run, this section must carry one line naming: the confirmed
hypotheses, the measured rows-lost-per-tick, and the returned-capacity estimate
in rows/day and seconds/tick.

> **VERDICT: _not yet run_** — this is a measurement against the live prod DB and
> is deliberately left for a human. See "Not run" in the PR body.

---

## 3. The OPEN-only backfill scope (`P0-4`)

### 3.1 Why the scope must come from JVN

⚠ **Verified, not stylistic — the enricher has NO OPEN/CLOSED signal of its own:**

* `inbox.status` is **pipeline** state, not job state:
  `CHECK (status IN ('claimed','cleaned','enriched','sent','failed'))` (`store.py:75-76`).
* JVN's `_JOB_PROJECTION` (`internal_enrichment.py:61-72`) narrows `details` to
  exactly `department` + `experience_level`, **so JVN has never shipped the
  enricher a status or company tags.**

Backfilling CLOSED jobs is pure waste, so the scope is exported from prod
Postgres and imported into the one scope table, `backfill_scope`.
**`backfill_roster` does not exist and must not appear anywhere.**

### 3.2 Export + import

```sh
# 1. Export from JVN's prod Postgres (READ-ONLY).
psql "$DATABASE_URL" -At -f scripts/export_open_swe_scope.sql > /tmp/open_swe_scope.ndjson

# 2. Import (idempotent upsert on the composite key).
uv run python -m job_enricher.cli subcategory-scope-import --json-file /tmp/open_swe_scope.ndjson
# -> imported=<N> matched_local=<M> missing_local=<N-M>
```

### 3.3 ⚠ REFRESH POLICY — and the two refusals

The scope is a **point-in-time** export and **jobs open and close overnight**.
**Re-run the export AND the import immediately before each night's run.**

The run refuses (**exit 2**) on:

| Condition | Why |
|---|---|
| scope older than `SCOPE_MAX_AGE_HOURS = 24` | stale scope = labelling jobs that closed overnight |
| an **empty** scope | ⚠ a silently-empty scope makes `--open-only` a **no-op that reports success** |

### 3.4 ⚠ Record the denominator here

`matched_local` **is `PARAM_BACKFILL_DENOMINATOR`.** It replaces the placeholder
`~8,126` in every downstream estimate **and in the 90% coverage denominator**.
`ADM-6`'s `swe_open_total` must use the SAME definition or the admin tile and
the backfill disagree about what 90% means.

⚠ **8,126 is a JVN-side OPEN-SWE count, NOT a backfillable count.** Do not reuse it.

> **`PARAM_BACKFILL_DENOMINATOR` = _not yet measured_** — needs the prod export.
> See "Not run" in the PR body.

---

## 4. Rehearsing the v3→v4 SQLite migration (`P0-7`)

**This is the ONE rehearsal step.** It gates the migration reaching
`/Users/bpotter/developer/personal/app`.

```sh
scripts/rehearse_v4_migration.sh /Users/bpotter/developer/personal/app/data/enricher.db
```

### 4.1 ⚠ Copy with `.backup`, NEVER `cp`

The prod DB is **WAL-mode**. A plain `cp` of the main file silently drops the
`-wal` sibling and is racy against a running tick, so the copy you rehearse on
would not be the database you have. Use:

```sh
sqlite3 <live> ".backup /tmp/enricher-rehearsal.db"
```

### 4.2 What the rehearsal asserts

* `PRAGMA user_version` becomes **4**
* **all TEN new columns** — seven on `enrichments`, three on `ticks`
* **BOTH new tables** — `backfill_runs`, `backfill_scope`
* unchanged `inbox` / `enrichments` / `ticks` row counts
* `PRAGMA integrity_check` = `ok`
* **every pre-existing enrichment at `subcategories IS NULL`** (never `'[]'`)
* re-running `init_schema` is a no-op still at v4

### 4.3 ⚠ The decision rule

Record `MIGRATION_V3_V4_SECONDS`. **If it is > 30 s, SPLIT the migration** —
`deploy.sh` runs it at step 6 with the worker parked, and a long stall there is
a parked-worker outage.

### 4.4 ⚠ v3→v4 is a ONE-WAY DOOR

`init_schema` has **no downgrade** and `user_version` only moves forward, so
**the `.backup` copy IS the rollback artifact.** Record its path here, and the
ticks that restoring it would lose.

> **`MIGRATION_V3_V4_SECONDS` = _not yet measured_** · **`.backup` artifact path
> = _not yet taken_** — this is a run against a copy of the live 240 MB prod DB
> and is deliberately left for a human. See "Not run" in the PR body.
>
> ⚠ This is a point-in-time measurement of a **growing** database. If the DB
> grows materially before the deploy, **re-run it** rather than trusting the
> recorded number against the 30 s rule.

---

## 5. Deploying the enricher (`DEP-1`)

### 5.1 ⚠ Merging to `job-enricher` main deploys NOTHING

The live worker runs from **`/Users/bpotter/developer/personal/app`**
(`.checkout-role='prod'`), launchd label **`com.bp.job-enricher`**,
`StartInterval` 60, `ProgramArguments` = `<prod>/scripts/enrich_tick_wrapper.sh`.
This repo is the DEV checkout; nothing you merge here reaches production on its own.

### 5.2 The procedure

```
dev worktree  ->  PR  ->  merge to main  ->  cd ~/developer/personal/app && scripts/deploy.sh
```

⚠ **The idle window is unhittable by guessing.** Ticks run ~6,700 s and fire
every 60 s, so there is no reliable moment when nothing is running.
`deploy.sh` handles it in order: **arm the resume trap → unload → WAIT on the
in-flight wrapper (live-pid lock check) → pull → health → resume via the EXIT
trap.** Do not shortcut it.

### 5.3 ⚠ The v3→v4 ALTERs run inside `deploy.sh` step 6

Step 6's `cli health` opens the DB, which runs `init_schema()`, which runs the
migration ladder — **with the worker parked.** That is exactly why `P0-7`'s
timing gate exists: a migration longer than 30 s is a parked-worker outage.

**GATE: do not deploy the v4 migration until `P0-7` has recorded
`MIGRATION_V3_V4_SECONDS`** on a `.backup` copy of the live 240 MB DB.

### 5.4 The backfill is run BY HAND from the prod checkout

A documented exception to "never run things by hand in prod", permitted **only
because the backfill holds `.backfill.lock`** — so it cannot collide with the
launchd tick's `.tick.lock`. Nothing else may be run by hand there.

### 5.5 Verify after

```sh
launchctl list | grep job-enricher     # the label must be loaded
uv run python -m job_enricher.cli health   # must exit 0
```

---

## 6. Cross-repo deploy ORDER (`DEP-2`)

**Thirteen steps. Every inversion has a failure mode, and every one of them is
silent** — the whole reason the order is written down instead of remembered.

> ⚠ Step 1's prerequisite is `SCHEMA-6`: **Phase 1 must be confirmed LIVE in
> prod**, not merged. See §6.1 (the deploy-skip trap).

| # | Step | Repo | ⚠ What breaks if you do it EARLIER |
|---|---|---|---|
| 1 | Ship JVN **Phase 1** (subcategory columns, `SUBCATEGORY_SOURCES`, `/results` accepting the three new keys) | JVN | **THE WORST INVERSION.** `EnrichmentResultItem` has **no `extra='forbid'`**, so a `subcategories` key arriving before Phase 1 is **silently dropped while the response still says `written: N`**. Nothing errors, nothing logs, and the labels are simply gone. |
| 2 | **Verify** Phase 1 in prod — `alembic_version` moved, one hand-posted result read back non-null (`SCHEMA-6`) | JVN | Skipping this is the **deploy-skip trap**: a merged PR whose deploy was skipped looks identical to a shipped one from the enricher side, and step 1's failure mode then applies in full. |
| 3 | Enricher **schema-only** deploy, dark (`writeback:send_subcategories` OFF, `backfill:enabled` OFF) | enricher | Deploying with either knob already on starts writing before the far side or the rubric is proven. |
| 4 | **D1 — raise the CATEGORY human gold pool past 50** (`EV-2b` / `EV-9b`) | enricher | `regression_gate` **refuses below `GATE_MIN_N=50`** on `current.category.n` (21 today), so `--allow-draft` returns 0 on failure and **phase 5's gate is decorative**. |
| 5 | **Capture the v6 baselines** (`EV-2`, `EV-2c`) | enricher | ⚠ **IRREVERSIBLE ONCE SKILL.md's HASH MOVES.** After the v7 edit the v6 arm is only reproducible from `SKILL_MD_V6_GIT_SHA`; if that SHA was never recorded the A/B is unrecoverable. |
| 6 | **Taxonomy v7** — `version: v7` as the FIRST edit, §1b kept COMPACT per D3, the long rubric in `SUBCATEGORIES.md` | enricher | Bumping `version:` later than the rest of the edit makes `_version_below` **silently skip**. A non-compact §1b spends the classify lane's prompt budget (`ENR-LAT-1`). |
| 7 | **The v6→v7 gate** (`EV-12`) — run WITHOUT `--allow-draft` | enricher | An ungated v7 ships an unmeasured rubric to both lanes at once. |
| 8 | Flip **`writeback:send_subcategories` ON** | enricher | Before step 1 this is step 1's failure mode; before step 7 it ships ungated labels. |
| 9 | **The canary** — `cli subcategory-backfill --limit 200 --until <now+30m>` | enricher | ⚠ The canary is also **what SETS the breaker thresholds**: `BACKFILL_BREAKER_EMPTY_RATIO` must come from its MEASURED per-layer `[]` rate. Running the sustained night on the placeholder means the breaker either fires constantly or never. |
| 10 | **The sustained run** (`--until 09:00 --open-only`) | enricher | Before step 9 there is no measured seconds/row, so the night's length is a guess. |
| 11 | **D2 — the throttled bulk drain** into `SCHEMA-14` (`cli subcategory-push`) | enricher → JVN | Before `SCHEMA-14` exists the drain has no endpoint. ⚠ Pushing through the legacy `/results` instead is the deleted design: `apply_result` **returns early for any row with `human_corrected_at` set while still counting it `written`**, so a backfilled label can NEVER land on the human-corrected pool the eval gate depends on. |
| 12 | JVN **Phase 2** + the frontend (`?subcategory=`, facets, the proxy allowlist) | JVN | ⚠ **Inverted before `RA-6`: the serverless proxy DROPS the `subcategory` param and returns an unfiltered 200** — a filter that silently does nothing, with no error anywhere. |
| 13 | **Flip the reveal flag at 90% coverage** (`ADM-11` computes it, a human flips it) | JVN | Flipping before coverage means most SWE rows match no subcategory and the filter reads as broken. Do **not** build auto-reveal — a filter that switches itself on mid-session is surprising and a threshold near the line flaps the UI. |

### 6.1 The two round-trips that prove the order held

Both live in the **JVN** repo and are run by hand as part of `GO-1` item 3:

1. A `subcategory` written through `POST /api/internal/enrichment/results`
   **reads back non-null from `GET /api/jobs`** — this is what proves step 1
   actually shipped rather than merged.
2. `subcategory` is present in the proxy's `REPEATABLE_PARAMS`
   (`api/jobs.ts`, owned by `RA-6`) — this is what proves step 12 held.

> ⚠ Neither test can live in this repo: both assert on JVN source. **They are
> not run by PR-E.**

---

## 7. Post-deploy prod verification (`DEP-3`)

> ⚠ **NOT RUN BY PR-E.** This section is the checklist; performing it needs a
> live prod deploy. Tick each box **with the observed value**, not a checkmark.

### 7.1 After JVN Phase 1

| Check | Command | Expected | Observed |
|---|---|---|---|
| Migration actually ran | `SELECT version_num FROM alembic_version;` | moved past `536c1cddcd28` | ☐ |
| Health denominator | `GET /api/admin/enrichment/health` | `sweOpenTotal` ≈ the recorded `PARAM_BACKFILL_DENOMINATOR` | ☐ |
| ⚠ No slug drift | same response | **`subcategoryUnknownSlugs = 0`** | ☐ |
| Retired category | `SELECT count(*) FROM job_categories;` | **6** | ☐ |

### 7.2 After JVN Phase 2

| Check | Command | Expected | Observed |
|---|---|---|---|
| Facets expose the tree | `GET /api/jobs/facets` | **15** subcategory slugs, **6** categories | ☐ |

### 7.3 After the enricher deploy

```sh
# from the PROD checkout, /Users/bpotter/developer/personal/app
sqlite3 data/enricher.db 'PRAGMA user_version;'      # -> 4  (read-only)
uv run python -m job_enricher.cli health             # must exit 0
uv run python -m job_enricher.cli health | jq .inbox.cleaned   # must TREND DOWN
```

### 7.4 ⚠ The parity check is THREE-WAY

Prod facets **==** the enricher frozenset **==** the committed `taxonomy.json`,
for **both** subcategories (15) **and** categories (6).

```sh
uv run python -m job_enricher.cli parity-check
```

Run **that command**, not an ad-hoc curl — the ad-hoc version compares two of the
three sources and reads green while the third has drifted.

> The CI halves of this check are owned elsewhere and are **not authored here**:
> `SCHEMA-15` owns the JVN assertion (`api/tests/test_taxonomy_artifact.py`, JVN
> repo) and `ENR-PAR-2` owns the enricher's. **DEP-3 only RUNS them against prod
> and records the output.**

---

## 8. Seconds/row: haiku vs sonnet on the same sample (`P0-5`)

> ⚠ **NOT RUN BY PR-E.** It needs a live model. The harness and the decision rule
> are committed; the table below is empty on purpose. **Repeat no night-length
> claim until it is filled in.**

```sh
uv run python scripts/measure_subcategory_cost.py --n 20 \
    --tiers haiku,sonnet --batches 1,4,10 --out data/p0-5.json
```

It consumes **`BF-9`'s `--dry-run` harness**, not a second probe — so the number
the runbook quotes and the number the night's run produces cannot diverge.

### 8.1 The cost table — six cells, circle the chosen one

| tier | batch | s/row p50 | s/row p95 | parse-failure | `[]` rate | echo-mismatch |
|---|---|---|---|---|---|---|
| haiku | 1 | ☐ | ☐ | ☐ | ☐ | ☐ |
| haiku | 4 | ☐ | ☐ | ☐ | ☐ | ☐ |
| haiku | 10 | ☐ | ☐ | ☐ | ☐ | ☐ |
| sonnet | 1 | ☐ | ☐ | ☐ | ☐ | ☐ |
| sonnet | 4 | ☐ | ☐ | ☐ | ☐ | ☐ |
| sonnet | 10 | ☐ | ☐ | ☐ | ☐ | ☐ |

**Projected whole-run duration = `matched_local` × ⟨chosen s/row⟩ = ☐**
(`matched_local` is `PARAM_BACKFILL_DENOMINATOR`, from §3.4 — **not** 8,126.)

### 8.2 The decision rule

> **Lowest p95 s/row, subject to parse-failure ≤ 2% and haiku-vs-sonnet
> agreement ≥ 85%. Below 85% agreement, SONNET WINS** — cost does not get a vote,
> because 8,000 rows nobody will re-read is not the place to save money on a tier
> the two models disagree about.

### 8.3 ⚠ The concurrency arithmetic, written down rather than assumed

`ChunkEngine._call_with_repair` is **strictly sequential** — one `subprocess.run`
per chunk, plus one more on the repair path.

```
wall_seconds     = ceil(rows / batch) * T_chunk(batch)
seconds_per_row  = T_chunk(batch) / batch
```

There is **no concurrency term** because there is no concurrency. The only levers
are `--batch` and the model tier.

### 8.4 ⚠ The disclosure that must travel with every tag-layer number

Every prompt is built from **TITLE + `enrichments.tags` only**, never
`clean_description` — enforced structurally, since `chunk_rows` raises on a row
that even carries a description key.

**Those tags are the enricher's OWN v6-generated tags, not company tags.** JVN's
`_JOB_PROJECTION` has never shipped `details->'tags'`. So **layer-2 tag agreement
is NOT independent evidence** — it is v6 grading its own homework. Say so here,
and say it again in the morning report.

### 8.5 ⚠ The per-layer `[]` rate sets a breaker, not just a stat

`BACKFILL_BREAKER_EMPTY_RATIO` must be **this measured number plus a stated
band** — never the 0.60 placeholder. The corpus-wide `[]` rate is 41.2%, but
layer 3 is by construction the residue where the title says nothing and the tags
disagree, so its true rate is far higher. **A breaker tuned to 41% fires
constantly.**

---

## 9. Stopping things: the three levels (`OPS-4`)

Each level has a different **latency**, and picking the wrong one is how a
"stopped" backfill keeps running for two hours.

| Level | Mechanism | Latency | What it does NOT do |
|---|---|---|---|
| **1 — soft** | the knobs (`cli set-backfill-enabled off`, `reset-knob`, the dashboard's Knobs panel) | the **runner** honours them at the next **chunk** boundary — *seconds*. ⚠ **The write-back honours them at the next TICK — up to ~2 h, because a tick runs ~6,700 s.** | does not interrupt a chunk in flight |
| **2 — hard** | `SIGINT` / `SIGTERM`, or `touch data/.backfill.stop` / `data/.subcategory-push.stop` | the next chunk/batch boundary | ⚠ **Nothing is rolled back — and nothing needs to be. Every committed row stays committed, because the NULL tri-state IS the queue.** The lock's exit trap clears the lock. |
| **3 — nuclear** | `launchctl bootout ...` | immediate | ⚠ **LIVE PIPELINE ONLY.** The backfill and the drain are launched BY HAND and are not under launchd — booting the agent out does nothing to them. |

> ⚠ **There is deliberately no mid-unit stop.** That is exactly what protects a
> write in flight.

### 9.1 ⚠ The stale-rubric trap — the runner must be RESTARTED, not re-knobbed

`prompts._taxonomy_text` is `lru_cache(maxsize=1)`. **The overnight backfill is
the FIRST long-lived prompt-building process in this codebase**, so it caches
`SUBCATEGORIES.md` at first use and **never sees a mid-run edit**.

That is the behaviour we want — the run row's `taxonomy_version` **and**
`rubric_version` stamps prove which rubric produced the labels. But it means:

> **After ANY rubric edit, restart the runner. Flipping a knob will not pick it
> up, and the run will keep labelling against the old rubric while looking fine.**

### 9.2 Every knob, and where it must be registered

A knob has to be in **four** places or it is invisible somewhere:

| Registry | Consequence of omission |
|---|---|
| `enrich_config.KNOB_META_KEYS` | `reset-knob` cannot clear it |
| `enrich_config.config_snapshot` | ⚠ it never rides `/metrics` |
| `cli.build_parser`'s knob-setter table | no CLI setter |
| `dashboard._KNOB_SETTERS` | ⚠ **it cannot be toggled from the UI at all** |

The six added by this workstream — `backfill:enabled`, `backfill:batch_size`,
`backfill:max_attempts`, `writeback:subcategory_push_batch`,
`writeback:subcategory_push_duty_pct`, `writeback:subcategory_push_max_seconds` —
are in all four, and `tests/test_dashboard.py` asserts the fourth.

---

## 10. Per-phase rollback — and what is NOT undoable (`RB-1`)

### ⚠ 10.1 JVN IS ROLL-FORWARD-ONLY

`api/migrations.py:100` runs `command.upgrade(cfg, "head")` **inside the FastAPI
lifespan and re-raises**. So redeploying the **previous** image after Phase 1
leaves `alembic_version` at a revision that image does not contain, and **the
container never boots**.

> **Recovery is a NEW revision. The correct rollback is to revert the CODE and
> LEAVE the nullable columns in place.**

The JVN-side scoped reversal is **`ADM-15`** (dry-run by default) — **not** a
hand-run `UPDATE`.

### 10.2 The enricher's own reset

`BF-14` / `cli subcategory-reset`, keyed on the five-value source enum and
**excluding human rows by construction**. `tests/test_store.py`'s all-five-sources
fixture is what proves the `WHERE` clause.

> ⚠ **The `.backup` copy from `P0-7` is the enricher's rollback artifact, because
> v3→v4 is a ONE-WAY DOOR — `init_schema` has no downgrade.**

### ⚠ 10.3 NOT UNDOABLE — say these out loud before you start

- **Wall-clock spent.** A wrong night is a lost night.
- **Human rows overwritten by an UNSCOPED reset.** Scope it, always.
- **The v6 baseline, if SKILL.md moved first.** Recoverable only from
  `SKILL_MD_V6_GIT_SHA`; without that SHA the A/B is gone.
- **Retired `'failed'` ids that were never recorded.**

### 10.4 The rehearsal

Rehearse the scoped reset on `P0-7`'s `.backup` copy. **The affected row count
must equal the sum of the run's `labelled` + `empty` counters** — pinned by
`test_rb1_the_reset_count_equals_the_runs_labelled_plus_empty`.

> ⚠ **NOT REHEARSED BY PR-E** — it needs the prod-DB copy, and `ADM-15` (the JVN
> half) does not exist in this repo.

---

## 11. GO / NO-GO before the backfill runs at scale (`GO-1`)

**Eighteen items. Each one gets its OBSERVED VALUE written beside it — a
checkmark alone is not evidence.** This section IS the gate; there are no tests
for it.

> ⚠ **NOT RUN BY PR-E.** Every box below is open.

| # | Item | Observed value |
|---|---|---|
| 1 | JVN Phase 1 live **AND `alembic_version` verified moved** (the deploy-skip trap) | ☐ |
| 2 | The three-way parity command prints identical output (`SCHEMA-15` / `DEP-3`) | ☐ |
| 3 | ⚠ **`EnrichmentResultItem` round-trip proven — one hand-posted result AND one READ-BACK.** This is the only cross-repo proof that step 1 shipped rather than merged | ☐ |
| 4 | Enricher on v4 and `cli health \| jq .subcategory` present | ☐ |
| 5 | A `.backup` copy of the prod DB taken **today**, path recorded | ☐ |
| 6 | `P0-3` shipped **AND** `inbox.cleaned` below 50 for three consecutive ticks | ☐ |
| 7 | `backfill_scope` imported and `matched_local` substituted **everywhere** (it is `PARAM_BACKFILL_DENOMINATOR`, not 8,126) | ☐ |
| 8 | `P0-5`'s cost table filled in and the projected p95 fits the window | ☐ |
| 9 | ⚠ **The CATEGORY human gold pool is ≥ 50 and the gate ran WITHOUT `--allow-draft` and PASSED.** A green `--allow-draft` PASS is NOT a gate — it returns 0 on failure, and `regression_gate` refuses below `GATE_MIN_N=50` on `current.category.n`, which is **21 today** | ☐ |
| 10 | `ENR-LAT-1`'s two budgets met and its go/no-go recorded **PASSED** | ☐ |
| 11 | ⚠ **`BF-9`'s breaker constants set from the canary's MEASURED per-layer rate, not the 0.60 / 0.20 placeholders** | ☐ |
| 12 | ⚠ **`SCHEMA-14` is the write-back path and the legacy `/results` `sent_at` re-open must NOT fire** | ☐ |
| 13 | `ADM-6`'s denominator equals `PARAM_BACKFILL_DENOMINATOR` (or the tile and the backfill disagree about what 90% means) | ☐ |
| 14 | `BF-14` rehearsed on the `.backup` copy | ☐ |
| 15 | `ADM-15` rehearsed **dry-run** | ☐ |
| 16 | Both kill switches exercised | ☐ |
| 17 | ⚠ **hours-to-visible = `matched_local / rows_per_hour` (from `BF-16`), written next to the "overnight instead of a week" claim. IF IT IS NOT HOURS, THE CLAIM IS FALSE** | ☐ |
| 18 | ⚠ **The JVN-side rollback (`ADM-15`) EXISTS and has been dry-run** — `BF-14` alone leaves pushed rows live in Postgres | ☐ |

### 11.1 The three items most likely to be waved through

- **#9** — the gate cannot fire at n=21, and `--allow-draft` returning 0 makes a
  failure look like a pass. **D1 (`EV-2b`/`EV-9b`) is the only path to a real
  gate**; the admin correction loop is sustaining, not building.
- **#11** — the placeholders are *documented as placeholders* in code
  (`UNMEASURED — placeholder; set by ...`). Shipping them is a decision, not an
  accident, and it must be a deliberate one.
- **#18** — `BF-14` reads like a complete rollback and is not. Without `ADM-15`,
  every already-drained row stays wrong in production.
