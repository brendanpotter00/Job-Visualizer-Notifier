# verify-onesecondswe — feature map

The maintained source of truth for what to verify. One file per **user-facing
route** in `src/frontend/src/config/routes.ts`, each with the same four H2s:
`## Sub-features`, `## How to get to it (user POV)`, `## Driving it with WebMCP`,
`## Gotchas`. A proof that drives one convenient route is incomplete while this
map lists others. See the parent [`SKILL.md`](../SKILL.md) for Launch / Doctor /
Drive / Evidence / Cleanup.

Everything is driven through the 14 tools on `window.__webmcp__` (never raw DOM
clicks). WebMCP arranges/acts; the DOM (and `jobscraper_e2e`) is where you read
the proof.

## Mapped routes

| File | Route (`ROUTES.*`) | Primary tools |
|---|---|---|
| [`recent-jobs.md`](recent-jobs.md) | `/` `RECENT_JOBS` | `search_jobs`, `apply_feed_filters`, `reset_feed_filters`, `open_job`, `list_filter_options`, `search_locations`, `list_companies` |
| [`company-hiring-trends.md`](company-hiring-trends.md) | `/companies` `COMPANIES` | `get_company_hiring_trend`, `get_job`, `list_companies` |
| [`curated-companies.md`](curated-companies.md) | `/curated-companies` `CURATED_COMPANIES` | `list_companies` |
| [`saved-filters.md`](saved-filters.md) | `/saved-filters` `SAVED_FILTERS` (login-gated) | `save_filter_defaults`, `set_enabled_companies` |
| [`vote-features.md`](vote-features.md) | `/vote-features` `VOTE_FEATURES` | `upvote_feature`, `submit_feedback` |
| [`account.md`](account.md) | `/account` `ACCOUNT` | `request_sign_in` |
| [`add-companies.md`](add-companies.md) | `/add-companies` `MY_COMPANIES` (flag-gated) | none — cross-references the `e2e/add-companies` gate, plus the one non-shim `@live-view` drive |
| [`company-name-search.md`](company-name-search.md) | `/add-companies` `MY_COMPANIES` (flag-gated) — the **name** half of the same box | none — the non-shim `@name-search` drive, plus the folded `e2e/company-name-search` judge (`helpers/name_search.sh`, $0; `--live` ~$0.27) |
| [`why.md`](why.md) | `/why` `WHY` | none (static) |
| [`landing.md`](landing.md) | `/landing` `LANDING` (direct URL only — no nav entry) | none (static marketing) |

## Intentionally unmapped

The **admin** routes — `/qa` (`QA`), `/admin/users`, `/admin/location-normalization`,
`/admin/enrichment`, `/admin/custom-companies`, `/admin/feedback`, and the public-but-
admin-linked `/location-pipeline` — are **not** WebMCP-driven. They sit behind
`AdminRoute`, reachable only with an admin grant (a row in the `admins` table; the
product's own grant path is itself admin-gated). No WebMCP tool touches them, so they are
`verified-unreachable` from this surface, not "missing". To exercise one, grant admin the
way `e2e/shared/db/assertions.py::grant_admin` does (a direct `INSERT INTO admins`, paired
with `revoke_admin` in a `finally`) — that is fixture territory, out of scope for this
user-facing skill.

`MY_COMPANY_DETAIL` (`/add-companies/:id`) and `MY_COMPANIES_LEGACY` (`/my-companies`) are
sub-paths/redirects of Add Companies, covered by [`add-companies.md`](add-companies.md).

`/add-companies` has **two** files because its one input box has two backend paths: paste a
careers URL and you are in [`add-companies.md`](add-companies.md); type a company name and
you are in [`company-name-search.md`](company-name-search.md). They are separate features
with separate gates, separate failure modes, and different costs.

## Data reality of the `jobscraper_e2e` clone (read before asserting counts)

- **~246k open jobs, 131 public companies, 1662 canonical locations, a 6-category /
  6-level facet catalog** — so `search_jobs`, `list_companies`, `search_locations` and
  `list_filter_options` all return real, non-trivial data.
- **Enrichment is ~100% NULL** (only ~24 sidecar rows). A `category`/`level` filter
  therefore narrows to `filteredTotal ≈ 0`. Prove those filters by their `meta` shape;
  use **company / keyword / timeWindow** filters (which have data) whenever you need the
  list to narrow to something non-empty.
