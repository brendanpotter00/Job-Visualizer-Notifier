# Incident: Eightfold First-Fetch Hit CardinalityViolation, Self-Healed via Procrastinate Retries

**Date:** 2026-05-20
**Severity:** Low
**Impact:** The first periodic Eightfold fan-out tick after merging PR #124 ("Move Eightfold to Backend Cron + Queue", `a9cbf2d`) crashed twice with `psycopg2.errors.CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row a second time` on the only enabled Eightfold company (`netflix`) before succeeding on attempt 3 at 19:11:26Z (`seen=591 new=591`). Net user-facing impact: ~2 minutes of stale data on the brand-new Eightfold column of the Why page. No data loss. Procrastinate's `RetryStrategy(max_attempts=5, exponential_wait=2)` budget fully absorbed the failure with three attempts to spare. Would have recurred on every 30-minute tick (~2 wasted attempts, ~1 minute added latency per tick) until fixed.

## Summary

Eightfold's `/api/apply/v2/jobs` endpoint paginates by offset (`start=0, 10, 20, …`, server-side cap of 10 rows/page). On a live tenant like Netflix's 591-position board, new postings get added near the front of the dataset between page fetches and existing positions shift to higher offsets. A single underlying position can therefore appear on two adjacent pages of a single walk. The transformer (`src/backend/api/services/eightfold_client.py::transform_to_job_listings`) did not dedup, so both copies landed in the list passed to `upsert_jobs_batch`. PostgreSQL's `ON CONFLICT (source_id, id) DO UPDATE` clause cannot touch the same composite primary key twice in one statement and raises SQLSTATE 21000 (`cardinality_violation`). The whole batch fails atomically; the task retries; on a later attempt the page boundaries happen to land differently and no duplicate is emitted.

The pattern is genuinely Eightfold-specific today — the other backend-cron ATSes (Greenhouse, Ashby, Lever, Gem) use a single canonical `id` field per row and don't paginate by shifting offsets. But the `upsert_jobs_batch` failure mode is class-wide: any future ATS whose transformer emits a duplicate composite key would crash the same way, including the existing scrapers (Apple/Google/Microsoft) if their transformers were to regress.

## Timeline

| Time (UTC)        | Event |
|-------------------|-------|
| 2026-05-20 18:57:00 | PR #124 (`a9cbf2d`) merged. Vercel and Railway both deploy successfully. Migration `b29c1ef88006 → 08e719b2aa03` (add `provider_config` JSONB column, seed Netflix row) applies cleanly. Worker reboots with `queues=['greenhouse_fetch','ashby_fetch','lever_fetch','gem_fetch','eightfold_fetch'], concurrency=5`. |
| 2026-05-20 19:09:15 | `enqueue_eightfold_fan_out` (periodic `*/30 * * * *`) fires for the first time. Defers `fetch_eightfold_company[6459]` for `company_id='netflix'` with `provider_config={tenant_host:'explore.jobs.netflix.net', domain:'netflix.com'}`. |
| 2026-05-20 19:09:42 | Attempt 1 fails after 27.5s: `psycopg2.errors.CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row a second time`. Status `Error, to retry`. |
| 2026-05-20 19:10:06 | Attempt 2 starts. |
| 2026-05-20 19:10:34 | Attempt 2 fails after 29.4s — same error. Status `Error, to retry`. |
| 2026-05-20 19:10:57 | Attempt 3 starts. |
| 2026-05-20 19:11:26 | Attempt 3 SUCCESS: `fetch_eightfold_company netflix: seen=591 new=591 closed=0`. All 591 Netflix positions land in `job_listings` with `source_id='eightfold_api'`, all OPEN, `last_seen_at=19:11:24Z`. |
| 2026-05-20 ~19:15 | Side-finding surfaced during deploy verification of PR #124. No alerts fired (system self-healed before any monitor noticed). |

## Root cause

Two issues compounded; either alone would not have caused the symptom.

### 1. `transform_to_job_listings` did not dedup

The transformer at `src/backend/api/services/eightfold_client.py:288-326` built the output list with a straight `for raw in raw_positions` loop. Each raw position passed through `_extract_eightfold_id`, which returns the first non-empty of `id`, `ats_job_id`, `display_job_id`. When the upstream API returned the same underlying position twice (pagination drift) or two different positions sharing an `ats_job_id`/`display_job_id` (id fallback chain collapse), both rows ended up in the output list.

The Eightfold transformer was ported from the deleted `src/frontend/src/api/transformers/eightfoldTransformer.ts`, which also had no dedup pass. The frontend tolerated this because its consumer was an in-memory normalized map (`byCompany` in `jobsApi.ts`) where a duplicate id silently overwrites — exactly the behavior we now want at the SQL boundary.

### 2. `upsert_jobs_batch` was not defense-in-depth

