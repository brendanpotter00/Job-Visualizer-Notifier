# Incident: Recent Jobs Page Reports "No Jobs Found" for SWE Filters While 116 Matches Exist

**Date:** 2026-08-10 (trigger deployed ~15:23 UTC with the Amazon scraper's first import; root-caused and fixed same day)
**Severity:** High (user-facing: the site's core filter combination — Software Engineering + New Grad/Entry — returned zero results for every user)
**Impact:** Any Recent-page filter selective enough to match nothing in the newest ~90 minutes of rows rendered a terminal "No jobs found matching your filters" with no way to load older pages. Software Engineering + New Grad/Entry at a 90-day window showed 0 jobs while 116 matching OPEN rows existed in the window. The page's own metrics made the lie visible: 1022 jobs "Past 24 Hours" and an identical 1022 "Past 3 Hours" (the clamped set only reached ~90 minutes back).

## Summary

Three independent mechanisms stacked:

1. **Trigger — Amazon initial import.** The Amazon scraper (merged 2026-08-10) imported its full catalog in one run: 1,291 rows, every `first_seen_at` within minutes of 15:23 UTC, none enriched.
2. **Amplifier — the complete-prefix clamp.** The Recent page loads via three per-company-chunk keyset walks (1,000 rows per chunk per page, ordered `first_seen_at DESC`) and clamps the merged set at the shallowest still-walking chunk's floor (`computeCompleteHorizon`, `keysetWalk.ts`) so no company is silently underrepresented. Amazon's chunk filled its entire first page from that single import minute, pinning the horizon to ~15:23 — collapsing the whole page's visible dataset from ~6 days to ~90 minutes of (almost entirely unenriched) rows.
3. **The bug — empty-state early return unmounts the walk.** `RecentJobsList.tsx` early-returned the terminal `EmptyJobListState` whenever the filtered list was empty (unless a fetch was mid-flight or auto-fetching had stopped short). That return unmounts the infinite-scroll sentinel — the only trigger that advances the keyset walk. Zero matches on page 1 therefore meant the walk could never fetch page 2: the empty-fetch budget (`MAX_EMPTY_AUTO_FETCHES`) never spent, the "Search older jobs" affordance never appeared, and the page reported "No jobs found" forever.

The deadlock existed for any zero-match first page; the Amazon flood merely made zero-match first pages near-certain for every selective filter.

## Contributing factor: enrichment lag (job-enricher — separate repo, not fixed here)

The category/level filters match only enriched rows, and the entire clamped ~90-minute window was unenriched — guaranteeing the zero-match page 1. A read-only investigation of the laptop enricher (live service = the prod checkout at `~/developer/personal/app`, launchd `com.bp.job-enricher`) found it alive (524 sidecar writes in the 24h before diagnosis; last write 16:44 UTC) but with two real defects of its own:

1. **41-hour poison-pill crash loop (Aug 8 00:00 → Aug 9 16:52 UTC).** The local qwen3:32b model emitted items whose `job_listing_id`/`source_id` were dicts; the recorders hash those values with no scalar guard (`TypeError: unhashable type: 'dict'`, 864 occurrences in `~/Library/Logs/job-enricher.err`). The per-chunk handler catches only `EngineError`, so every tick crashed; at temperature 0 the same queue reproduced the same malformed output — a deterministic loop of ~11 ticks/hour, each claiming 40 jobs server-side and completing 0 (~440 claims/hour abandoned — the origin of the 1,396 stuck-`claimed` rows). It ended only because the laptop rebooted. **Every crashing tick still reported `status=ok`**, so no watchdog fired.
2. **Claim-then-discard churn (ongoing).** Each tick's `/pending` pull claims 40 rows server-side, but the local store silently skips rows already mid-flight locally (1,588-row local `cleaned` backlog), so ~25–38 claims/tick are abandoned to the TTL reclaim by design.

Effective throughput is hard-capped at ~40 jobs/~2h tick ≈ ~500/day — a 1,291-row import is ~2.5 days of capacity, and the 18.7k unenriched backlog (~37 days at zero influx) is structural. Fix recommendations (harden recorders to coerce scalars + per-item try/except; skip the pull while the local backlog exceeds the per-tick cap; mark crashed ticks `status=error` so the watchdog can see them; raise capacity) are tracked in the job-enricher repo, not this one.

## Root Cause (the fixed defect)

`src/frontend/src/components/recent-jobs-page/RecentJobsList/RecentJobsList.tsx`:

```tsx
if (jobs.length === 0 && !isLoadingMore && !showContinueAffordance) {
  return <EmptyJobListState />;   // unmounts the sentinel => walk can never advance
}
```

`showContinueAffordance` requires `emptyFetchStreak >= MAX_EMPTY_AUTO_FETCHES` — a counter that only increments when the sentinel fires a fetch. The early return removed the sentinel before it could ever fire, so the guard that was supposed to hand control back to the user was unreachable. Terminal state, entered on a transient condition.

## Fix

PR `fix/recent-jobs-empty-filter-deadlock`:

- The terminal empty state now additionally requires `!hasMoreServer` (walk exhausted). With cursors outstanding, the list stays mounted at zero rows: the sentinel fires, the walk auto-deepens under the existing `MAX_EMPTY_AUTO_FETCHES` budget, then the existing "Search older jobs" affordance takes over.
- New status line (`SEARCHING_OLDER_JOBS_IN_PROGRESS`) renders while the list is empty and deepening (signed-in only — signed-out users never page), so users see progress instead of bare skeletons. Not a `role="status"` live region: the loading skeletons already announce the activity.
- Regression tests fire the sentinel only while it is genuinely in the DOM (`fireSentinelWhileMounted`), so the deadlock tests fail on the pre-fix component instead of simulating fires a browser could never produce.
- **Adversarial review follow-through (same PR):** the review surfaced the same deadlock template one layer down — a **failed window-widening restart** claimed the new window (cursors cleared) *before* awaiting its pages, with no rollback, leaving a terminal "No jobs found"/"All N loaded" over a transient network error, the latched error never rendered, and retry a silent no-op. Fixed: the widen claim rolls back on failure (regression test in `jobsApi.keyset.test.ts`). Also fixed: the sentinel/manual advance path now honors the `firstPageSettled` gate, so a widen can no longer fire mid-initial-stream and discard the in-flight page-1 load (the sentinel firing at t≈0 was new exposure from this fix).

## Verification

- Full frontend suite: 1,890 tests / 157 files green; type-check and lint clean.
- Browser validation against production data (local Vercel Dev via `lvh.me` so the serverless proxies target the Railway backend): SWE + New Grad/Entry at 90 days auto-deepens past the Amazon flood and renders matching jobs instead of the terminal empty state.

## Lessons / Follow-ups

1. **A terminal UI state must be provably terminal.** "No results" was rendered on a condition ("nothing visible *yet*") that the component itself had the means to change. Any early return that unmounts the machinery that could invalidate it is a deadlock template.
2. **Initial imports are horizon floods.** Any newly onboarded high-volume company will pin the complete-prefix horizon to its import minute until its chunk's cursor exhausts. The walk now digs itself out, but onboarding a very large board (10k+ rows) would still burn several auto-fetch pages on one company. Consider backfilling `first_seen_at` from the ATS posting date on a company's *first* scrape, or excluding a chunk's page-1-of-first-import from horizon math.
3. **Enricher capacity vs. import size.** A one-shot 1,291-row import is ~2.5 days of enricher throughput; category/level filters are blind to those rows meanwhile. Worth a backlog alarm (claims abandoned/hour, done/hour vs. influx) on the admin enrichment page.
4. **Identical "Past 24 Hours" and "Past 3 Hours" counts are a clamp-collapse signature** — cheap to alert on client-side.

## Review follow-ups deliberately NOT fixed in this PR (pre-existing)

- **Wholesale page-1 failure masquerades as "no jobs found."** If the initial batched load fails entirely, no cursor is ever written, `hasMoreServer` is false from birth, and the terminal empty state renders with the only error signal buried in the progress-bar chips. Needs a real outage UX (gate the terminal state on the initial load having settled *and* not wholesale-failed).
- **Demo mode:** a demo filter matching zero curated jobs now shows the searching line and fires real (useless) pages, since `hasMoreServer` derives from the live cache while the rows come from `DEMO_JOBS`. Admin-only; wants a demo-mode escape in the list's conditions.
- **Budget miscount:** the empty-fetch streak increments before dispatch, and `inFlightRef` can silently swallow the dispatch (widening effect racing the sentinel), so the affordance can appear one page early. Return "actually fired" from `loadNextServerPage` and count only those.
- **Manual "Search older jobs" resets the streak to 0**, so one click buys up to `MAX_EMPTY_AUTO_FETCHES` more automatic pages (~3 chunk-requests × 1000 rows each), not one — the comment on `continueLoading` says "fetches once." Either fix the comment or set the streak to `MAX - 1` on continue. Backend headroom note: each page is 3 batched keyset requests, not the 49-request fanout of the 2026-05-17 pool-exhaustion incident.
- **Signed-out zero-match copy overclaims:** signed-out users get the terminal "No jobs found" while pages are outstanding (paging is auth-gated by design) and no hint that signing in searches deeper. Consider a "Sign in to search older jobs" variant.
