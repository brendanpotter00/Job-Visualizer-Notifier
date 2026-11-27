# Company categories: plan

Branch `feat/company-categories`, cut from `origin/main` `abb98b4c`.
Data: `src/backend/api/data/company_categories.json` (committed with this plan).

## What we're building

- **Every tracked company gets 1+ of 10 categories.** One company can have many (Google is Big Tech, AI Labs and Household Names).
- **Recent Jobs gets a "Company type" checkbox dropdown.** Check several; the server filters.
- **Saved filters store it.** The Saved Filters page edits it. Reset to default search puts the saved one back (signed out: clears it).
- **Landing cards deep-link** to `/jobs?company_type=<slug>`.
- **Onboarding gains step 4 of 4:** "What kinds of companies do you want?" Skippable.
- **add-company skill** makes picking categories a required step.

STRATEGY.md check: aligns ("narrowed by what the candidate asked for"). The factual categories (YC, Unicorns, Big Tech) are claims that can rot, so they need sources and a yearly review (see Risks).

## Decisions

| Decision | Why |
|---|---|
| **Big Tech = $100B+ independent tech company** (market cap if public, last priced round if private). Not subsidiaries, not aerospace, not non-tech. | Crisp, checkable, about 20. Gives 18 today. |
| **Anthropic and OpenAI are in Big Tech** (also AI Labs). | Both clear $100B by far ($1.1T, $852B). No exception clause needed. |
| **Subsidiaries are out of Big Tech** (GitHub, Slack, Twitch, Waymo, Zoox, xAI). | Keeps it to the giants themselves. Each keeps another category. |
| **Box -> Household Names, Figma -> Dev Tools & Infra.** | They had only Big Tech. Both are stretches (see Data). |
| **One JSON file is the only source.** Backend seeds tables from it on boot; frontend imports the same file. | No second list to drift. Probed: `tsc`, `vitest` and `vite build` all accept the cross-package import. |
| **Category array order = display order. `companyIds` order = landing logo order.** | One structure holds membership and curation. No separate `sortOrder` to drift. |
| **Saved-filters PUT: `companyCategory` absent = keep stored value.** The one exception to full-replace. | Old SPA tabs, feature A before wiring, and WebMCP calls can't wipe it. |
| **Frontend sends `companyCategory` to write endpoints only if the saved-filters GET returned it.** | The old backend 422s unknown keys (`extra='forbid'`). Saved-filters GET is per-user and uncached, so it is a precise capability signal. Facets is not (edge-cached 24h). |
| **Dropdown options: facets if non-empty, else the bundled list.** Never hidden. | Covers the old backend, the stale facets edge cache, and an empty seed. A selected chip stays visible and clearable. |
| **Server resolves slugs to company ids, then `job_listings.company = ANY(...)`.** | Same plan shape as today's company filter. EXPLAIN on prod: keyset `Index Scan Backward`, company as a `Filter`, no Sort. No new index. |
| **Recency tiles ignore company type.** | Same rule as category/level: tiles mean "boards I follow". |
| **Private (custom) boards have no categories.** An active filter hides them. | Categories describe the curated public roster only. |
| **URL param `company_type`, API param `company_category`, label "Company type".** | URL reads like the label; API matches the data model. |
| **Label is sentence case ("Company type")** even though its neighbour reads "Job Category". | House style. Renaming "Job Category" is out of scope. |
| **Landing card click resets the Recent filters, then sets the type, then navigates (SPA).** | A full page load would re-fire `signup_funnel_landing`. The URL-sync READ latches once per mount, so a Back-then-click path would drop the param without the dispatch. |
| **Onboarding always shows 4 steps.** On an old backend the step-4 answer is not sent. | No "1/3 -> 1/4" flicker. Loss only inside the deploy window. |
| **WebMCP tools learn the field** (list, search, apply, save). | Four small edits; keeps the agent surface in step with the UI. |
| **New e2e section `company-categories`**, plus new cases in `onboarding`. | Repo convention for a gated feature. The worst failure here is silent (an unfiltered 200). |

## Data

### Big Tech rule (for the skill)

