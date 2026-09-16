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
