# End-to-End Feature Catalog — onesecondswe (JVN)

A plain-language map of **every user-facing feature the end-to-end suite exercises**, and
under each one the **concrete use cases** it tests — framed as *what a user does → what they
should observe*. It is written for a human reader (a reviewer, a new maintainer, the owner)
who wants to know what is covered without reading test code.

## Two test surfaces

The app is verified through two independent harnesses. This catalog covers both.

| Surface | What it drives | How it acts | How it proves |
|---|---|---|---|
| **`verify-onesecondswe` skill** | The 8 user-facing routes, through **14 typed WebMCP tools** on `window.__webmcp__` | Tool calls (never raw DOM clicks) arrange and act | The rendered **DOM**, and rows in the **`jobscraper_e2e`** database |
| **`e2e/add-companies` gate** | The paste-a-careers-URL "Add Companies" flow only | Real form + real discovery pipeline (LLM + headless browser) | Cases **AC-01..AC-25** in [`e2e/add-companies/CASES.md`](../../../e2e/add-companies/CASES.md) |

**How to read a use-case row:** *Use-case ID* · *What it tests* (user outcome) · *WebMCP
arrange → act* (the tool call(s)) · *DOM / DB assert* (the observable end state). WebMCP is
the **arrange/act** layer; the DOM and DB are the **proof** layer.

## Two limits the tests must not assert naively

Recorded up front so no reader is misled by a "failing-looking" number that is actually correct.

- **Category / level filters hide un-enriched rows.** Those two filters only keep jobs the
  enrichment pipeline has already labelled, and in the `jobscraper_e2e` clone enrichment is
  **~100% NULL** (only ~24 rows labelled). So a category or level filter narrows the feed to
  **≈ 0** — that is the data, not a broken filter. Assert these by the **shape** of
  `search_jobs.meta.filteredTotal`, never against the total open-job count. Use **company /
  keyword / time-window** filters (which have real data) whenever a test needs the list to
  narrow to something non-empty.
- **`search_jobs` cursors are filter-bound.** Replaying a `nextCursor` after changing any
  filter restarts the walk from page 1 — it is **not** a 409, it is a fresh (valid) walk.
  Treat any filter change as "re-search from scratch." *(This corrects PLAN.md line 51, which
  described a 409; this branch does not raise one.)*

Also note: **the on-screen row count is never asserted equal to `meta.filteredTotal`.** The
signed-in list is virtualized (only a screenful is mounted) and the signed-out list is
hard-capped at ~12 behind a sign-in overlay. Tests assert a *per-card invariant* (e.g. "every
visible card is Apple"), not exact-count equality — and the page renders no total to
compare against (the "Displayed Jobs" tile was removed on 2026-09-05).

## Feature areas at a glance

| Feature area | Route | Primary WebMCP tools | Surface |
|---|---|---|---|
| Recent job feed | `/` | `search_jobs`, `apply_feed_filters`, `reset_feed_filters`, `open_job`, `list_filter_options`, `search_locations`, `list_companies` | skill |
| Company hiring trends | `/companies` | `get_company_hiring_trend`, `get_job`, `list_companies` | skill |
| Curated companies directory | `/curated-companies` | `list_companies` | skill |
| Saved filters (login-gated) | `/saved-filters` | `save_filter_defaults`, `set_enabled_companies` | skill |
| Feedback & voting | `/vote-features` | `submit_feedback`, `upvote_feature` | skill |
| Account / sign-in | `/account` | `request_sign_in` | skill |
| Why this was built | `/why` | none (static page) | skill |
| Add Companies (flag-gated) | `/add-companies` | none — form-driven | add-companies gate |

**Intentionally not covered:** the admin routes (`/qa`, `/admin/*`, `/location-pipeline`) sit
behind an admin grant and no WebMCP tool touches them — they are *verified-unreachable* from
the user surface, not missing.

---

## 1. Recent job feed — `/`

The home page: recent openings across every tracked company, a recency metric row,
and an infinite-scrolling list of job cards. Filters read open jobs from the server, then
narrow them by keyword, company, location, employment type, software-only, category, level,
and time window.

| Use-case ID | What it tests | WebMCP arrange → act | DOM / DB assert |
|---|---|---|---|
| UC-recent-01 | Filter the feed to one company | `reset_feed_filters` → `apply_feed_filters({company:['apple']})` | Every visible card is Apple; a company visible unfiltered (e.g. SpaceX) is gone; `search_jobs({company:['apple']}).meta.filteredTotal > 0` |
| UC-recent-02 | Keyword include / exclude | `apply_feed_filters({include:['engineer'], exclude:['staff']})` | Visible titles all match an include term; none match an exclude term |
| UC-recent-03 | Filter by location | `search_locations({q:'Seattle'})` → `apply_feed_filters({location:[canonicalName]})` | Visible cards show that location |
| UC-recent-04 | Filter by category (the NULL-row limit) | `list_filter_options` → `apply_feed_filters({category:['software_engineering']})` | List narrows to `meta.filteredTotal` (≈ 0 in the clone — proven by `meta` **shape**, per the limit above) |
| UC-recent-05 | Narrow by time window | `apply_feed_filters({timeWindow:'24h'})` | Feed narrows to recent postings; "Past 24 Hours" metric reflects the window |
| UC-recent-06 | Reset restores the full feed | (filters applied) → `reset_feed_filters` | Filter chips cleared; the full unfiltered feed is back |
| UC-recent-07 | Open a posting | `search_jobs(...)` → `open_job({url: jobs[0].url})` | Popup **intent** recorded (`page.on('popup')` / `window.open` stub); returns `{opened:true, url}` — headless popups are blocked, so intent not live nav |
| UC-recent-08 | Filter catalog + company resolution load | `list_filter_options`; `list_companies({query})` | `{categories, levels}` non-empty; a display name resolves to its company id |

**Feature notes:** the metric row shows one tile, Past 24 Hours ("Displayed Jobs" and "Past
3 Hours" were both removed on 2026-09-05 — the first because the server defers the filtered
total so it could only ever show a lower bound, the second as a redundant second window).
The
list virtualizes when signed in and hard-caps at ~12 (behind a sign-in overlay) when signed
out. `apply_feed_filters` is **additive** — it only changes the fields you pass — so tests
call `reset_feed_filters` first for a clean slate.

---

## 2. Company hiring trends — `/companies`

Per-company view: a time-bucketed hiring-activity chart plus the same job cards as the Recent
page, both driven by one shared filter source (the list reflects the chart).

| Use-case ID | What it tests | WebMCP arrange → act | DOM / DB assert |
|---|---|---|---|
| UC-trends-01 | Trend buckets render for a company | `list_companies` → `get_company_hiring_trend({company:'apple', timeWindow:'90d'})` | `total > 0`; `buckets` is `[{bucketStart, bucketEnd, count}]`; page heading "Company Hiring Trends" over a non-empty card list |
| UC-trends-02 | Empty buckets are preserved | `get_company_hiring_trend({...})` | Zero-count buckets exist across the full range (a `count:0` bucket is intentional, not missing data) |
| UC-trends-03 | Click through to one posting | `get_job({source, id})` (id from UC-trends-01 or `search_jobs`) | `job.url` is the apply link; `title`, `company`, `location`, `firstSeenAt`, `category`, `level` present |

**Feature note:** the trend tool defaults to a **90-day** window (the page's own default),
whereas `search_jobs` defaults to `all` — tests pass `timeWindow` explicitly when comparing
the two. `total` is the company's own fetched job set (what the chart buckets), not a global
figure.

---

## 3. Curated companies directory — `/curated-companies`

A searchable directory of every tracked company with brand info. The same public payload
`list_companies` reads is what this page renders.

| Use-case ID | What it tests | WebMCP arrange → act | DOM / DB assert |
|---|---|---|---|
| UC-curated-01 | Directory lists all tracked companies | `list_companies` | ~131 companies returned; the grid renders one card each; heading "Curated Companies" |
| UC-curated-02 | Client-side search narrows the grid | `list_companies({query:'apple'})` | Rendered card count matches the filtered result length (this grid is **not** virtualized, so a count assertion is fair here) |
| UC-curated-03 | Name → id resolution | `list_companies({query:'apple'})` | "Apple" resolves to id `apple` — the resolver of record the other tools rely on |

**Feature note:** filtering is a case-insensitive substring over `id` **or** display name — the
same predicate the page's search box uses, so the two agree. User-added (`u-…`) boards are not
in this curated set by design.

---

## 4. Saved filters — `/saved-filters` (login-gated)

A signed-in page to set default time windows (per page), shared locations, category/level
defaults, the enabled-companies picker, and reusable keyword lists. Both writes here are proven
by their **database** side effect. Authentication comes from the JWKS-seam fixture
(`signedInPage`), not from a real Auth0 round trip.

| Use-case ID | What it tests | WebMCP arrange → act | DOM / DB assert |
|---|---|---|---|
| UC-saved-01 | Save default time windows + locations | `save_filter_defaults({recentTimeWindow:'7d', trendTimeWindow:'90d', locations:['Seattle, WA']})` on `signedInPage` | **DB:** a `user_saved_filters` row for the primary identity |
| UC-saved-02 | Set enabled companies | `set_enabled_companies({companyIds:['apple','spacex'], autoEnroll:true})` on `signedInPage` | **DB:** `user_enabled_companies` rows for the identity |
| UC-saved-03 | Feed reflects the enabled set after reload | UC-saved-02 → reload `/` | Feed scope / fetch-progress chips narrow to the enabled set |

**Feature note:** signed out, the page prompts to sign in and nothing is drivable — both tools
return "Sign in required" without a token. The primary test identity is
`e2e+add-companies@jvn.test`.

---

## 5. Feedback & voting — `/vote-features`

Upvote candidate features and submit free-text feedback. Shipped features move to a read-only
"Shipped" section. Both writes are proven by their database side effect.

| Use-case ID | What it tests | WebMCP arrange → act | DOM / DB assert |
|---|---|---|---|
| UC-vote-01 | Submit feedback **signed-out** (anonymous) | `submit_feedback({message:'…marker…'})` on a plain page | **DB:** a `feedback` row with the marker and a NULL `user_id` |
| UC-vote-02 | Submit feedback **signed-in** | `submit_feedback({message})` on `signedInPage` | **DB:** a `feedback` row tied to the identity |
| UC-vote-03 | Upvote a feature | `upvote_feature({featureId:'mcp-server'})` on `signedInPage` | Returns `hasUpvoted:true`; **DB:** a `feature_upvotes` row for `(identity, mcp-server)` |

**Feature note:** feedback is the one Tier-3 capability that works **anonymously**; upvoting
requires sign-in. Upvote is idempotent per (user, feature) — tests assert the row *exists*, not
that a count grew by exactly one. Seeded open feature ids in the clone: `custom-dashboards`,
`mcp-server`, `resume-match-ai`.

---

## 6. Account / sign-in — `/account`

The account page and the sign-in entry point. The sign-in tool maps the *prompt* path only —
no token ever reaches the agent; real signed-in state for verification comes from the fixture.

| Use-case ID | What it tests | WebMCP arrange → act | DOM / DB assert |
|---|---|---|---|
| UC-account-01 | Sign-in prompt fires (smoke) | `request_sign_in` | Returns `{prompted:true}` — confirms the bridge captured `useAuth().login` and the prompt fired; it **cannot** complete headlessly |
| UC-account-02 | Signed-in account view (via fixture) | Load with the JWKS-seam minted token (`signedInPage`) | The account page shows the signed-in user's profile |

**Feature note:** `request_sign_in` is smoke-only — a `{prompted:true}` is not proof of a
session. Every Tier-3 side-effect test gets its auth from the fixture, which injects a minted
token into `localStorage`. Two identities exist: primary (`e2e+add-companies@jvn.test`) and a
second (`e2e+other@jvn.test`) used for ownership-isolation.

---

## 7. Why this was built — `/why`

A static about page. Included so the map is complete and a maintainer knows it is deliberately
tool-free, not overlooked.

| Use-case ID | What it tests | WebMCP arrange → act | DOM / DB assert |
|---|---|---|---|
| UC-why-01 | The about page is reachable and renders | none — plain `page.goto('/why')` | The page's H1 heading renders |

**Feature note:** none of the 14 tools apply here (they drive jobs, filters, companies, auth,
feedback). The honest proof is "the route loads and its heading renders" — a WebMCP call would
be theater.

---

## 8. Add Companies — `/add-companies` (flag-gated)

Paste a company's careers URL and track the company behind it: **one press, one outcome** —
the board is added, routed into a one-time discovery, linked as already-public, or refused with
a reason. This flow is a form-driven, LLM-and-browser-backed pipeline, **not** something the 14
WebMCP tools wrap — so it is covered by its own dedicated regression gate. **This section is a
cross-reference; the assertions live in [`e2e/add-companies/CASES.md`](../../../e2e/add-companies/CASES.md), not here.**

The catalog anchors on **AC-01..AC-12** (the core user journeys). AC-13..AC-25 exist and extend
coverage (company-name dedupe, per-user add limits, admin cap exemption, board-failure triage
for Meta / Uber / IBM / Oracle / Bloomberg / Klarna and more, and rename survival) — see
`CASES.md` for the full set.

| Gate case | User outcome (what the user does → what they should see) | Company |
|---|---|---|
| **AC-01** | Paste a careers-host URL we already scrape via a script board → "we already track this", **terminal**, no way past | Microsoft |
| **AC-02** | Same careers-host dedupe on another script board | Amazon |
| **AC-03** | Paste an embedded-Workday careers URL → the board is added and harvests real jobs | Cisco |
| **AC-04** | Paste a non-ATS careers URL → one-time discovery runs → board is tracked and **verified** | Atlassian |
| **AC-05** | Same discovery-then-verify journey on a second board | Jane Street |
| **AC-06** | A domain that *names* a company we track → "this looks like Spotify…" with a **"This isn't the same company"** escape hatch; correcting us reaches real discovery | Spotify |
| **AC-07** | Remove a tracked board → it is deleted and its jobs purged → re-add it fresh | Cisco |
| **AC-08** | The full human journey: paste → **one press** → success card (no preview, no second confirm) | Cisco (UI) |
| **AC-09** | With the feature flags off, the flow refuses cleanly (503 / `no_ats_detected`) instead of hanging | flags |
| **AC-10** | Ownership isolation between two users: 403 on another user's jobs, 404 on deleting their board, the row survives | two users |
| **AC-11** | Re-adding an already-tracked board is idempotent and spends nothing extra | Atlassian |
| **AC-12** | The server still honours a `trackAnyway` override on the careers-host path (the UI just no longer offers it on exact matches) | Microsoft |

**Feature note:** both flags must be on (`VITE_CUSTOM_COMPANIES_ENABLED` + backend
`CUSTOM_COMPANY_SOURCES_ENABLED`). A green `verify-onesecondswe` run says **nothing** about Add
Companies — run `e2e/run.sh add-companies` (or `--fast` for the $0 subset) for that coverage.

---

*Sources: `src/frontend/src/config/routes.ts` (routes), the `verify-onesecondswe` feature map
(`.claude/skills/verify-onesecondswe/features/`), and `e2e/add-companies/CASES.md` (AC cases).
Contract: [`RUN1-SPEC.md`](./RUN1-SPEC.md) §4.*
