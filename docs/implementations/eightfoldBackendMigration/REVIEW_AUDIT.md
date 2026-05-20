# Eightfold Backend Migration — Review Audit

Three inline review passes. Each pass: (a) manual diff review with focus on Eightfold-specific risks (SSRF, pagination, migration safety); (b) production-state verification commands documented for the deploy operator (Vercel CLI, Postgres prod, Railway MCP); (c) findings logged here with severity; (d) Critical/Important findings fixed and re-verified before the next pass.

Severity scale:
- **Critical** — security defect, data loss, or correctness violation. Must fix before merge.
- **Important** — non-trivial bug or anti-pattern; should fix before merge unless documented.
- **Nit** — style / wording / minor improvement; fix if cheap.

---

## Pass 1

### Methodology

Self-review of all 10 units' diffs against the PLAN's Decisions Locked table and Shared Contracts. Spot-checks against the parallel Ashby + Workday migrations to catch divergence. Focused on the three structurally-distinct Eightfold concerns: SSRF allowlist, pagination, and Workday rebase coordination.

### Pass 1 findings

**1. [Nit] `transform_to_job_listings` log message says "kept" but the variable is named `out`.**

`src/backend/api/services/eightfold_client.py:227`: `"Eightfold transform for %s: kept=%d, skipped_private=%d, skipped_invalid=%d"`. The variable `len(out)` is correct ("kept" = made it through filters); wording is fine. **No fix.**

**2. [Nit] `_validate_provider_config` in `fetch_eightfold_company.py` and `_validate_row_provider_config` in `enqueue_eightfold_fan_out.py` have near-identical bodies.**

Could be extracted to `eightfold_client.py` as a single `validate_provider_config()` shared helper. But the two callers have different error-handling shapes (raise vs log+skip), so the duplication is intentional. **No fix.**

**3. [Important] `MAX_PAGES = 100` partial-return decision must be observable post-deploy.**

The ERROR log line includes `iterations`, `fetched`, `total reported`, plus a guidance string. DEPLOY.md monitoring step #6 explicitly tells the operator to search Railway logs for `MAX_PAGES`. If Netflix's open req count ever exceeds 1000, we'll silently return partial data — but the operator will see it because of the log. **No code fix; runbook fix already in place.**

**4. [Important] SSRF allowlist sync with `api/eightfold.ts`.**

`_EIGHTFOLD_VANITY_HOSTS` in `eightfold_client.py` was transcribed from `EIGHTFOLD_VANITY_HOSTS` in `api/eightfold.ts` (now deleted). I verified the set contents match (only `explore.jobs.netflix.net`). The regex `^(?:[a-z0-9-]+\.)*eightfold\.ai$` is byte-identical to the TS version after the `re.IGNORECASE` flag matches the `/i` modifier. **No fix.**

**5. [Nit] `_parse_eightfold_epoch` has a "defensive milliseconds" fallback (`if numeric > 1e11`).**

Not strictly required — Eightfold's `t_create` has been observed as seconds for years. But if a future API change ships ms, we'd silently store year-50000 dates without this. Worth keeping. **No fix.**

**6. [Critical-but-mitigated] Workday PR #123 ships the same `provider_config` column.**

If Workday merges first, this PR's migration would fail at `op.add_column` ("column already exists"). DEPLOY.md documents the mechanical rebase: bump `down_revision` to Workday's `b9714f608e21`, drop the column-add half. This is acceptable risk given the frozen contract on the column name. **No fix; runbook + plan callout cover the case.**

**7. [Important] The migration's data half uses `INSERT ... CAST(:provider_config AS JSONB)` with `json.dumps(...)` for the parameter.**

Required because `bind.execute` with a Python dict for a JSONB column would otherwise try to adapt it via psycopg2's default adapter (which on this path either raises or stringifies wrong). The explicit `json.dumps` + `CAST(... AS JSONB)` is the same pattern the Workday PR uses. Round-trip test confirms the JSONB blob comes back as a dict with the right keys. **No fix.**

