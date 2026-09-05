# WebMCP-driven end-to-end tests — plan

**Goal:** expose JVN's user actions as WebMCP tools, then write an agent-driven e2e suite that drives the app through those *typed tool calls* (stable across redesigns) instead of brittle DOM selectors — and asserts on the rendered DOM.

**Why WebMCP for e2e:** the tools are the **arrange/act** layer (deterministic, typed, redesign-proof); the DOM is still the **assert** layer. Tier-1 tools verify the *API*; Tier-2 tools exercise the *real UI*.

> Scope note: this folder is the **implementation plan**, not where the tools live. The tools themselves get registered in the frontend (`src/frontend/src/…`, via `document.modelContext.registerTool(...)`); the e2e suite lives with the other tests.

---

## The WebMCP tools I'd use

### Tier 1 — Read & discover (anonymous, `readOnlyHint: true`)
- **`search_jobs`** — flagship. Filter the live OPEN feed. Inputs: `include[]`/`exclude[]` (keywords), `category[]`, `level[]`, `company[]`, `location[]`, `timeWindow`, `limit`≤500, `cursor`. → `GET /api/jobs/search`
- **`list_filter_options`** — valid categories & levels (labels, order, hierarchy) so the test picks legal enum values. → `GET /api/jobs/facets`
- **`list_companies`** — directory (id, name, ATS, URL); resolves company *name* → *id* for `search_jobs`. → `GET /api/companies`
- **`search_locations`** — canonical location autocomplete (country→region→city). → `GET /api/locations/search`
- **`get_job`** — one posting's full detail + apply URL. → `GET /api/jobs/{src}/{id}`
- **`get_company_hiring_trend`** — the `/companies` chart as data (time-bucketed series); can render the chart while it answers. → client-side bucketing over search results

### Tier 2 — Drive the live page (mutates on-screen state — the real e2e "act")
- **`apply_feed_filters`** — apply filters to the on-screen Recent feed + navigate to `/` so the visible list updates. Same filter shape as `search_jobs` + `softwareOnly`. → `recentJobsFiltersSlice`
- **`reset_feed_filters`** — clear all on-screen filters. → `resetRecentJobsFilters`
- **`open_job`** — open a posting's apply page (ATS URL) in a new tab. → `window.open()`

### Tier 3 — Personalize (needs sign-in)
- **`request_sign_in`** — opens the Auth0 / Google prompt for the human; no token ever reaches the agent. (Needs no auth itself.) → `loginWithRedirect()` / Google One Tap
- **`set_enabled_companies`** — choose which companies feed the signed-in user. → `PUT /api/users/enabled-companies`
- **`save_filter_defaults`** — persist default filters / keyword lists / location & time defaults. → `PUT /api/users/saved-filters`
- **`upvote_feature`** — upvote a roadmap feature. → `POST /api/features/{id}/upvote`
- **`submit_feedback`** — send feedback (works anonymously). → `POST /api/feedback`

---

## How they map to e2e scenarios (arrange → act → assert)

| Scenario | Arrange (tool) | Act (tool) | Assert (DOM) |
|---|---|---|---|
| Filter feed by category | `list_filter_options` | `apply_feed_filters({category:['software_engineering']})` | job cards render; count matches `search_jobs.meta.filteredTotal` |
| Company hiring-trend renders | `list_companies` | navigate `/companies` + `get_company_hiring_trend` | chart has expected buckets |
| Keyword include/exclude | — | `apply_feed_filters({include:['backend'],exclude:['staff']})` | titles reflect include, none match exclude |
| Location filter | `search_locations('New York')` | `apply_feed_filters({location:[...]})` | cards show that location |
| Reset | (filters applied) | `reset_feed_filters` | filter chips cleared, full feed back |
| Signed-in enabled companies | `request_sign_in` (human) | `set_enabled_companies([...])` | feed limited to those companies after reload |

---

## Gotchas the tests must account for
- ⚠️ **Category/level filters hide ~65% of jobs** (unenriched NULL rows) — assert against `search_jobs.meta.filteredTotal`, not against total OPEN count.
- ℹ️ **`search_jobs` cursor is filter-bound** — replaying a cursor after changing filters → **409**. Re-search from scratch when filters change.
- ⛔ **No alerts/notifications/bookmarks exist** — don't write tests for them (roadmap-only).
- 🔑 **Agents can't self-auth** — Tier-3 scenarios need a real human sign-in (or a test session/token seeded out of band); `request_sign_in` only surfaces the prompt.
- 🌐 **Tools ship in prod** — they're real user capabilities, not hidden test hooks; design them as features.

---

## Rough phases
1. **Register Tier-1 tools** (read-only, lowest risk) + a WebMCP feature flag. Wire `execute` to the same edge proxies the UI uses.
2. **Register Tier-2 tools** (dispatch existing Redux actions / router navigation).
3. **Register Tier-3 tools** behind auth checks; `request_sign_in` first.
4. **e2e harness**: an agent (or Playwright + a WebMCP shim) that calls tools to arrange/act, reads the DOM to assert. Seed a test auth session for Tier-3.
5. **CI**: run the suite against a preview deploy; assert on `meta` counts + DOM.

_Source: WebMCP audit artifact at `.lavish/webmcp-audit.html` on the working branch._