> An independent software, internet, device, chip or cloud company worth **$100B or more**: market cap if public, last priced round if private. Check with a dated source when adding.
> **Not:** subsidiaries (GitHub, Slack, Twitch, Waymo, Zoox, xAI), aerospace (SpaceX), non-tech (Disney, GM, Capital One).
> Don't move a company on day-to-day price swings. Review the whole list once a year.

**Final Big Tech (18):** Google, Apple, Microsoft, Amazon, Meta, NVIDIA, Netflix, TikTok, OpenAI, Anthropic, Spotify, Airbnb, Salesforce, Cisco, Intel, Palantir, CrowdStrike, Cloudflare.

Market caps checked 2026-11-26 (companiesmarketcap.com): Apple $5.17T, Microsoft $3.64T, NVIDIA $3.61T, Alphabet $3.33T, Amazon $2.64T, Meta $1.56T, Anthropic $1.11T, Palantir $394B, Cisco $371B, Intel $290B, Netflix $244B, CrowdStrike $216B, Salesforce $162B, Spotify $127B, Airbnb $103B, Cloudflare $102B. Private: OpenAI $852B (round closed 2026-03-31), ByteDance ~$550B (Feb 2026 secondary).

**Just under the bar, so out:** Snowflake $94B, Adobe $91B (was $150B at end of 2025), DoorDash $73B.

### Counts

| Category | Count | Card shows first 6 |
|---|---|---|
| Big Tech | 18 | Google, Apple, Microsoft, Amazon, Meta, NVIDIA |
| AI Labs | 9 | OpenAI, Anthropic, Google, Meta, xAI, Mistral AI |
| AI Startups | 129 | Scale AI, Glean, Replit, Lovable, Suno, HeyGen |
| YC Alumni | 41 | Airbnb, Stripe, Coinbase, Reddit, Dropbox, DoorDash |
| Unicorns | 82 | OpenAI, Stripe, Databricks, Anduril, Notion, Ramp |
| Breakout Startups | 29 | Cursor, Perplexity, ElevenLabs, Cognition, Sierra, Harvey |
| Space, Defense & Robotics | 29 | SpaceX, Palantir, Anduril, Blue Origin, Waymo, Neuralink |
| Fintech & Trading | 25 | Stripe, PayPal, Coinbase, Block, Capital One, Robinhood |
| Dev Tools & Infra | 72 | Cloudflare, GitHub, GitLab, Atlassian, MongoDB, Datadog |
| Household Names | 38 | Netflix, Disney, Spotify, Airbnb, Reddit, Discord |

All 251 roster companies have 1 to 5 categories, all from the 10 approved slugs. 472 memberships.

### Left Big Tech (32), and where they live now

All keep the proposal's other categories. Two gained one (bold).

| Company | Now in |
|---|---|
| Adobe, Clear, Expedia, Lyft, Pinterest, Roblox, Slack, Snap, Zoom | Household Names |
| **Box** | **Household Names** (stretch: an office brand, not a consumer one) |
| Atlassian, Cerebras, Datadog, GitHub, MongoDB, Okta, Snowflake, Twilio | Dev Tools & Infra |
| **Figma** | **Dev Tools & Infra** (stretch: Dev Mode and Figma Make, used by engineers) |
| Affirm, Block | Fintech & Trading |
| PayPal, Robinhood | Fintech & Trading, Household Names |
| Coinbase | YC Alumni, Fintech & Trading, Household Names |
| DoorDash, Dropbox, Instacart, Reddit, Twitch | YC Alumni, Household Names |
| GitLab | YC Alumni, Dev Tools & Infra |
| Waymo, Zoox | Space, Defense & Robotics |

Joined Big Tech: **OpenAI**.

### Ordering choices

- Household Names leads with non-Big-Tech brands so its card doesn't repeat the Big Tech logos.
- AI Startups leads with names not on the Breakout card.
- Beyond the hand-picked head, each list's tail is alphabetical by display name.

### Visible landing changes

- Big Tech card and the "Just Posted" Big Tech slot change (the slot uses all Big Tech members). Out: Adobe, Snap, Reddit, Pinterest, Dropbox, Block, Twitch, Slack, Figma. In: Amazon, Meta, TikTok, OpenAI, Anthropic, Salesforce, Cisco, Intel, Palantir, CrowdStrike, Cloudflare.
- Card headings shorten: "Y Combinator Alumni" -> "YC Alumni", "Developer Tools & Infrastructure" -> "Dev Tools & Infra".
- 10 cards, not 9.