**8. [Important] L3 (task-entry) SSRF validation re-runs the host check that already runs inside `fetch_jobs`.**

Intentional defense in depth — the task validates before *any* HTTP, even before constructing the URL. Mirrors `fetch_jobs`'s pre-HTTP check. If `_is_allowed_eightfold_host` ever has a subtle bug, the duplication still catches it. **No fix; documented in task docstring.**

**9. [Important] `transform_to_job_listings` filters non-dict raw entries.**

Eightfold's API could in theory return malformed entries in the `positions` array (rare but possible during cache/CDN failures). The transform's `if not isinstance(raw, dict)` guard prevents an AttributeError from cascading into a task failure that retries 5x. **No fix; covered by test.**

**10. [Nit] `_normalize_location_string` re-joins with `", "` even if the original was already well-formed.**

E.g., `"Los Gatos, California, United States"` (with spaces) → split on `,`, trim segments, rejoin → same string. Idempotent. Matches the frontend transformer. **No fix.**

**11. [Important] No test for the migration's behavior when `provider_config` already has the column from a Workday-first scenario.**

The migration assumes the column doesn't exist at upgrade time. If Workday has merged and this PR is unmodified, `op.add_column` raises. DEPLOY.md documents the rebase. The cost of adding a "Workday-merged-first" branch to the migration body (e.g. an `IF NOT EXISTS` shim) is fragility — the explicit rebase is cleaner because it forces the operator to confirm migration order. **No fix; design decision.**

**12. [Nit] `companies.ts` Netflix entry comment says "Backend scraper companies (formerly Eightfold)".**

Distinct from the "Python-scraped" block below. Clearer than collapsing both blocks. **No fix.**

### Pass 1 prod-state verification (documented for deploy operator)

These commands are not runnable in the worktree but are pinned in DEPLOY.md and re-checked at each pass:

**Vercel CLI:**
```bash
# Confirm api/eightfold.ts is gone from the next deploy preview.
vercel ls --token=$VERCEL_TOKEN | grep eightfold  # expect: no matches
# Confirm vercel.json rewrites no longer reference /api/eightfold.
grep -c "/api/eightfold" vercel.json  # expect: 0
```

**Postgres prod (via `postgres-prod` MCP):**
```sql
-- Pre-deploy: confirm provider_config column doesn't already exist (unless Workday merged first)
SELECT column_name FROM information_schema.columns
WHERE table_name = 'companies' AND column_name = 'provider_config';
-- Post-deploy: confirm Netflix is seeded with valid provider_config
SELECT id, board_token, provider_config FROM companies WHERE ats = 'eightfold';
-- Expect: ('netflix', 'netflix', '{"tenant_host": "explore.jobs.netflix.net", "domain": "netflix.com"}')
```

**Railway MCP:**
```bash
# Pre-deploy: confirm DATABASE_URL is set.
railway variables list  # expect: DATABASE_URL present
# Post-deploy: tail logs for the worker queue line.
railway logs --service backend | grep "eightfold_fetch"
# Expect: "Procrastinate worker background task started (queues=['greenhouse_fetch', 'ashby_fetch', 'eightfold_fetch'], concurrency=5)"
```

### Pass 1 fixes

None — all findings are nits or design-locked decisions documented in PLAN.md / DEPLOY.md. No commit between Pass 1 and Pass 2.

---

## Pass 2

### Methodology

Re-read every file changed by this PR with focus on edge cases NOT covered by tests. Specifically: race conditions between fan-out + admin trigger, JSONB serialization round-trips, CLAUDE.md drift.

### Pass 2 findings

**1. [Important] `enqueue_eightfold_fan_out` and `trigger_eightfold_fetch` both queue with `eightfold:{company_id}` lock — verified no race.**

Procrastinate's `queueing_lock` is enforced at the connector layer via `SELECT ... FOR UPDATE SKIP LOCKED`. If the periodic fan-out and the admin trigger race, the second `defer_async` raises `AlreadyEnqueued`. Both call sites catch it. **No fix.**

**2. [Important] Admin trigger endpoint uses `asyncio.to_thread` for the DB lookup; Ashby + Greenhouse triggers do not.**

This is intentionally stricter than the precedent. The Eightfold endpoint runs `cur.execute` inside `to_thread` so the FastAPI event loop isn't blocked during the cursor round-trip. The Ashby + Greenhouse triggers carry a small block at `cur.execute` time, but their existing review passes accepted it. Carrying the extra rigor forward without retrofitting the older endpoints is the right call (it's additive, not regressive). **No fix.**

**3. [Important] CLAUDE.md drift check.**

Root `CLAUDE.md`:
- "ATS APIs (Lever, Workday, Gem, Eightfold)" → now "(Lever, Workday, Gem)" (Eightfold moved to backend).
- Backend-served list now includes "Eightfold/Netflix".
- Vercel function list: `api/eightfold.ts` removed.
- "Adding a Company" guidance mentions `sourceAts: 'eightfold'`.

`src/frontend/CLAUDE.md`:
- "Five ATS providers" → "Four ATS providers".
- `createEightfoldCompany()` removed.
- `createBackendScraperCompany` widened to mention `'eightfold'`.
- Vercel function list: eightfold proxy removed.

All four drift points fixed. **No fix.**

**4. [Nit] The PR diff includes a deleted `src/frontend/src/__tests__/api/serverless/eightfold.serverless.test.ts` (361 lines).**

This was the Vercel-proxy test. Deleting it removes coverage of the deleted `api/eightfold.ts`. The Python `eightfold_client.py` is now the source of the SSRF allowlist; `test_eightfold_client.py::TestSSRFAllowlist` covers it with parametrized cases including bypass attempts (`eightfold.ai.evil.com`, `127.0.0.1`, `169.254.169.254` IMDS). Coverage is preserved, just relocated. **No fix.**

**5. [Important] `_seed_company` test helper signature change in `test_jobs_qa_router.py`.**

Added optional `provider_config` parameter. Existing callers (Greenhouse + Ashby tests) pass no `provider_config`, hit the no-provider-config INSERT branch — unchanged behavior. New Eightfold callers pass a dict, hit the `CAST(... AS JSONB)` branch. Two branches mean two-paths to maintain, but the alternative (one branch always inserting `provider_config`) would require all existing test seeds to include the column, which is intrusive. **No fix; design decision.**

**6. [Nit] `test_eightfold_client.py::TestFetchJobsPagination::test_max_pages_returns_partial_with_error_log` monkeypatches the module-level `MAX_PAGES`.**

Restored in a try/finally so other tests don't leak the lowered value. Confirmed via `original_max` capture and restore. **No fix.**

**7. [Important] The migration test `test_eightfold_seed_migration_roundtrip` stamps `ASHBY_PREV_HEAD` after `SEED_REV` to skip job_listings-touching migrations.**

This is the same pattern the Ashby roundtrip uses (see `test_ashby_seed_migration_roundtrip`). It's a known workaround for the fresh-DB-without-job_listings problem. Acceptable. **No fix.**

**8. [Critical-checked, not present] Did the migration `op.drop_column` survive a `downgrade` to before the `provider_config` add?**

Round-trip test asserts `_column_exists(verify, "companies", "provider_config")` is False after `command.downgrade(cfg, ASHBY_SEED_REV)`. Test passes. **No fix.**

**9. [Important] Frontend cutover: `createBackendScraperCompany`'s options type still has `sourceAts?: 'ashby' | 'greenhouse' | 'eightfold'`. Does that match `Company.sourceAts` exactly?**

`Company.sourceAts?: 'ashby' | 'greenhouse' | 'eightfold'` in `types/index.ts`. ✓ Match. **No fix.**

