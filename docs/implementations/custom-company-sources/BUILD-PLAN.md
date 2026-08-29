# Custom Company Sources — build plan

Executable plan for an implementing agent. **Read `OVERVIEW.md` first** for the architecture and why. This file is the phase-by-phase how. Owner approved the OVERVIEW shape on 2026-08-09.

> **This plan is written to survive a context compaction.** If you are a fresh agent picking this up: everything you need is in this file plus `OVERVIEW.md`. Do not trust conversation history you don't have; re-verify any `file:line` against current code before relying on it (the repo moves).

---

## 0. Start clean — new branch, pull over only what's proven

The owner's instruction: **scrap PR #243 and its branch. Start a new branch off `origin/main` and cherry-pick over only the parts that are done and verified.** Rationale: retrofitting the old 5-tier plan into the new gated-script model would leave dead code and broken logic. Cleaner to restart.

**Do this first:**

1. `git fetch origin`, branch `feat/custom-companies` off **`origin/main`** (not off `feat/custom-company-sources-spike`). Branching off main is deliberate — main already carries the recalibrated safety guard (`SCRAPER_GUARD_MIN_RATIO = 0.85`, `evaluate_safety_guard` / `resolve_safety_guard`, `RELEASED_RUN_MISS_THRESHOLD`, `scrape_runs.guard_reason`) that the spike worktree lacks.
2. **Pull over from the `feat/custom-company-sources-spike` branch (worktree 2), these only** — all reviewed/tested, keep them:
   - `src/backend/api/services/url_guard.py` + `test_url_guard.py` (SSRF boundary, 336-test suite, two adversarial passes)
   - `src/backend/api/services/ats_link_resolver.py` + `test_ats_link_resolver.py` (L0 resolver; includes the Greenhouse **API-host** fix `boards-api.greenhouse.io/v1/boards/<token>` — keep it)
   - `src/backend/api/services/ats_discovery.py` + `test_ats_discovery.py` (L1/L2 + `probe_candidate`)
   - `POST /api/companies/resolve` in `routers/companies.py`, its 4 Pydantic models, the `custom_company_sources_enabled` + `resolve_rate_limit_*` config, and the `enforce_resolve_rate_limit` reuse
   - `vercel.json`: the `/api/companies/:path(.*)` rewrite (without it the endpoint 404s in prod)
   - **The entire frontend resolve slice** (built + browser-verified against Intel/Cisco/Duolingo): `config/customCompanies.ts`, `features/userCompanies/userCompaniesApi.ts` + `resolveErrors.ts`, `components/my-companies/*`, `pages/MyCompaniesPage/*`, the `NavIconName` change in `config/routes.ts` + `NavigationDrawer.tsx`, store/testUtils registration, and the `/my-companies` SPA rewrite. All its tests.
   - The docs: this directory (`OVERVIEW.md`, `BUILD-PLAN.md`), `docs/spikes/2026-08-browser-agent-discovery.md`, and `docs/implementations/custom-company-sources/PLAN.md` (the locked owner decisions D1–D12 still hold).
3. **Do not pull over** any of the old PR's handoff docs or the 5-tier scaffolding (there wasn't much backend beyond the above; the recipe-runtime tier, separate Railway service, DNS-pinning hack, guess-and-verify L3 were never built — good).
4. Verify the pulled-over backend still passes (`cd src/backend && pytest api/tests/test_url_guard.py api/tests/test_ats_link_resolver.py api/tests/test_ats_discovery.py api/tests/test_companies_resolve_endpoint.py -q` against an isolated test DB — see §0.5) and the frontend suite is green (nvm Node 22.14.0, `npm test`).

### 0.2 How to execute each phase (owner-mandated agent loop)

Do **not** hand-code phases yourself. Orchestrate; review; verify. Per phase:

1. **Implement** with a fresh **opus-level subagent**, given this file + `OVERVIEW.md` + the phase's §7-style spec. One phase per subagent so its context stays clean.
2. **Adversarially review** the result with a *separate* opus subagent whose instructions are to break it — check it against the live repo code (not assertions), specifically the closure-safety invariants, the three visibility leaks, the source_id isolation, and the "UNVERIFIED never closes" rule. Feed findings back to a fix subagent; loop until the review is clean.
3. **Verify end-to-end and locally** — run the phase's acceptance test (§7.3 for Phase 1) in a real browser against the running local stack, with two real accounts. Do not declare done on unit tests alone; the review found that fixtures built from reading source can mask a real runtime mismatch.
4. **You (the orchestrator) review, you do not implement.** Relay only what matters back to the owner; keep the subagent file-dumps out of the summary.

Verify claims against code before writing them down — this plan already had to retract one subagent assertion (a "0.85 guard" that was on `main`, not the worktree) that was recorded as fact without checking. Don't repeat it.

### 0.1 Ground rules (unchanged from the owner's standing constraints)

