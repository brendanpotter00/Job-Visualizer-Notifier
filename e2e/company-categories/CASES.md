# company-categories — cases

Design: `PLAN.md`. Runbook: `.claude/skills/e2e-gate/sections/company-categories.md`.
Status legend: ⚪ planned · 🟢 green · 🔴 red (with reason).

**Last real run: 2026-11-27, `e2e/run.sh company-categories` @ `feat/company-categories`:
8 API + 5 UI = 13 collected, 13 PASS, exit 0.** UI tier ~16 s; a first provision of the
database (schema-only clone of `jobscraper_pr243`, then `upgrade head`) adds about a minute, once.

The corpus (`fixtures.py`): nine rows. Six at Big Tech members (Google, Apple, Microsoft,
Netflix, Anthropic, plus a Google product-manager row), two Fintech rows (Stripe, Ramp), and
`CC-DECOY`, a senior SWE job at `e2e-cc-decoy`, a company in no type.

## API tier (`api/`, pytest, anonymous — `--fast` runs only these)

| ID | Behaviour | Oracle / decoy | Status |
|---|---|---|---|
| **CC-00** | **One source.** `GET /api/jobs/facets` `companyCategories` = the committed JSON (10, in order, `parentSlug` null) = `company_categories` + `company_category_members` (members in `position` order) | Three-way equality. Also checks the fixtures' restated membership against the JSON, so every other case's oracle describes real data | 🟢 3/3 |
| **CC-01** | **One type returns members only.** `?company_category=big_tech` → exactly the six Big Tech rows | `CC-DECOY` and the Fintech rows absent; mirror: unfiltered returns all nine, so the absence is the filter | 🟢 1/1 |
| **CC-02** | **Types OR.** `ai_labs` + `fintech` → Google (2), Anthropic, Stripe, Ramp | Apple / Microsoft / Netflix (Big Tech, not AI Labs) and the decoy absent | 🟢 1/1 |
| **CC-03** | **ANDs with category and level.** `big_tech` + `software_engineering` + `senior` → Google, Apple, Netflix, Anthropic | `CC-MICROSOFT` (mid), `CC-GOOGLE-PM` (PM) and `CC-STRIPE` (senior SWE, not Big Tech) each fail one side | 🟢 1/1 |
| **CC-04** | **An unknown type matches nothing**, not everything; a malformed slug is a 422 | Rejects reading an empty membership as "no filter" (the `is not None` rule) | 🟢 1/1 |
| **CC-05** | **A keyset walk is complete.** `big_tech`, `limit=2` → 3+ pages, no duplicates, exactly the six rows | Rejects a cursor that loses the filter between pages | 🟢 1/1 |

## UI tier (`ui/`, Playwright)

| ID | Behaviour | Oracle / decoy | Status |
|---|---|---|---|
| **CC-U1** | **The dropdown.** Signed in, `/jobs`: "Company type" reads All and lists the 10 types in order as checkboxes; tick Big Tech + Fintech & Trading → the search carries both, the list holds exactly those rows, the field reads "Big Tech, Fintech & Trading", the URL has both `company_type` values. No horizontal scroll at 768 and 1024px (the row wraps). Also at 375px: the field fits, no horizontal scroll | Exact rows (the decoy is the tell); screenshots `01-dropdown-open`, `02-filtered`, `03-phone-375` | 🟢 1/1 |
| **CC-U2** | **Landing card.** Signed out, `/`: the Big Tech card links to `/jobs?company_type=big_tech`; clicking it lands there filtered. Back, then the Fintech card → only `fintech` in the URL and the list | The Back-then-card path fails without the click handler (the URL is read once per load). **Proven to bite:** with the handler's two dispatches removed, CC-U2 went red (no `company_category=fintech` search after Back) | 🟢 1/1 |
| **CC-U3** | **Saved default.** `/saved-filters` → "Default company types" → Big Tech → "Save company types": the PUT carries `companyCategory`; a NEW context opening `/jobs` gets the filter applied | New context = no memory, only the server's saved filters | 🟢 1/1 |
| **CC-U4** | **Reset.** `/jobs?company_type=fintech` → Reset Filters → the field reads All, `company_type` leaves the URL, all nine rows are back | | 🟢 1/1 |
| **CC-U5** | **Older facets.** `GET /api/jobs/facets` routed to drop `companyCategories` → the dropdown still offers the 10 bundled types in order, and picking one filters | The deploy window and the 24h facets edge cache | 🟢 1/1 |

## Known non-coverage

- The Vercel proxy's `company_category` forwarding (plain `vite dev` here) — `jobs.serverless.test.ts`.
- The onboarding question — the `onboarding` section (OB-10, OB-U1, OB-U18).