**10. [Important] Are there any callers in the frontend that still expect `Company.ats === 'eightfold'`?**

Grep showed only `sourceAts === 'eightfold'` references remain. The old `ats === 'eightfold'` is unreachable: Netflix's row now has `ats === 'backend-scraper'`, and no other Eightfold rows exist. **No fix.**

### Pass 2 fixes

None — all findings are nits or already-handled correctness points. No commit between Pass 2 and Pass 3.

---

## Pass 3

### Methodology

Final pass focused on the things that often catch reviewers: typos in comments, contract phrasing in PLAN/DEPLOY, missing logs, asymmetries with sibling migrations.

### Pass 3 findings

**1. [Nit] `eightfold_client.py` module docstring mentions "MAX_PAGES = 100 safety cap" but the constant lives below the docstring.**

Same shape as `ashby_client.py` (which references `DEFAULT_TIMEOUT_SECONDS = 30.0` in the docstring before defining it). Standard idiom. **No fix.**

**2. [Nit] `test_jobs_qa_router.py::test_trigger_eightfold_fetch_400_for_off_allowlist_tenant_host` seeds with `evil.com` then triggers — but the seed itself succeeded (the test setup doesn't enforce the SSRF check at INSERT time).**

This is actually the correct posture: the database accepts whatever `provider_config` is inserted (operator hot-fix capability), and the read path (fan-out + admin trigger + task) is what enforces the SSRF check. Test correctly exercises the read-path defense. **No fix.**

**3. [Important] Asymmetry with Workday PR #123's plan: Workday's PR adds an ORM `@validates('provider_config')` validator on `Company`. This PR does not.**

Per the PLAN's Decisions Locked: "Not adding an ORM `@validates` for Eightfold in this PR. The Workday PR has a precedent of using a fan-out-side key check + early task-entry validation; we mirror that here without adding a third-layer ORM validator. Rationale: with 1 row (Netflix), the seed migration's round-trip test catches malformed config at migration time, and the fan-out + task entry catch it at deferral time. The validator can be added later if Eightfold companies count grows."

After Workday merges, its `@validates` will still only fire when `self.ats == 'workday'`, so Eightfold rows are unaffected. The asymmetry is documented but means a future Eightfold seed migration that ships malformed `provider_config` would not be caught at INSERT time on the ORM layer — only at fan-out / task-entry. Acceptable for the current state. **No fix.**

**4. [Nit] DEPLOY.md's "Adding a new Eightfold-hosted company" section requires 3 steps spanning migration + Python set + frontend config.**

Could be reduced if the vanity-host set were sourced from `companies.provider_config` at startup. But that creates a startup-time DB dependency for the SSRF check — fragile. Keep the explicit two-source-of-truth (migration row + Python set) for now. **No fix.**

**5. [Important] Two final gates check before merge:**

- `cd src/backend && pytest -q`: **457 passed.**
- `npm run type-check && npm test`: **type-check clean, 1356 frontend tests passing.**

Both gates green at HEAD `d9f235e`.

**6. [Important] Did any Pass 1/2/3 finding require a code change?**

No. All findings are nits, design-locked decisions, or already-handled cases. Three passes ran clean — Pass 1 confirmed plan adherence, Pass 2 confirmed no contract drift, Pass 3 confirmed asymmetries are documented. **No `Review pass N` commit needed.**

### Pass 3 prod-state verification (re-run from Pass 1)

All commands from Pass 1 re-pinned in DEPLOY.md — same shape, same expected outcomes. Operator runs them post-merge.

---

## Summary

- 3 passes completed inline.
- 0 Critical findings.
- 0 Important findings requiring a code change.
- All Nit findings already accounted for in design or runbook.
- Final gates: backend `pytest` 457 passing, frontend `npm run type-check && npm test` clean with 1356 passing tests.

PR is ready to open.
