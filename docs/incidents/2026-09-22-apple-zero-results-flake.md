# Incident: Apple scraper dark, one flaky page abandoned every ~228-page walk

**Date:** 2026-09-22 ~16:09Z (failure began), 2026-09-23 (root cause identified & fixed)
**Severity:** High (not Urgent: no rows were falsely closed; the guards held)
**Impact:** Every Apple run from 2026-09-22 16:09Z onward failed. The last good
run was 14:39Z (3,377 jobs). No Apple data was ingested, refreshed or closed
after that. The 3,377 OPEN rows went **stale, not falsely closed**. Runs that
failed on page 2 or later raised `SCRAPER TRUNCATION` and recorded an errored
run. Runs that failed on page 1 returned 0 jobs and tripped the `empty_scrape`
guard, which the health-watch then reported as a latched guard heading for
CRITICAL.

## Summary

Apple's search backend began **intermittently answering the unchanged US-board
query with its zero-results template**: HTTP 200, the normal page title,
`totalRecords: 0` in the hydration data, and
`<div id="search-no-search-results">There are no results that match your
search.</div>` where the job list should be. Requesting the same URL again
returns the real 20 listings.

It is not a block page, a markup change, or a board move. The captured bad page
is byte-identical every time (197,538 bytes vs ~328 KB for a real page), the
job-list markup on good pages is unchanged, and an immediate reload recovered
every occurrence observed.

The scraper had **zero tolerance** for it. `extract_job_cards_from_list` waited
10s for `ul[aria-label="Job Opportunities"]`, timed out, and raised
`JobCardExtractionError`. `scrape_query` treated that as fatal: it `break`s out
of the walk, and the post-loop truncation guard (added after the 2026-08-28
incident) then raised. So **one bad page threw away the whole run**. A full walk
is ~228 pages, so the odds of finishing are `(1 - p)^228`:

| per-page flake rate `p` | chance a full walk finishes |
|---|---|
| 0.1% | 80% |
| 1% | 10% |
| 10% | ~0.000000004% |

That is why the failure was a cliff, not a slope: ~40 consecutive clean walks,
then none. It also explains the pattern the health-watch saw ("page walk
collapsing run-over-run: 9 pages -> 2 -> 0"). Where the first bad page lands is
random, and at ~10% it is usually within the first few pages.

## Timeline (Railway logs)

| Run (UTC) | Outcome |
|---|---|
| 09-18 18:45 → 09-22 14:39 | every run walked all 228–231 pages; 3,366–3,418 jobs |
| 09-22 16:09 | failed on page 49 (walked 48 of 228) |
| 09-22 17:26 | page 18 |
| 09-22 18:38 | page 9 |
| 09-22 19:48 | page 3 |
| 09-22 21:00 | page 1 → returned 0 jobs → `empty_scrape` guard |
| 09-22 22:11 | page 2 |
| 09-22 23:22 | page 3 |
| 09-23 00:33 | page 1 → `empty_scrape` guard |

No deploy happened in the window: the last Railway deploy was 09-18, and it
ran clean for four days. The change was on Apple's side.

## Diagnosis

The health-watch concluded "Apple is blocking/throttling our headless client;
needs UA/proxy". That was a reasonable guess from the outside, since plain curl
worked and Playwright on Railway didn't, but it was wrong. Reproducing with the
scraper's exact browser config (headless Chromium, the same UA, launch args and
`domcontentloaded` wait) from a different network hit the same failure about 1
page in 7–10. Dumping the DOM at the moment of failure showed Apple's own
zero-results page, not an Akamai/bot block page. A reload fixed it every time.

The scraper never logged what the page actually contained, only
`Timeout 10000ms exceeded`, so a transient backend miss looked the same as a
selector break or a block.

## Fix

`scripts/apple_jobs_scraper/`:

1. **`parser.py`**: `extract_job_cards_from_list` waits for **either** the job
   list or `#search-no-search-results`, so the zero-results page is recognised
   as soon as it renders, not after a 10s timeout. It then raises a distinct
   `ZeroResultsPageError`. That subclasses `JobCardExtractionError`, so any
   caller that doesn't know it still treats the page as unreadable, never as
   "no more jobs".
2. **`scraper.py`**: new `_load_page_cards` retries **the same page** up to
   `PAGE_MAX_ATTEMPTS` (5) times, on a fresh Playwright page each time, with
   growing backoff (`PAGE_RETRY_BACKOFF_S` = 3/8/20/45s plus jitter). It
   retries navigation errors, unreadable lists, zero-results pages and empty
   lists alike. At a 10% per-attempt flake rate this leaves ~0.2% odds of
   losing a 228-page run.
3. **Never skip a page.** The old nav-error path moved on to `page_num + 1`,
   silently dropping that page's ~20 jobs from a run that could still pass the
   truncation slack. When all attempts fail, `_load_page_cards` now raises
   `JobSearchError` (`SCRAPER PAGE FAILURE (apple): page N failed all 5
   attempts; last: ...`), naming the actual cause.
4. **Page 1 is no longer special.** A page-1 failure used to return `[]`,
   because Apple's page count hadn't been read yet so the truncation check was
   skipped. That tripped the `empty_scrape` guard and looked like a latched,
   empty board. It now raises like every other page and records an errored
   run.
5. The completion log line reports how many page retries the walk needed
   (`Completed Apple scrape: N jobs collected (K page retries)`), so a rising
   flake rate is visible in the logs before it becomes an outage again.

## Verification

- Unit/integration tests pin every piece: the either-selector wait, the
  distinct error, same-page retry, increasing backoff, a fresh page per retry,
  never skipping ahead, a page-1 failure raising, and exhausted retries
  raising (`tests/unit/test_apple_parser_mocked.py`,
  `tests/integration/test_apple_scraper_async.py`).
- A live full-board walk with the patched `scrape_query` against
  jobs.apple.com completed despite the flakes (see the PR for the numbers).

## What to watch

- `(K page retries)` in the `Completed Apple scrape` log line. A handful per
  run is Apple's normal flake. Dozens means Apple's backend is degrading, or
  starting to throttle, and a slower `_random_delay` is the next lever.
- `SCRAPER PAGE FAILURE (apple)` in the logs means one page failed 5 times
  running over ~80s. That is no longer a one-off flake.