## Source of truth

```
src/backend/api/data/company_categories.json
  ├─ backend boot: seed_company_categories() ─> company_categories + company_category_members
  │     ├─ GET /api/jobs/facets  -> companyCategories[]
  │     └─ GET /api/jobs/search?company_category=  -> resolve members -> SQL
  └─ frontend import (config/companyCategories.ts)
        ├─ landing cards + "Just Posted" Big Tech slot
        ├─ fallback dropdown options (old backend / stale facets cache)
        └─ demo-mode client-side filter
```

File shape (array order is display order):

```json
{ "categories": [
  { "slug": "big_tech", "label": "Big Tech", "definition": "...", "companyIds": ["google", "apple", ...] }
] }
```

## Backend

### B1. Schema + migration

`api/db_models.py`:

- `CompanyCategory` -> `company_categories`: `slug TEXT PK`, `label TEXT NOT NULL`, `definition TEXT NOT NULL`, `sort_order INTEGER NOT NULL DEFAULT 0`.
- `CompanyCategoryMember` -> `company_category_members`: `category_slug TEXT NOT NULL FK company_categories.slug ON DELETE CASCADE`, `company_id TEXT NOT NULL` (soft link, no FK: house style, `companies` is truncated freely in tests), `position INTEGER NOT NULL` (0 = most recognizable). PK `(category_slug, company_id)`. No extra index (472 rows).
- `UserSavedFilters.company_category`: `JSONB NOT NULL DEFAULT '[]'::jsonb`. SINGULAR, like its siblings. Recent page only.

Migration:

- `alembic revision --autogenerate -m "company categories"`, then review.
- `down_revision = 'ef0f7d8c8e11'` today (prod head too). Re-run `python3 .claude/skills/add-company/scripts/current_head.py` before committing and again before merge. It is a VARIABLE, not just the docstring.
- Hand-adjust to the house pattern (`c48b0f2e7d19`): `op.execute("SET LOCAL lock_timeout = '5s'")` first in both directions; one combined `ALTER TABLE user_saved_filters ADD COLUMN company_category JSONB NOT NULL DEFAULT '[]'::jsonb`.
- Catalog-only: two new tables plus a constant-default column. No rewrite.
- **No seed rows in the migration.** Boot seeds them.
- Downgrade: drop the column, then members, then categories.
- Railway runs it in the lifespan (`apply_alembic_migrations_with_retry`) before the seed. After deploy, check `alembic_version` moved and `SELECT count(*) FROM company_category_members` = 472.

### B2. Seed + service (`api/services/company_categories.py`, new)

- `DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "company_categories.json"`.
- `load_company_categories(path=DATA_PATH) -> list[CompanyCategoryDef]` (TypedDict: `slug, label, definition, company_ids`). Validates and raises `ValueError` on: bad slug (`\A[a-z_]{1,40}\Z`), duplicate slug or label, empty label/definition, a member id failing `ENABLED_COMPANY_ID_PATTERN`, a duplicate member in one category.
- `seed_company_categories(conn, categories=None) -> dict`. Loads lazily (like `seed_company_profiles`). One transaction:
  1. Upsert categories; `sort_order` = array index.
  2. Delete member rows not in the file.
  3. Upsert members; `position` = index in `companyIds`.
  4. Delete categories not in the file (cascades).
  5. Commit. Roll back and re-raise on `psycopg2.Error`.
  - WARN on member ids with no `companies` row (still seeded). Always log one INFO line with inserted/updated/deleted counts.
- `list_company_category_facets(conn) -> list[dict]`: `SELECT slug, label, sort_order, NULL AS parent_slug FROM company_categories ORDER BY sort_order`. Guard on the relation existing (`_regclass`, as the subcategory arm does) and return `[]`.
- `resolve_company_category_members(conn, slugs) -> list[str]`: `SELECT DISTINCT company_id ... WHERE category_slug = ANY(%s) ORDER BY company_id`.
- `main.py` lifespan: call after `seed_company_profiles`, same broad `except Exception` soft-fail (log, keep last-good DB content, never crash-loop boot).

