# Workday Backend Migration PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-05-19 — Review pass 1

### Code-review findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion / Nit:**
- `src/backend/api/services/workday_client.py:140-150` — the URL is built by string-concatenating `base_url` + `/wday/cxs/{tenant}/{site}/jobs`. If a tenant ever ships a `base_url` with a trailing slash, the `.rstrip("/")` handles it; if a `tenant_slug` or `career_site_slug` ever has a leading slash, the URL would have a double `//`. **Not fixing** — `_validate_provider_config` rejects empty values but doesn't validate the no-slash invariant, and the seed migration is the source of truth for the 11 rows so the values are reviewed at PR time. A future helper could centralize URL normalization but it would only matter for an operator-pushed bad row that bypasses code review.
- `src/backend/api/services/workday_client.py:280-282` — `parsed.tzinfo is None: parsed = parsed.replace(tzinfo=timezone.utc)` assumes a naive timestamp is UTC. The frontend `parseWorkdayDate` doesn't assume that — it passes the string straight into JS `new Date(...)` which treats naive as local. Tenants don't return naive ISO strings on the CXS list endpoint (the regex paths cover the realistic input space), so this divergence is theoretical. **Not fixing** — would require a behavior decision and the visualization buckets to day-level anyway.
- `src/backend/api/tasks/fetch_workday_company.py:99` — `_validate_provider_config(provider_config)` is called inside the try/except that catches `ValueError`. Belt-and-suspenders with the same call in `fetch_jobs`. **Keeping** — the comment documents the "fail fast before doing IO" intent so the task records a clean error_count=1 if a bad row makes it here.

### Production-environment findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion:**
- (none)

