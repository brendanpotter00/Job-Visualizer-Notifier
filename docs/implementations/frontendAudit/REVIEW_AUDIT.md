# Frontend Audit PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-04-19 — Review pass 1

Dispatched agents: code-reviewer, silent-failure-hunter, pr-test-analyzer, type-design-analyzer, comment-analyzer, vercel-prod-verifier. Postgres / Railway verifiers not dispatched — diff is frontend-only (no migrations, no SQL, no `src/backend/**`, no `Dockerfile`/`railway.toml`).

### Code-review findings

**Critical:** None.

**Important:**

- `src/frontend/src/hooks/useCompanyLoader.ts:58-64` — still hand-rolls nested `typeof`/`'data' in`/ternary error decode. `extractErrorMessage` not imported. Violates the new CLAUDE.md rule "All error decoding goes through `extractErrorMessage`." Real symptom: `{ data: { detail: '…' } }` RTK Query shape renders as `"[object Object]"` to the user. (code-reviewer, silent-failure-hunter)
- `src/frontend/src/features/jobs/jobsSelectors.ts:35-41` — `selectCurrentCompanyError` still hand-rolls the RTK Query decode. PLAN Shared Contracts §4 lists this as an `extractErrorMessage` target. (code-reviewer)
- `src/frontend/src/features/auth/useCurrentUser.ts:30`, `src/frontend/src/features/preferences/useEnabledCompanies.ts:51`, `src/frontend/src/components/layout/UserMenu.tsx:35` — still `err instanceof Error ? err.message : '…'` ternaries. PLAN Unit 1 targeted these; rule in CLAUDE.md forbids retaining them. (code-reviewer)
- `src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx:57-61` — RTK Query `error` destructured but never decoded; UI always shows the static `ERROR_MESSAGES.LOAD_JOBS_FAILED`. Real fetch failures masked. Route through `extractErrorMessage(error, ERROR_MESSAGES.LOAD_JOBS_FAILED)`. (silent-failure-hunter)
- `src/frontend/src/hooks/useFetchWithStatus.ts:125-132` — `AbortError` check is `err instanceof Error && err.name === 'AbortError'`. `DOMException` is not an `Error` subclass in older engines. Broaden to an object-shape check or rely on `controller.signal.aborted` alone. (silent-failure-hunter)
- `src/frontend/src/components/shared/ErrorDisplay.tsx` — `ErrorDisplayProps.inline` allows invalid prop combinations: `title`/`description` are silently dropped when `inline={true}`. Encode the invariant via a discriminated union. (type-design-analyzer)
- `src/frontend/src/components/shared/LoadingIndicator.tsx` — `fullPage` + `minHeight` silently conflict; currently resolved in runtime precedence, but both props are typed as optional-and-combinable. Discriminated union. (type-design-analyzer)
- `src/frontend/CLAUDE.md:63,82,87` — comment rot: "Units 1–9", "as of Unit 10", "exactly seven", "Decision finalized in Unit 5". Task-scoped / count-precise language in permanent docs will drift the moment anyone adds or removes a disable. Rewrite to be count-free and unit-free. (comment-analyzer)
- `src/frontend/src/hooks/useFetchWithStatus.ts:62-65` — hook JSDoc ties the hook's purpose to "Unit 3" and "QAPage's two hand-rolled blocks." Hook is permanent API. Strip the unit/caller history. (comment-analyzer)
- `src/frontend/eslint.config.js:34-36` — comment says disables "stay until Unit 5." Unit 5 has landed; authoritative list now lives in CLAUDE.md. Replace with a forward-looking statement. (comment-analyzer)
- `src/frontend/src/components/shared/LoadingIndicator.tsx:14-17` — `caption` JSDoc references "CompaniesPageContent" and "Unit 7 swap." Prop docs should describe the prop, not the migration. (comment-analyzer)
- `src/frontend/src/components/companies-page/FetchProgressBar/FetchProgressBar.tsx:65` — "equivalent to the previous useEffect + wasLoadingRef bookkeeping." The "previous" implementation is not in the file anymore. (comment-analyzer)
- `src/frontend/src/hooks/useCompanyLoader.ts:38` — comment "lets the exhaustive-deps rule stay at `error` globally" pins to a global rule severity. Strip. (comment-analyzer)
- `src/frontend/src/lib/errors.ts:14` — "inline across ~12 call sites" — count will rot. (comment-analyzer, nit-but-cheap)
- `useFetchWithStatus` test gaps: (a) React 19 StrictMode double-mount not covered; (b) RTK Query `{ data: { detail } }` error shape not thrown through the hook; (c) `reload()` aborting a still-pending first fetch not covered. (pr-test-analyzer)
- `errors.test.ts` branch gap: non-string `detail` fall-through (`{ data: { detail: 123, message: 'x' } }` should return `'x'`). (pr-test-analyzer)
- `GraphFilters.test.tsx:122-128` / `ListFilters.test.tsx:121-127` / `RecentJobsFilters.test.tsx:127-131` — `TimeWindow` resolved by `el.textContent === '30 days'`. Brittle. Prefer `getByLabelText('Time Window')`. (pr-test-analyzer)

