# Saved Filters — `/saved-filters` (`ROUTES.SAVED_FILTERS`, login-gated)

A signed-in page to set default time windows (per page), shared locations,
category/level defaults, the saved-companies picker, and reusable keyword lists.
Both Tier-3 writes here are asserted by their DB side effect.

Page: `src/frontend/src/pages/SavedFiltersPage/SavedFiltersPage.tsx`.

## Sub-features

- **Scalar saved filters** — `recentTimeWindow`, `trendTimeWindow`, `locations`, category /
  level defaults, active keyword-list pointers. Written by `save_filter_defaults`
  (`PUT /api/users/saved-filters`).
- **Enabled-companies picker** — the set of companies the feed is scoped to. Written by
  `set_enabled_companies` (`PUT /api/users/enabled-companies`).
- **Sign-in gate** — signed-out, the page prompts to sign in; nothing is drivable until
  authenticated.

## How to get to it (user POV)

Sidebar "Saved Filters", route `/saved-filters`. **Login-gated** — the JWKS-seam fixture
(`signedInPage` / `signedInContext`) provides the auth; `request_sign_in` cannot complete
headlessly.

## Driving it with WebMCP

Use `signedInPage` (already carrying a minted token). Both tools return `Sign in required`
when no token is present, so this is where the fixture matters.

- **Save scalar defaults (Tier-3):**
  ```ts
  const saved = await call(signedInPage, 'save_filter_defaults', {
    recentTimeWindow: '7d', trendTimeWindow: '90d', locations: ['Seattle, WA'],
  });                                                    // returns the server echo
  ```
  **DB proof** — a `user_saved_filters` row for the primary identity:
  ```bash
  .venv/bin/python helpers/db_assert.py --table user_saved_filters --email 'e2e+add-companies@jvn.test'
  ```
- **Set enabled companies (Tier-3):**
  ```ts
  const echo = await call(signedInPage, 'set_enabled_companies', {
    companyIds: ['apple', 'spacex'], autoEnroll: true,
  });                                                    // { companyIds, autoEnroll }
  ```
  **DB proof** — `user_enabled_companies` rows (this is what `helpers/drive.spec.ts` drives):
  ```bash
  .venv/bin/python helpers/db_assert.py --table user_enabled_companies --email 'e2e+add-companies@jvn.test'
  ```
- **Feed reflects the enabled set after a reload** — after `set_enabled_companies`, reload
  `/` and confirm the fetch-progress chips / feed scope narrow to the enabled set.

## Gotchas

- **Auth comes from the fixture, not `request_sign_in`.** Drive these on `signedInPage`;
  `request_sign_in` only fires the prompt path and returns `{ prompted: true }`.
- **The primary identity is `e2e+add-companies@jvn.test`** (`e2e/shared/auth/mint.py`
  `PRIMARY_USER`) — that is the `--email` to pass `db_assert.py`. AC-10's second identity is
  `e2e+other@jvn.test`.
- **`save_filter_defaults` copies the `SavedFilters` field set** — pass only real fields
  (`recentTimeWindow`, `trendTimeWindow`, `locations`, `category`, `level`,
  `recentActiveKeywordListId`, `trendActiveKeywordListId`); an unknown/owned-elsewhere
  keyword-list pointer is a 409 server-side.
- **`set_enabled_companies` also refreshes the store** (best-effort `loadEnabledCompanies`)
  after the write — the DB row is the authoritative side effect, asserted above.
- **Re-runnable:** `cleanup.sh` sweeps owned companies, and `ensure_db.sh` scrubs on the next
  launch, so a prior run's saved filters / enabled set do not poison the next.