**Verifier results (verified inline via prod MCP):**
- `vercel-prod-verifier` (repo state): Vercel project `job-visualizer-notifier` configuration. PR deletes `api/workday.ts` + the `/api/workday/:path(.*)` rewrite in `vercel.json` + the `X-Workday-Base-Url` CORS allow-header. No env-var changes required (Workday's CXS endpoint needs no auth). Auto-deploys on merge.
- `postgres-prod-verifier` (via `mcp__postgres-prod__query`):
  1. `companies` table currently has **46 ashby + 45 greenhouse rows, 0 workday rows**. Confirmed via `SELECT ats, count(*) FROM companies GROUP BY ats`.
  2. **No row-id collision** — `SELECT id FROM companies WHERE id IN (11 workday ids)` returns 0 rows. The 11 ids are safe to seed.
  3. `alembic_version` in prod is `a17b7c0ffee500` (the Ashby seed), which is exactly the `down_revision` of the new migration `b9714f608e21`. Migration chain is clean — `alembic upgrade head` will apply this PR's migration in one step on next backend deploy.
  4. The `companies` table currently has columns `(id, display_name, ats, board_token, enabled, created_at)` — the new `provider_config` column is not yet present and will be added by `b9714f608e21::upgrade()`.
  5. The new migration adds a `provider_config` JSONB NOT NULL DEFAULT `'{}'::jsonb` column and 11 Workday rows via `ON CONFLICT (id) DO NOTHING`.
  6. `workday_fetch` queue + `enqueue_workday_fan_out` periodic appear after merge.
- `railway-prod-verifier` (repo state + checklist): No new env vars required — DEPLOY.md pre-merge checklist explicitly notes "env vars unchanged."

**Rebase risk note:** PR #121 (Gem, `b29c1ef8800600`) and PR #122 (Lever, `b29cd1eef0aab1`) both chain off `a17b7c0ffee500` as well. If either merges first, this migration's `down_revision` must be rebased one-line to chain off the new head. Trivial — no schema conflict because `provider_config` is a new column.

### Gates re-run between passes

- Backend `pytest`: **448 passed, 0 failed**.
- Frontend `npm run type-check`: clean.
- Frontend `npm test -w src/frontend`: **1303 passed, 0 failed**.

### Deferred (not fixing this pass)

- All three suggestion-level URL/date-parser micro-comments above. None block merge.

---

## 2026-05-19 — Review pass 2

### Code-review findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion / Nit:**
- `src/backend/api/services/workday_client.py:228` — `not isinstance(raw_total, int)` doesn't reject `bool` (since `bool` is a subclass of `int` in Python). If Workday's CXS endpoint ever returned `total: true`, the validation would pass and `total=True` would later compare as `len(all_postings) >= 1`. Real Workday API contract is `int`; the edge case is theoretical. The Lever client has a similar narrow guard. **Not fixing** — additional `isinstance(raw_total, bool)` guard would mirror Lever's `_ms_to_iso8601` defensive style but is suggestion-level only.
- `src/backend/api/services/workday_client.py:166` — `str(provider_config["base_url"]).rstrip("/")` defends against trailing slashes but not against leading slashes in `tenant_slug` / `career_site_slug`. **Not fixing** — `_validate_provider_config` enforces non-empty, and the seed migration is the source of truth for the 11 values.

### Cross-cutting checks

**Surface-area sweep:** `grep -rn "workday\|Workday" src/backend/api src/frontend/src` returned only the expected references (seed comments, task names, queue names, sourceAts tags, why-page column). No dangling references to deleted files (workdayClient.ts / workdayTransformer.ts / workdayDateParser.ts / WorkdayConfig / ATSConstants.Workday).

**Other-suite regression:** Re-ran `pytest -k "ashby or greenhouse or jobs_router or migration_companies"` → 131 passed. The widened `list_enabled_companies` return shape (added `provider_config` key) is invisible to Greenhouse/Ashby fan-outs (they only read `id` + `board_token`).

**SQL injection:** The new trigger endpoint (`/trigger-workday-fetch`) uses `psycopg2`'s parameterized SQL (`%s` placeholders) for `company_id`. The query body literal is a static string with `AND ats = 'workday'` baked in. No string formatting.

**Async + sync DB:** All sync `db.*` calls in the new code are wrapped in `asyncio.to_thread` (or behind `Depends(get_db)` in the trigger endpoint). Matches the Greenhouse / Ashby / Lever pattern.

**Admin gating:** Both new trigger endpoints (`trigger-workday-fetch`, `trigger-workday-fan-out`) carry `Depends(require_admin)`. Tests pin the 401-without-auth and 403-without-admin branches for both.

**Procrastinate task registration:** `tasks/__init__.py` side-effect-imports both `fetch_workday_company` and `enqueue_workday_fan_out`. Worker queue list in `main.py` includes `workday_fetch`.

### Production-environment findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion:**
- (none)

**Verifier results (verified inline via prod MCP):**
- `postgres-prod-verifier`: re-confirmed prod state unchanged since pass 1 (46 ashby + 45 greenhouse, 0 workday/lever/gem; `alembic_version = a17b7c0ffee500`; no row-id collisions on the 11 Workday ids; `companies` table still 6 columns — `provider_config` will be added by `b9714f608e21::upgrade()`).
- `vercel-prod-verifier` (repo state): deletions verified — `api/workday.ts` gone, no `/api/workday/:path(.*)` rewrite in `vercel.json`, `X-Workday-Base-Url` removed from CORS allow-headers.

### Gates re-run between passes

- Backend `pytest`: **448 passed, 0 failed**.
- Frontend `npm run type-check`: clean.
- Frontend `npm test -w src/frontend`: **1303 passed, 0 failed**.

### Deferred (not fixing this pass)

- Suggestion-level findings above. None block merge.

---

## 2026-05-19 — Review pass 3

### Code-review findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion / Nit:**
- (none — re-read of every owned file in the PR diff turned up no new
  findings beyond the suggestion-level items already deferred in passes
  1 and 2.)

### Doc accuracy spot-check

Re-read `PLAN.md`, `DEPLOY.md`, and the PR-body skeleton against the
shipped code:

- **PLAN.md Units 1-10** match committed file boundaries.
- **DEPLOY.md pre-merge checklist** matches actual gates: backend
  `pytest`, frontend `type-check + npm test`, the `grep -c` counts on
  `sourceAts: 'workday'`, and the required-keys SQL.
- **DEPLOY.md rollback section** correctly warns about the parallel
  Eightfold PR sharing the `provider_config` column.
- **Frozen contracts** ship as documented: queue `workday_fetch`,
  periodic id `workday_fan_out`, task name `fetch_workday_company`,
  source id `workday_api`, column name `provider_config`.

### Production-environment final state

**Verifier results (verified inline via prod MCP for the third time):**
- `postgres-prod-verifier`:
  - `alembic_version = a17b7c0ffee500` (unchanged across passes).
  - 46 ashby + 45 greenhouse, 0 workday/lever/gem (unchanged).
  - `procrastinate_jobs` currently runs only `ashby_fetch` (276 succeeded `fetch_ashby_company` + 6 succeeded `enqueue_ashby_fan_out`) and `greenhouse_fetch` (3690 succeeded + 82). Workday queues appear on merge.
  - `companies` table is still 6 columns; `provider_config` will be added by `b9714f608e21::upgrade()`.
- `vercel-prod-verifier` (repo state): final deletion set verified — `api/workday.ts`, the `/api/workday/:path(.*)` rewrite, and the `X-Workday-Base-Url` CORS allow-header are all gone in HEAD.
- `railway-prod-verifier` (repo state + checklist): No new env vars required. Railway service auto-deploys on merge.

### Gates re-run between passes

- Backend `pytest`: **448 passed, 0 failed**.
- Frontend `npm run type-check`: clean.
- Frontend `npm test -w src/frontend`: **1303 passed (102 files), 0 failed**.

### Verdict

**Ready to land.** Zero Critical or Important findings across all three
review passes. Three suggestion-level micro-comments deferred to a
future polish PR — none block this merge.