### B3. Facets

- `models.JobFacetsResponse.company_categories: list[FacetOption] = Field(default_factory=list)` -> wire key `companyCategories`.
- `routers/jobs.py::list_facets` fills it from `list_company_category_facets`. Not added to `taxonomy.json` (the enricher doesn't need it).

### B4. Search (`/api/jobs/search`)

- `routers/jobs_search.py`: new repeatable `company_category: list[str] | None = Query(None, ...)`.
  - Validate with `_validate_slugs(..., pattern=_COMPANY_CATEGORY_RE, field="company_category")`: `\A[a-z_]{1,40}\Z`, 20-value cap (400), malformed is 422, deduped.
  - Unknown but well-formed slug: matches nothing, no error (same as `category`).
  - Inside the timed `try`, after owned-source resolution: `company_category_ids = resolve_company_category_members(conn, company_categories) if company_categories else None`.
  - Fingerprint **only when active**: `company_category` (slugs) and `company_category_ids` (resolved, sorted). Absent keeps every in-flight cursor valid on deploy day. A membership change mid-walk becomes a 409 restart.
  - Add the count to the slow-search log line.
- `services/job_search.py`:
  - `SearchFilters.company_category_ids: list[str] | None`. `None` = no filter. `[]` = active, matches nothing.
  - `build_search_where`: `if company_category_ids is not None:` append `job_listings.company = ANY(%s::text[])`. **Must be `is not None`.** A truthiness check turns an empty membership into "all jobs".
  - `get_search_counts` / `_header_counts_where`: unchanged (tiles ignore it).
- Keyset paging: the predicate ANDs with the cursor predicate; ordering untouched.

### B5. Saved filters

- `models.SavedFiltersResponse.company_category: list[str] = []` (always emitted: this is the frontend's capability signal).
- `models.SavedFiltersUpdateRequest.company_category: list[_FacetSlug] | None = Field(default=None, max_length=_MAX_FACET_VALUES)`. Dedupe validator must pass `None` through. Still `extra='forbid'`.
- `saved_filters_service`: add to `SavedFiltersRow`, `default_saved_filters` (`[]`), `_row_to_saved_filters`, the GET `SELECT`.
- `upsert_saved_filters(..., company_category: list[str] | None)`:
  - INSERT value `COALESCE(%s::jsonb, '[]'::jsonb)`.
  - ON CONFLICT `company_category = COALESCE(%s::jsonb, user_saved_filters.company_category)`.
  - Pass the param twice: `Json(v)` or `None`. (Don't use `EXCLUDED`; it already holds the coalesced `[]`.)
  - Docstring: the one exception to full-replace, and why.
- `routers/saved_filters.py`: pass `body.company_category`.

### B6. Onboarding

- `models._ONBOARDING_STEPS = 4`. `OnboardingRequest.company_category: list[_FacetSlug] | None = None`, deduped.
- `user_service.complete_onboarding(..., company_category)`: add the column to the onboarding upsert with the same COALESCE rule. Idempotency unchanged.
- `routers/users.py`: pass it; add `company_category_count` to the PostHog counts.

### Backend docs

- `src/backend/AGENTS.md`: search param bullet, facets key, saved-filters exception, onboarding fields and step range, the new seed in the lifespan list, `company_category_members` in the tables list.
- `src/backend/docs/database-schema.md`: the two tables and the column.

## Frontend

### F1. Shared data module + landing

- New `src/config/companyCategories.ts`:
  - `import data from '../../../backend/api/data/company_categories.json'`.
  - Exports: `COMPANY_CATEGORIES` (`{slug, label, definition, companyIds}[]`), `COMPANY_CATEGORY_SLUGS`, `FALLBACK_COMPANY_CATEGORY_OPTIONS: FacetOption[]` (`sortOrder` = index, `parentSlug: null`), `companyCategoryOptions(facets?: JobFacets): FacetOption[]` (facets if non-empty, else fallback), `companyIdsInCategories(slugs): Set<string>`.
- Delete `pages/LandingPage/companyCategories.ts`. Update `sections/CompanyCategoriesSection.tsx`, `sections/triptychJobs.ts`, and the tests that import it (`id` becomes `slug`).
- `CompanyCategoriesSection`:
  - Each card `to={recentJobsHrefForCompanyType(slug)}`.
  - `onClick`: dispatch `resetRecentJobsFilters()`, then `setRecentJobsCompanyCategory([slug])`, then let the RouterLink navigate.
  - Keep `VISIBLE_LOGOS = 6` and "+N".
  - Replace the header comment about "wiring query params now would ship dead params".
  - 10 cards in a 3-column grid leaves one alone on the last row. Pick a layout without it (e.g. 2 columns up to `lg`, 5 at `lg+`). Screenshot at 390, 768, 1280 and 1440.
- `triptychJobs.ts`: read `big_tech` from the new module. No other change.
- Dev server: Vite's `fs.allow` defaults to the workspace root (repo root, because of root `package.json` `workspaces`). Confirm the landing renders under `npm run dev` and `vercel dev`; that path was not probed.

### F2. Recent Jobs filter

- `types/index.ts`:
  - `RecentJobsFilters.companyCategory?: string[]` (Recent only; the trend page is one company).
  - `SavedFilters.companyCategory?: string[]`. OPTIONAL on purpose: absent means "this backend doesn't know the field". Unlike `subcategory`, do not normalize it to `[]`.
  - `JobFacets.companyCategories?: FacetOption[]`.
- Slice:
  - Give `createFilterSlice` an optional third argument for slice-only reducers, merged into `reducers`. The `userModified` matcher covers them by prefix.
  - `recentJobsFiltersSlice` adds `setRecentJobsCompanyCategory` (`[]` -> `undefined`).
  - Add `companyCategory: undefined` to `initialFilters`. Reset copies only keys present there; miss it and Reset leaves the filter on.
- `features/filters/urlFilters.ts`:
  - Add `'company_type'` to `FILTER_PARAMS`.
  - Parse with `isFacetSlug`, capped at `MAX_URL_FACET_VALUES`. Build by appending.
  - Export `COMPANY_TYPE_PARAM` and `recentJobsHrefForCompanyType(slug)`.
- `features/filters/selectors/recentJobsFilterSignature.ts`: add `companyCategory: stableList(...)`. Skip it and the dropdown issues no request.
- `features/jobs/searchJobsArgs.ts`: `companyCategory: normalizeList(filters.companyCategory)`; `buildSearchJobsQuery` appends `company_category`. `SearchJobsArgs.companyCategory?: string[]`.
- `api/jobs.ts`: add `'company_category'` to `REPEATABLE_PARAMS`. If it's missing, the backend never sees the filter and returns an unfiltered 200.
- `features/jobs/jobsApi.ts` `getFacets`: pass `companyCategories` through when it's an array, else `undefined`. Never an error.
- `components/recent-jobs-page/RecentJobsFilters.tsx`: `<FacetMultiSelect label="Company type" options={companyCategoryOptions(facets)} value={filters.companyCategory} onChange={(s) => dispatch(setRecentJobsCompanyCategory(s))} />`, after Level, before Location.
- Demo mode: `jobFilteringUtils.filterJobsByFilters` gains `matchesCompanyCategory` (`job.company` in `companyIdsInCategories`), active only when the filters carry the field.

### F3. Saved filters

- `savedFiltersApi.validateSavedFilters`: absent stays absent; present must be a string array.
- `useHydrateSavedFilters`: `companyCategory: savedFilters.companyCategory` in `hydrateRecentJobsFilters` only.
- `propagateSavedFilters`: push `setRecentJobsCompanyCategory(saved.companyCategory)` only when defined. Never to the graph slice.
- `SavedFiltersPage`:
  - `draftFromServer` copies the field only when defined.
  - `handleSave` spreads `companyCategory` into the PUT only when `draft.companyCategory !== undefined`. Every section's Save does this.
  - New `SaveSection` value `'companyTypes'` and a `companyTypesDirty` memo.
  - Render the new section only when `draft.companyCategory !== undefined`. Add a 4th skeleton row.
- New `components/saved-filters/CompanyTypeDefaults.tsx` (mirror `CategoryLevelDefaults`):
  - Title "Default company types".
  - Helper "Applied when you open Recent Job Postings. Only jobs at these kinds of companies are shown."
  - `FacetMultiSelect` label "Company type". Save label "Save company types".

### F4. Onboarding step 4

- `onboardingModel.ts`:
  - `ONBOARDING_STEP_COUNT = 4`, `OnboardingStep = 0 | 1 | 2 | 3`.
  - Add question `{ title: 'What kinds of companies do you want?', shortName: 'Companies' }`.
  - `EMPTY_ANSWERS.companyCategory = []`.
  - Update `toRequestAnswers`, `stepHasAnswer` (step 3) and `savedFiltersHaveAnswers`.
- `savedFiltersApi`: `OnboardingAnswers.companyCategory?: string[]`; `CompleteOnboardingArgs.step: 1 | 2 | 3 | 4`.
- New `components/onboarding/CompanyTypeQuestion.tsx`: chips, like `LevelQuestion`. Options come from `companyCategoryOptions(facets)`.
- `OnboardingFlow.tsx`:
  - Render it at `step === 3`. "Show my jobs" moves to step 4.
  - In `submit`, read `savedFiltersApi.endpoints.getSavedFilters.select()` for the capability.
  - If `data?.companyCategory === undefined`, drop `companyCategory` from the body and send `step: Math.min(step + 1, 3)`.
- Update `src/frontend/AGENTS.md` (the onboarding bullet says "roles -> levels -> places").

### F5. WebMCP

- `list_filter_options` adds `companyCategories`.
- `search_jobs` and `apply_feed_filters` accept `companyCategory`.
- `save_filter_defaults` includes `companyCategory` only when the caller passed it.

### Frontend docs

- Root and frontend `AGENTS.md`: the `api/jobs.ts` repeatable-param list, the Recent filters list, key files, onboarding step count, and "Adding a Company" now includes categories.

## Deploy window (Vercel ships ~6 min before Railway)

| Situation | What the user sees | Accepted? |
|---|---|---|
| New SPA, old backend | Dropdown uses the bundled list. The search ignores `company_category`, so the list is unfiltered under the chip. | Yes, per brief |
| Same | Saved Filters page hides "Default company types". The PUT omits the key, so saving works. | Yes |
| Same | Onboarding shows 4 steps. The step-4 answer is not sent; `step` is clamped to 3. | Yes |
| Facets edge cache (24h + SWR) still holds the old payload | Bundled list, which is the same data. | Yes |
| Old SPA tab after both deploys | Its PUT omits the key; the stored value is kept. | Yes, by design |
| Feature A merged before its one-line wiring | Its PUT omits the key; the stored value is kept. | Yes |
| Railway deploy skipped (merge-train trap) | The first row lasts until a redeploy. | Check `alembic_version` |

## add-company skill (`.claude/skills/add-company/SKILL.md`)

- Intro table: "four edits plus logos" becomes five. New row: categories -> `src/backend/api/data/company_categories.json`.
- New **Step 4.5: Company categories (required)**:
  1. Read each category's `definition` in the JSON. They are the rules.
  2. Pick every category that fits, at least one. If none fits, stop and ask. Never add a category.
  3. Factual claims need a source in the PR body:
     - YC Alumni: the company's `ycombinator.com/companies/<slug>` page (batch).
     - Unicorns: a dated source for a $1B+ valuation; private and independent.
     - Big Tech: a dated $100B+ market cap or priced round.
     - AI Labs: strict, frontier models only.
     - Breakout Startups and Household Names are editorial. No source, stay conservative.
  4. Insert the id into each chosen `companyIds` at its recognizability rank. If unsure, append; only the first 6 show on a landing card.
  5. Verify: `npx vitest run src/__tests__/config/companyCategories.test.ts` and `cd src/backend && pytest api/tests/test_company_categories_data.py`.
- Checklist line: "`company_categories.json`: id in 1+ categories, sources for factual ones in the PR".
- Optional stdlib helper `scripts/check_categories.py <id>`: prints the id's categories and fails if it has none.

## Tests to add

### Backend

| File | Cases |
|---|---|
| `test_company_categories_data.py` (pure) | Exactly the 10 slugs, in the committed order. Labels unique and non-empty. Definitions non-empty. Ids match the company-id pattern. No duplicates inside a category. 5+ members each. Every `company_profiles.json` id is in 1+ category and every member is a profile id (backend-side roster parity). Big Tech has 25 or fewer members and contains no subsidiary (github, slack, twitch, waymo, zoox, xai). |
| `test_company_categories_seed.py` | Seeds empty tables. A second run changes nothing. A removed member or category is deleted (cascade). Label and definition edits apply. `position` and `sort_order` follow array order. Malformed data raises before any write. An id with no `companies` row is still seeded and WARN-logged. |
| `test_main_lifespan.py` | A seed exception does not stop boot. |
| `test_jobs_router.py` (facets) | `companyCategories` in order with `parentSlug: null`. A missing relation gives `[]`, not a 500. |
| `test_jobs_search_company_category.py` | One type returns only member rows (decoy: a non-member). Two types OR. ANDs with `company`, `category` and `level`. Unknown slug returns 0 rows (not all). A category with no members returns 0 rows. Malformed is 422; 21 values is 400. A 3-page keyset walk is complete with no duplicates. A cursor minted without the param keeps working. A cursor replayed with the filter changed is 409. A membership change mid-walk is 409. Recency counts unchanged. Custom boards hidden when active. |
| `test_saved_filters_router.py` / `_service.py` | GET defaults `companyCategory: []`. PUT stores and dedupes, caps at 50. **PUT omitting it keeps the stored value.** PUT `[]` clears. Unknown keys still 422. |
| `test_onboarding_router.py` | Saves `companyCategory` on new and existing rows. Skip keeps it. `step=4` OK, `step=5` 422. Counts include `company_category_count`. Omitted keeps the stored value. |
| `test_migration_company_categories.py` | Modelled on `test_migration_user_saved_filters_subcategory.py`. A pre-existing row reads `[]`. Tables, PK and FK exist. Downgrade drops all three. Re-upgrade works. Single head (`test_migrations_paths.py`). |

Run `mypy` clean. On a bare DB, compare pytest against main's baseline (about 21 failed / 1072 passed / 197 errors), not zero.

### Frontend (Node 22.14.0, `npx vitest run`)

- `__tests__/config/companyCategories.test.ts` (replaces the landing one): every `COMPANIES` id is in 1+ category; every member is in `COMPANIES`; the 10 approved slugs in order; overlap is allowed; the fallback options mirror the data; `companyIdsInCategories` takes the union.
- `CompanyCategoriesSection.test.tsx`: 10 cards; each href is `/jobs?company_type=<slug>`; the first 6 logos follow data order; "+N" is right; a click leaves the slice holding only `[slug]`, even after other filters were set.
- `triptychJobs.test.ts`: the Big Tech slot is the sorted 18. `content.test.ts`: the em-dash walk still covers the categories.
- `urlFilters.test.ts`: `company_type` parse, drop, cap, build and round-trip. A link with only `company_type` counts as a link. `useRecentJobsUrlSync`: the URL beats saved filters.
- Slice: setter normalizes `[]`; Reset clears; `userModified` flips; the graph slice has no such field.
- Signature selector moves when the field changes. `searchJobsArgs`: sorted, repeated `company_category`, absent when empty.
- `jobs.serverless.test.ts`: both `company_category` values are forwarded (appended).
- `RecentJobsFilters.test.tsx`: "Company type" combobox. Options from facets; fallback when the key is missing or `[]`. Two picks. Reset.
- `savedFiltersApi`, `propagateSavedFilters`, `useHydrateSavedFilters`, `SavedFiltersPage`: absent stays absent; the section is hidden when absent; the PUT includes the key only when defined; saving pushes it to the Recent slice only.
- Onboarding (`onboardingModel`, `OnboardingFlow`): 4 steps, "1/4"; step 4 options; Finish sends `companyCategory`. Cached saved filters without the field mean the body omits it and a Skip on step 4 sends `step: 3`.
- Demo mode filters by company type. WebMCP tool tests for the four tools.

### e2e

- **`onboarding`** (update + add):
  - Every drive-through gains step 4 (`helpers.ts`). Counters become "/4". Tab title becomes "Question 1 of 4".
  - OB-10 (API): `companyCategory` saved; `step: 4` accepted.
  - OB-U1: answer Big Tech; the list holds only the Big Tech match (decoy: the same job at a non-member).
  - OB-U14 (older backend): route the saved-filters GET to strip `companyCategory`, and the POST to 422 when the body carries it or `step > 3`. The flow still saves, and the body had neither.
- **New section `company-categories`** (ports 8208/3208, DB `jobscraper_e2e_company_categories`, modelled on `subcategories`):
  - CC-00: facets equal the JSON (10, in order) and the seeded tables.
  - CC-01: one type returns members only.
  - CC-02: OR across types.
  - CC-03: ANDs with category and level.
  - CC-04: unknown slug returns 0 rows.
  - CC-05: complete 3-page keyset walk.
  - CC-U1: check two types; the list narrows and the URL shows `company_type`.
  - CC-U2: landing card goes to `/jobs` pre-filtered, including the Back-then-another-card path.
  - CC-U3: a saved default applies on reload.
  - CC-U4: Reset clears the filter and the URL.
  - CC-U5: facets without the key still renders the fallback options.
  - Add a runbook at `.claude/skills/e2e-gate/sections/company-categories.md` and rows in the gate's `SKILL.md` and `e2e/README.md`.
- **Regression gates to run:** `subcategories` (this touches `job_search.py`, `jobs_search.py`, `RecentJobsFilters.tsx`, `searchJobsArgs.ts`, `JobFacetsResponse`) and `onboarding`.

## Feature A hand-off (`feat/save-default-search`)

`companyCategory` is a plain `string[]` on the Recent slice and on `SavedFilters`. Once both PRs are on main, in `src/frontend/src/features/defaultSearch/defaultSearch.ts`:

- Payload mapping: add `companyCategory` (only when the cached saved filters carry the key).
- `isSameDefaultSearch`: compare sorted lists.

Until then, feature A's PUT simply leaves the stored value alone. Say this in the PR.

## Build order (one commit per unit)

| # | Unit | Commit |
|---|---|---|
| B1 | Models + migration + migration test | `feat(db): company category tables and saved-filter column` |
| B2 | Loader, seed, lifespan, data and seed tests | `feat(api): seed company categories from json on boot` |
| B3 | Facets + search filter + tests | `feat(api): filter job search by company category` |
| B4 | Saved filters + onboarding API + tests, backend docs | `feat(api): save company types in saved filters and onboarding` |
| F1 | Shared module, landing cards, triptych, tests | `feat(landing): category cards link to filtered recent jobs` |
| F2 | Slice, URL, args, proxy, dropdown, demo, tests | `feat(recent): company type filter` |
| F3 | Saved filters plumbing + page section, tests | `feat(saved-filters): default company types` |
| F4 | Onboarding step 4, tests | `feat(onboarding): ask which kinds of companies, step 4 of 4` |
| F5 | WebMCP tools | `feat(webmcp): company type in filter tools` |
| S1 | add-company skill + check script, AGENTS.md updates | `docs(skill): categories are a required add-company step` |
| E1 | e2e section + onboarding cases | `test(e2e): company categories gate` |

## Risks

- **Claims rot.** A unicorn IPOs, a giant drops under $100B. Cloudflare ($102B) and Airbnb ($103B) sit on the line today. Review yearly.
- **Silent unfiltered 200** if the proxy or the router drops the param. The serverless test and CC-01 guard it.
- **`is not None` vs truthiness** in `build_search_where`. A wrong check makes an empty membership return everything. A test pins it.
- **The old-backend window shows an unfiltered list under an active chip** for ~6 min, longer if Railway skips the deploy.
- **The frontend build now reads a backend file.** Moving it breaks the build (loudly). `tsc`, `vitest` and `vite build` were probed; the dev server was not.
- **A 4th onboarding question adds friction.** Watch `onboarding_skipped` by `step`.
- **Private boards vanish** while a company type is active.
- **Stretches:** Box (Household Names), Figma (Dev Tools & Infra), plus the proposal's own list (Airtable, Tools for Humanity, Nox Metals, Paraform, ...).
