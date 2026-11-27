# Company categories (Company type filter) — e2e gate runbook

Design: `e2e/company-categories/PLAN.md`. Cases and the corpus: `e2e/company-categories/CASES.md`.

## Run it

```bash
e2e/run.sh company-categories              # full gate
e2e/run.sh company-categories --fast       # API tier only (CC-00..CC-05), seconds
e2e/run.sh company-categories --case CC-02 # one case
e2e/run.sh company-categories --keep-up    # leave :8208/:3208 up for a fix loop
e2e/run.sh company-categories --refresh-db # re-provision jobscraper_e2e_company_categories
```

**Cost: $0, unconditionally.** No LLM, no Browserbase, PostHog blanked, the browser fenced to
`127.0.0.1`.

**Ports `8208`/`3208`, database `jobscraper_e2e_company_categories`** (schema-only clone of
`jobscraper_pr243`, else the local `jobscraper`). Its own run lock, so it runs alongside the
other gates.

## When to run it

Before "ready to test" on anything touching:

- `src/backend/api/data/company_categories.json` or `services/company_categories.py` (the boot seed)
- `routers/jobs_search.py` / `services/job_search.py` (the `company_category` param, the cursor fingerprint)
- `routers/jobs.py` facets (`companyCategories`), `routers/saved_filters.py`, `saved_filters_service.py`
- `RecentJobsFilters.tsx`, `config/companyCategories.ts`, `urlFilters.ts`, `searchJobsArgs.ts`,
  the landing `CompanyCategoriesSection.tsx`, `CompanyTypeDefaults.tsx`

Also run `onboarding` (question 4 lives there) and `subcategories` (same search code).

## On red, check first

| ID | First thing to check |
|---|---|
| CC-00 | Which of facets / JSON / tables disagrees. Tables wrong = the boot seed failed (backend.log, "company categories"); it soft-fails so boot never crash-loops |
| CC-01 | Decoy back = the filter is not applied (router param, `SearchFilters.company_category_ids`). All nine back = an unfiltered 200 |
| CC-02 | Fewer rows = AND across types instead of OR (`company = ANY(...)` over the UNION of members) |
| CC-03 | A decoy back = the clause is OR-ed onto the WHERE instead of appended to the AND list |
| CC-04 | Rows back = an empty membership read as "no filter": `build_search_where` must test `is not None`, not truthiness |
| CC-05 | Duplicates or a short walk = the cursor fingerprint or keyset predicate lost the filter |
| CC-U1 | No request with `company_category` = `recentJobsFilterSignature` lacks the field (the dropdown is inert) or `searchJobsArgs` drops it |
| CC-U2 | Second card shows the first card's type = the card's click no longer dispatches reset + set before navigating |
| CC-U3 | The section is missing = the saved-filters GET lacks `companyCategory`; the PUT lacks it = `handleSave` |
| CC-U4 | The field still reads a type = `companyCategory` missing from the Recent slice's `initialFilters` |
| CC-U5 | No options = `companyCategoryOptions` no longer falls back to the bundled list |

## Files this suite does not own

The backend services and routers, and the frontend files above. A red case is a bug report
against them, not a reason to change the case.
