# Incident: Apple scraper single-paged for 3.5 days (pagination selector broke)

**Date:** 2026-08-28 (failure began), 2026-08-31 (root cause identified & fixed)
**Severity:** High (not Urgent — no data was lost; the safety guard held)
**Impact:** From 2026-08-28 the Apple scraper returned **15–17 jobs per run instead
of ~3,350**, on ~21 runs/day. Every run tripped the `empty_scrape` safety guard
(`skipped_update=true`, `guard_reason='empty_scrape'`, `error_count=1`), so no
Apple data was ingested, refreshed, or closed for 3.8 days. Apple's 3,357 OPEN
rows in `job_listings` went **stale, not falsely closed** — `max(first_seen_at)`
for an OPEN Apple row froze at `2026-08-27T23:15:48Z`. The guard did exactly its
job; the failure is that nothing alarmed while it did.

## Summary

Apple redesigned its careers-site pagination control into an **icon-only chevron
button with empty text content** — the accessible label now lives only in
`aria-label="Next Page"`. The scraper's pagination probe,
`apple_jobs_scraper/parser.py::check_has_next_page`, selected the control by its
text with Playwright's `button:has-text("Next Page")`. `:has-text()` matches on
`textContent`, which is now `""`, so the selector matched **nothing**,
`check_has_next_page` returned `False`, and `scrape_query` broke out of the
pagination loop after page 1 — collecting one page (20 cards → ~17 after the title
filter) of a ~226-page board on every run.

Two distinct defects:

1. **The selector** — a text-content match against a control that no longer has
   text (the outage).
2. **The monitoring blind spot** — a scraper that collapses to a small *non-zero*
   number and is guard-blocked was invisible to every health check, because they
   all ask "did anything come back?" and none asked "did the run actually *do*
   anything?". This is why it ran 3.5 days unnoticed.

## Timeline (from `scrape_runs`, prod)

The break landed inside a 72-minute window with nothing in between.

| Time (UTC)            | jobs_seen | Duration | skipped_update | Event |
|-----------------------|-----------|----------|----------------|-------|
| Aug 19–27             | 3,300–3,373 | ~1,150–1,300s | false | Healthy — walks all ~226 pages |
| **2026-08-28 00:27:28** | 3,356   | 1,312s   | false | **Last healthy run** |
| **2026-08-28 02:01:28** | 13      | 3s       | true (`empty_scrape`) | **First broken run** — stops after page 1 |
| Aug 28 (rest)         | 8–17      | ~3s      | true (ALL) | Guard blocks every run |
| Aug 29–31 (~21/day)   | 15–17     | ~3s      | true (ALL) | 81 consecutive `empty_scrape` skips by 2026-08-31 |

`jobs_seen` of 15–17 is exactly one page: `JOBS_PER_PAGE = 20`, page 1 renders 20
cards, and the INCLUDE/EXCLUDE title filter drops 3–5. A clean page-1 count (not
0) is what ruled out a card-selector break and bot-blocking — both of those give 0.

## Root cause 1 — text-content selector against an icon-only button

`check_has_next_page` before the fix:

```python
next_button = await page.query_selector('button:has-text("Next Page")')
if not next_button:
    return False
is_disabled = await next_button.get_attribute("disabled")
return is_disabled is None
```

Apple's live pagination markup, captured 2026-08-31 (a real browser, against
`https://jobs.apple.com/en-us/search?location=united-states-USA`):

```html
<nav class="rc-pagination" aria-label="Results pagination" id="search-pagnation">
  <button class="icon icon-chevronstart" disabled aria-disabled="true"
          aria-label="Previous Page"></button>
  <input id="pagination-search-page-number" type="number" value="1">
  <span class="rc-pagination-delimiter">Of</span>
  <span class="rc-pagination-total-pages" data-autom="paginationTotalPages">226</span>
  <button class="icon icon-chevronend" aria-label="Next Page"></button>
  <!-- textContent === "" -->
</nav>
```

Reproduced end to end: enumerating all 108 buttons on the page, the number whose
text contains "Next Page" is **0**. The card selector
`ul[aria-label="Job Opportunities"] > li` still returns exactly 20; URL pagination
(`&page=2`, `&page=50`) still returns unique ids; plain `curl` gets HTTP 200 with
server-rendered job HTML. The *only* thing broken was the Next-button probe.

This was an **Apple-side change, not ours**: the last commit touching
`apple_jobs_scraper/` before the break (`b1783878`, 2026-08-26) only changed
posted-date handling; `check_has_next_page` was untouched since the scraper
landed apart from a return-type annotation.

**Prior art:** Apple has moved this markup before. A prod audit caught Apple
*truncating* 7 times in 21 days (2026-07-07 → 07-28); the `partial_scrape` guard
rule (b) exists because of Apple. This is the same scraper failing the same way,
now permanent rather than intermittent.

## Root cause 2 — the monitoring blind spot (why it took 3.5 days)

`scraper-health-watch` (runs every 3h) never referenced `guard_reason`,
`skipped_update`, or `empty_scrape`. Check by check, against the Apple shape:

| Check | Why it missed Apple |
|---|---|
| A1 — staleness | `last_ok = max(started_at) FILTER (WHERE jobs_seen > 0)`. Apple returned 17 (>0), so `last_ok` was always minutes old. Measured: 0h stale under the old filter vs **91h** under the fix. |
| A2 — silent-zero | Fires on the last 3 runs being all **zero**. Apple's were 15–17. |
| D — coverage collapse | `... AND jobs_seen > 0` counted Apple as scraped-ok. |

Also latent: `resolve_safety_guard`'s bounded auto-release counts `partial_scrape`
only (`incremental.py::count_consecutive_partial_skips`). **`empty_scrape` has no
auto-release and latches forever** — this could not self-heal; it needed a code
fix *and* an alarm.

## What is NOT broken (each verified)

| Suspect | Verdict |
|---|---|
| Card selector `ul[aria-label="Job Opportunities"] > li` | Fine — 20 cards live |
| `h3 a` title/href extraction | Fine — ids/URLs intact |
| URL pagination (`&page=N`) | Fine — unique ids per page, no overlap |
| Bot-blocking / rate limiting | No — `curl` → HTTP 200, 330 KB of job HTML |
| The safety guard | Working as designed — it blocked the empty result, preventing mass closure |
| Our own code | No — no relevant change since the scraper landed |

## Fixes applied

### 1. Select the Next control by accessible name (`parser.py`)

```python
next_button = await page.query_selector('button[aria-label="Next Page"]')
if not next_button:
    return False
disabled = await next_button.get_attribute("disabled")
aria_disabled = await next_button.get_attribute("aria-disabled")
return disabled is None and aria_disabled != "true"
```

Honours **both** disabled encodings Apple sets on the last page (`disabled=""` and
`aria-disabled="true"`); the `disabled` attribute is present as an empty string,
so presence (`is None`), not truthiness, is the correct test. Verified live:
returns `True` on page 1 (keeps paginating) and `False` on page 226 (loop
terminates — no walk to `MAX_PAGES`).

### 2. Make a truncated walk loud (`parser.get_total_pages` + `scraper.scrape_query`)

The scraper now reads Apple's own advertised page count
(`.rc-pagination-total-pages` → 226) once on page 1 and logs a distinct
`SCRAPER TRUNCATION (apple)` **error** when the walk ends far short of it. A
one-page result on a 226-page board is no longer indistinguishable from a genuine
one-page board — the indistinguishability that let this run 3.5 days. `MAX_PAGES`
250 → 300 for headroom; hitting the cap is now covered by the same loud check.

### 3. Pin the markup in tests

- `tests/unit/test_apple_pagination_markup.py` (per-PR, browser-free): pins the
  aria-label selector and both disabled encodings; a revert to `:has-text` fails.
- `tests/e2e/test_apple_pagination_markup_e2e.py` (`-m e2e`, real Chromium via
  `set_content` against the captured markup): asserts the old `:has-text("Next
  Page")` selector finds nothing (the root-cause pin) and the fix returns
  True/False on the middle/last page.

### 4. Close the monitoring blind spot (`scraper-health-watch/SKILL.md`)

- **New Check A3 — latched guard** (CRITICAL, key `guard_latched:<company>`): the
  last 4 runs all `skipped_update`. 4 = `SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS`(3)+1,
  so a normally auto-releasing `partial_scrape` can never trip it — only a
  non-releasing `empty_scrape` latch. Validated on prod: fires on **exactly
  apple** (81 consecutive `empty_scrape` skips), zero other companies.
- **A1 fix:** `last_ok` filter gains `AND skipped_update IS NOT TRUE` — a run that
  wrote nothing is not an "ok" run. This alone flips Apple from 0h → 91h stale.
- **Check D** gains the same clause for consistency.

## Verification

```sql
-- recovery: recent runs unguarded and back to full volume
SELECT started_at, jobs_seen, error_count, skipped_update, guard_reason
FROM scrape_runs WHERE company = 'apple'
ORDER BY started_at::timestamptz DESC LIMIT 10;

-- new Apple rows arriving again (was frozen at 2026-08-27T23:15:48Z)
SELECT count(*) FILTER (WHERE status='OPEN') AS open_rows, max(first_seen_at)
FROM job_listings WHERE company='apple';
```

**Recovery caveat:** the first post-fix run closes 3.8 days of genuinely-gone
Apple jobs at once and ingests 3.8 days of new ones. If more than ~15% of 3,357
(~504 rows) genuinely disappeared during the blind window, that run itself trips
`partial_scrape` and skips — the guard doing its job. Read `jobs_seen` (should be
~3,350), not the guard, to judge the fix; recovery may need a second run.

## Lessons

1. **Never select an interactive control by its visible text when an accessible
   name exists.** Text is presentational and Apple changed it to an icon; the
   `aria-label` is the contract. The other four script scrapers are all
   `:has-text`-shaped — worth auditing (filed separately).
2. **A guard that fires silently is half a system.** The `empty_scrape` guard
   correctly prevented mass closure but had no alarm; "prevented harm" read
   identically to "healthy" for 3.5 days. Every "did it come back?" check needed a
   paired "did it *do* anything?" check (A3).
3. **A latch with no auto-release must have an alarm**, because it will never
   self-heal — the two properties have to ship together.
