# Location-normalization prod monitor (runbook)

An **on-demand, read-only** health check for the live two-tier location-normalization
pipeline. It answers: *is the backlog draining? is the worker normalizing? do the
integrity invariants hold on the live corpus? is the alias cache healthy? is the
model still normalizing real strings correctly?*

Two existing nets guard *code* and *quality* but **neither watches production**: the
unit suite (`api/tests/test_*`) mocks the LLM, and the Tier-2 quality eval
(`api/eval/`, see `api/eval/README.md`) is a local pre-merge check that never touches
prod. This monitor closes that gap.

> **READ-ONLY / REPORT-ONLY — the governing rule.** This procedure never writes prod.
> No `INSERT/UPDATE/DELETE`, no `re-normalize-all`, no editing `prod_sample.json`. When
> it finds something, it writes a dated **findings doc** and a human decides what to do
> (fold a case into the eval golden set, fix a prompt, file an integrity bug).
> Remediation is always a separate, human-initiated action.

The deterministic, SQL-derivable groups **A–D** are automated by the CLI
(`api/eval/monitor_prod.py`). The log-stream (**E**) and quality (**F**) arms need
Railway logs and the Anthropic key, which a pure-SQL CLI can't reach, so they're driven
from this runbook.

---

## 1. What "100% working" means

| Group | Question | Source | Covered by |
|---|---|---|---|
| **A. Deployment/liveness** | Did the migration land and is the worker alive? | Postgres + heartbeat | CLI |
| **B. Backlog/throughput** | Is `NULL` draining and `done` climbing? | Postgres | CLI |
| **C. Integrity invariants** | Do the cross-table guarantees hold on live data? | Postgres | CLI |
| **D. Queue health** | Is the `normalize` queue draining, not piling failures? | `procrastinate_jobs` | CLI |
| **E. Log-stream signals** | Are known error/warn lines firing? | Railway logs (MCP) | Runbook |
| **F. Quality** | Is the model still normalizing real strings correctly? | Spot-check + Tier-2 eval | Runbook |

Pipeline recap: **Tier 1** is a deterministic Postgres alias cache
(`location_aliases` → `alias_locations` → `locations`); **Tier 2** is Claude Haiku
(`claude-haiku-4-5-20251001`) on cache misses, cached so the next occurrence is free.
It runs on the Procrastinate worker, queue `normalize`. Status machine on
`job_listings.normalization_status`: **`NULL`** (never attempted / no-key dormant) →
**`'done'`** (≥1 `job_locations` row) → **`'failed'`** (blank location, low-confidence
`< 0.5`, or permanently unparseable after 5 attempts).

---

## 2. Scope & access

- **On-demand only.** No cron, no `/schedule`, no `/loop`. Run it when a human or agent
  invokes it.
- **Railway:** project `onesecondswe` (`a69d8bf5-7235-4d56-afe3-c42f781ca437`);
  services `Job-Visualizer-Notifier` (`8239c326-b836-46c6-9181-cfb26b1ea0e6`) and
  `Postgres` (`e9fe1feb-83c3-422f-b034-f06308bbcb56`).
- **Tools:** the CLI (read-only DSN), `mcp__postgres-prod__query` (read-only SQL when
  no local DSN), `mcp__railway-mcp-server__get_logs` (group E). The F2 eval arm needs
  `ANTHROPIC_API_KEY` locally.
- **CLI DSN:** the CLI reads **`MONITOR_DATABASE_URL`** — a *distinct* env var from
  `DATABASE_URL` on purpose, so it can never accidentally hit local dev. Get the
  read-only/public URL from Railway → onesecondswe → Postgres → Connect (never a write
  role).

---

## 3. The procedure (top to bottom)

### Step 1 — Run the CLI (groups A–D)

```bash
# from the repo ROOT
MONITOR_DATABASE_URL='postgresql://readonly:...@host:port/db' PYTHONPATH=. \
  python -m src.backend.api.eval.monitor_prod \
    --baseline docs/implementations/locationNormalization/monitoring/findings/<prev>.json \
    --json     docs/implementations/locationNormalization/monitoring/findings/<today>.json \
    --verbose
```

Exit codes: **0** healthy · **1** degraded (≥1 warn/crit) · **2** setup
(`MONITOR_DATABASE_URL` unset/unreachable, or the **A1 schema gate failed** =
`FEATURE NOT DEPLOYED`). **Stop early on exit 2** — report and end.

