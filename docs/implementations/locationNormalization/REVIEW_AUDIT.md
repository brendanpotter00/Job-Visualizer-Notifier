# Location Normalization PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

**Branch:** `feature/location-normalization` → base `main` (`f6a62b3`). Diff scope: `git diff f6a62b3...HEAD`.

## Do not revert (load-bearing decisions)
- **Two-transaction discipline (Decision #3):** `normalize_location` closes its tx1 connection BEFORE the LLM `await`; tx2 opens a fresh connection. Never hold a DB connection across the LLM call.
- **`uq_locations_canonical` is `NULLS NOT DISTINCT`** (PG17) — required so NULL-containing canonical rows dedup. Upserts use `ON CONFLICT ON CONSTRAINT uq_locations_canonical`; existing-id SELECTs use `IS NOT DISTINCT FROM`.
- **`job_locations.job_listing_id` has NO DB FK** — `job_listings` PK is composite `(source_id, id)` and there's no standalone UNIQUE on `id`; a single-column FK is invalid Postgres. `id` is globally unique in practice (0 collisions / 44,666 prod rows). Keyed by job alone (Decision #5).
- **No-key degradation (FINAL):** `normalize_location` leaves status NULL on missing key (no write, no raise); `scan_unnormalized` SKIPS deferring when the key is unset → auto-recovery when the key is set; no manual re-normalize-all needed.
- **`upsert_jobs_batch` is unchanged** — Unit 6 reuses `seen_ids - pre_upsert_active` instead (smaller blast radius; the int return is consumed by batch_writer + tests).
- **Manual override (Unit 8) uses `DO UPDATE` (manual wins);** `persist_llm_result` uses `DO NOTHING` (so a later LLM run never clobbers a manual alias). Do not unify the two writers.
- **`re-normalize-all` is the conservative break-glass** (reset done/failed→NULL + defer scan_unnormalized; does NOT clear the cache / does NOT force fresh LLM). Intentional deviation from F3's literal framing.

---

## 2026-06-08 — Review pass 1

Agents: code-reviewer, silent-failure-hunter, pr-test-analyzer, type-design-analyzer, comment-analyzer + postgres-prod-verifier, railway-prod-verifier, vercel-prod-verifier (all dispatched).

### Code-review findings

**Critical:**
- `location_normalization.py` (`write_job_locations_from_ids`, `persist_llm_result`) — **C1: stale `job_locations` rows are never cleared on re-normalization.** Both writers only `INSERT ... ON CONFLICT DO NOTHING`; a re-run after a mapping change (manual override + re-normalize, or scan re-run) leaves the job linked to BOTH old and new locations, and can leave two `is_primary=true` rows. Corrupts the primary correction workflow. (code-reviewer C1, pr-test-analyzer #1, type-design S7)

**Important:**
- `requirements.txt:13` — anthropic floor `>=0.92.0` is below the version that supports `output_config` structured outputs (code tested on 0.107.1). A clean build at the floor would `TypeError` at runtime. Pin `>=0.107.0,<1.0.0`. (code-reviewer I1)
- `normalize_location.py` low-confidence branch — sync `set_normalization_status` + `commit` block the worker event loop (every other DB touch uses `asyncio.to_thread`). Wrap both. (code-reviewer I2)
- `routers/admin.py` `admin_re_normalize_all` — reset commits, then a failed `scan_unnormalized.defer_async` (ConnectorException) 500s AFTER the destructive reset, hiding partial success. Catch ConnectorException → return 200 `scanDeferred=False`. (silent-failure I1)
- `scan_unnormalized.py` — a tick where ALL defers fail logs INFO and exits green; the safety-net-of-last-resort should escalate. `logger.error` when `failed>0 and deferred==0`. (silent-failure I2)
- `llm_client.py` `CanonicalLocation` + `models.py` `LocationSpec` — the documented `kind`↔`remote_scope` invariant (remote_scope only for kind='remote'; city/region/country only otherwise) is enforced NOWHERE. Add a `@model_validator(mode="after")` to both. (type-design I1)
- `db_models.py:59` + migration docstring — `normalization_status` comment lists `'pending'`, which is NEVER written (only NULL/done/failed). Fix both comments. (comment-analyzer I1/I2)
- `llm_client.py:201` `_call_via_forced_tool_use` — dead code (PATH A shipped) carrying a stale authoring-time "Step 0 / ship one path" instruction. Delete the function. (comment-analyzer I3, code-reviewer S1)

**Suggestion / Nit (DEFERRED — not fixing this pass):**
- `persist_llm_result` dedup `location_ids` preserving order before alias_locations/job_locations loops (LLM returns two phrasings → same id → lost position). (code-reviewer S3) — folded into C1 fix as a cheap add.
- Partial index `ON job_listings (normalization_status) WHERE normalization_status IS NULL` for the drained-state safety-net scan (full seq-scan every */5 once backlog drains; cheap now). Create CONCURRENTLY outside Alembic — **follow-up, not this PR.** (postgres verifier)
- Type polish: `confidence: Field(ge=0,le=1)`, Literal for response `kind`/`source`/`status`, shared `LocationKind`, `frozen=True`, envelope `min_length=1`, DB CHECK backstops, partial unique index for `is_primary`. (type-design S3–S10) — deferred polish.
- Comment nits: re-normalize-all docstring note that scan no-ops when no key; scan throughput "best-case" caveat; remove unused `normalize_string` re-export import in `location_admin.py:31`; `(no-location)` log reason. (comment-analyzer S4-S6,N7) — low-value, will fold the easy ones in.
- Vercel: latent `%2F` (literal slash in raw_text) catch-all edge — pre-existing, document for the audit-skill caller. **follow-up note.** (vercel verifier)
- Test gaps: re-normalization-replaces (drives C1), IS-NOT-DISTINCT-FROM fallback on a NULL-bearing existing row, two-transaction-discipline behavioral assertion, AlreadyEnqueued branches. (pr-test-analyzer #1-#5) — adding the C1 + fallback + cross-field + re-normalize-fail tests.

### Production-environment findings

**Critical:** none.
**Important:**
- `ANTHROPIC_API_KEY` presence on Railway could NOT be confirmed (var dump correctly blocked; service shows 8 vars by count only). **Manual action required before merge/activation:** set `ANTHROPIC_API_KEY` on Railway service `Job-Visualizer-Notifier`. Deploy itself is safe without it (graceful degradation verified); normalization stays dormant until set, then auto-drains. (railway verifier)

**Verified clean:** migration applies against prod single-head `c4f0a2d8b9e1`; additive column catalog-only (44,670 rows); PG 17.9 supports NULLS NOT DISTINCT; `id` globally unique (0 collisions); no destructive DDL; worker boots clean with new queue/tasks; memory comfortable (1.24/3GB); no-key degradation keeps worker green; Vercel near-no-op (no `api/*`/env/config changes; encoding round-trip for comma/space/semicolon verified).

### Implementation applied (pass 1)
(see fix commit below)

**Manual action required before merge:**
- Set `ANTHROPIC_API_KEY` on the Railway `Job-Visualizer-Notifier` service (feature dormant until then; auto-recovers after).

**Follow-ups (not blocking this PR):**
- Partial index `ON job_listings (normalization_status) WHERE normalization_status IS NULL` (create CONCURRENTLY) once backlog drains / table grows.
- Audit-skill / frontend callers of `PUT /api/admin/locations/aliases/{raw_text}` must avoid (or double-encode) a literal `/` in raw_text (catch-all proxy edge).
- Type/comment polish deferred above.

### Implementation applied (pass 1)
Fix commit `a9b1928` — FIX-1 (C1 stale job_locations: DELETE-before-insert in both writers + order-preserving location_ids dedup), FIX-2 (anthropic `>=0.107.0,<1.0.0`), FIX-3 (low-confidence `asyncio.to_thread`), FIX-4 (re-normalize-all catches defer ConnectorException → 200 scanDeferred=False), FIX-5 (scan_unnormalized ERROR on fully-failed tick), FIX-6 (kind↔remote_scope `@model_validator` on CanonicalLocation + LocationSpec), FIX-7 ('pending' comment fix), FIX-8 (deleted dead `_call_via_forced_tool_use`), + removed unused re-export. Tests added: re-normalization-replaces-links, IS-NOT-DISTINCT-FROM remote dedup, cross-field rejection (LLM + admin), re-normalize-all defer-failure 200. **777 backend + 57 scripts tests green.**

## 2026-06-08 — Review pass 2

Agents: code-reviewer, silent-failure-hunter, postgres-prod-verifier (focused on the pass-1 fix commit `a9b1928`). Vercel skipped (no `api/*` change since pass 1); railway boot/memory profile unchanged by the fixes (Python validators + an index-backed DELETE).

### Findings
- **code-reviewer:** all four targeted fixes verified CORRECT and complete (C1 DELETE concurrency-safe under READ COMMITTED + resets is_primary; dedup order-preserving; cross-field validator no false-reject; ConnectorException catch ordering correct; to_thread wrap correct). **No new Critical/Important.**
- **postgres-prod-verifier:** migration DDL byte-identical to pass 1 (MD5 match; docstring-only change); prod still single head `c4f0a2d8b9e1`; the new per-job `DELETE FROM job_locations WHERE job_listing_id=%s` is a Bitmap Index Scan on `idx_job_locations_job_listing_id` (cost ~13.68), index-backed, fine at backfill scale. **No new Critical/Important.**
- **silent-failure-hunter (1 Important):** the `psycopg2.Error` arm in the defer-catch tuples (`admin.py` re-normalize-all + `scan_unnormalized.py`) is effectively dead — Procrastinate's psycopg3 `PsycopgConnector` wraps DB errors into `ConnectorException` (which IS caught + `logger.exception`-logged). Real failures are caught loudly; the dead arm is only future-maintainer-misleading.

### Conflicts with prior audit / decisions (NOT fixed — deliberate)
- The `(ConnectorException, psycopg2.Error)` defer-catch tuple **intentionally mirrors the repo-wide `enqueue_*_fan_out` convention** (`enqueue_greenhouse_fan_out.py:107` and siblings catch the same tuple). Units 6/7 were built to match it. Keeping it preserves consistency with the established, shipped pattern; the `psycopg2.Error` arm is harmless (the real failure surface is `ConnectorException`, which is caught + logged). Diverging only the new code would make it inconsistent with the family. **Decision: keep for consistency; acknowledged as harmless dead arm.**
- Minor suggestion (chronic partial-failure ticks stay at INFO) — deferred (consistent with the existing fetch-task logging; a fully-failed tick now escalates to ERROR via FIX-5, which is the load-bearing signal).

### Implementation applied (pass 2)
None required — no new Critical/Important demanding a code change; the one Important is a documented consistency decision. Code unchanged since `a9b1928`.

## 2026-06-08 — Review pass 3 (final convergence)

Agents: code-reviewer (holistic merge-readiness) + pr-test-analyzer (coverage re-check).

### Findings
- **code-reviewer: MERGE-READY.** Verified end-to-end (migration single-head `c876c313e55c`→`c4f0a2d8b9e1`; two-transaction discipline; DELETE-before-insert REPLACE; enqueue chaining; safety-net; admin authz; manual-wins; structured-outputs API; anthropic pin). **No new Critical/Important; no code changes recommended.** (Noted a stale untracked `__pycache__/*.pyc` — not git-tracked, no effect.)
- **pr-test-analyzer: MERGE-READY.** Confirmed all four Pass-1 gaps adequately covered and **empirically proved the C1 regression test fails without the fix** (neutralized both DELETEs → `assert 2 == 1` with two `is_primary=true` rows → restored, git clean). 87 location tests pass. One minor (3/10) untested branch: FIX-5 fully-failed-tick ERROR escalation — **now closed** by `test_all_defers_failed_escalates_to_error` (test-only commit).

### Implementation applied (pass 3)
Test-only: added `test_all_defers_failed_escalates_to_error` to `test_scan_unnormalized.py` closing the FIX-5 observability-branch gap (asserts the distinct ALL-failed ERROR escalation, not the per-id exception logs).

## Final disposition: MERGE-READY
All three passes converged. No Critical/Important findings remain in code. Outstanding items are non-blocking:
- **Manual action before activation:** set `ANTHROPIC_API_KEY` on Railway service `Job-Visualizer-Notifier` (feature dormant + safe until then; auto-recovers after).
- **Follow-ups:** partial index on `normalization_status` (CONCURRENTLY) once backlog drains; document the `%2F`-in-raw_text proxy edge for alias-override callers; deferred type/comment polish.

---