**Suggestion / Nit:**

- `src/frontend/src/features/filters/slices/createFilterSlice.ts:60-79` — `hasDepartmentField` / `hasCompanyField` are unsound predicates (`void filters;` tells you the runtime check ignores the argument and asserts on the closure-captured `name`). Agent flags as MEDIUM; better fix is a tighter generic signature pairing `name` with `T`. **Deferred** — non-trivial refactor, PLAN explicitly left room for follow-up.
- `useFetchWithStatus.ts:101-107` clears `data` to `null` when `skip` toggles false→true; undocumented. Add a JSDoc line. **Deferred** — not load-bearing for current callers.
- `errors.ts:29` — string branch returns `''` as-is; an empty-string alert would render empty. **Deferred** — callers pass sensible fallbacks.
- `LoadingIndicator.tsx:10` — `minHeight` JSDoc says it overrides `fullPage`'s default; doc is on the wrong prop (should be on `fullPage`). **Deferred** — cosmetic.
- Test-level implementation-detail coupling (chip `MuiChip-root`, icon `data-testid="AddIcon"`, `MuiTypography-root`, etc.) in `SearchTagsInput.test.tsx`, `SyncFiltersButton.test.tsx`, `LoadingIndicator.test.tsx`, `QAPage.test.tsx:484-519`. **Deferred** — cosmetic unless these tests flake.

### Production-environment findings

**Critical:** None.

**Important:** None.

**Suggestion:** None above noise.

**Could not verify:**
- `postgres-prod-verifier` — not dispatched (no matching diff signal: no migrations, no models, no SQL, no ORM query edits).
- `railway-prod-verifier` — not dispatched (no matching diff signal: no `src/backend/**`, no `Dockerfile`, no `railway.toml`/`railway.json`, no `Procfile`).

Vercel verifier confirmed: zero env-var drift, zero serverless-function edits, zero `vercel.json`/`vite.config.ts`/`tsconfig` edits, no new deps, prod deployment history all green.

### Deferred (not fixing this pass)

- `createFilterSlice` generic refactor (factory name↔shape pairing). MEDIUM-risk; PLAN left as follow-up.
- `useFetchWithStatus` `skip` data-clearing JSDoc.
- `errors.ts` empty-string-branch handling.
- `LoadingIndicator.tsx` JSDoc wrong-prop placement.
- Test implementation-detail coupling (non-flaking).
- `QAPage.test.tsx` scrape-run refresh baseline snapshot.

### Implementation applied — pass 1

**Commits:**
- 8585db8 — Route remaining error decodes through extractErrorMessage
- 093f79a — Broaden useFetchWithStatus abort detection to non-Error throws
- f77d96d — Make ErrorDisplay and LoadingIndicator props discriminated unions
- 8d9355b — Remove task-scoped language from permanent docs and comments
- b231fc2 — Backfill test gaps surfaced in review

**Do not revert (new in this pass):**
- `extractErrorMessage` adoption in `useCompanyLoader`, `jobsSelectors.selectCurrentCompanyError`, `useCurrentUser`, `useEnabledCompanies`, `UserMenu`, and `RecentJobPostingsPage` is required by the CLAUDE.md Frontend Foundations rule "All error decoding goes through extractErrorMessage." Do not reintroduce `err instanceof Error ? err.message : '…'` ternaries or `'data' in err` decodes.
- `useFetchWithStatus` abort detection is intentionally shape-based (`controller.signal.aborted` OR `{ name: 'AbortError' }`) rather than `instanceof Error` so older-engine `DOMException` and custom-fetcher bare-object rejections are handled. Do not tighten back to `instanceof Error`.
- `ErrorDisplay` and `LoadingIndicator` props are discriminated unions on purpose: inline mode excludes `title`/`description`; `fullPage: true` excludes `minHeight`. Do not relax to flat optional-everything shapes. The former "explicit minHeight overrides fullPage default" runtime precedence test was removed because the combination is now uncallable.
- `TimeWindowSelect` wires a `useId` `labelId` between `InputLabel` and `Select` so the combobox exposes its accessible name. Tests resolve it via `getByRole('combobox', { name: 'Time Window' })`. Do not drop the `labelId` — the filter tests will regress to textContent scraping.
- `RecentJobPostingsPage` error text is now the decoded backend message (with `ERROR_MESSAGES.LOAD_JOBS_FAILED` as the fallback). Tests assert both branches.