If you have no local DSN, run the same A–D queries via `mcp__postgres-prod__query`
(they're embedded in `api/eval/monitor_prod.py` as the `Check.sql` strings) and apply
the §6 thresholds by hand.

- `--baseline` enables the run-over-run deltas the on-demand cadence needs: B1
  `null_aged` **must be decreasing** during drain; D `failed` **must not be rising**.
- `--json` writes today's snapshot — it becomes the next run's `--baseline`.

### Step 2 — Key-state (the B0 confirmation, group E)

The pipeline is *designed* to sit fully `NULL` when `ANTHROPIC_API_KEY` is unset
(dormant; the safety-net skips deferring, so it auto-recovers when the key is set). A
giant `NULL` backlog is a **failure only if the key is set**. The CLI *infers* dormancy
(large `null_backlog`, `done=0`, `failed_nonblank=0` → an `info` note); the **logs are
authoritative**:

```
mcp__railway-mcp-server__get_logs  service=8239c326-...  log_type=deploy  since=1d
  search="ANTHROPIC_API_KEY unset"
```

Decide: **pre-key** (backlog dormancy is expected — `info`) vs **post-key** (a `NULL`
backlog is a real problem, and a post-key `"ANTHROPIC_API_KEY unset"` line is `crit` —
the key was unset/not propagated).

### Step 3 — Log-stream sweep (group E)

Run each search against the same service/window. Each pattern is a literal line the code
emits:

| Search pattern | Meaning | Severity |
|---|---|---|
| `ANTHROPIC_API_KEY unset` | `normalize_location.py:138` + `scan_unnormalized.py:55`. Pre-key: expected. Post-key: key lost. | pre `info` / post `crit` |
| `permanently unparseable after` | `normalize_location.py:161` — terminal-unparseable tail. A few are normal; a spike is a parse/quality problem (cross-check B2 `failed_nonblank`). | `warn` (spike) |
| `low-confidence (max=` | `normalize_location.py:178` — low-confidence drops. Elevated rate = model returning vague output on real strings. | `warn` (elevated) |
| `alias cache invariant violated` | `normalize_location.py:110` — the C2 zero-children bug at runtime (silent Tier-2 re-spend). | `warn` |
| `ALL` + `defer(s) FAILED` | `scan_unnormalized.py:108` — `scan_unnormalized` made zero progress this tick (safety-net of last resort broken). | `crit` |
| `pool` / `too many clients` / `connection` errors | the 2026-05-17 pool-exhaustion anti-pattern returned (a connection held across the LLM await). | `crit` |
| `Tier-1 cache HIT` vs `normalized via Tier-2` | `normalize_location.py:117` / `:188` — cache-hit-rate proxy: count HIT vs Tier-2 over the window. | `info` (warn if < ~70% sustained post-warmup) |

Also confirm worker boot health: around the latest deploy, the worker should register
the `normalize` queue / `normalize_location` + `scan_unnormalized` tasks with no
crash-loop.

### Step 4 — Quality (group F)

**F1 — Live spot-check (read-only SQL via MCP).** Eyeball recent normalizations for
systematic errors (reversed order, garbled, wrong country, remote-as-city):

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

Record any suspect `raw → canonical` pair in the findings doc as a **candidate eval
case** (report-only — do **not** edit `prod_sample.json`).

**F2 — Run the Tier-2 eval (authoritative quality check).** From the repo root, with
`ANTHROPIC_API_KEY` in `.env.local`:

```bash
PYTHONPATH=. python -m src.backend.api.eval.eval_locations \
  --set all --repeat 3 --baseline src/backend/api/eval/eval-baseline.json
```

Exit 0 = at baseline (no gating regressions). Exit 1 = a regression → the model drifted;
capture it in the findings doc and flag for prompt/model review. The monitor *invokes*
this harness; it never duplicates it. (See `api/eval/README.md`.)

### Step 5 — Write the findings doc

**Always**, even when healthy — it's the audit trail and the next run's comparison
point. One file per run under
`docs/implementations/locationNormalization/monitoring/findings/<YYYY-MM-DD>-prod-monitor.md`,
using the template in §5. The committed `--json` snapshot lives beside it. (See
`…/findings/2026-06-14-prod-monitor.md` for the first post-merge run.)

### Step 6 — Verdict

**HEALTHY / DEGRADED / SETUP**, plus recommended next actions — which are *suggestions*
(report-only), never auto-applied.

---

## 4. First-run acceptance — "verify it works 100%"

Run this the first time after merge + `ANTHROPIC_API_KEY` is set on Railway. The
pipeline is verified end-to-end in prod when **all** hold:

1. **A1** schema gate passes (4 tables + the column).
2. **A2** heartbeat fresh (< 10 min).
3. **E** logs: worker booted registering the `normalize` queue; **no**
   `"ANTHROPIC_API_KEY unset"` after the key was set; `scan_unnormalized` ticking
   (`deferred N / … unnormalized`).
4. **B1** backlog draining: `null_aged` strictly lower across two runs ~10 min apart;
   `done` climbing; `job_locations` populating.
5. **C1–C9** every integrity invariant = 0.
6. **B2** `failed_blank ≈ 9.2%` of corpus (the blank-location floor); `failed_nonblank`
   ratio low.
7. **D** `normalize` queue: `succeeded` climbing, `todo`/`doing` draining, `failed`
   small.
8. **F2** Tier-2 eval passes at baseline (66/66).
9. **F1** spot-check of 100 `done` jobs shows no systematic mis-normalization.

If all pass, record the snapshot JSON as the **steady-state reference** (it becomes the
`--baseline` for routine runs) and note "prod pipeline verified 100%" in the findings
doc.

> **Initial-drain caveat.** During the first ~1.5 days the corpus drains (`SCAN_LIMIT=100`
> × 12 ticks/hr). `null_aged` is *expected* to be large then — so a no-baseline run
> reports **DEGRADED** purely on B1 even though everything else is green. That is correct
> behavior: judge B1 by the run-over-run delta (`--baseline`), not by the absolute number,
> until the drain completes.

---

## 5. Findings template (report-only)

```markdown
# Location Normalization — Prod Monitor Findings — <YYYY-MM-DD> (UTC <…>)

- **Verdict:** HEALTHY | DEGRADED | SETUP
- **Run by:** <human/agent> · **Deployment:** <railway deployment id / commit>
- **Key-state:** SET | UNSET (per group-E log probe)

## A–D — CLI health table
<paste monitor_prod.py table / JSON summary; note any warn/crit and value vs threshold>

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

**The feedback loop is deliberately manual:** suspect strings from F1 and any F2
regressions are *listed* as candidate `prod_sample.json` additions with a hand-label
TODO — never a guessed label (labeling by the current model bakes in today's mistakes;
see `api/eval/README.md` § Refreshing). A human reviews, adds the good ones, re-baselines
the eval, and files any integrity fix. The monitor's job ends at the report.

---

## 6. Threshold reference (calibrate on the first clean steady-state run)

| Check | `info` | `warn` | `crit` |
|---|---|---|---|
| A2 heartbeat age | < 10 min | > 10 min | > 30 min |
| B1 `null_aged` (key set, steady) | < 500 | > 500 **or** not decreasing during drain | > 2000 |
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

These start as **proposals**; the first steady-state run sets the real numbers
(especially B1 and the D queue sizes). Record the chosen values in that run's findings doc.

> **Why C3 is load-bearing.** `job_listings`' PK is the composite `(source_id, id)` —
> there is **no** unique constraint on `id` alone, and `job_locations` keys on
> `job_listing_id` with **no DB FK** (integrity is enforced in the app layer). The whole
> feature relies on `id` being globally unique *in practice* (verified: 0 collisions). If
> **C3 ever fires, treat C1/C4/F1 as unreliable** until it's resolved — a single
> collision silently corrupts the join.

---

## 7. Source map

| Path | Role |
|---|---|
| `src/backend/api/eval/monitor_prod.py` | The CLI (groups A–D); the `Check.sql` strings are the single source of truth for the SQL. |
| `src/backend/api/tests/test_monitor_prod.py` | Pure-function tests (thresholds/verdict/dormancy/read-only guard) — runs in normal CI. |
| `src/backend/api/eval/` (`eval_locations.py`, `README.md`, `eval-baseline.json`) | The Tier-2 quality eval the monitor invokes (F2) and feeds (§5). |
| `src/backend/api/tasks/normalize_location.py` | Status machine, `CONFIDENCE_FLOOR=0.5` (`:43`), `_RETRY_MAX_ATTEMPTS=5` (`:49`), the group-E log lines. |
| `src/backend/api/tasks/scan_unnormalized.py` | `*/5` safety-net, `SCAN_LIMIT=100` (`:40`), skip-when-no-key, the all-defers-failed line (`:108`). |
| `src/backend/api/db_models.py` | Schema of the 4 location tables + `normalization_status`; the `job_locations` no-FK / `id`-unique note (C3). |
| `docs/implementations/locationNormalization/MONITORING_PLAN.md` | The original build plan this runbook + CLI were built from (historical). |
| Railway: project `a69d8bf5-…`, service `8239c326-…` | Log-stream group-E target. |
