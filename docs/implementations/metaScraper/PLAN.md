# Add Meta (metacareers.com) as a custom "script" scraper — implementation plan

**Status:** PLAN (not implemented). This document is written so a fresh implementer with
zero prior context can build the whole feature by following it top to bottom.

**Goal:** add **Meta** as a sixth `ats='script'` company, scraped by a new
`scripts/meta_jobs_scraper/` package modeled on `scripts/tiktok_jobs_scraper/`. Meta has no
standard ATS. Its listings page (`https://www.metacareers.com/jobsearch`) is a client-side
SPA that hydrates from a **single GraphQL POST returning the ENTIRE ~890-job catalogue in one
shot** (no pagination). We scrape it with Playwright by sniffing the GraphQL response.

**Proven reference:** the user's other repo, **job-watcher**, already scrapes Meta
successfully. The working recipe lives in
`/Users/bpotter/developer/personal/job-watcher/src/job_watcher/adapters/meta.py`
(and `_playwright.py`). **Read it first** — this plan ports its pure logic almost verbatim
and re-homes it onto JVN's `BaseScraper` ABC. Nearly all the load-bearing functions
(`_iter_job_containers`, `_container_jobs`, `parse_list_job`, `_advertised_job_count`,
`_iter_job_counts`, `_is_truncated`, `_reduce_payloads`, `_SettlePoll`, `_finalize_capture`,
`_decode_graphql_payload`, `_empty_capture_reason`, `_capture_stats`, `_has_job_payload`)
are **pure** and copy across with only the return type changed from job-watcher's `RawJob`
to a plain dict "card".

**First cut is LIST-ONLY.** Job-watcher also fetches per-job detail pages (Relay island /
JSON-LD parsing, `_DETAIL_HEADERS`, `parse_detail_html`). We deliberately **defer all of
that** — mirroring TikTok/Amazon, `extract_job_details` returns `{}` and
`scrape_job_details_streaming` is a pass-through. `posted_on` is `None` for every Meta job
(the list query carries no date — same as TikTok).

---

## 0. The single most important invariant (read before anything else)

**An empty or short capture MUST raise, never return `[]` or a partial list.**

JVN's incremental lifecycle (`scripts/shared/incremental.py`) closes any OPEN job absent from
a scrape run after `MISSED_RUN_THRESHOLD` misses. A scraper that returns `[]` (or a truncated
list) during a transient outage is indistinguishable from "every Meta job is gone" and would
mass-close the board. This is the 2026-03-29 incident
(`docs/incidents/2026-03-29-mass-job-closure.md`) and it is exactly why TikTok/Amazon/Apple
"raise on an incomplete run, never return short". Meta must do the same:

- **No job arrays captured / all empty / nothing parsed →** raise `MetaCaptureError`.
- **Parsed count `< 0.9 × job_count` (Meta's own advertised total) →** raise `MetaCaptureError`
  (truncation guard — because Meta ships the whole catalogue in one response, a large
  shortfall means a truncated payload, not a shrinking board).

Because Meta returns everything in one GraphQL response, the `partial_scrape` guard in the
incremental algorithm (trips ~85%) does NOT protect against a payload that was 50% read — the
completeness guard against `job_count` is what closes that gap. `raise` propagates out of
`scrape_query` → `scrape_all_queries` → `run_incremental_scrape`, which records the failure
and re-raises **without running the destructive close phase**.

---

## 1. Scraper design

### 1.1 The capture flow (in `scrape_query`)

Meta has **no keyword search and no pagination** — one page load yields the whole catalogue.
So `get_search_queries()` returns a single sentinel `["all"]`, `scrape_all_queries` calls
`scrape_query` once, and `scrape_query` ignores the query text. The flow (ported from
job-watcher's `MetaAdapter.fetch_list`, adapted to `BaseScraper`, which already gives us
`self.context` from a headless Chromium):

1. `page = await self.context.new_page()` (the base class already launched Chromium with the
   anti-automation args and a desktop-Chrome UA — same profile job-watcher's `_playwright.py`
   uses, so the site behaves identically).
2. Attach a response handler **before navigating**:
   `page.on("response", on_response)`. The handler:
   - ignores anything whose URL does not contain `/graphql` or whose request method is not
     `POST`;
   - counts every GraphQL POST seen (`graphql_seen`, for diagnostics);
   - reads the body under an `asyncio.wait_for` timeout, JSON-decodes it via
     `_decode_graphql_payload`, and appends decoded dict payloads to a `captured` list;
   - **must never raise** (it runs fire-and-forget inside Playwright's event loop) — wrap the
     body read in `try/except`, log-and-return on failure.
3. `await page.goto(LIST_URL, wait_until="networkidle", timeout=_PAGE_TIMEOUT_MS)`.
   `networkidle` can time out on slow CDNs even after the results body already landed, so
   **catch the PlaywrightError, remember it as `nav_error`, and continue** — only surface it
   if the capture ends up empty.
4. **Settle-poll** with `_SettlePoll` (pure, unit-tested): poll `captured` every
   `_POLL_INTERVAL_S` until a payload carrying a **non-empty** job array lands (the *wait*
   phase), then keep polling a short *drain* until the captured count is stable. The
   non-empty requirement is load-bearing: the page emits strips (saved/featured searches)
   whose arrays can resolve empty first, and ending the poll on one of those tears the
   browser context down mid-read of the real payload.
5. Close the page (in `finally`, so it closes even when the loop raises — mirror TikTok's
   `try/finally` around `page.close()`).
6. Hand `captured` to the **pure** `_finalize_capture(captured, graphql_seen, nav_error)`,
   which reduces → parses → dedupes → applies the completeness guard → raises or returns
   the parsed cards.
7. Apply JVN's **client-side US + title filters** to the parsed cards (see §1.4) and return
   the kept list.

Everything from step 6 on is pure and fully unit-testable; steps 1–5 drive a real browser
and, like job-watcher's `fetch_list` and TikTok's browser code, get thin coverage via a
mocked `page`/`context` in the integration test (§5.3).

### 1.2 Shape-based selection (do NOT key on operation or container name)

Meta renamed its operation (`CareersJobSearchResultsDataQuery` →
`...V2DataQuery`) and its response container (`job_search_with_featured_jobs` → `..._v2`)
once already, silently zeroing job-watcher for **41 days**. So selection is **by shape**:

- `_iter_job_containers(node)` walks the whole `data` subtree and yields **every** dict that
  carries an `all_jobs` **or** `featured_jobs` list — regardless of the wrapper key. It does
  **not** stop at the first hit (an outer node with an empty `featured_jobs` strip must not
  hide the real container nested beneath it).
- `_container_jobs(container)` returns `all_jobs + featured_jobs` (each only if it is really a
  list).
- `_reduce_payloads` flattens all containers across all payloads, parses each job with
  `parse_list_job`, and **dedupes on job id** (featured jobs routinely duplicate `all_jobs`
  entries).

This survives the inevitable `..._v3` rename. Keep the leaf key names (`all_jobs`,
`featured_jobs`, `job_count`) as named constants at the top of `parser.py` with the same
"anchor on the leaf, not the wrapper" comment job-watcher carries.

### 1.3 Completeness guard (`job_count`)

Meta's filters query returns a `job_count` scalar (e.g. `{"job_count": 890}`) alongside the
results. `_iter_job_counts` yields every plausible count scalar under `data` (key == `job_count`
or ends with `_job_count`; rejects `bool` and non-positive), and `_advertised_job_count`
takes the **max** (and returns `None` + a WARNING if none is found — a missing count disables
the guard but must never do so silently). `_is_truncated(parsed, advertised)` is
`advertised is not None and parsed < advertised * _MIN_COMPLETENESS_RATIO` (0.9).

**Guard runs on the FULL parsed set, BEFORE the US/title filter.** `job_count` counts Meta's
whole returned catalogue; comparing it against the post-filter kept count would false-trip
every run. So: parse everything → run truncation guard against `job_count` → *then* filter.

### 1.4 Client-side US + title filter (mirror TikTok)

Every other JVN script scraper narrows to US software/data roles. Meta's `/jobsearch` returns
a broad set, so apply the same client-side `filter_location` (`LOCATION_FILTER = "United
States"`, substring match on the joined locations string) and `filter_job`
(`INCLUDE_TITLE_KEYWORDS` substring / `EXCLUDE_TITLE_KEYWORDS` **word-boundary**) that TikTok
uses. Copy TikTok's `_EXCLUDE_RE` word-boundary regex verbatim (bare "HR" as a substring
matches "T-h-r-eat").

> **OPEN DECISION — resolve at smoke-test (§6).** It is not yet verified whether
> `metacareers.com/jobsearch` returns a US-scoped set already or the full global catalogue,
> nor whether it accepts URL query params to pre-filter server-side. Baseline is client-side
> filtering identical to TikTok. During the mandatory prod smoke test, inspect one live
> capture: (a) confirm the `job_count` magnitude, (b) tune `INCLUDE/EXCLUDE/LOCATION_FILTER`
> to the real data, and (c) set the changelog's headline count from the **actual kept
> count** (working estimate: ~890). If `/jobsearch` supports office/team query params, prefer
> them and relax the client filter — but keep the completeness guard on the full returned set.

### 1.5 `parse_list_job` → the card dict

Port job-watcher's `parse_list_job`, returning a plain dict (not `RawJob`). For each job:

| field | source | notes |
| --- | --- | --- |
| `id` | `job["id"]` → `str` | drop the row if missing/empty |
| `title` | `job["title"]` | drop the row if missing/not a str |
| `location` | `_join_strings(job["locations"])` | `[str]` or `[{title}]` → `", ".join` |
| `department` | teams + sub_teams | `_join_strings(teams)` and `_join_strings(sub_teams)`; if both, `f"{teams} — {sub_teams}"`, else whichever is present |
| `job_url` | `https://www.metacareers.com/profile/job_details/{id}` | key it `job_url` (BatchWriter/base read `job_card["job_url"]`) |
| `raw` | the whole job dict | carried into `details.raw` |

Keep `_join_strings` verbatim from job-watcher.

### 1.6 Mapping onto `BaseScraper`'s ABC

Verified against `scripts/shared/base_scraper.py`. `@abstractmethod`s: `get_company_name`,
`build_search_url`, `extract_job_cards`, `extract_job_details`, `get_search_queries`.
`scrape_query`, `scrape_job_details_streaming`, `transform_to_job_model`, `deduplicate_jobs`
are **not** abstract but are required by the run path (`scrape_all_queries` calls
`self.scrape_query`; `run_scraper.py` calls `deduplicate_jobs`; `BatchWriter` calls
`transform_to_job_model`) — TikTok defines all four, so Meta must too.

| Method | Meta implementation |
| --- | --- |
| `get_company_name()` | returns `"meta"` |
| `build_search_url(query, page_num)` | returns `LIST_URL` (`https://www.metacareers.com/jobsearch`); args ignored — it's the human debugging URL |
| `get_search_queries()` | returns `["all"]` (single sentinel; Meta has no keyword search) |
| `extract_job_cards(page)` | thin ABC-satisfier — delegates to the shared capture helper (or returns `[]`); the real capture lives in `scrape_query`, exactly as TikTok's `extract_job_cards` is a token entry over `fetch_search_results` |
| `extract_job_details(page, url)` | returns `{}` (list-only first cut) — assert it touches nothing, like TikTok |
| `get_search_queries()` → `scrape_query(query, max_jobs)` | the GraphQL-sniff capture (§1.1); ignores `query`; honours `max_jobs` by slicing the kept list; **raises** on empty/truncated |
| `scrape_job_details_streaming(cards)` | pass-through async generator yielding each card unchanged (override is mandatory — the base default opens a page and sleeps 2–5 s per job) |
| `scrape_job_details_batch(cards)` | list form of the pass-through (mirror TikTok) |
| `transform_to_job_model(card)` | builds `shared.models.JobListing` (see §1.7) |
| `deduplicate_jobs(cards)` | dedupe by id + `transform_to_job_model` (copy TikTok) |
| `SOURCE_ID` class attr | `SourceId.META` |

### 1.7 `transform_to_job_model` — the JobListing

Copy TikTok's `transform_to_job_model` and change the constants. Critical fields:

- `id` = card `id`; `company="meta"`; `source_id = SourceId.META`.
- `title`, `location`, `url = job_url`.
- `details = {"description": None, "department": card["department"], "apply_url": job_url,
  "raw": card["raw"]}` (list-only ⇒ description None; keep whatever extra keys TikTok's shape
  suggests, but do not invent scraped fields we don't have).
- **`posted_on = None`** — Meta's list query carries no date (identical to TikTok).
- `first_seen_at = effective_posted_date(None, created_at)` — routed through the shared helper
  (`scripts/shared/posted_date.py`; signature `effective_posted_date(value, fallback)`) so
  the rule is *stated*, not coincidental. With `value=None` it always returns `created_at`
  (first sight), which is the only honest signal for a dateless board. **Do not synthesise a
  date.**
- `status="OPEN"`, `closed_on=None`, `has_matched=False`, `ai_metadata={}`,
  `last_seen_at=created_at`, `consecutive_misses=0`, `details_scraped=False` (mirror TikTok).

### 1.8 The raise-exception type

Define `class MetaCaptureError(Exception)` in `parser.py` (job-watcher's analogue is
`TransientAdapterError`; TikTok's is `JobSearchError`). `_finalize_capture` raises it on empty
and on truncation. Any exception out of `scrape_query` triggers the safe path in
`run_incremental_scrape`, but use a named type so tests can assert on it and the message can
carry the five-way diagnosis (`_empty_capture_reason`: page never loaded / no GraphQL / arrays
renamed / arrays empty / jobs present but none parsed).

### 1.9 Module layout (`scripts/meta_jobs_scraper/`)

Mirror the TikTok package shape so the repo stays uniform:

- `__init__.py` — exports `MetaJobsScraper` + the public config/parser symbols (mirror
  `tiktok_jobs_scraper/__init__.py`).
- `config.py` — `LIST_URL`, `JOB_DETAIL_URL_TEMPLATE`, `GRAPHQL_URL_SUBSTRING="/graphql"`,
  the leaf-key anchors (`ALL_JOBS_KEY`, `FEATURED_JOBS_KEY`, `JOB_COUNT_KEY`,
  `JOB_COUNT_SUFFIX`), `MIN_COMPLETENESS_RATIO=0.9`, the poll/timeout budgets
  (`PAGE_TIMEOUT_MS`, `RESPONSE_WAIT_S`, `POLL_INTERVAL_S`, `DRAIN_MAX_S`, `DRAIN_STABLE_S`,
  `BODY_READ_TIMEOUT_S`, `NEW_PAGE_TIMEOUT_S`), `LOCATION_FILTER`, `INCLUDE_TITLE_KEYWORDS`,
  `EXCLUDE_TITLE_KEYWORDS`, output dir/file names. Copy the values from job-watcher's
  `meta.py` module constants.
- `parser.py` — **all the pure functions** (`MetaCaptureError`, `build_job_url`,
  `_join_strings`, `parse_list_job`, `_payload_data`, `_iter_job_containers`,
  `_container_jobs`, `_reduce_payloads`, `_iter_job_counts`, `_advertised_job_count`,
  `_is_truncated`, `_capture_stats`, `_has_job_payload`, `_decode_graphql_payload`,
  `_empty_capture_reason`, `_finalize_capture`, and the `_SettlePoll` class). Ported almost
  verbatim from job-watcher; change `RawJob(...)` construction to a dict and drop the
  detail-page helpers (`_strip_html`, `_find_relay_island`, `parse_detail_html`, etc. — not
  needed for the list-only cut).
- `scraper.py` — `MetaJobsScraper(BaseScraper)` with the methods in §1.6. The only
  browser-driving code is `scrape_query` (mark it `# pragma: no cover` like TikTok's/job-
  watcher's browser code if the repo uses coverage gates on scrapers — check `pytest.ini`).

No `api_client.py` (there is no JSON endpoint to call — the browser sniffs the response).
No new dependency: `playwright` is already required; `bs4` would only be needed for the
deferred detail parsing.

---

## 2. Backend wiring — every file to edit (exact additions)

### 2.1 `scripts/shared/constants.py`

**(a)** Add a `SourceId` member (below `TIKTOK`, keeping the `_scraper` group together):

```python
    META: Final[str] = "meta_scraper"
```

**(b)** Add the careers-host entry to `SCRIPT_COMPANY_CAREERS_HOSTS`:

```python
    "meta": (("metacareers.com", ""),),
```

Notes:
- Declare **`metacareers.com`** (bare, normalized). `normalize_host` strips a leading `www.`,
  so this one entry matches both `www.metacareers.com` and `metacareers.com`. Do **not**
  declare `www.metacareers.com` — `test_every_declared_host_is_already_normalized` requires
  each host to equal its own normalized form and would fail.
- Verify live at implement time whether `careers.facebook.com`, `www.facebook.com/careers`,
  or `meta.com/careers` redirect to `metacareers.com` and add path-scoped entries **only** if
  a redirect is confirmed (a careers-host hit is terminal, so a wrong entry hard-blocks a
  user — see the `apple.com/careers` near-miss note already in the file). Baseline is the
  single `metacareers.com` entry.

### 2.2 `scripts/run_scraper.py`

**(a)** Import (beside the other scraper imports, ~line 29):

```python
from scripts.meta_jobs_scraper.scraper import MetaJobsScraper
```

**(b)** Register in `SCRAPER_CLASSES` (~line 67):

```python
    "meta": MetaJobsScraper,
```

**(c)** Add `"meta"` to the `--company` `choices` list (~line 372):

```python
        choices=["google", "apple", "microsoft", "amazon", "tiktok", "meta", "all"],
```

### 2.3 `src/backend/api/config.py`

Add `meta` to the `scraper_companies` default (~line 18):

```python
    scraper_companies: str = "apple,google,microsoft,amazon,tiktok,meta"
```

⚠️ **Gate this on the prod smoke test (§6/§7).** `SCRAPER_COMPANIES` is *not* set in Railway
prod (verified 2026-08-10 per `src/backend/CLAUDE.md`), so editing this literal is what
actually enables Meta on the next deploy. Adding it is **safe even if Meta is bot-walled on
Railway's datacenter IP**, because the raise-on-empty invariant means a walled fetch raises
(non-zero exit, logged as a warning by `auto_scraper`) and inserts/closes nothing — and Meta
has no rows to close on first runs anyway. But it is *pointless* until we confirm Meta
actually returns jobs from Railway. Recommended sequence: land the code, deploy, run the smoke
test; keep `meta` in the default only if the smoke test shows a real, non-zero, healthy
harvest. If `SCRAPER_COMPANIES` turns out to be set in Railway, add `meta` to the env var
instead (the literal would be ignored).

`auto_scraper.py` needs **no change** — it iterates `config.companies_list`.

### 2.4 `src/backend/api/tests/test_careers_host_match.py` (guard-test update — REQUIRED)

Adding a `*_scraper` `SourceId` deliberately breaks two assertions in
`test_every_script_scraper_has_its_careers_hosts_registered`. Update the hardcoded literal
(~line 261):

```python
    assert expected == {"google", "apple", "microsoft", "amazon", "tiktok", "meta"}, (
```

The `set(SCRIPT_COMPANY_CAREERS_HOSTS) == expected` line then passes automatically once §2.1(b)
is in place. Also **add positive + near-miss cases** (new parametrize entries):

- `("https://www.metacareers.com/jobsearch", "meta")` and
  `("https://metacareers.com/", "meta")` to the "each board names its company" style tests.
- Near-misses returning `None`: `"https://www.meta.com/"`, `"https://about.meta.com/"`,
  `"https://www.facebook.com/careers"` (unless a redirect was confirmed and declared),
  `"https://notmetacareers.com/jobsearch"` (the `endswith` trap).

`test_no_two_companies_claim_the_same_careers_host` and
`test_every_declared_host_is_already_normalized` cover the new entry automatically.

### 2.5 `src/backend/api/data/company_profiles.json`

Add a `"meta"` key with `blurb` + `accomplishment` — and **deliberately OMIT the `ats`
key** (mirror the `tiktok`/`amazon` entries, which omit it; only `google`/`apple`/`microsoft`
carry `ats: "script"`). This keeps `services/companies_seed.py`'s `script_inserted` count
unchanged so `test_companies_seed.py` stays green (the row itself is created by the seed
migration in §3, not by the profile). Suggested copy (tune freely):

```json
  "meta": {
    "accomplishment": "Meta built Facebook, Instagram, WhatsApp, and Messenger into a family of apps used by billions of people, and is now one of the largest investors in AI and virtual/augmented reality.",
    "blurb": "Meta operates the world's largest social platforms — Facebook, Instagram, WhatsApp, and Messenger — alongside its Reality Labs hardware and a major AI research and infrastructure effort."
  }
```

---

## 3. Seed migration (`src/backend/alembic/versions/`)

Create **one** hand-written data migration (the documented exception to the
autogenerate-only rule), modeled on
`20260809_123000_d8b52c04f6e3_seed_tiktok_company.py`. It inserts the `meta` row into
`companies`.

### 3.1 Compute `down_revision` FRESH — and do NOT trust `current_head.py` blindly

**Do not hardcode a parent from this doc.** Compute the current single head at implement time.

> **⚠️ CRITICAL, verified 2026-09-03:** the helper
> `.claude/skills/add-company/scripts/current_head.py` is **currently unreliable in this
> repo**. Two merge migrations use **tuple** `down_revision`s that its regex cannot parse:
> - `20260831_034716_a5cf3aed5f15_...` → `down_revision = ('fb8467065dfc', '1d2d6c17acfc')`
> - `20260826_050323_2633dd6348e4_...` → `down_revision = ('a5cf3aed5f15', '9d2f7ae5c1b4')`
>
> Because of that, `current_head.py` reports **four** heads and exits 1
> (`1d2d6c17acfc`, `9d2f7ae5c1b4`, `a5cf3aed5f15`, `d7b3c9e15af2`). Three of those are false
> — they are consumed inside the tuple `down_revision`s above. The **true single head is
> `d7b3c9e15af2`** (the `seed_easy_batch2_companies` migration; nothing references it).
>
> To get the right parent, use one of these instead of the helper's raw output:
> 1. **Real Alembic** (authoritative): from `src/backend/`, `alembic heads` — it should print
>    exactly one revision. (Local pytest/alembic env is known-flaky per MEMORY; if `alembic
>    heads` won't run cleanly, use option 2.)
> 2. **A tuple-aware DAG parse**: the head is the revision that appears as **no** other
>    migration's `down_revision`, counting hex ids inside tuple `down_revision`s too. Today
>    that is `d7b3c9e15af2`.
>
> Whichever you use, set `down_revision` to the confirmed single head **as of your branch's
> rebase against main**, not the value in this doc — `main` may have advanced. Chaining off
> the wrong revision creates a multi-head and crash-loops the backend on boot. Consider fixing
> `current_head.py` to parse tuple `down_revision`s as a small side-quest, but that is not
> required for this feature.

### 3.2 The migration file

Filename: `<UTC timestamp>_<rev>_seed_meta_company.py` (match the repo's
`YYYYMMDD_HHMMSS_<rev>_...` convention; `<rev>` is a fresh 12-hex id). Body modeled on the
TikTok seed:

```python
revision: str = '<fresh rev id>'
down_revision: Union[str, None] = '<confirmed single head, e.g. d7b3c9e15af2>'
branch_labels = None
depends_on = None

SEED_ROWS = [
    # board_token is meaningless for a script company but the column is NOT NULL,
    # so it mirrors the id (same as the tiktok/google/apple/microsoft rows).
    {'id': 'meta', 'display_name': 'Meta', 'ats': 'script', 'board_token': 'meta'},
]

def upgrade() -> None:
    bind = op.get_bind()
    insert_sql = sa.text(
        "INSERT INTO companies (id, display_name, ats, board_token, enabled, created_at) "
        "VALUES (:id, :display_name, :ats, :board_token, TRUE, now()) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for row in SEED_ROWS:
        bind.execute(insert_sql, row)

def downgrade() -> None:
    op.execute("DELETE FROM companies WHERE id = 'meta'")
```

Key points (all mirror the TikTok migration):
- `ats = 'script'`, `ON CONFLICT (id) DO NOTHING`.
- **Omit `provider_config`** from the INSERT — the column is `NOT NULL DEFAULT '{}'::jsonb`
  (confirmed in `db_models.py::Company`), so it defaults to `{}` for a script company. (If you
  ever set it explicitly, use `'{}'::jsonb`.)
- `created_at = now()` (a **real** timestamp, not the 2020 backfill) so the row auto-enrolls
  existing users via `user_preferences_service` (`c.created_at > u.company_enroll_watermark`)
  — the behaviour every newly-added company gets.
- Copy the TikTok migration's docstring, updating the company name and noting the fresh
  head-check per §3.1.

---

## 4. Frontend

### 4.1 `src/frontend/src/config/companies.ts`

**(a)** Add a script-company entry in the "Custom Web Scrapers" group (~line 915, beside the
`tiktok` entry). **OMIT `sourceAts`** — that absence is what groups it under Custom Web
Scrapers (see `config/atsSource.ts`):

```ts
  createBackendScraperCompany('meta', 'Meta', 'https://www.metacareers.com/jobs', {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%2210667%22%5D',
  }),
```

`recruiterLinkedInUrl` is optional — verify/replace the `authorCompany` id with Meta's real
LinkedIn company id (`10667` is a placeholder), or drop the option entirely if you don't want
the recruiter link.

**(b)** Add the `COMPANY_IDS` enum member (~the `M` section of the enum, ~line 1000+):

```ts
  Meta = 'meta',
```

### 4.2 `src/frontend/src/config/changelog.ts`

Prepend a new entry near the top of the `CHANGELOG` array (newest first — put it above the
`add-tiktok` entry or at the very top with today's date), modeled on `add-tiktok`. It **must**
mention the Custom Web Scrapers group, the no-posted-date quirk, and ~890 US roles (set the
real number from the smoke-test capture):

```ts
  {
    id: 'add-meta',
    title: 'Added Meta',
    description:
      "Meta — the company behind Facebook, Instagram, WhatsApp, and Messenger, plus its Reality Labs and AI efforts — is now tracked. Its careers site has no standard job board behind it, so this needed a purpose-built scraper rather than the usual ATS integration, joining Google, Apple, Microsoft, Amazon, and TikTok in the Custom Web Scrapers group. Coverage is US software and data roles, currently around 890 open postings, refreshed hourly like everything else. One quirk worth knowing: Meta's listings carry no posted date, so their timeline reflects when this site first saw them.",
    tags: ['new-companies'],
    date: '<implement date, e.g. 2026-09-03>',
    link: {
      to: ROUTES.ACCOUNT,
      label: 'Add Meta to your company preferences',
    },
  },
```

### 4.3 Logo (fetch-company-logo skill)

Run the `fetch-company-logo` skill for `meta` to generate the three opaque variants into
`src/frontend/public/logos/{icons,wordmarks,lockups}/meta.png`. Meta's brand is the infinity
"∞"/loop mark plus the "Meta" wordmark; pick the most on-brand background with legible
contrast and visually verify. Do this after the `companies.ts` entry exists (the skill reads
`companies.ts`).

---

## 5. Tests — thorough

Fixtures live in `scripts/tests/fixtures/`. Unit tests in `scripts/tests/unit/`, integration
in `scripts/tests/integration/`. Add a `meta_scraper` fixture to `scripts/tests/conftest.py`
(mirror the `amazon_scraper` fixture) returning `MetaJobsScraper(headless=True,
detail_scrape=False)`.

### 5.1 Fixture: `scripts/tests/fixtures/meta_graphql_capture.json`

A **small** captured metacareers GraphQL payload (2–5 jobs) shaped like the live response.
Include, deliberately:
- a **versioned wrapper key** (e.g. `job_search_with_featured_jobs_v2`) holding `all_jobs`
  **and** `featured_jobs`, with **one featured job that duplicates** an `all_jobs` id (tests
  dedupe);
- one job **missing `title`** (must be dropped) and one **missing `id`** (must be dropped);
- one **non-US** location and one US location (tests the location filter);
- teams + sub_teams on at least one job (tests the `department` join);
- a sibling entry carrying the **`job_count` scalar** equal to the number of *distinct valid*
  jobs (so the guard passes on the happy path).

Store it as one JSON object representing the decoded `captured` list, e.g.
`[{"data": {...results...}}, {"data": {...job_count...}}]`, so tests can load it and feed it
straight to the pure functions. Keep a second tiny inline variant (or mutate `job_count`
in-test) for the truncation case.

### 5.2 Unit tests

**`scripts/tests/unit/test_meta_parser.py`** — the load-bearing pure logic. Assert:

- **Shape-based selection:** `_iter_job_containers` finds the container under the real wrapper
  key; then **rename the wrapper** in a copy of the fixture (e.g. to `..._v3`) and assert the
  jobs are still found — proving selection is not keyed on the wrapper name.
- **`parse_list_job`:** correct `id`/`title`/`location`(joined)/`department`(teams — sub_teams)/
  `job_url` (`.../profile/job_details/{id}`); rows missing id or title return `None`/are
  dropped; `posted_at`/`posted_on` is absent/None in the card.
- **`_reduce_payloads`:** dedupes the featured-vs-all_jobs duplicate → distinct-by-id.
- **`_iter_job_counts` / `_advertised_job_count`:** picks the max; ignores a `bool` value;
  accepts a `_job_count`-suffixed variant (e.g. `open_job_count`); returns `None` **and warns**
  when no count scalar exists.
- **`_is_truncated`:** `parsed < 0.9×advertised` → True; `advertised is None` → False (guard
  disabled, never false-fails).
- **`_finalize_capture` — raise on empty:** payloads with no job arrays raise
  `MetaCaptureError`; assert the message distinguishes the mode (no GraphQL vs renamed arrays
  vs empty arrays vs jobs-present-but-none-parsed — one test per branch of
  `_empty_capture_reason`, feeding `graphql_seen`/`containers_seen`/`jobs_seen` accordingly).
- **`_finalize_capture` — raise on truncation:** parsed 1 job against `job_count` 100 →
  raises `MetaCaptureError` (message names both numbers).
- **`_finalize_capture` — happy path:** returns the parsed cards; and with a non-None
  `nav_error` but a non-empty capture, still returns (recovered) — assert it does not raise.
- **`_decode_graphql_payload`:** invalid JSON → `None`; a large/`all_jobs`-mentioning
  undecodable body is treated as suspicious (warns) — non-fatal, still `None`.
- **`_SettlePoll`:** the *wait* phase does **not** stop on an empty-array payload; stops once a
  **non-empty** array lands; the *drain* stops when the captured length is stable for
  `stable_polls`, and is capped by `drain_polls`.

**`scripts/tests/unit/test_meta_scraper_methods.py`** — sync methods (mirror
`test_tiktok_scraper_methods.py`). Assert:

- **Identity:** `get_company_name() == "meta"`; `SOURCE_ID == SourceId.META == "meta_scraper"`;
  `get_search_queries() == ["all"]`.
- **`build_search_url`** returns the metacareers `/jobsearch` URL.
- **`transform_to_job_model`:** `posted_on is None`; `first_seen_at ==
  effective_posted_date(None, created_at)`; `source_id == SourceId.META`; `url` shape;
  `department` join; `details` carry `raw` + `department` + `description is None`.
- **`deduplicate_jobs`** dedupes by id and returns `JobListing`s.
- **`extract_job_details`** returns `{}` and calls nothing on the page (list-only).
- **`filter_job` / `filter_location`** (if client-side filters are kept): keeps US software,
  drops non-US / non-tech; regression: `"Software Engineer, Threat Intelligence"` is kept
  (bare "HR" must not match "T-h-r-eat"); empty/None title → dropped.

### 5.3 Integration test

**`scripts/tests/integration/test_meta_scraper_async.py`** — drives `scrape_query` with a
**mocked** `page`/`context` (mirror the TikTok async test's fixtures), since `scrape_query`
owns the browser + poll. The seam: build a fake `page` (`AsyncMock`) whose `.on("response",
handler)` **captures the handler**, and whose `.goto(...)` (or the first `asyncio.sleep` in the
poll) **invokes that handler** with fake response objects — each fake `resp` needs `.url`
(contains `/graphql`), `.request.method == "POST"`, and an async `.text()` returning a JSON
string from the fixture. Patch `asyncio.sleep` and shrink the `_SettlePoll` budgets so the test
runs instantly. Assert:

- **Full capture → returns filtered cards**, completeness guard passes, count matches the
  fixture's valid US jobs.
- **Empty capture** (handler fed payloads with no job arrays) → **raises `MetaCaptureError`,
  never returns `[]`** (the headline invariant — mirror TikTok's
  `test_consecutive_error_bail_raises_instead_of_returning_partial`).
- **Truncated capture** (job arrays present but `job_count` says far more) → raises
  `MetaCaptureError`.
- **Renamed wrapper key** still yields jobs (shape-based selection end-to-end).
- **`page.close()` is awaited even when the loop raises** (mirror TikTok's
  `test_page_closed_even_when_loop_raises`).
- **`nav_error` tolerated:** goto raises a PlaywrightError but the handler still delivered a
  good payload → returns jobs (does not surface the nav error).

> If coverage gating on `scripts/` makes a fully-mocked `scrape_query` awkward, follow
> job-watcher's split exactly: keep `scrape_query`'s browser lines `# pragma: no cover` and put
> the exhaustive assertions on `_finalize_capture` + `_SettlePoll` in the unit file (§5.2),
> leaving the integration test as a lighter wiring smoke (handler attached, poll composes,
> finalize called, raises propagate).

### 5.4 Backend test — `test_careers_host_match.py`

Covered in §2.4 (the literal-set update is mandatory; add the meta URL + near-miss cases).

### 5.5 Run the suites

- Scrapers: `cd` project root, `pytest scripts/tests/unit/test_meta_parser.py
  scripts/tests/unit/test_meta_scraper_methods.py
  scripts/tests/integration/test_meta_scraper_async.py -v`.
- Backend guard: `cd src/backend && pytest api/tests/test_careers_host_match.py -v`. Also run
  `pytest api/tests/test_companies_seed.py` to confirm the profile-omits-`ats` decision keeps
  `script_inserted` unchanged.
- Frontend: `npm run type-check` (COMPANY_IDS + companies.ts) and `npm test` (changelog /
  companies snapshots if any). `cd src/backend && mypy` for the new Python (backend package
  is type-checked; `scripts/` is not under mypy, but keep it clean).
- Watch for any snapshot/count test over `companies.ts` or `company_profiles.json` that
  enumerates companies — update if present.

---

## 6. Mandatory production smoke test (before trusting Meta)

**This is not optional.** job-watcher scrapes Meta from a **residential IP**; JVN's scrapers
run on **Railway (a datacenter IP)**. Meta's anti-bot may serve a bot wall or an empty board
to datacenter IPs. Local dev on a residential IP passing tells you nothing about prod.

Sequence:
1. Land all code + migration + tests; deploy the backend to Railway (see `src/backend/CLAUDE.md`
   § merge-train deploy-skip trap — confirm the backend deployment actually ran and
   `alembic_version` advanced to the new meta revision).
2. Trigger a Meta scrape in prod: `POST /api/jobs-qa/trigger-scrape?company=meta` (or wait for
   the auto-scraper cycle). Watch Railway logs for the run.
3. Verify with the `smoke-test-deployed` / `onesecondswe-backend-audit` skills, or directly:
   - **Railway logs**: did the Meta subprocess exit 0 and report a plausible job count, or did
     it raise `MetaCaptureError` ("no GraphQL", "behind a bot wall", "arrays empty")?
   - **Prod SQL** (`mcp__postgres-prod__query`, read-only):
     `SELECT count(*) FROM job_listings WHERE source_id='meta_scraper' AND status='OPEN';`
     and `SELECT max(last_seen_at) FROM job_freshness f JOIN job_listings j ON ... WHERE
     source_id='meta_scraper';` — expect a healthy non-zero count and a fresh timestamp.
   - Frontend: Meta appears in Custom Web Scrapers, the trend chart populates, jobs show in
     Recent.

**Interpreting the result:**
- **Healthy harvest (non-zero, matches `job_count`):** ship — keep `meta` in
  `scraper_companies`.
- **`MetaCaptureError` / zeros (bot wall):** the raise-on-empty invariant already protected the
  DB (nothing inserted, nothing closed). Do **not** ship Meta as live. Options to escalate:
  route Meta's capture through a residential/stealth proxy or Browserbase (JVN already carries
  Browserbase plumbing behind `capture_use_browserbase` — see `config.py`), then re-smoke; or
  hold the feature. Either way, remove `meta` from `scraper_companies` until it demonstrably
  works from prod so the scraper-health watchdog doesn't flag a permanently-stale source.

---

## 7. Risks & mitigations

| Risk | Mitigation (built into this plan) |
| --- | --- |
| **Datacenter-IP anti-bot (biggest risk).** Railway is a datacenter IP; Meta may serve a bot wall / empty board where job-watcher (residential) succeeds. | (a) **Raise-on-empty invariant** (§0): a walled/empty fetch raises, so it can **never** mass-close Meta jobs — and Meta has no rows to close early on. (b) **Mandatory prod smoke test** (§6) before trusting it; escalation path via residential proxy / Browserbase; keep out of `scraper_companies` until it works from prod. |
| **Meta renames the GraphQL operation/container again** (it has, twice; cost job-watcher 41 days). | **Shape-based selection** (§1.2) — walk for `all_jobs`/`featured_jobs` by shape, never by wrapper/operation name; leaf-key anchors as named constants; renamed-wrapper unit + integration tests (§5.2/§5.3). |
| **Truncated/partial payload** slipping past the ~85% `partial_scrape` guard and reaching close-detection. | **Completeness guard** against Meta's own `job_count` (§1.3), run on the full parse before filtering; `< 90%` raises. Unit + integration coverage. |
| **Multi-head Alembic** crash-looping the backend on boot. | §3.1: compute the head fresh via real `alembic heads` or a **tuple-aware** parse; **do not trust `current_head.py`** (it mis-reports 4 heads today because of tuple `down_revision`s). True head today: `d7b3c9e15af2`. |
| **Guard test breaks by design** when a `*_scraper` SourceId is added. | §2.4: update the hardcoded literal set to include `"meta"` in the same change. |
| **`company_profiles.json` `ats` key** bumping `script_inserted` and breaking `test_companies_seed`. | §2.5: OMIT the `ats` key in the Meta profile (mirror tiktok/amazon); the row is created by the migration, not the profile. |
| **Settle-poll tears down mid-read** on an empty strip arriving first. | `_SettlePoll` *wait* phase requires a **non-empty** array (§1.1); pinned by unit test (§5.2). |
| **Response handler raising** inside Playwright's event loop (invisible failure). | Handler wraps the body read in try/except and returns on any error (§1.1) — ported from job-watcher. |
| **Client-side filter over-narrows / `job_count` scope mismatch.** | Filter runs *after* the guard; the guard uses Meta's own count. OPEN DECISION (§1.4) resolved at smoke-test by inspecting one live capture and tuning `INCLUDE/EXCLUDE/LOCATION_FILTER` + the changelog count. |

---

## 8. Implementation order (checklist)

1. `scripts/meta_jobs_scraper/` — `config.py`, `parser.py` (port pure logic + `MetaCaptureError`),
   `scraper.py` (`MetaJobsScraper`), `__init__.py`.
2. `scripts/shared/constants.py` — `SourceId.META` + `SCRIPT_COMPANY_CAREERS_HOSTS["meta"]`.
3. `scripts/run_scraper.py` — import + `SCRAPER_CLASSES` + `--company` choice.
4. `scripts/tests/` — `conftest.py` `meta_scraper` fixture, fixture JSON, unit + integration
   tests. Run them green locally.
5. `src/backend/api/tests/test_careers_host_match.py` — literal update + meta cases. Run green.
6. Seed migration — compute head fresh (§3.1), write the file, confirm single head after.
7. `src/backend/api/data/company_profiles.json` — meta entry (omit `ats`).
8. `src/backend/api/config.py` — add `meta` to `scraper_companies` (gated on smoke test §6).
9. Frontend — `companies.ts` (entry + `COMPANY_IDS.Meta`), `changelog.ts` (`add-meta`).
10. Logo via `fetch-company-logo` skill.
11. `npm run type-check`, `npm test`, backend `pytest` + `mypy`, scraper `pytest`.
12. **Deploy + mandatory prod smoke test (§6).** Decide live/hold from the result.

## 9. Files touched — summary

**CREATE (7 + fixture + tests):**
- `scripts/meta_jobs_scraper/__init__.py`
- `scripts/meta_jobs_scraper/config.py`
- `scripts/meta_jobs_scraper/parser.py`
- `scripts/meta_jobs_scraper/scraper.py`
- `src/backend/alembic/versions/<ts>_<rev>_seed_meta_company.py`
- `scripts/tests/fixtures/meta_graphql_capture.json`
- `scripts/tests/unit/test_meta_parser.py`
- `scripts/tests/unit/test_meta_scraper_methods.py`
- `scripts/tests/integration/test_meta_scraper_async.py`
- `src/frontend/public/logos/{icons,wordmarks,lockups}/meta.png` (via skill)

**EDIT (7):**
- `scripts/shared/constants.py`
- `scripts/run_scraper.py`
- `scripts/tests/conftest.py` (add `meta_scraper` fixture)
- `src/backend/api/config.py`
- `src/backend/api/tests/test_careers_host_match.py`
- `src/backend/api/data/company_profiles.json`
- `src/frontend/src/config/companies.ts`
- `src/frontend/src/config/changelog.ts`

(`auto_scraper.py` needs **no** change — it iterates `config.companies_list`.)
