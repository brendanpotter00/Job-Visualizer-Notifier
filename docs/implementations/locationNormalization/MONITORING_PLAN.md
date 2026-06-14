# Location Normalization — Production Monitoring Plan

> **For the implementing agent.** This is a self-contained build plan for an
> **on-demand, human/agent-run** production monitor for the two-tier location
> normalization pipeline. It is the companion to [`PLAN.md`](./PLAN.md) (the
> feature build) and [`EVAL_PLAN.md`](./EVAL_PLAN.md) (the Tier-2 *quality* guard).
> Read §1–§3 first, then build the two deliverables in §4–§7 in order. All paths
> are relative to the repo root `/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier`.
>
> **Decisions already made** (asked & answered 2026-06-13):
> - **Deliverable = a runbook doc + a Python check CLI** (not a bare doc, not a
>   scheduled agent).
> - **Cadence = on-demand only.** No cron, no `/schedule`, no `/loop`. It runs
>   when a human or an agent invokes it.
> - **On finding a bad normalization = report-only.** Write a dated findings doc;
>   a human decides whether to fold the case into the eval golden set or fix the
>   prompt. **Do NOT auto-append to `prod_sample.json`.**

---

## 1. Why this exists (and what "100% working" means)

The location-normalization feature (PR #145, branch `feature/location-normalization`)
adds a two-tier cascade that turns free-text `job_listings.location` into
deduplicated canonical locations:

- **Tier 1** — deterministic Postgres alias cache (`location_aliases` →
  `alias_locations` → `locations`). After warmup ~90%+ of incoming strings are
  zero-LLM-cost cache hits.
- **Tier 2** — Claude Haiku (`claude-haiku-4-5-20251001`) on cache misses,
  cached so the next occurrence is free.
- Runs on the Procrastinate worker, queue `normalize`. The job status machine is
  `job_listings.normalization_status` ∈ **`NULL`** (never attempted / no-key
  dormant) → **`'done'`** (Tier-1 or Tier-2 success, ≥1 `job_locations` row) →
  **`'failed'`** (terminal: blank location, low-confidence `< 0.5`, or
  permanently-unparseable after 5 LLM attempts).

Two existing safety nets already guard *code* and *quality*:

- The **unit suite** (`api/tests/test_*`) mocks the LLM — it catches code
  regressions but is blind to runtime/data health.
- The **Tier-2 quality eval** (`api/eval/`, see [`EVAL_PLAN.md`](./EVAL_PLAN.md))
  scores the real Haiku output against a golden set — it catches prompt/model
  drift, but it is a **local, pre-merge** check that never touches prod data.

**Neither watches production.** Nothing currently answers: *is the backlog
actually draining? is the worker normalizing? are the integrity invariants
holding on 48k+ live rows? did the alias cache develop the zero-children bug? did
the `2026-05-17` pool-exhaustion anti-pattern come back? is the model quietly
mis-normalizing real strings?* This monitor closes that gap.

**"100% working" in production** decomposes into six observable groups (§4):

| Group | The question it answers | Source |
|---|---|---|
| **A. Deployment/liveness** | Did the migration land and is the worker alive? | Postgres + heartbeat |
| **B. Backlog/throughput** | Is `NULL` draining and `done` climbing? | Postgres |
| **C. Integrity invariants** | Do the cross-table guarantees hold on live data? | Postgres |
| **D. Queue health** | Is the `normalize` queue draining, not piling failures? | Postgres (`procrastinate_jobs`) |
| **E. Log-stream signals** | Are the known error/warn lines firing? | Railway logs (MCP) |
| **F. Quality** | Is the model still normalizing real strings correctly? | Spot-check + Tier-2 eval |

The CLI (§5) covers the deterministic, SQL-derivable groups **A–D**. The runbook
(§6) layers **E** (Railway logs) and **F** (quality) on top — those need the
Railway MCP and the Anthropic key respectively, which a pure SQL CLI can't reach.

### Non-goals
- **Not a CI gate.** On-demand only. (The Tier-2 eval is also never-CI; same spirit.)
- **Not a writer.** Strictly read-only against prod. Never `INSERT/UPDATE/DELETE`,
  never `re-normalize-all`. (Remediation is a separate, human-initiated action.)
- **Not auto-remediation.** It reports; it does not fix, re-defer, or re-normalize.
- **Not a replacement for the Tier-2 eval.** It *invokes* the eval as its quality
  arm and *feeds* it candidate cases — it does not re-implement scoring.

---

## 2. Deployment status & verified prod facts (captured 2026-06-13, UTC 2026-06-14)

> Re-verify these at build time — prod moves. All captured read-only via
> `mcp__postgres-prod__query` and `mcp__railway-mcp-server__*`.

- **The feature is NOT in production yet.** PR #145 is **open**. Confirmed against
  prod: the `job_listings.normalization_status` column is **absent**, and none of
  `locations` / `location_aliases` / `alias_locations` / `job_locations` exist.
  → The monitor's first job is the **schema-presence gate** (§4-A): if the tables
  are absent it must report **NOT DEPLOYED (exit 2)**, never a false "0% healthy."
- **This monitor is written now, exercised after** (a) PR #145 merges + the
  Alembic migration applies on Railway boot, **and** (b) `ANTHROPIC_API_KEY` is
  set on the Railway service. Before the key is set the pipeline is *intentionally
  dormant* (all `NULL`); the monitor must not alarm on that (§4-B, key-state branch).
- **Railway** — project `onesecondswe` (`a69d8bf5-7235-4d56-afe3-c42f781ca437`);
  services `Job-Visualizer-Notifier` (`8239c326-b836-46c6-9181-cfb26b1ea0e6`) and
  `Postgres` (`e9fe1feb-83c3-422f-b034-f06308bbcb56`).
- **Corpus scale:** `job_listings` = **48,066 rows**; **4,418** have a blank/null
  location (**9.2%**). That 9.2% is the **legitimate `failed` floor** — those rows
  fail as `no-location` by design; the monitor must separate them from LLM-side
  failures (§4-B).
- **`id` global-uniqueness holds:** `count(distinct id) == count(*)` → **0
  collisions**. This is the load-bearing assumption behind `job_locations` being
  keyed by `job_listing_id` alone (no DB FK). Monitor it (§4-C) — a single
  collision silently corrupts the join.
- **Worker is alive:** `worker_heartbeats` MAX(at) was **3.4 min** old at capture
  (heartbeat fires every 5 min). This is the liveness signal the monitor reuses.
- **`procrastinate_jobs`** columns include `queue_name`, `task_name`, `status`
  (enum: `todo`/`doing`/`succeeded`/`failed`/`cancelled`/`aborting`/`aborted`),
  `attempts`, `scheduled_at`. Succeeded rows are **retained** (not pruned), so
  cumulative counts are queryable. The `normalize` queue is **not present yet**.
- **Pipeline constants** (cite, don't hardcode duplicates): `CONFIDENCE_FLOOR =
  0.5` (`tasks/normalize_location.py:43`); `normalize_location` retry
  `max_attempts = 5`; `scan_unnormalized` `SCAN_LIMIT = 100`, cron `*/5`, retry
  `max_attempts = 3`; per-task statement timeout `60_000 ms`.
- **Tier-2 eval baseline:** 100% gating accuracy (66/66) vs
  `claude-haiku-4-5-20251001`, `--repeat 3`, captured 2026-06-13, saved to
  `src/backend/api/eval/eval-baseline.json`.

---

## 3. Deliverables & file layout

```
src/backend/api/eval/
└── monitor_prod.py          # NEW: read-only prod-health CLI (groups A–D). exit 0/1/2.

docs/implementations/locationNormalization/
├── MONITORING_PLAN.md       # THIS FILE (the plan).
├── MONITORING.md            # NEW: the on-demand agent runbook (orchestrates CLI + logs + quality).
└── monitoring/
    └── findings/
        └── <YYYY-MM-DD>-prod-monitor.md   # NEW per run: report-only findings (template in §7).
```

Plus a unit test for the **pure** parts of the CLI (threshold/verdict logic, no DB):
```
src/backend/api/tests/test_monitor_prod.py   # NEW: pure-function tests only.
```

And doc pointers (§9): one line in `src/backend/api/eval/README.md`, a short
note in `src/backend/CLAUDE.md`, and a memory pointer.

> **Why `monitor_prod.py` lives in `api/eval/`:** it shares the eval package's
> "on-demand, never-CI, real-prod" character and its quality arm literally shells
> out to `eval_locations.py`. Keeping them adjacent makes the relationship obvious.
> It imports nothing from `eval_locations.py` at module load (the CLI must run with
> only a DB DSN, no `ANTHROPIC_API_KEY`); the eval is invoked as a subprocess in
> the runbook, not imported by the CLI.

---

## 4. The health signals (the heart of the monitor)

Each signal below is a **named check** with: the exact SQL (or MCP step), the
expected value, the threshold, and the severity. **The SQL is the single source of
truth** — `monitor_prod.py` runs it via `psycopg2`; the runbook runs the *same*
SQL via `mcp__postgres-prod__query` when no local DSN is configured. Keep them
byte-identical so the two paths can't drift.

Severity → exit-code mapping (see §5): `crit` or `warn` ⇒ **degraded (exit 1)**;
`info` is contextual and never fails the run; a missing schema or unreachable DB ⇒
**setup (exit 2)**.

### A. Deployment & liveness

**A1 — Schema-presence gate (gates everything; `crit`→exit 2 if absent).**
```sql
SELECT
  (SELECT count(*) FROM information_schema.columns
     WHERE table_name='job_listings' AND column_name='normalization_status') AS has_status_col,
  (SELECT count(*) FROM information_schema.tables
     WHERE table_name IN ('locations','location_aliases','alias_locations','job_locations')) AS n_loc_tables;
```
Expect `has_status_col = 1` and `n_loc_tables = 4`. Anything less ⇒ print
**`FEATURE NOT DEPLOYED`** and **exit 2** (it's a setup state, not a health
failure). All other checks are skipped.

**A2 — Worker liveness (`crit`).** The `normalize` queue runs on the shared
Procrastinate worker; a dead worker = zero normalization regardless of backlog.
```sql
SELECT extract(epoch FROM (now() - max(at)))/60.0 AS minutes_since_heartbeat
FROM worker_heartbeats;
```
Heartbeat fires every 5 min. **Threshold:** `> 10` min ⇒ `warn`; `> 30` min ⇒
`crit` (worker likely dead/crash-looping). (No timezone math — `now()` and `max(at)`
are both `timestamptz`; the `CLAUDE.md` Postgres-MCP timezone gotcha does **not**
apply here. Do not cast to `timestamp without time zone`.)

### B. Backlog & throughput

**B0 — Key-state branch (read FIRST, decides how to read B1).** The pipeline is
*designed* to sit fully `NULL` when `ANTHROPIC_API_KEY` is unset (dormant,
auto-recovers when set — `scan_unnormalized` skips deferring while the key is
absent). So a giant `NULL` backlog is a **failure only if the key is set**.
- The CLI **infers** dormancy: if `null_backlog` is large **and** `done = 0`
  **and** `failed_nonblank = 0`, emit **`info: looks dormant — is ANTHROPIC_API_KEY
  set on Railway?`** instead of `crit`.
- The runbook (§6) is **authoritative**: it greps Railway logs for
  `"ANTHROPIC_API_KEY unset"` (group E) to confirm true key-state before escalating.

**B1 — Status distribution + aged backlog (`info` counts; `crit` only when key is set).**
```sql
SELECT
  count(*) FILTER (WHERE normalization_status IS NULL)                                   AS null_backlog,
  count(*) FILTER (WHERE normalization_status IS NULL
                   AND first_seen_at < now() - interval '1 hour')                        AS null_aged_1h,
  count(*) FILTER (WHERE normalization_status='done')                                    AS done,
  count(*) FILTER (WHERE normalization_status='failed')                                  AS failed,
  count(*)                                                                                AS total
FROM job_listings;
```
- `null_aged_1h` is the real stall signal: a `NULL` row older than 1h has survived
  Unit-6 enqueue chaining **and** ≥12 `*/5` safety-net ticks **and** 5 retries.
- **During the initial drain (~1.5 days):** `null_aged_1h` is expected to be large
  but **strictly decreasing run-over-run** and `done` strictly increasing. The CLI
  is on-demand so use `--baseline` (§5) to diff against the previous run's saved
  JSON; "not decreasing" ⇒ `warn`.
- **Steady state (key set, drain complete):** `null_aged_1h` should be near 0.
  **Threshold:** with key set, `null_aged_1h > 500` ⇒ `warn`, `> 2000` ⇒ `crit`
  (calibrate on the first clean steady-state run; record the chosen numbers in the
  findings doc).

**B2 — Failed breakdown: legitimate vs LLM-side (`warn`/`crit`).** Split blank-location
failures (expected, ~9.2% ≈ 4,418 today) from the real quality signal.
```sql
SELECT
  count(*) FILTER (WHERE normalization_status='failed'
                   AND (location IS NULL OR btrim(location)=''))            AS failed_blank,
  count(*) FILTER (WHERE normalization_status='failed'
                   AND location IS NOT NULL AND btrim(location)<>'')        AS failed_nonblank,
  count(*) FILTER (WHERE normalization_status='done')                       AS done
FROM job_listings;
```
- `failed_blank` ≈ blank-location count → **sanity check**, not an alarm.
- `failed_nonblank` = low-confidence + permanently-unparseable → the real signal.
  **Threshold:** `failed_nonblank / NULLIF(done + failed_nonblank, 0)` ⇒ `> 2%`
  `warn`, `> 5%` `crit`. (At capture there are 0 normalized rows; this ratio is
  meaningful only once `done > 0`.)

### C. Integrity invariants (each breach = `warn` or `crit`; expected value is 0)

**C1 — `done` without locations (`crit`).** Every `'done'` job must have ≥1
`job_locations` row (the persist writer always writes ≥1). A violation = a job
marked done with no canonical location attached.
```sql
SELECT count(*) AS done_without_locations
FROM job_listings jl
WHERE jl.normalization_status='done'
  AND NOT EXISTS (SELECT 1 FROM job_locations l WHERE l.job_listing_id = jl.id);
```

**C2 — Alias without children (`warn`).** Every `location_aliases` row must map to
≥1 `alias_locations` child. A childless alias is the exact "zero-children" bug the
task logs as `"alias cache invariant violated"` — it forces a silent Tier-2
re-spend on a string that should be a cache hit.
```sql
SELECT count(*) AS aliases_without_children
FROM location_aliases a
WHERE NOT EXISTS (SELECT 1 FROM alias_locations al WHERE al.raw_text = a.raw_text);
```

**C3 — `id` collisions (`crit`).** The `job_locations` keying assumption. Verified
0 today; a single collision corrupts the join silently.
```sql
SELECT count(*) AS colliding_ids
FROM (SELECT id FROM job_listings GROUP BY id HAVING count(*) > 1) t;
```

**C4 — Orphan `job_locations` (`warn`).** Rows pointing at a `job_listing_id` that
no longer exists (the Pass-1 Critical fix was about stale `job_locations` on
re-normalization). `job_locations` has no DB FK to `job_listings`, so DB won't
prevent this.
```sql
SELECT count(*) AS orphan_job_locations
FROM job_locations l
WHERE NOT EXISTS (SELECT 1 FROM job_listings jl WHERE jl.id = l.job_listing_id);
```

**C5 — Remote-with-city (`warn`).** Schema invariant: `kind='remote'` ⇒ `city IS
NULL` (a remote may carry `region`/`country` scope, but never a city). This is the
schema fix from the pre-prod relaxation — a violation means the `CanonicalLocation`
validator drifted or a bad row got in.
```sql
SELECT count(*) AS remote_with_city FROM locations WHERE kind='remote' AND city IS NOT NULL;
```

**C6 — City-kind missing city (`warn`).**
```sql
SELECT count(*) AS city_kind_null_city FROM locations WHERE kind='city' AND city IS NULL;
```

**C7 — Low-confidence cached LLM alias (`warn`).** Low-confidence results (`< 0.5`)
are *not* supposed to be cached (the task marks the job `failed` and writes nothing).
An LLM-sourced alias with `confidence < 0.5` means a low-conf result leaked into the
cache. (Manual overrides may legitimately have `NULL` confidence — exclude them.)
```sql
SELECT count(*) AS lowconf_llm_aliases
FROM location_aliases
WHERE source='llm' AND confidence IS NOT NULL AND confidence < 0.5;
```

**C8 — Geo populated in v1 (`warn`).** Decision #7: `lat`/`lng` stay `NULL` until
the geocoding follow-up ships. A non-NULL is an unexpected write.
```sql
SELECT count(*) AS geo_populated FROM locations WHERE lat IS NOT NULL OR lng IS NOT NULL;
```

**C9 — Multiple primaries per job (`warn`, optional).** The persist writer marks
exactly the first location `is_primary`. >1 primary on a job = a write bug.
```sql
SELECT count(*) AS jobs_multi_primary
FROM (SELECT job_listing_id FROM job_locations WHERE is_primary
      GROUP BY job_listing_id HAVING count(*) > 1) t;
```

### D. Procrastinate `normalize` queue health (`info` counts; `warn`/`crit` on failures)

```sql
SELECT status, count(*) AS n
FROM procrastinate_jobs
WHERE queue_name='normalize'
GROUP BY status ORDER BY status;
```
- Persistent large `todo`/`doing` while the heartbeat is fresh (A2) ⇒ the worker
  isn't draining `normalize` ⇒ `warn`.
- `failed` jobs here ≈ the permanently-unparseable tail (the task re-raises after
  marking the row `failed` "to keep the job record honest") **plus** any
  fully-broken `scan_unnormalized` ticks. Cross-check against `failed_nonblank`
  (B2). **Threshold:** rising `failed` run-over-run (via `--baseline`) ⇒ `warn`.

Optional throughput slice (last hour of normalize successes, via events):
```sql
SELECT count(*) AS normalize_succeeded_last_hour
FROM procrastinate_events e
JOIN procrastinate_jobs j ON j.id = e.job_id
WHERE j.queue_name='normalize' AND e.type='succeeded'
  AND e.at > now() - interval '1 hour';
```
(Verify `procrastinate_events` column names — `job_id`, `type`, `at` — at build
time; Procrastinate's event schema is version-dependent. If the join is awkward,
drop this optional slice rather than guess.)

### E. Log-stream signals (Railway MCP — runbook only; the CLI can't read logs)

Run via `mcp__railway-mcp-server__get_logs` against service
`8239c326-b836-46c6-9181-cfb26b1ea0e6` (`Job-Visualizer-Notifier`), project
`a69d8bf5-7235-4d56-afe3-c42f781ca437`, `log_type='deploy'`, an appropriate
`since` window (e.g. `'1d'`), optionally `level='error'`/`'warn'`. Each pattern is
a literal line emitted by the code:

| Search pattern | Meaning | Severity |
|---|---|---|
| `ANTHROPIC_API_KEY unset` | Key not set. **Pre-key: expected.** **Post-key: the key was unset/not propagated.** Also the authoritative key-state probe for B0. | pre-key `info` / post-key `crit` |
| `permanently unparseable after` | Terminal-unparseable tail. A few are normal; a spike is a quality/parse problem. Cross-check B2 `failed_nonblank`. | `warn` (spike) |
| `low-confidence (max=` | Low-confidence drops. Elevated rate = model returning vague output on real strings. | `warn` (elevated) |
| `alias cache invariant violated` | The C2 zero-children bug at runtime (silent re-spend). | `warn` |
| `ALL` + `defer(s) FAILED` | `scan_unnormalized` made zero progress this tick — the safety-net of last resort is broken. | `crit` |
| `pool` / `too many clients` / `connection` errors | The `2026-05-17` pool-exhaustion anti-pattern returned (a connection held across the LLM await). | `crit` |
| `Tier-1 cache HIT` vs `normalized via Tier-2` | Cache-hit-rate proxy: count HIT vs Tier-2 over the window; warmed-up steady state should trend **> ~90% HIT**. | `info` (warn if < ~70% sustained post-warmup) |

Also confirm worker boot health: search deploy logs around the latest deploy for
the worker registering the `normalize` queue / `normalize_location` +
`scan_unnormalized` tasks, with no crash-loop.

### F. Quality (runbook only — needs the Anthropic key)

**F1 — Live spot-check (read-only SQL via MCP).** Eyeball recent normalizations
for systematic errors (reversed order, garbled, wrong country, remote-as-city):
```sql
SELECT jl.id, jl.location AS raw,
       l.canonical_name, l.kind, l.city, l.region, l.country, l.remote_scope,
       jloc.is_primary
FROM job_listings jl
JOIN job_locations jloc ON jloc.job_listing_id = jl.id
JOIN locations l        ON l.id = jloc.normalized_location_id
WHERE jl.normalization_status='done'
ORDER BY jl.last_seen_at DESC
LIMIT 100;
```
Any suspect `raw → canonical` pair is recorded in the findings doc as a
**candidate eval case** (report-only — §7). Do **not** edit `prod_sample.json`.

**F2 — Run the Tier-2 eval (authoritative quality check).** From repo root, with
`ANTHROPIC_API_KEY` in `.env.local`:
```bash
PYTHONPATH=. python -m src.backend.api.eval.eval_locations \
  --set all --repeat 3 --baseline src/backend/api/eval/eval-baseline.json
```
Exit 0 = at baseline (no gating regressions). Exit 1 = a regression → the model
drifted; capture in the findings doc and flag for prompt/model review. This is the
same harness `EVAL_PLAN.md` describes — the monitor *invokes* it, never duplicates it.

---

## 5. The CLI — `src/backend/api/eval/monitor_prod.py`

A read-only, DB-only health checker for groups **A–D**. Pure-SQL so it's
deterministic and scriptable; groups E/F are the runbook's job.

**Access / prerequisites:**
- Reads **`MONITOR_DATABASE_URL`** (a *read-only* prod DSN) from the environment.
  If unset or unreachable ⇒ **exit 2** with a clear message and a pointer:
  *"Get the prod connection string from Railway → onesecondswe → Postgres →
  Connect (use the read-only/public URL); never a write role. Do NOT reuse the
  local dev `DATABASE_URL` (that's localhost)."* Use a **distinct** env var
  (not `DATABASE_URL`) so the CLI can never accidentally hit dev.
- Belt-and-suspenders read-only: open the connection and immediately
  `SET default_transaction_read_only = on; SET statement_timeout = '30s';`. The CLI
  must contain **zero** `INSERT/UPDATE/DELETE/ALTER` — enforce in code review and a test.
- No `ANTHROPIC_API_KEY` needed (the CLI never calls the model).

**Structure** (illustrative — keep it small and obvious):
```python
# monitor_prod.py
@dataclass(frozen=True)
class Check:
    id: str            # "A2_worker_liveness"
    title: str
    category: str      # "A"|"B"|"C"|"D"
    sql: str
    severity: str      # default severity if the evaluate() fn returns a breach
    evaluate: Callable[[list[dict]], tuple[str, object, str]]
        # returns (status, value, detail); status in {"ok","info","warn","crit"}

CHECKS: list[Check] = [ ... ]   # exactly the §4-A..D queries, in order

def run(dsn: str, baseline: dict | None) -> Report: ...
def render_table(report) -> str: ...      # readable per-check table
def overall_exit(report) -> int: ...      # 2 if schema gate failed; 1 if any warn/crit; else 0
```

**Flags:**
- `--json PATH` — write the full structured report (the §7 findings doc embeds it;
  also the `--baseline` target for the next run).
- `--baseline PATH` — load a prior run's JSON; enable the run-over-run deltas that
  the on-demand cadence needs: B1 `null_aged_1h` **must be decreasing** during
  drain, D `failed` **must not be rising**. A bad delta ⇒ `warn`.
- `--window-hours N` (default 1) — window for the aged-backlog / throughput slices.
- `--verbose` — print every check, not just non-`ok` ones.

**Exit codes** (match the runbook + findings verdict):
- **`0` healthy** — schema present, no `warn`/`crit`.
- **`1` degraded** — schema present, ≥1 `warn` or `crit` (the table shows which).
- **`2` setup** — `MONITOR_DATABASE_URL` unset/unreachable, **or** the A1 schema
  gate failed (feature not deployed). Never a misleading "0% healthy."

**Output:** a per-check table (id · category · value · threshold · status), then a
summary line (`ok/info/warn/crit` counts), then the overall verdict + exit code.
The dormancy note (B0) prints as `info`, not a failure.

**Unit test** (`api/tests/test_monitor_prod.py`) — **pure functions only**, no DB,
no network: feed canned `evaluate()` inputs and assert status; assert
`overall_exit()` mapping (schema-gate→2, any warn/crit→1, all ok→0); assert the
dormancy heuristic (large null + 0 done + 0 failed_nonblank → `info`, not `crit`).
This is the part that runs in normal CI; the live run never does.

---

## 6. The runbook — `docs/implementations/locationNormalization/MONITORING.md`

The on-demand orchestration an agent (or you) follows. Structure it as numbered
steps so an agent can execute top-to-bottom:

1. **Scope & access.** State it's read-only/on-demand; list the IDs (project
   `a69d8bf5…`, service `8239c326…`), the MCPs used (`mcp__postgres-prod__query`,
   `mcp__railway-mcp-server__get_logs`), and that quality (F2) needs
   `ANTHROPIC_API_KEY` locally.
2. **Run the CLI (groups A–D).**
   `MONITOR_DATABASE_URL=… python -m src.backend.api.eval.monitor_prod --baseline <prev>.json --json <today>.json`.
   If no local DSN, run each §4-A..D query via `mcp__postgres-prod__query` and apply
   the same thresholds by hand. **Stop early on exit 2** (NOT DEPLOYED / no DSN) —
   report and end.
3. **Key-state (group E, the B0 confirmation).** `get_logs` search
   `"ANTHROPIC_API_KEY unset"` over the window. Decide: pre-key (backlog dormancy
   is expected) vs post-key (backlog is a real `crit`).
4. **Log-stream sweep (group E).** Run each §4-E search; record counts and any
   `crit` hits (all-defers-failed, pool exhaustion). Note the Tier-1-HIT vs Tier-2
   ratio.
5. **Quality (group F).** Run the F1 spot-check SQL; eyeball the 100 rows; list
   suspect pairs. Then run the F2 Tier-2 eval; record pass/fail vs baseline.
6. **Write the findings doc (§7).** Always — even when healthy (it's the audit
   trail and the next run's `--baseline`/comparison point).
7. **Verdict.** HEALTHY / DEGRADED / SETUP, plus the recommended next actions
   (which are *suggestions*, per the report-only decision — never auto-applied).

The runbook must restate the **report-only** rule prominently: it never edits
`prod_sample.json`, never runs `re-normalize-all`, never writes to prod.

### First-run acceptance — "verify it works 100%"

A dedicated section in `MONITORING.md`, run **the first time after merge +
key-set**. The pipeline is verified end-to-end in prod when **all** hold:

1. **A1** schema gate passes (4 tables + the column).
2. **A2** heartbeat fresh (< 10 min).
3. **E** logs: worker booted registering the `normalize` queue; **no**
   `"ANTHROPIC_API_KEY unset"` after the key was set; `scan_unnormalized` ticking
   (`deferred N / … unnormalized`).
4. **B1** backlog draining: `null_aged_1h` strictly lower across two runs ~10 min
   apart; `done` climbing; `job_locations` populating.
5. **C1–C9** every integrity invariant = 0.
6. **B2** `failed_blank ≈ 9.2%` of corpus; `failed_nonblank` ratio low.
7. **D** `normalize` queue: `succeeded` climbing, `todo`/`doing` draining,
   `failed` small.
8. **F2** Tier-2 eval passes at baseline (66/66).
9. **F1** spot-check of 100 `done` jobs shows no systematic mis-normalization.

If all pass, record the snapshot JSON as the **steady-state reference** (it becomes
the `--baseline` for routine runs) and note "prod pipeline verified 100%" in the
findings doc.

---

## 7. The findings doc (report-only) + the eval feedback loop

One file per run: `docs/implementations/locationNormalization/monitoring/findings/<YYYY-MM-DD>-prod-monitor.md`.
**Report-only** — it records, it never changes the eval or prod. Template:

```markdown
# Location Normalization — Prod Monitor Findings — <YYYY-MM-DD> (UTC <…>)

- **Verdict:** HEALTHY | DEGRADED | SETUP
- **Run by:** <human/agent> · **Deployment:** <railway deployment id / commit>
- **Key-state:** SET | UNSET (per group-E log probe)

## A–D — CLI health table
<paste monitor_prod.py table / JSON summary; note any warn/crit and the value vs threshold>

## E — Log-stream
<per-pattern counts; Tier-1-HIT vs Tier-2 ratio; any crit hits>

## F — Quality
- Tier-2 eval: PASS at baseline (66/66) | REGRESSION (list cases)
- Spot-check suspects (candidate eval cases — human decides):
  | raw | produced canonical | looks-wrong-because | suggested expected | gating? |
  |-----|--------------------|---------------------|--------------------|---------|
  | …   | …                  | …                   | …                  | …       |

## Suggested follow-ups (NOT auto-applied)
- [ ] Add <raw strings> to `src/backend/api/eval/prod_sample.json` and hand-label
      (per EVAL_PLAN.md §3c), then re-run the Tier-2 eval.
- [ ] <prompt/model/integrity action if a crit fired>
```

**The feedback loop (deliberately manual, per the decision):** suspect strings from
F1 and any F2 regressions are *listed* under "Suggested follow-ups" as candidate
`prod_sample.json` additions — with a hand-label TODO, not a guessed label (labeling
by the current model bakes in today's mistakes; see `EVAL_PLAN.md` §3c). A human
reviews, adds the good ones to the golden set, re-baselines the eval, and (if a
`crit` integrity bug fired) files the fix. The monitor's job ends at the report.

---

## 8. Threshold reference (calibrate on the first clean steady-state run)

| Check | `info` | `warn` | `crit` |
|---|---|---|---|
| A2 heartbeat age | < 10 min | > 10 min | > 30 min |
| B1 `null_aged_1h` (key set, steady) | < 500 | > 500 **or** not decreasing during drain | > 2000 |
| B2 `failed_nonblank` ratio | < 2% | 2–5% | > 5% |
| C1 done-without-locations | — | — | > 0 |
| C2 alias-without-children | — | > 0 | — |
| C3 `id` collisions | — | — | > 0 |
| C4 orphan job_locations | — | > 0 | — |
| C5 remote-with-city | — | > 0 | — |
| C6 city-kind-null-city | — | > 0 | — |
| C7 low-conf cached alias | — | > 0 | — |
| C8 geo populated (v1) | — | > 0 | — |
| C9 multi-primary | — | > 0 | — |
| D normalize `todo`/`doing` (heartbeat fresh) | small | large/growing | — |
| D normalize `failed` | flat | rising (vs baseline) | — |
| E all-defers-failed / pool-exhaustion | absent | — | any |
| E post-key `ANTHROPIC_API_KEY unset` | absent | — | any |
| E Tier-1 HIT ratio (post-warmup) | > 90% | < 70% sustained | — |
| F2 Tier-2 eval | at baseline | — | gating regression |

These start as **proposals** — the first steady-state run sets the real numbers
(especially B1 and the D queue sizes). Record the chosen values in that run's
findings doc and in this table.

---

## 9. Doc updates & memory (small, do as part of the deliverable)

1. **`src/backend/api/eval/README.md`** — one line under a new "Prod monitor"
   note: points at `monitor_prod.py` + `../../../../docs/implementations/locationNormalization/MONITORING.md`,
   states it's read-only/on-demand and needs `MONITOR_DATABASE_URL` (DB) +
   `ANTHROPIC_API_KEY` (for the F2 eval arm). Link, don't duplicate.
2. **`src/backend/CLAUDE.md`** — extend the existing "Evals" subsection with a
   single sentence: a read-only prod monitor lives at `api/eval/monitor_prod.py`;
   run it on-demand to verify the live normalization pipeline; full runbook in the
   locationNormalization docs.
3. **Memory** (`type: project`) — a one-line pointer that an on-demand prod monitor
   for location normalization exists (CLI + runbook), it's read-only/never-CI,
   and where to find it. Add the matching `MEMORY.md` line. Relates to
   `[[project_location_eval_harness]]`.

---

## 10. Acceptance criteria (definition of done)

- [ ] `src/backend/api/eval/monitor_prod.py` runs read-only against
      `MONITOR_DATABASE_URL`, implements exactly the §4-A..D checks, prints the
      §5 table, and returns exit `0`/`1`/`2` per §5.
- [ ] Against **current** prod (feature not deployed) the CLI prints
      **`FEATURE NOT DEPLOYED`** and exits **2** — verify this now (it's the A1
      gate working).
- [ ] CLI is provably read-only (no write SQL; opens read-only txn) and needs no
      `ANTHROPIC_API_KEY`.
- [ ] `api/tests/test_monitor_prod.py` covers the pure threshold/verdict/dormancy
      logic and passes in normal `pytest` (no DB/network).
- [ ] `MONITORING.md` runbook exists with the §6 steps, the first-run "verify 100%"
      acceptance section, and the prominent **report-only / read-only** rule.
- [ ] The §7 findings template + `monitoring/findings/` location are documented;
      the eval feedback loop is **manual** (no auto-append to `prod_sample.json`).
- [ ] Doc pointers (§9) added; memory pointer written.
- [ ] **No production code path changed** — this is additive, read-only tooling only.

---

## 11. File reference index

| Path | Role for this plan |
|---|---|
| `src/backend/api/db_models.py` | Schema of the 4 location tables + `normalization_status`; the `job_locations` no-FK / `id`-unique note (C3) |
| `src/backend/api/tasks/normalize_location.py` | Status machine, `CONFIDENCE_FLOOR=0.5`, retry=5, the `failed`/terminal-unparseable paths, no-key leave-NULL |
| `src/backend/api/tasks/scan_unnormalized.py` | `*/5` safety-net, `SCAN_LIMIT=100`, skip-when-no-key, the all-defers-failed `@level:error` line (E) |
| `src/backend/api/services/location_normalization.py` | Tier-1 cache, persist writer (≥1 location per done → C1; first=primary → C9), alias invariant (C2) |
| `src/backend/api/services/llm_client.py` | Tier-2 Haiku; `CanonicalLocation` `kind`↔scope invariants (C5/C6); model pin |
| `src/backend/api/eval/` (`eval_locations.py`, `README.md`, `eval-baseline.json`) | The Tier-2 quality eval the monitor invokes (F2) and feeds (§7) |
| `docs/implementations/locationNormalization/PLAN.md` | Feature plan + Decisions (#3 conn discipline, #5 keying, #6 remote_scope uniqueness, #7 NULL geo, #10 manual-wins) |
| `docs/implementations/locationNormalization/EVAL_PLAN.md` | How to extend the golden set (§3c relabel rule) for the feedback loop |
| Railway: project `a69d8bf5-7235-4d56-afe3-c42f781ca437`, service `8239c326-b836-46c6-9181-cfb26b1ea0e6` | Log-stream group E target |