The shared bulk upsert at `scripts/shared/database.py:356-402` used `execute_values(..., ON CONFLICT (source_id, id) DO UPDATE SET …)`. PostgreSQL semantics: within a single statement, `ON CONFLICT` cannot target the same constraint-row twice. When two rows in the VALUES list collapse onto the same `(source_id, id)`, the database raises SQLSTATE 21000 (`cardinality_violation`) and the whole batch fails atomically — none of the 591 rows landed. The function had no pre-execute dedup pass before this incident.

## Why retries worked

Eightfold's offset-paginated walk is sensitive to dataset mutation between page boundaries. Attempt 1 saw drift; attempt 3 happened to walk the dataset in a window where no relevant mutations had landed. The retry budget (5 attempts with `exponential_wait=2`: T+0, +2s, +4s, +8s, +16s) covered ~30 seconds, which was enough for the upstream board to settle. This will not always be the case on a more-frequently-edited board, and the wasted ~1 minute per tick was real cost we should not pay long-term.

## Fixes applied

### Shared upsert dedup pass (defense-in-depth) — `scripts/shared/database.py`

`upsert_jobs_batch` now skips later occurrences of the same `(source_id, id)` and logs `WARNING` with the dropped count and the source_ids involved. This makes the class-wide failure mode unreachable from any ATS, present or future. The dedup pass is silent on the happy path — no log noise when the input is already unique.

### Eightfold transformer dedup with drift-vs-collision diagnostic — `src/backend/api/services/eightfold_client.py`

`transform_to_job_listings` dedupes by `job_id` and distinguishes two cases:

- **Pagination drift** (same `job_id`, same `(title, url)`) is logged `INFO` — expected behavior on a live offset-paginated tenant. Quiet enough that a non-incident doesn't generate alert noise but visible enough to diagnose if it ever spikes.
- **Id fallback chain collapse** (same `job_id`, different `(title, url)`) is logged `WARNING` with both `(title, url)` pairs. This is silent data corruption: two genuinely distinct positions are being merged onto one row in `job_listings`, and we need both halves of the merge visible in logs so it's investigable without a DB query.

## What is NOT changed

- **`RetryStrategy` on `fetch_eightfold_company`.** Still `max_attempts=5, exponential_wait=2`. The transformer + upsert dedup means attempt 1 will succeed; the retry budget remains correctly sized for legitimate transient HTTP/DB failures.
- **The `_extract_eightfold_id` fallback chain itself.** Removing the chain would drop rows that legitimately have only one of the three id keys (a small but real fraction of Eightfold tenants). The chain is correct; what was missing is dedup *after* the chain runs.
- **The `seen_ids` set in `fetch_eightfold_company.py:121`.** Already a set so `update_last_seen` is naturally idempotent; the bug only manifested at the bulk-upsert SQL boundary.
- **Other ATS transformers** (Greenhouse, Ashby, Lever, Gem). They use single canonical id fields with no fallback chain, so they don't have the symptom today. The shared upsert dedup pass covers them as defense-in-depth without needing per-transformer changes.

## Lessons

- **Class-wide failure modes in shared utilities deserve defense-in-depth even when only one caller is currently triggering them.** `upsert_jobs_batch` is the single bottleneck through which every provider's data lands; making it tolerant to per-batch duplicate keys is cheap insurance against a future regression in any transformer.
- **Offset-paginated APIs on live boards always need post-fetch dedup.** This applies to any future ATS adapter that doesn't have a cursor-based API. The pattern is easy to miss because it's fine on a small or static test board and only manifests when the upstream dataset is mutating during the walk.
- **Procrastinate retries hide first-fetch correctness bugs.** Without the deploy-time log audit, the failure would have been invisible until it became a real problem (e.g., a future ATS where retry doesn't happen to converge). Continue auditing first-fan-out logs on every new ATS launch.
- **`@level:error` Railway filter is your friend for "did anything quietly break after the deploy."** Filtering for `CardinalityViolation` surfaced this in seconds; a generic "look at logs" approach would have buried it under a mountain of normal task chatter.

## References

- **Trigger PR:** #124 (`a9cbf2d`), "Move Eightfold to Backend Cron + Queue".
- **Fix branch / PR:** `fix/eightfold-upsert-cardinality-violation` (this work).
- **Related incident:** `2026-05-19-procrastinate-worker-died-on-dns-blip.md` — different failure mode (worker death), but same diagnostic technique (Railway log audit after deploy verified the system was self-healing without alerting).
- **Code touched:**
  - `scripts/shared/database.py:370+` (upsert_jobs_batch dedup pass)
  - `src/backend/api/services/eightfold_client.py:288-380` (transform_to_job_listings dedup + drift/collision logs)
  - `scripts/tests/integration/test_database.py` (new `TestUpsertJobsBatchDedup`)
  - `src/backend/api/tests/test_eightfold_client.py` (new `TestTransformDedup`)
- **Eightfold pagination behavior:** empirically verified 2026-04-18; module constants at `src/backend/api/services/eightfold_client.py:60-67` (page cap of 10, MAX_PAGES=100).
- **PostgreSQL ON CONFLICT cardinality rule:** https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT
