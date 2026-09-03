# Curated Companies — `/curated-companies` (`ROUTES.CURATED_COMPANIES`)

A searchable directory of every tracked company, with brand info. The public
`GET /api/companies` payload that `list_companies` reads is the same one this page
renders.

Page: `src/frontend/src/pages/CuratedCompaniesPage/CuratedCompaniesPage.tsx`
(grid `CuratedCompaniesGrid`, client-side `SearchBar`).

## Sub-features

- **Full directory** — every enabled/public company (alphabetical), ~131 in the clone.
- **Client-side search** — the on-page search box filters the grid by substring.
- **Name → id resolution** — the directory is the source that maps a display name (e.g.
  "Apple") to a company id (`apple`) for the other tools.

## How to get to it (user POV)

Sidebar (INFO group) "Curated Companies", route `/curated-companies`. Public.

## Driving it with WebMCP

- **List the directory (Tier-1):**
  ```ts
  const all = await call(page, 'list_companies');            // { companies: [{ id, displayName, ats, … }] }
  // all.companies.length ~= 131 in jobscraper_e2e
  ```
- **Substring filter (mirrors the page's SearchBar):**
  ```ts
  const hit = await call(page, 'list_companies', { query: 'apple' });
  // hit.companies.every(c => `${c.id} ${c.displayName}`.toLowerCase().includes('apple'))
  ```
- **DOM assert:** the page heading is "Curated Companies"; the grid renders one card per
  company. Assert the rendered card count for a `query` matches `list_companies({ query })`'s
  length (this list is NOT virtualized, so a count assertion is fair here — unlike the
  Recent feed).

## Gotchas

- **`list_companies` filters over `id` OR `displayName`**, case-insensitive substring — the
  same predicate the page's SearchBar uses, so their results should agree.
- **This is the resolver of record for company names.** `search_jobs` / `apply_feed_filters`
  / `get_company_hiring_trend` accept a display name and resolve it via the compile-time
  `COMPANIES` list; when a name is ambiguous or you want the exact id, read it here first.
- **User-added (`u-…`) boards are not in this directory** — it is the curated/public set
  only. A `u-…` id resolves nowhere here; that's expected.
