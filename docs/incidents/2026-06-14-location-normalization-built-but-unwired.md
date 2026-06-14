# Incident: Location Normalization Built End-to-End in the Backend but Never Surfaced to Users

**Date:** 2026-06-14 (latent since #145 shipped on 2026-06-08; reported 2026-06-14)
**Severity:** Low (no outage, no data loss; degraded filter UX + wasted normalization compute on an unread dataset)
**Impact:** The **Location** filter on the Recent Job Postings page (`/`) and the Companies page listed raw, un-normalized location strings as filter options — building/site codes (`Austin - 5323`, `Atlanta, GA (ATL-01)`, `Ashville, OH (Arsenal 1)`), verbose forms (`Austin, Texas, United States`), and — most damaging — semicolon-joined **multi-location** strings (`Austin, TX, USA; Atlanta, GA, USA`) each shown as a single, distinct option. Because options were exact raw strings, selecting "Austin" did **not** match a job whose raw location also listed Atlanta or Mountain View, and the same physical city appeared as a dozen near-duplicate options. The normalized tag data that would have fixed all of this **existed in the database** (built by #145) but was never read by any user-facing endpoint. Separately, ~75% of production jobs had not yet been normalized, so even the (unused) tag data was incomplete.

## Summary

PR #145 ("Location Normalization", merged 2026-06-08, commit `b8830a2`) built a complete, correct normalized-location subsystem:

- Four tables — `locations` (canonical: `canonical_name`, `kind`, `city`, `region`, `country`, `remote_scope`), `location_aliases` (raw→cache), `alias_locations` (alias→N canonical, ordered), and `job_locations` (job→N canonical, `is_primary`).
- A Claude Haiku 4.5 normalizer (`services/llm_client.py`) that strips building/site codes and parentheticals, reorders reversed inputs, and **splits a multi-location string into separate canonical tags**.
- A two-tier cascade (Postgres alias cache → LLM) with a periodic `scan_unnormalized` drainer.
- An on-demand golden-set **eval** (`api/eval/`) that scores normalization quality and models multi-location as an order-independent **list** (it passed).
- Follow-up PRs added a read-only prod monitor and an admin "Location Normalization Monitor" page (`#149` branch).

All of that machinery produced clean canonical tags (`Austin, TX, US`) and stored them in `job_locations`. **Nothing consumed them for the user-facing product.** The jobs API (`GET /api/jobs`, `services/database.py::get_jobs`) still selected only the raw `job_listings.location` column; `JobListingResponse` exposed a single `location: str`; and the frontend dropdown selectors built options with `new Set(jobs.map(j => j.location))` over those raw strings. The normalization work was, from the user's perspective, a no-op — and worse, a no-op that cost real Haiku API spend on every scrape.

Two gaps compounded:

1. **Integration gap (headline):** the normalized tags were never plumbed from `job_locations` → `/api/jobs` → frontend filter. The feature was "done" in the backend and "invisible" in the product.
2. **Backfill gap:** `scan_unnormalized` drains ~28,800 jobs/day, and on a ~48k-row corpus the backlog was still ~75% NULL at report time. So the tag data that *did* exist covered only ~23% of jobs.

This was not a regression — the dropdown had *always* shown raw strings. #145 changed the **expectation** (locations are now a normalized, multi-valued tag) without changing the **read path** that the expectation depended on.

## Timeline

| Date | Event |
|------|-------|
| 2026-06-08 | #145 (`b8830a2`) merges: `locations` / `location_aliases` / `alias_locations` / `job_locations` tables, the Haiku normalizer, the alias cache, `scan_unnormalized`, and the golden-set eval. The eval passes (multi-location modeled as a list). `scan_unnormalized` begins draining the ~44k-row NULL backlog at ~28,800/day. |
| 2026-06-08 → 06-14 | Backlog drains steadily in the background. No user-facing surface changes — `/api/jobs` and the frontend continue to serve/render the raw `location` string. |
| 2026-06-13 | Prod monitor + formal runbook (#149, `7438520`); admin Location Normalization Monitor page (`d15286a`). Eval baseline captured. These verify the **pipeline**, not the **product surface**. |
| 2026-06-14 ~15:00 | User reviewing the live Recent Jobs **Location** dropdown notices many Austin variants and that semicolon-joined pairs (`Austin, TX, USA; Atlanta, GA, USA`) are treated as single, unique filter options that don't behave like tags. |
| 2026-06-14 ~15:20 | Investigation (code + prod via read-only Postgres MCP) establishes: the schema and eval **already** model locations-as-tags correctly and the normalizer already produces clean canonical names; the gap is that `/api/jobs` never exposes `job_locations`, and ~75% of jobs are still NULL. Prod snapshot: 48,073 jobs; 36,163 NULL (24,349 OPEN); 11,085 `done`; 825 `failed`; 1,521 distinct raw location strings; only 1,413 distinct unnormalized (~620 already cached). |
| 2026-06-14 ~15:35 | Confirmed the backfill is healthy and actively draining (`latest_alias_at` ~2 min before `now()`; NULL fell to 35,363 and `done` rose to 11,670 within the session) — i.e. `ANTHROPIC_API_KEY` is set and the worker is running; the 75% NULL is backlog, not a stalled pipeline. |
| 2026-06-14 ~16:00 | Fix implemented on the `feature/location-normalization-monitor` branch: expose canonical tags in the jobs API (SQL-aggregated, primary-first), consume them in the dropdown/filter/cards, add eval coverage for the flagged variants, and let the backfill complete before the dropdown ships. Validated against live prod data + `EXPLAIN ANALYZE`. |

## Root Cause

### Why the normalized tags never reached users

The read path and the write path were developed against **different mental models** of where a job's location lives, and nothing tied them together:

- **Write path (#145):** a job's locations live in the `job_locations` join — 0..N canonical rows per job. Multi-location strings are *split*. This is the model the schema, normalizer, and eval all encode.
- **Read path (pre-existing):** a job's location is the single `job_listings.location` TEXT column. `get_jobs` (`services/database.py`) selects it verbatim; `JobListingResponse.location` is one string; the frontend dedups raw strings into dropdown options and filters by exact string equality (`job.location === filterLoc`).

`#145` populated the new write-path model but left the read path untouched, so the product kept rendering the old single-string field. There was no failing test or error to flag the disconnect because **raw strings render perfectly fine** — the dropdown "worked," it was just showing the wrong (un-normalized, un-split) values. The defect was a missing invariant: *the user-facing location filter must read from `job_locations`, not `job_listings.location`.* That invariant was never asserted anywhere.

### Why the existing tests and eval did not catch it

- The **unit tests** for normalization mock the LLM and assert the persistence layer writes `job_locations` correctly — they verify the write path in isolation.
- The **golden-set eval** scores the Haiku output against expected canonical tags — it verifies normalization *quality*, again with no reference to the API or frontend.
- The **jobs-router tests** asserted the shape of `JobListingResponse` as it was (single `location` string) — they codified the gap rather than catching it.
- No test asserted the **end-to-end** contract "a normalized job exposes its tags through `/api/jobs` and the dropdown shows them." Each layer was green; the seam between them was untested.

### Why ~75% of jobs were still NULL

`scan_unnormalized` is deliberately throttled (`SCAN_LIMIT=100`/tick, every 5 min ≈ 28,800/day) and **skips entirely when `ANTHROPIC_API_KEY` is unset** (a load-bearing safety so the NULL backlog stays dormant rather than churning). On a ~44–48k-row corpus the initial backfill takes ~1.5 days of wall-clock drain; intermittent periods without the key (or competing queue load) stretch that. At report time the pipeline was healthy and draining — 75% NULL was simply backlog-in-progress, not a stall. This was an *expected* steady-state of a young feature, but it meant a tag-only dropdown shipped prematurely would have hidden most jobs from location filtering.

## Detection

Manual: a user inspecting the live Location dropdown noticed the un-normalized, un-deduplicated, multi-location-as-one-option behavior. There was **no automated signal** — no alert, no failing test, no log error — because the system was behaving exactly as its (un-updated) read path was written. The prod monitor added in #149 watches pipeline health (backlog drain, integrity invariants) but has no notion of "are these tags actually surfaced to users."

## Resolution

Fixed on `feature/location-normalization-monitor` (no schema or normalizer change — both were already correct):

- **A. Backend:** `get_jobs` / `get_job_by_id` now aggregate each job's canonical tags as a camelCase JSON array via a correlated `json_agg` subquery on `job_locations` (`is_primary` first), exposed as `JobListingResponse.locations: list[JobLocationResponse]`. Verified against live prod (`Austin, TX, USA; Atlanta, GA, USA` → `[Austin, TX, US (primary), Atlanta, GA, US]`) and `EXPLAIN ANALYZE` (index probe on `job_locations_pkey`, ~46 ms for 5,000 OPEN jobs).
- **B. Frontend:** the Job model carries `locations: JobLocation[]`; dropdown builders flatten canonical names (collapsing all variants of a city into one option) and prepend a country-code-based "United States" meta-option; `matchesLocation` matches a job by **any** of its tags (multi-location aware) with **no raw-string fallback**; job cards display canonical tags.
- **C. Backfill:** confirmed the pipeline is draining; sequence the dropdown change to land after OPEN-job backfill is ~complete so coverage is near-full before the raw fallback is removed.
- **D. Eval:** added gating golden cases for the exact flagged variants (`Atlanta, GA (ATL-01)`, `Austin - 5323`, `Austin, Texas, United States`, `Austin, TX, USA; Atlanta, GA, USA`) to lock in the clean output. No scoring-logic change.

## Lessons / Action Items

1. **A feature isn't "done" until a user can see it.** "Built end-to-end in the backend" is not the finish line; the read path and a user-facing surface are part of the feature. Track features against an end-to-end acceptance criterion, not per-layer completeness. — *process*
2. **Add a seam test when a new write-path model replaces an old read-path field.** A single test asserting `/api/jobs` exposes `job_locations` tags (and the dropdown consumes them) would have failed loudly on day one. Owned by this PR. — **done**
3. **Surfacing is part of "definition of done" for normalization-style features.** When introducing a derived/normalized representation, the PR that creates it should either consume it or explicitly file the consume-it follow-up; an unread derived dataset is silent waste (here, Haiku spend on data nobody reads). — *process*
4. **Monitor the product surface, not just the pipeline.** The prod monitor watches backlog/integrity but not "tags are exposed and non-empty in the API." Consider a cheap synthetic check (e.g. a sample of OPEN jobs returns non-empty `locations`) once backfill completes. — *backlog*
5. **Sequence backfill before removing fallbacks.** Removing the raw-string fallback only after the OPEN backlog drains avoids a window where most jobs vanish from filtering. Captured in the rollout plan. — **done**

## Evidence (prod, 2026-06-14, read-only Postgres MCP)

```
total jobs:            48,073
  normalization NULL:  36,163  (75.2%)   — OPEN+NULL: 24,349
  done:                11,085
  failed:                 825
distinct raw locations: 1,521   (unnormalized: 1,413; ~620 already cached)
job_locations links:   12,556    canonical locations: 382
drain check (same session): NULL 36,163 → 35,363 ; done 11,085 → 11,670 ;
                            latest_alias_at ≈ now() − 2 min  → pipeline healthy
```

Example of the (correct, but unread) normalization the dropdown was *not* showing:

| Raw `job_listings.location` (shown in dropdown) | Canonical tags in `job_locations` (unused) |
|---|---|
| `Austin, TX, USA; Atlanta, GA, USA` | `Austin, TX, US` + `Atlanta, GA, US` |
| `Austin - 5323` / `Austin, Texas, United States` | `Austin, TX, US` |
| `Atlanta, GA (ATL-01)` | `Atlanta, GA, US` |
| `Ashville, OH (Arsenal 1)` | `Ashville, OH, US` |
