# Lever Backend Migration PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-05-18 — Review pass 1

### Code-review findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion / Nit:**
- `src/backend/api/services/lever_client.py:111` — `_sanitize_tags(raw.get("tags") or [])` passes `[]` if `tags` is missing, but `_sanitize_tags` already returns `[]` for non-list input. The `or []` is redundant defensive code. **Not fixing** — the redundant guard matches the Gem migration's `_normalize_employment_type` defensive-style and is harmless.
- `src/backend/api/services/lever_client.py:124-137` — `_ms_to_iso8601` is the second epoch-ms helper in the codebase (would also be needed for Workday if/when migrated). Could be promoted to `scripts/shared/utils.py`. **Not fixing this pass** — single use site today; the duplicate-vs-share decision is captured in PLAN's "duplicate the Ashby helper" convention.
- `src/backend/api/services/lever_client.py:115-120` — `cats = raw.get("categories") or {}` followed by `if not isinstance(cats, dict): cats = {}` is belt-and-suspenders. The `or {}` already handles `None`/falsy; the isinstance guard only catches the case where Lever returns a list/string. **Keeping** — the comment documents the schema-drift defensive intent and the cost is one extra `isinstance` call per posting.

### Production-environment findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion:**
- (none)

**Could not verify:**
- (none — production verifier checks ran successfully)

**Verifier results:**
- `vercel-prod-verifier` (inline checks via repo state): Vercel project `job-visualizer-notifier` configuration. PR deletes `api/lever.ts` + the `/api/lever/:path(.*)` rewrite in `vercel.json`. No env-var changes required (Lever's public Postings API needs no auth). Auto-deploys on merge.
- `postgres-prod-verifier` (inline via `mcp__postgres-prod__query`):
  1. `companies` table currently has 46 ashby + 45 greenhouse rows, **0 lever rows**.
  2. No row-id collision — none of `('palantir', 'spotify', 'zoox')` exist in prod.
  3. `procrastinate_jobs` currently has `ashby_fetch` + `greenhouse_fetch` queues with their fan-out periodic tasks (`enqueue_ashby_fan_out`, `enqueue_greenhouse_fan_out`).
  4. `alembic_version` in prod is `a17b7c0ffee500` (the Ashby seed), which is exactly the `down_revision` of the new migration `b29cd1eef0aab1`. Migration chain is clean — `alembic upgrade head` will apply this PR's migration in one step on next backend deploy.
  5. The new `seed_lever_companies` migration will cleanly add 3 rows via `ON CONFLICT (id) DO NOTHING`.
  6. `lever_fetch` queue + `enqueue_lever_fan_out` periodic appear after merge.
- `railway-prod-verifier` (inline checks via repo state): No new env vars required by the PR — DEPLOY.md pre-merge checklist explicitly notes "env vars unchanged."

### Deferred (not fixing this pass)

- Suggestion-level helper-duplication / defensive-style noted above.

### Implementation applied

No Critical or Important findings — no fix commits this pass.

---

## 2026-05-18 — Review pass 2

### Code-review findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion / Nit:**
- (none new — Pass 1 noted the defensive-style items. All are by-design per the PLAN.)

### Production-environment findings

**Critical:**
- (none)

**Important:**
- (none)

**Verifier results:**
- Re-ran the inline production verifier checks via MCP. State unchanged from Pass 1 (no traffic between passes). `alembic_version` still `a17b7c0ffee500`; the new revision `b29cd1eef0aab1` chains cleanly off it.
- Sweep for stale "Lever" doc references across `src/` and `api/` returned the expected hits: 3 `sourceAts: 'lever'` in `companies.ts` (intentional), the Lever Postings API URL in `CLAUDE.md` / `src/frontend/CLAUDE.md` (clarified as "used by backend client"), and the `lever_*` files I created in this PR. No stragglers.
- Sweep for stray `'lever'` literals outside the intentional usages (company id, `sourceAts` type, ATSGroupKey, WhyPage test, comments) returned zero matches.

### Deferred (not fixing this pass)

- Same Pass 1 suggestion-level items.

### Implementation applied

No Critical or Important findings — no fix commits this pass.

---

## 2026-05-18 — Review pass 3

### Code-review findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion / Nit:**
- (none new — Pass 1 catalogue holds.)

### Production-environment findings

**Critical:**
- (none)

**Important:**
- (none)

**Verifier results:**
- Final test gates: backend `pytest` **448 passed**, frontend `npm run type-check` **clean**, frontend `npm test` **1394 passed across 104 files**.
- TODO/FIXME/XXX sweep across new backend Lever files (`lever_client.py`, `fetch_lever_company.py`, `enqueue_lever_fan_out.py`): zero matches. No deferred work hidden in comments.
- Prod state at PR-open time (via `mcp__postgres-prod__query`):
  - `alembic_version = 'a17b7c0ffee500'` (Ashby seed, the new revision's `down_revision`)
  - `companies` table: 46 ashby + 45 greenhouse + 0 lever
  - No `palantir`/`spotify`/`zoox` id collisions
  - `procrastinate_jobs` queues: `ashby_fetch`, `greenhouse_fetch`
  - `procrastinate_periodic_defers` task_names: `enqueue_ashby_fan_out`, `enqueue_greenhouse_fan_out`

### Deferred (not fixing this pass)

- Same suggestion-level items as Pass 1.

### Implementation applied

No Critical or Important findings — no fix commits this pass. PR is ready to open.
