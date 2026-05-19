# Gem Backend Migration PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-05-18 — Review pass 1

### Code-review findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion / Nit:**
- `src/backend/api/services/gem_client.py:188-194` — `details` keys drift from Ashby (`secondary_offices` vs `secondary_locations`, `content_html` vs `description_html`). Intentional — Gem's API natively uses "offices" and returns HTML in `content`, not `descriptionHtml`. Frontend `backendScraperTransformer.ts` only reads `experience_level` + `is_remote_eligible`, so the source-specific keys are stored for debugging. **Not fixing** — documented in PLAN Shared Contracts.
- `src/backend/api/services/gem_client.py:235-241` — `_normalize_iso8601` duplicates the Ashby version verbatim. Intentional per PLAN ("duplicate the Ashby helper, ~10 lines"). Future fix-once-fix-both is captured in the docstring. **Not fixing.**

### Production-environment findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion:**
- (none)

**Could not verify:**
- (none — all three verifiers ran successfully)

**Verifier results:**
- `vercel-prod-verifier`: not dispatched in subagent form (harness lacks parallel subagent dispatch), but the verifier's checks were executed inline. Vercel project `job-visualizer-notifier` is healthy. PR deletes `api/gem.ts` + the `/api/gem/:path(.*)` rewrite in `vercel.json`. No env-var changes required (Gem's public API needs no auth). Auto-deploys on merge.
- `postgres-prod-verifier`: ran inline against prod via `mcp__postgres-prod__query`. Findings: (1) `companies` table currently has 46 ashby + 45 greenhouse rows, 0 gem rows; (2) no row id collision — none of `('nominal', 'retool', 'gem')` exist in prod; (3) `procrastinate_jobs` currently has `ashby_fetch` + `greenhouse_fetch` queues with their fan-out periodic tasks; (4) the new `seed_gem_companies` migration (`b29c1ef8800600`) will cleanly add 3 rows via `ON CONFLICT (id) DO NOTHING`; (5) `gem_fetch` queue + `enqueue_gem_fan_out` periodic appear after merge.
- `railway-prod-verifier`: ran inline against the `onesecondswe` Railway project (service `Job-Visualizer-Notifier`). No new env vars required by the PR — DEPLOY.md pre-merge checklist explicitly notes "env vars unchanged."

### Deferred (not fixing this pass)

- Suggestion-level Ashby/Gem helper-duplication noted above.

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
- (none new — Pass 1 noted the intentional Ashby/Gem details-key drift and the duplicated `_normalize_iso8601`. Both are by-design per the PLAN.)

### Production-environment findings

**Critical:**
- (none)

**Important:**
- (none)

**Verifier results:**
- Re-ran the inline production verifier checks via MCP. `alembic_version` in prod is `a17b7c0ffee500` (the Ashby seed), which is exactly the `down_revision` of the new migration `b29c1ef8800600`. Migration chain is clean — `alembic upgrade head` will apply this PR's migration in one step on next backend deploy.
- Sweep for stale "Lever, Gem, Workday" doc references across `src/` and `api/` returned zero matches — root CLAUDE.md and `src/frontend/CLAUDE.md` updates from Unit 7 caught everything.
- Sweep for stray `'gem'` literals outside the intentional usages (company id, `sourceAts` type, ATSGroupKey, WhyPage test, comments) returned zero matches.

### Deferred (not fixing this pass)

- Same Pass 1 suggestion-level items.

### Implementation applied

No Critical or Important findings — no fix commits this pass.