1. **Vertical slices.** Each phase ships backend + frontend together and is testable in a browser. Never all-backend-then-all-frontend. After each phase, get the local stack running and hand it to the owner to test end-to-end.
2. **Only a VERIFIED run may close a job.** Everything else upserts and stops. In Phase 1 there is no oracle yet, so *everything is UNVERIFIED and nothing ever closes* — that is the safe default, not a bug.
3. **First harvest of a new company, and the first run after any script change, close nothing.**
4. **Never fake `first_seen_at`.** It means "when we first saw this," everywhere.
5. Never commit credentials, cookies, or browser profiles. No "generated by Claude" text in commits/PRs.
6. Work in this worktree (`.claude/worktrees/2`) or a fresh one per the owner's worktree rules; never `cd` to the parent repo from an isolated session.

### 0.5 Local environment traps (verified, will cost you hours otherwise)

- **Vitest hangs silently on Node < 22.12.0.** Use `source ~/.nvm/nvm.sh && nvm use 22.14.0`.
- **Backend tests read `TEST_DATABASE_URL`, not `DATABASE_URL`.** The shared `jobscraper` dev DB is stamped by an unmerged branch and yields ~125 phantom failures. Point tests at an isolated DB: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobscraper_wt2 pytest ...`. Baseline before you start so you can prove no regressions.
- **`vercel dev` must run from the repo root** (`dev:vercel` is `cd ../.. && vercel dev`) or the `/api/*` rewrites don't load. Start backend with `--reload` explicitly or your changes won't take effect.
- **`docker compose up -d postgres`** first; backend on :8000, frontend on :3000.

---

## 1. Architecture, in one paragraph (full detail in OVERVIEW.md)

Every company is a **stored script**, authored once and replayed nightly with **no agent**. There are no tiers: a script is a list of primitives from a **closed vocabulary**, and the ATS client is **primitive #1** — Duolingo's script is one primitive, Amazon's is nine, and **both face the identical verification gate every night.** Scripts run in a browser page context (HTTP primitives as `fetch()` after navigating to the board origin — CORS-verified; DOM primitives natively), defaulting to Browserbase with local Playwright/`httpx` as fallback; the vendor is swappable. Discovery (one-time per add) is an agent; replay is not. The gate decides VERIFIED / UNVERIFIED / FAILED, and **only VERIFIED may close jobs.**

### 1.1 The verdict ladder

```
FAILED               transport/parse error, oracle path vanished, or an exception
                     → raise. Write nothing. Retry once. Then auto-repair (§4.4).
                     → a FAILED (non-executed) run is NOT a miss.

UNVERIFIED           harvested rows but couldn't prove completeness:
                     no oracle yet (Phase 1), oracle==none, tolerance>0 this run,
                     or a browser run whose last scroll still added ids
                     → upsert + update_last_seen ONLY. Never miss++, never close.
                     → scrape_runs.guard_reason = 'unverified_harvest'; user badge.

VERIFIED             every applicable gate check passed exactly (tolerance 0)
                     → full destructive path, ANDed with resolve_safety_guard(),
                       gated by the fleet circuit breaker (§4.3) and the 1.5x-cadence wall-clock floor (§4.2).
```

**Why UNVERIFIED still upserts:** the `ON CONFLICT` clause is purely protective (`status='OPEN'`, `closed_on=NULL`, `consecutive_misses=0`). Writing the rows we *did* get can only move jobs away from closure. We distrust the *absence* of the rest, not the presence of these.

---

## 2. Data model

All new columns nullable-or-defaulted → migrations stay metadata-only (2026-04-18 volume incident). One combined `ALTER TABLE` per table. Autogenerate from `db_models.py`; single Alembic head. **Re-confirm line numbers against `origin/main` — they differ from the spike worktree.**

```python
# companies — ONE combined ALTER TABLE
visibility            Text NOT NULL server_default 'public'   # 'public' | 'user'
cadence_hours         Integer NULL                            # NULL = legacy 30-min cron
next_run_at           TIMESTAMPTZ NULL
tracking_started_at   TIMESTAMPTZ NULL                        # first VERIFIED harvest
health_state          Text NULL      # 'healthy'|'unverified'|'quarantined'|'refused'
last_success_at       TIMESTAMPTZ NULL
consecutive_failures  Integer NOT NULL server_default '0'

# user_companies — ownership. NOT user_enabled_companies (that is a soft
# allow-list where ZERO ROWS MEANS "see all"; reusing it leaks to everyone).
user_id              Text FK users.id ON DELETE CASCADE
company_id           Text                       # soft link, house style
canonical_source_key Text                       # f"{ats}:{token}"  (Phase 1)
created_at           TIMESTAMPTZ NOT NULL default now()
PRIMARY KEY (user_id, company_id)
UNIQUE (user_id, canonical_source_key)          # idempotent re-adds

# company_scripts — the stored script. DATA, validated on write AND read.
# Phase 1: a one-primitive script { "kind":"ats_client", "provider":..., "token":... }.
company_id     Text PRIMARY KEY
script         JSONB NOT NULL
script_version Integer NOT NULL
transport      Text NOT NULL   # 'ats_client' (P1) | 'page_fetch' | 'page_request' | 'dom'
oracle_kind    Text NOT NULL   # 'none' (P1) | 'declared_probed'|'facet_sum'|'header'|'sitemap'|'self_consistent'
created_at, updated_at

# company_harvests — per-run evidence. Makes a wrong match diagnosable weeks later.
id, company_id, run_id, started_at, completed_at
verdict, verdict_reason, records_harvested, declared_total, oracle_total, oracle_kind
cap_hit, page_advance_ok, id_dedup_dropped, tolerance_used
INDEX (company_id, started_at DESC)

# company_add_attempts — audit of every add attempt incl. failures/refusals (D4)

# scrape_runs — CURRENTLY: run_id, company, started_at/completed_at (Text!), mode,
#   jobs_seen, new_jobs, closed_jobs, details_fetched, error_count. NO source_id,
#   NO success, NO guard_reason (main adds guard_reason). ADD: source_id Text,
#   success Boolean, and use main's guard_reason Literal += 'unverified_harvest'.
```

Index: `CREATE INDEX ix_companies_visibility ON companies (visibility) WHERE visibility <> 'public';`

### 2.1 `source_id` — one namespace per company

```python
# scripts/shared/constants.py
def custom(company_id: str) -> str:
    """custom:<company_id>. PER COMPANY, not one shared 'custom' namespace.
    job_listings PK is (source_id, id); every destructive helper is
    WHERE source_id=%s AND id IN (...). Per-company source_id makes the DATABASE
    enforce cross-company isolation — a mis-scoped id list can only ever damage
    one user's company. That is where the 2026-03-29 class of bug lives.
    """
    if not _COMPANY_ID_RE.fullmatch(company_id): raise ValueError(...)
    return "custom:" + company_id
```
`companies.id` format: `u-<10 chars base36 of uuid4>` (satisfies `^[a-z0-9][a-z0-9.\-]*$`, can't collide with `COMPANY_IDS` or logo filenames).

### 2.2 Job `id`

Phase 1 uses `upstream` (the ATS client's own stable id, verbatim). `url_hash` / `content_hash` / the two-harvest id-stability check arrive with the agent-scripted phases (they can produce unstable ids); ATS ids are stable, so P1 doesn't need them. **`job_listings` mapping:** `source_id=custom:<id>`, `company=<id>`, `details` hard-capped 8 KB (OOM/TOAST incidents), `posted_on` only if it parses and falls in `[now-365d, now+7d]` else NULL (never synthesize), enrichment/normalization left NULL in P1 (they spend Claude Haiku per job — a 12k-job add is a real bill).

### 2.3 `job_freshness` is dead code — do not extend it

It has a table, trigger, tests, and is **read/written by nothing in production** (the 2026-06-14 "built but unwired" incident). Call only the existing helpers (`update_last_seen`, `increment_consecutive_misses`, `get_jobs_exceeding_miss_threshold`) so the eventual Unit-4 cutover is one change. Flag Unit 4 as a scheduling dependency.

### 2.4 Day-0 spike — fix in presentation, never in data

The graph buckets on `firstSeenAt` (`timeBucketing.ts`), ignores `postedOn`. A 12k-job board would render one giant "posted today" bucket on day one. Fix: `companies.tracking_started_at` set on first harvest; the trend page shades everything before it and labels the seed bucket *"N openings already live when tracking began"*, excluded from the "new postings" series. Derive membership (`first_seen_at <= tracking_started_at + 1h`) — **do not add a boolean to `job_listings`** (backfill on that table is expensive, 2026-04-18).

---

## 3. The verification gate (built incrementally across phases)

Ordered, every step fatal. Emits one verdict. **Phase 1 ships only checks 1, 2, 7, 8 + "oracle=none ⇒ UNVERIFIED"; Phase 2 adds the rest.**

| # | check | scope | phase |
|---|---|---|---|
| 1 | HTTP/transport status in allowed set | generic | 1 |
| 2 | non-empty; `expected_min_jobs` floor; **raise, never return `[]`** | generic | 1 |
| 3 | `assert_no_inband_error` — fatal key inside a 200 (`error`/`errors`/`message`) | generic mech, per-vendor key | 2 |
| 4 | `assert_pinned_operation` — discovery-time op identity still live (Meta: **pin `doc_id`, not operationName**) | per-vendor | 3 |
| 5 | `assert_cap_not_hit` — `offset+page_size <= window_cap`; **Workday's 2,000 ceiling is a cap** | generic mech, per-vendor cap | 2 |
| 6 | `assert_page_advances` — page N ids disjoint from N-1 | generic | 2 |
| 7 | dedupe, then `assert_unique_ids_vs_total` on the **post-dedup** count | generic | 1 (dedup) / 2 (vs-total) |
| 8 | `assert_unique(field)` for any field used as a key | generic | 1 |
| 9 | independent **oracle** agrees within tolerance; record provenance | generic mech, per-vendor oracle | 2 |
| 10 | **fatal in BOTH directions** — over-harvest means a dropped filter widened scope | generic | 2 |
| 11 | if 0 rows → the **zero-proof chain** (liveness → declared-0 → empty-state string → **brand present** → **canonical backlink**). Zero is just an oracle returning 0. | generic chain, per-vendor signals | 2 |
| 12 | `assert_delta_vs_last_run` (trailing-14-run median) — the only check that works below ~10 jobs | generic | 2 |

**Two rules the review forced, both Phase 2:**
- **`tolerance > 0` on a run ⇒ that run closes nothing.** Approximation may only *add*. (Amazon's 43 facet-invisible jobs score 0.998 vs a 1% tolerance and would otherwise be closed nightly. A percentage can never catch a *structural* hole.)
- **Self-consistency oracle** (`oracle_kind='self_consistent'`): a run with no declared total is complete iff pages advanced monotonically with disjoint id-sets, the last page was short, nothing 429'd/timed out, and the count is within X% of the trailing-14-run median. Lets no-total boards (YC, Jane Street) close on 3 consecutive complete runs instead of never.

**Oracle single-valued flag is mandatory** (Phase 2): a facet that *covers* is not a facet that *partitions*. GM's location facet sums to 1,042 vs a true 835 (multi-location jobs counted twice). The discovery agent must verify single-valuedness on a board known under the cap.

### 3.1 ATS → oracle mapping (definitive, Phase 2)

| ATS | fetch shape | trusted independent total | cap | Phase-2 `oracle_kind` |
|---|---|---|---|---|
| **Greenhouse** | single GET `?content=true` | `payload.meta.total` ✅ | none | `declared_probed` |
| **Workday** | POST offset-paginated | `payload.total` (page 1) ✅ | `WORKDAY_MAX_PAGES×20 = 2000` | `declared_probed` |
| **Ashby** | single GET | none | none | `self_consistent` |
| **Lever** | single GET `?mode=json` | none (flat array) | none | `self_consistent` |
| **Gem** | single GET | none (flat array) | none | `self_consistent` |
| **Eightfold** | GET start-paginated | `payload.count` ⚠️ unreliable | `MAX_PAGES×10 = 1000` | `self_consistent` (count = evidence only) |

`declared_probed` compares the ATS's own declared total against the **post-dedup** unique-id count **exactly** (`tolerance_used = 0`), and additionally requires `not cap_hit` and `page_advance_ok is not False`. `self_consistent` has no trusted total, so the oracle is the conjunction *terminated cleanly (short or empty last page, **not** a cap) + disjoint page id-sets + nothing errored + count within the delta band of the trailing-run median* — and **closing** additionally requires the 3-consecutive-VERIFIED streak. Eightfold's `count` is recorded as evidence but is never the oracle: it over/under-reports across tenants (`PROD-VERIFY` — observed on a handful, want ~20).

**Where Target lands:** `declared_total=11960`, `len(deduped)=2000`, `cap_hit=True` → UNVERIFIED (§9.1).

### 3.2 Two Phase-2 check effects that are easy to get wrong

- **Check 6 failing (`page_advance_ok=False`) is UNVERIFIED, not FAILED.** UNVERIFIED keeps the rows we did harvest — and written rows can only move jobs *away* from closure — whereas FAILED discards them. Intel's offset-wrap is the live case.
- **Check 11 (zero-proof), Phase-2 ATS scope.** `declared_total == 0` on a live 200 (Greenhouse/Workday) → VERIFIED `zero_proven`, but it **still closes nothing that run**: the safety guard's `empty_scrape` rule (`jobs_seen=0 < 0.10*active`, `incremental.py:340`) trips first and short-circuits the close (belt-and-suspenders, per the 2026-03-29 lesson). `declared_total is None` (Ashby/Lever/Gem/Eightfold) → the zero **cannot be proven from the ATS payload** → UNVERIFIED `zero_unproven`, never closes. That is the Marcus & Millichap outcome: the design refuses to close 204 real jobs off a polished, empty Lever `200 []`. The canonical-backlink / brand-present signals that *could* prove such a zero are page checks, and arrive with Phases 3–4 (see OVERVIEW's trap table).

---

## 4. Closure safety

The completeness verdict is **ANDed with** the existing `resolve_safety_guard` (from main), never a replacement. Clone the leaf task from `fetch_greenhouse_company.py` and **copy its load-bearing ordering comment verbatim**: upsert → last_seen → miss-increment → close.

```python
guard   = resolve_safety_guard(conn, company_id, jobs_seen, active_count)   # from main
verdict = verify_harvest(script, harvest, baseline)                          # NEW

# 1. Upsert is safe under everything except FAILED (which already raised).
db.upsert_jobs_batch(conn, jobs); db.update_last_seen(conn, source_id, seen_ids, ts)

# 2. Destructive phases require BOTH, plus the fleet breaker and the wall-clock floor.
#    VERDICT IS EVALUATED FIRST — decision D1, confirmed by the orchestrator
#    (STACK-ORCHESTRATION.md:59). See the note below.
if verdict is not VERIFIED:       guard_reason = 'unverified_harvest'  # NEW — the gate is primary
elif guard.reason is not None:    guard_reason = guard.reason          # VERIFIED but the board shrank
elif tolerance_used > 0:          guard_reason = 'approximate_no_close' # NEW (§3 rule)
else:  ...increment_misses → get_jobs_exceeding_miss_threshold → mark_jobs_closed
```

> **D1 — why the verdict is evaluated before `guard.reason`.** Safety is identical either
> way: *any* non-None reason skips the close. Only the recorded string changes. Verdict-first
> means a capped/incomplete harvest records `guard_reason='unverified_harvest'` rather than
> `partial_scrape` — the accurate root cause for a custom company, and what §8's Target
> regression asserts. The ratio guard stays a real secondary net for the
> VERIFIED-but-the-board-shrank case (the `elif` branch).

### 4.1 Preserve the three distinct guard reasons
`count_consecutive_partial_skips` counts on `guard_reason='partial_scrape'` specifically. Never collapse `empty_scrape` / `partial_scrape` / `unverified_harvest` / `approximate_no_close`. `unverified_harvest` must **not** count toward the bounded auto-release (an unknown is not evidence for releasing a destructive guard).

### 4.2 `MISSED_RUN_THRESHOLD` + wall-clock floor
Keep threshold 2. **Add a floor on `last_seen_at`, not on the counter** (a retry or scheduler double-fire can otherwise close in minutes):
```sql
AND last_seen_at < now() - (1.5 × cadence_hours)
```

> **Updated 2026-08-29.** Written when `cadence_hours` was 24, so the plan quoted the two derived numbers as literals: threshold 2 ≈ 48 h, floor = `INTERVAL '36 hours'`. The **code was always written as `1.5 × cadence_hours`**, so both scale automatically. At the current 1 h cadence they are ≈2 h and 1.5 h, and the 2-miss rule is the binding one. The floor's *purpose* is unchanged and is the reason it is expressed as a multiple: it only ever makes closing harder.

### 4.3 Fleet circuit breaker (the 2026-03-29 generalization)
**If >20% of the night's scheduled companies FAIL, no company closes anything that night.** Short-circuit the close step. This is the check that would have made the 3,582-job Apple incident a non-event.

**Read it at close time, not at claim time.** The fan-out is async — leaf tasks finish independently, there is no barrier where "the night's companies" all complete together, and the claim task runs *before* the fetches, so it cannot know this night's failures. So the breaker is a **night-scoped aggregate** (`count(*)` plus `count(*) FILTER (WHERE success IS FALSE)` over `scrape_runs WHERE source_id LIKE 'custom:%'` inside the window), read by **each leaf task immediately before its own close step**. Tripped iff `total >= min_sample AND failed/total > fail_fraction` (defaults: 24h window, `min_sample=5`, `fail_fraction=0.20`).

**Global across all custom companies on purpose.** A systemic failure — a shared-client bug now, a Browserbase outage in Phase 4 — is exactly the 2026-03-29 class this generalizes. It never touches another user's *data*: `source_id` isolation still holds; the breaker only suppresses *this* company's close.

> **Trap — `scrape_runs.started_at` is `Text`**, not a timestamp (ISO-8601 written by `get_iso_timestamp`). Compare with `started_at >= %s` passing a **Python-computed ISO cutoff string**; never `now() - interval` against the column. Lexicographic compare is correct for zero-padded ISO-8601 UTC. Pin it with a boundary-row test.

### 4.4 Auto-repair — board identity, not job identity
On repeated FAILED: one agent re-discovery pass. Gate the swap on **canonical backlink + tenant/eTLD+1 stability**, NOT Jaccard (a Greenhouse→Ashby migration changes every id → Jaccard 0, yet is the most common real repair; a superset parent board shares ids and passes by coincidence). Split: **re-tune** (same host+tenant) hot-swaps with no human; **re-point** (host/tenant changed) requires admin approval. Rate-limit 1/company/7d. **First run after any swap closes nothing** → a bad swap can only add rows. Jaccard is a log line.

### 4.5 Calibration — do NOT reuse 0.85 for daily companies

> **Largely defused 2026-08-29 by the cadence change.** This section's premise was "custom
> companies run at 24 h, the 0.85 guard was tuned at 30 min, therefore it is mis-calibrated
> for them". Custom companies now run at **1 h**, i.e. the cadence the 0.85 knee was tuned at,
> so the mismatch this section exists to work around is mostly gone. Two knock-on effects, both
> in the safe direction: hour-over-hour retention is far closer to 1.0 than day-over-day, so
> the learned `p01` lands at or near the 0.85 ceiling rather than well below it; and
> `_CALIBRATION_MIN_RUNS = 14` is now ~14 **hours**, not 2–3 weeks, so a board leaves the loose
> 0.5 floor for the tighter learned ratio within a day. The "PROD-VERIFY / largest single
> unknown" note below is correspondingly much smaller. The machinery in
> `services/custom_baseline.py` is kept as-is — it is still the right shape and it is still
> what runs.

`SCRAPER_GUARD_MIN_RATIO=0.85` was tuned at 30-min cadence; at 24h a company that turns over 20%/day trips it every run. Ship daily companies with a **per-company learned baseline**, derived on the fly from `company_harvests.records_harvested` — no stored value and no new column, because a stored ratio goes stale:

```
run_count <  14  ->  min_ratio = 0.5                                       # conservative until calibrated
run_count >= 14  ->  min_ratio = clamp(min(0.85, p01_delta - 0.05), 0.5, 0.85)

  p01_delta = the 1st percentile of the day-over-day retention ratios
              r_i = min(1.0, records[i] / records[i-1])
              taken over consecutive VERIFIED harvests
```

`min_ratio` overrides the global `SCRAPER_GUARD_MIN_RATIO` **for custom companies only** — a keyword-only `min_ratio` threaded through `evaluate_safety_guard` / `resolve_safety_guard` that defaults to `None`, so the six public crons are untouched.

**`PROD-VERIFY`. This cannot be calibrated locally** — `p01` is meaningless until a company has ~14 daily runs (2–3 weeks of prod data), and locally `min_ratio` is therefore always the 0.5 floor. Tests can prove the *arithmetic* (0.5 below 14 runs; the clamp/floor math on a synthetic 14-run history), never the tuning quality. **Largest single unknown.**

---

## 5. Per-user visibility — three leaks (re-verify against main, then fix in Phase 1)

1. **Auto-enroll has no user scoping.** The `user_preferences_service.py` UNION enrolls *every* user whose watermark predates a new `enabled` row. **Fix:** `AND c.visibility = 'public'`.
2. **Public directory** (`GET /api/companies`, no auth) selects every `enabled=TRUE` row. **Fix:** `AND visibility='public'`.
3. **`/api/jobs` is entirely unauthenticated** and only hides *explicitly deactivated* companies. **Fix (fail-closed, don't touch the public hot path):** add an unconditional `NOT EXISTS (SELECT 1 FROM companies c WHERE c.id=job_listings.company AND c.visibility='user')` predicate to the public list/detail reads. Serve user companies **only** via a new authed `GET /api/users/companies/{id}/jobs` that joins `user_companies` on the caller. `api/companies.ts` already forwards `Authorization` → **no new Vercel proxy.** Reject a viewer-scoped predicate on `/api/jobs` (turns a leak into a conditional leak — the kind that ships).
4. **Gate the fan-out:** `list_enabled_companies(conn, ats)` feeds the six ATS crons — add `AND visibility='public'`, and give custom companies their own queue.

---

## 6. The vertical slices

Each ends at the UI and is independently testable. Later slices only make the gate stricter — until then everything is safely UNVERIFIED (shown, never closed).

- **Phase 1 — "Add an ATS company, private to me, see its jobs."** *(the immediate work — §7)*
- **Phase 2 — The gate + oracles.** Independent oracle (facet_sum/header/sitemap), self-consistency oracle, cap-smell (**the Workday 2,000 ceiling surfaces as `cap_hit` → UNVERIFIED — §9.1**), page-advance, post-dedup-vs-total, tolerance>0⇒no-close, zero-proof chain, fleet breaker, wall-clock floor, per-company baseline. Companies graduate to VERIFIED and begin closing. *Test: a company drops a job → closes after 2 runs + the 1.5x-cadence floor; a capped Workday tenant lands UNVERIFIED, not silently-partial; Marcus & Millichap fails the zero-chain on canonical-backlink.*
- **Phase 3 — Stored HTTP scripts + one-time local-browser discovery.** The closed primitive vocabulary (`fetch`, `paginate_offset/page/cursor/facet`, `extract_json_path/css/embedded_island`, `lookup_join`, `parse_date/transform`, `dedupe_key`, the assert family, the oracle block; **NOT `click_sequence`** — cut from v1). Discovery agent (Sonnet, ~$0.25–1) drives local Playwright, authors a script, gate validates it agent-free, ≤2 attempts then REFUSE. *Test: paste amazon.jobs → ~30s discovery → Amazon VERIFIED at 22,191 via facet partition; Meta 821 via pinned doc_id.*
- **Phase 4 — Browser runtime (Browserbase) + execution-time SSRF pinning.** For scripts whose transport is `page_fetch`/`dom` and that need a real browser (CBRE WAF, DOM-virtualized). CDP `Fetch.requestPaused` host allowlist, `ignoreCertificateErrors:false`, per-company timeout + checkpointing, batched sessions. *Test: paste CBRE → in-session pagination → VERIFIED.*
- **Phase 5 — Repair loop, refuse UX, admin dashboard, name input.** Board-identity repair (§4.4), the admin observability dashboard (every add/attempt/cost, promote-to-public), the slug-variant name→URL resolver with a mandatory picker (no auto-accept < confidence 80).

---

## 7. Phase 1 — full spec (implement this, then get it running for the owner)

**Goal:** a signed-in user pastes a Greenhouse/Ashby/Lever/Gem/Workday URL → it resolves → a private company is created and scraped nightly by the existing ATS client running as script-primitive #1 behind a minimal gate → the user sees its jobs on a private trend page. **Everything is UNVERIFIED (never closes)** because no oracle exists yet — the safe default.

### 7.1 Backend
- Migrations from §2 (companies cols, `user_companies`, `company_scripts`, `company_harvests`, `company_add_attempts`, `scrape_runs` cols). Single head, autogenerated.
- `scripts/shared/constants.py`: the `custom()` source_id helper (§2.1).
- The three leak fixes + fan-out gate (§5).
- Endpoints (ride the existing `/api/users` proxy + JWT; camelCase via `to_camel`):
  - `POST /api/users/companies` — body `{url}`. Resolve (existing L0/L1/L2) → `probe_candidate` → **require `job_count > 0`** → create `companies` row (`visibility='user'`, `health_state='unverified'`) + `user_companies` ownership + a one-primitive `company_scripts` row (`{kind:'ats_client', provider, token}`, `transport='ats_client'`, `oracle_kind='none'`) + a `company_add_attempts` audit row. Idempotent per `UNIQUE(user_id, canonical_source_key)`. Non-ATS URL → attempt row `outcome='unsupported'`, 422 (Phase 3 will handle these).
  - `GET /api/users/companies` — the caller's companies + `health_state`, `openJobCount`, `lastSuccessAt`.
  - `DELETE /api/users/companies/{id}` — remove ownership; if last owner, disable the company.
  - `GET /api/users/companies/{id}/jobs` — **authed, owner-scoped** (403 if not owner). This is the only path that serves `visibility='user'` jobs.
- Worker: a `custom_ats_fetch` Procrastinate queue + leaf task **cloned from `fetch_greenhouse_company.py`** (copy the ordering comment verbatim). It runs the existing ATS client for the company's provider/token, then the **minimal gate** (checks 1, 2, 7-dedup, 8) → verdict is UNVERIFIED for everything (oracle_kind='none') → upsert + last_seen only, never close. Writes a `company_harvests` row + a `scrape_runs` row (`source_id`, `success`, `guard_reason='unverified_harvest'`). Scheduling: `cadence_hours` (**1 h since 2026-08-29, was 24 h**) + `next_run_at` + a `*/15` claim task with `FOR UPDATE SKIP LOCKED`, jitter of ±¼ cadence capped at 90 min (**was a flat ±90 min**, which is larger than a 1 h cadence and would have pushed `next_run_at` into the past), global concurrency ceiling 3.
- **Feature flag** `custom_company_sources_enabled` gates all of it (already exists; the resolve endpoint 503s when off).

### 7.2 Frontend
- The pulled-over `/my-companies` resolve preview gains an **"Add"** button on a successful resolve → `POST /api/users/companies` → optimistic add.
- A **list** of my companies with a `health_state` badge ("Tracking — building history" for unverified) + open-job count + last-checked.
- A **private trend page**: reuse the existing companies-page chart components, but feed a *runtime* company object (from `GET /api/users/companies/{id}/jobs`) instead of the compile-time `COMPANY_IDS` lookup. Day-0 shading per §2.4 (or defer the shading polish to Phase 2 and just avoid the fake spike by labeling).
- Keep the whole thing behind `VITE_CUSTOM_COMPANIES_ENABLED` (already wired).

### 7.3 Phase 1 acceptance test (E2E, two real accounts)
Account A adds `boards.greenhouse.io/duolingo`. Assert:
- anonymous `GET /api/companies` omits it; anonymous `GET /api/jobs?company=<id>` returns `[]`;
- as **B**, `GET /api/users/enabled-companies` omits it and `GET /api/users/companies/<id>/jobs` is 403;
- as **A**, the jobs return (~65) and the private trend page renders;
- B adds the *same* board → distinct `company_id` + `source_id`; deleting A's company doesn't touch B's rows;
- after a simulated second run that drops a job, **nothing closes** (UNVERIFIED).

Then **start the local stack and hand off to the owner** (backend :8000 with `--reload`, `vercel dev` from repo root, both flags on, Node 22.14.0). Report the two account credentials / how to sign in, and the exact URL (`/my-companies`).

---

## 8. The regression test (write it in Phase 2, but keep the shape in mind from Phase 1)

The 2026-03-29 incident's modern form is a run that **succeeds, returns a plausible number, matches the source's own declared total, and is still 83% short** (Target: Workday says 2,000, real 11,960). The test seeds 11,960 open jobs, harvests a capped 2,000, and asserts across two runs: verdict UNVERIFIED, `closed_jobs==0`, `OPEN==11,960`, `max_consecutive_misses==0`, `guard_reason='unverified_harvest'`. Plus: `test_manual_rerun_cannot_accelerate_closure` (the wall-clock floor), `test_fleet_breaker_suppresses_closes`, `test_abandoned_board_fails_zero_chain` (Marcus & Millichap → must fail on canonical_backlink), `test_non_executed_run_is_not_a_miss`.

---

## 9. Per-target implementer notes (verified; for Phases 2–3)

- **Workday (Cisco/Intel and any tenant)** — **2,000-job hard ceiling** (`WORKDAY_PAGE_SIZE=20 × WORKDAY_MAX_PAGES=100`); on cap-hit `workday_client.py` **logs error and returns partial, does not raise**. Phase 2's fix is **§9.1** — surface `cap_hit` and let gate check 5 map it to UNVERIFIED. Intel also: `total` populated on the `offset=0` page only; offset ≥ total **wraps to page 1 forever** (terminate on first-record-id-change, never `len>0`); 636 unique on a 663 board → check-7 on post-dedup count. `corpredirect.intel.com` 403s a browser UA.
- **Amazon** — `hits` caps at 10,000 (ES window); the `facets` block is uncapped and six single-valued facets each sum to 22,191. Boundary probe passes cleanly, so it is NOT a cap detector. 43 jobs are unreachable by any geographic facet → structural hole, record it, tolerance can't catch it. Not an ATS (`source_system:"JobCreator"`).
- **Meta** — pin the **`doc_id`, not `operationName`** (Meta doesn't validate the friendly name; a rename returns byte-identical 821). Assert response shape `job_search_with_featured_jobs_v2.all_jobs`. `is_leadership:false` excludes. No posted-at → `first_seen` is ours.
- **Duolingo** — Greenhouse `boards-api.greenhouse.io/v1/boards/duolingo`, 65 jobs, the Phase 1 golden test. `/offices` view emits 99 rows for 65 jobs — dedupe by id if ever used.
- **YC** — per-company pages (`ycombinator.com/companies/<slug>/jobs`) are server-rendered JSON islands (raindrop 9/9, stable). The *aggregate* is 1,490 employers behind one line — treat as per-company, not one company. Publishes no total → `self_consistent` oracle.
- **CBRE** — AWS WAF, plain GET = 202/0 bytes; token single-use outside the browser; but in one continuous session pagination is plain GETs (`?jobRecordsPerPage=25&jobOffset=N`). Local headless Chromium cleared it. Phase 4.

### 9.1 The Workday 2,000 cap — the fix is `cap_hit` → UNVERIFIED

Surface `cap_hit=True` from the client (custom path only) and let check 5 map it to UNVERIFIED. Both obvious alternatives were considered and **rejected**:

- **Do NOT raise on cap-hit.** Raising means FAILED, which (a) discards the 2,000 rows we *did* get, (b) mislabels a legitimately-large board as a transport error, and (c) contradicts §8, which mandates **UNVERIFIED** + `guard_reason='unverified_harvest'`. A capped board is not a failure; it is an *incomplete but valid* harvest, and UNVERIFIED is exactly the ladder state for "harvested rows but couldn't prove completeness."
- **Do NOT paginate past 2,000 in Phase 2.** Raising `WORKDAY_MAX_PAGES` high enough to fully harvest Target (**≥598 pages**) would also change the **public** Workday cron (the client is shared), risks the 120 s task timeout, and can only be validated at prod scale → `PROD-VERIFY`, deferred. It is explicitly **not** what makes the §8 regression pass; `cap_hit → UNVERIFIED` is.

The public `fetch_jobs` delegator must preserve today's "return the partial, log ERROR" behaviour for the six public crons; only the custom path additionally reports `cap_hit`, so the gate can act on it. Net outcome for Target: 2,000 jobs shown with an *unverified* badge, and **nothing ever closes**.

---

## 10. Open decisions, falsifier, and what can't be verified locally

**Owner decisions still open** (defaults in the plan, override anytime): (1) do permanently-unverifiable companies ship as live-can't-close or get refused? — plan ships them; (2) name input in Phase 5 or earlier?; (3) Browserbase runtime vs local browser worker — plan defaults Browserbase, `replay.py` fallback; (4) per-user quotas (plan assumes 5 companies/user, 1 add/min, global concurrency 3).

**The week-1 falsifier:** *if >15% of real adds land UNVERIFIED, close-detection doesn't exist for them and we should refuse those URLs rather than badge them.* Measure it.

**The real scaling limit is repair throughput, not cost:** ~3% board churn/month × 300 companies ≈ ~9 human-approved repairs/month, forever. State this to the owner; don't let it surface as "plan #5".

**Cannot be verified locally, flag before shipping:** Browserbase from Railway's egress IP; browser subprocess memory on the 4 GB Railway container; the 24h churn calibration (§4.5, needs 2–3 weeks prod data); facet-oracle single-valued generality across Workday tenants (verified on 6, want ~20); empty-board shapes for Greenhouse/Ashby/ADP/UKG/Paylocity (inferred, never observed).
