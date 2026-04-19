# Frontend Audit Plan

## Context

The React SPA at `src/frontend/` has grown organically: 5 routes, 7 ATS API clients behind a factory, a filter-slice factory, 3 filter slices, an RTK Query jobs layer, Auth0 + Google One Tap auth, an enabled-companies preference slice with a 5-subcomponent Account section, and ~60 tests files covering ~90% of the foundational code. Three pages (`RecentJobPostingsPage`, `CompaniesPage`, `AccountPage`) and one dev-only page (`QAPage`) are the primary render targets. Core primitives are already in reasonable shape: typed `useAppDispatch`/`useAppSelector` exist (`src/frontend/src/app/hooks.ts`), a `renderWithProviders` test helper exists (`src/frontend/src/test/testUtils.tsx`), `LoadingIndicator`/`ErrorDisplay`/`EmptyJobListState` shared components exist, strict TS is on, and ESLint has react-hooks rules at recommended. This audit is surgical, not a rewrite.

What's growing unevenly and needs to tighten up:
- **Duplicated loading/error UI at page level.** `AccountPage` and `QAPage` inline `<CircularProgress />` in centered `Box`es and hand-roll `<Alert severity="error" ...>` blocks despite `LoadingIndicator` and `ErrorDisplay` existing and being used elsewhere. `CompaniesPageContent` has its own centered-spinner variant. `EnabledCompaniesSection` does the same. At least 6 duplications to collapse.
- **Ad-hoc fetch-with-status inside QAPage.** `QAPage.tsx` hand-rolls three `useState(loading/error/data)` + `useEffect(fetch)` blocks for `/api/jobs`, `/api/jobs-qa/scrape-runs`, and `/api/jobs-qa/trigger-scrape`. None has an AbortController (unlike `useCurrentUser.ts` and `useEnabledCompanies.ts`, which do it right). This is a leaking pattern and the only page in the app that still handles its own fetch lifecycle.
- **`createFilterSlice` has 10+ `as any` casts** suppressing real type drift on department/company field access across `GraphFilters | ListFilters | RecentJobsFilters`. The factory's type variable `T extends Filters` loses narrowing when reducers access fields that only exist on some members. Fixable without changing behavior via a stricter generic plus helper-type guards.
- **Tests miss the page components** that coordinate state: `RecentJobPostingsPage`, `CompaniesPage`, `CompaniesPageContent`, `WhyPage` have no `*.test.tsx`. Also missing: `GraphFilters`, `ListFilters`, `RecentJobsFilters`, `CompanyChipGrid`, `CompanySearchAddInput`, `SelectedCompaniesPanel`, `BrowseCompaniesAccordion`, `MultiSelectAutocomplete`, `SearchTagsInput`, `SoftwareOnlyToggle`, `TimeWindowSelect`, `SyncFiltersButton`, `JobPostingsChart`, `GraphSection`, `ListSection`, `ChartTooltip`, `CustomDot`, `MetricsRow`, `MetricCard`, `LinksRow`. Vitest coverage thresholds are set at 80%; the project's written bar per `CLAUDE.md` is >85%.
- **Two `// eslint-disable` comments on react-hooks rules** (`useCompanyLoader.ts:39` disables `exhaustive-deps`; `RootLayout.tsx:50` disables `set-state-in-effect`). `useCompanyLoader`'s disable hides a subtle mount-vs-nav issue. `RootLayout`'s is intentional but can be refactored to a `useSyncExternalStore`-free `useLayoutEffect` pattern with an explicit prev ref, eliminating the disable.
- **No typed error envelope.** `useCompanyLoader` decodes RTK Query errors inline with a nested ternary; the same decode exists in `jobsSelectors.ts` and the page alerts. One shared `extractErrorMessage(err: unknown): string` utility would kill three near-identical blocks.

This plan is **refactor-only**. It preserves:
- RTK Query caching and the `getAllJobs` streaming `onCacheEntryAdded` flow
- Factory patterns (`createAPIClient`, `createFilterSlice`)
- Graph-vs-List filter independence and `sync*` actions
- Time bucketing (including empty buckets)
- Memory-management rules on tables (QAPage pagination stays)
- Enabled-companies semantics (`null`/`[]` = all, race guards in the slice)
- Auth bypass module-level dispatch in `useAuth` (do not convert to runtime branching)
- All observable behavior, copy, routing, and visual appearance

---

## Shared Contracts (frozen — all units must match)

### Shared primitives (new or rehomed)

**1. `LoadingState` (already partly exists as `LoadingIndicator`).**
Location: `src/frontend/src/components/shared/LoadingIndicator.tsx` — keep file; add a named re-export `LoadingState` and a new variant prop:
```ts
interface LoadingIndicatorProps {
  size?: number;
  minHeight?: number | string;
  /** Optional caption rendered under the spinner (replaces CompaniesPageContent's inline Typography). */
  caption?: string;
  /** Full-viewport centering for page-level initial loads. */
  fullPage?: boolean;
}
```
No new file. `LoadingIndicator` keeps its existing prop-compat and gets `caption` + `fullPage`. All callers migrate to the same component.

**2. `ErrorState` (rename-only re-export of `ErrorDisplay`).**
`src/frontend/src/components/shared/ErrorDisplay.tsx` already exports `ErrorDisplay`, `NetworkErrorDisplay`, `EmptyStateDisplay`. Add a named alias `ErrorState = ErrorDisplay` for call-site consistency with `LoadingState`/`EmptyState`. No API change.

**3. `EmptyState` (rename-only re-export of `EmptyStateDisplay`).**
Same file. Add `EmptyState = EmptyStateDisplay`. `EmptyJobListState` stays — it is a job-specific wrapper and reads messages from `constants/messages.ts`.

**4. `extractErrorMessage(err: unknown): string` utility.**
Location (new): `src/frontend/src/lib/errors.ts`. Single source for RTK Query / fetch / thrown-Error decoding. Signature:
```ts
export function extractErrorMessage(err: unknown, fallback?: string): string;
```
Replaces the nested-ternary in `useCompanyLoader.ts`, the duplicate in `jobsSelectors.ts#selectCurrentCompanyError`, and the `err instanceof Error ? err.message : '...'` boilerplate in `QAPage`, `AccountPage`, `EnabledCompaniesSection`, `UserMenu`, `useCurrentUser`.

**5. `useFetchWithStatus<T>` data hook.**
Location (new): `src/frontend/src/hooks/useFetchWithStatus.ts`. Targets **only** QAPage's three hand-rolled fetches — do not force RTK Query endpoints or `useEnabledCompanies`/`useCurrentUser` to adopt it (they have specialized behavior). Signature:
```ts
interface FetchWithStatusOptions<T> {
  /** Called on mount + whenever any key in deps changes. Must be a stable (useCallback'd) function. */
  fetcher: (signal: AbortSignal) => Promise<T>;
  /** Controls re-fetch; treat as useEffect deps. */
  deps: ReadonlyArray<unknown>;
  /** Skip the fetch entirely (returns { data: null, loading: false }). Default: false. */
  skip?: boolean;
}
interface FetchWithStatusResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}
function useFetchWithStatus<T>(options: FetchWithStatusOptions<T>): FetchWithStatusResult<T>;
```
Internally uses `AbortController` + `useRef`, mirroring the pattern already proven in `useCurrentUser.ts` and `useEnabledCompanies.ts`. Handles the standard "aborted-after-unmount shouldn't set state" flow.

### Baselines

Run from the worktree root `/Users/brendanpotter/Documents/develop/Job-Visualizer-Notifier/.claude/worktrees/frontendAudit/`:
- TypeScript compiles cleanly: `npm run type-check`
- ESLint passes with zero errors and zero new warnings: `npm run lint`
- All tests remain green: `npm test`
- Coverage equal or better than baseline per touched directory: `npm run test:coverage` (Vitest v8 provider; thresholds in `src/frontend/vitest.config.ts` stay at 80, but touched units target >=85%)
- Zero visual regressions (asserted via render-stability tests on the two highest-traffic pages in Unit 7/8)
- Zero new `as any` (each removed cast is net-negative; added casts only with a justification comment)

### Conventions (preserved)

- **Factory patterns stay factories.** `createAPIClient` (`src/frontend/src/api/clients/baseClient.ts`) and `createFilterSlice` (`src/frontend/src/features/filters/slices/createFilterSlice.ts`) are the single implementation site — changes go into the factory, not each caller.
- **`selectCurrent*` / `select*Filtered*` selectors stay memoized** via `createSelector`. Do not collapse them into inline selectors.
- **Graph and List filter independence** is by design. Sync only via explicit `sync*` actions.
- **Empty buckets** are rendered deliberately — never filter them out.
- **Pagination is mandatory** on any table >=100 rows (QAPage's two tables already comply).
- **Typed Redux hooks are the one-and-only import source.** `useAppDispatch` / `useAppSelector` from `src/frontend/src/app/hooks.ts`. Raw `useDispatch` / `useSelector` in `src/` is forbidden. (Audit confirms exactly one file uses them: `app/hooks.ts`. This is the intended entry point.)
- **Auth bypass dispatch stays at module load** (`features/auth/useAuth.ts`). Do not convert to runtime branching.
- **Enabled-companies selector semantics:** `null` or `[]` means "all enabled." Do not narrow this.

---

## Work Units

### Unit 1 — Foundation: error utility, test helper polish, ESLint tightening

**Status:** DONE
**Prerequisites:** none
**Owned files (create):**
- `src/frontend/src/lib/errors.ts`
- `src/frontend/src/__tests__/lib/errors.test.ts`

**Owned files (modify):**
- `src/frontend/src/test/testUtils.tsx` — add an optional `initialEntries?: string[]` param that swaps `BrowserRouter` for `MemoryRouter` when provided. Page-level tests in later units need route-based rendering.

**Shared-file edits (coordinate):**
- `src/frontend/eslint.config.js` — upgrade `react-hooks/exhaustive-deps` from default (warn) to `error`, keep `@typescript-eslint/no-explicit-any` at `warn`. Do not mass-disable anything.

**Details:**
`extractErrorMessage(err, fallback='Unknown error')` handles:
1. `err` is an `Error` → `err.message`
2. `err` is a string → `err`
3. `err` is an object with `{ data: string | { detail?: string; message?: string } }` (RTK Query shape) → data.detail/message/string
4. `err` is an object with `{ message: string }` → message
5. Everything else → `fallback`

Tests cover all five branches plus `null`/`undefined`.

`testUtils.tsx` additions are purely additive (new optional param, default behavior unchanged), so no existing test breaks.

**Done when:**
- `npm run type-check` green
- `npm run lint` green (zero warnings added)
- `npm test -- lib/errors` green
- `npm test` green overall (existing test helper calls unaffected)
- Coverage for `src/frontend/src/lib/errors.ts` == 100%

---

### Unit 2 — Consolidate LoadingState / ErrorState / EmptyState primitives

**Status:** DONE
**Prerequisites:** Unit 1
**Owned files (modify):**
- `src/frontend/src/components/shared/LoadingIndicator.tsx` — add `caption` and `fullPage` props to `LoadingIndicator`; add named export `LoadingState` (alias of `LoadingIndicator`).
- `src/frontend/src/components/shared/ErrorDisplay.tsx` — add named exports `ErrorState` (alias of `ErrorDisplay`) and `EmptyState` (alias of `EmptyStateDisplay`). Rewrite `inline` branch's `onRetry` alert to use `extractErrorMessage` when caller passes `unknown` (new overload, additive).

**Owned files (create):**
- `src/frontend/src/__tests__/components/shared/LoadingIndicator.test.tsx` — covers `caption`, `fullPage`, default sizing.
- `src/frontend/src/__tests__/components/shared/ErrorDisplay.test.tsx` — covers inline vs. card, retry click, alias re-exports render identically.

**Shared-file edits:** none (aliases are additive).

**Done when:**
- `npm run type-check` green
- `npm test -- components/shared/LoadingIndicator components/shared/ErrorDisplay` green
- No existing test broken by the new props (they are optional)
- Coverage for both files >=95%

---

### Unit 3 — useFetchWithStatus hook + QAPage migration

**Status:** DONE
**Prerequisites:** Unit 1, Unit 2
**Owned files (create):**
- `src/frontend/src/hooks/useFetchWithStatus.ts`
- `src/frontend/src/__tests__/hooks/useFetchWithStatus.test.ts`

**Owned files (modify):**
- `src/frontend/src/pages/QAPage/QAPage.tsx` — migrate the `fetchJobs` effect and `fetchScrapeRuns` callback to `useFetchWithStatus`. Keep `handleTriggerScrape` as-is (it's a user-triggered mutation, not a lifecycle fetch — `useFetchWithStatus` is read-only by design). Replace the inline loading/error UI blocks with `<LoadingState />` and `<ErrorState inline ... />`.

**Shared-file edits (coordinate):**
- `src/frontend/src/__tests__/pages/QAPage/QAPage.test.tsx` — update mock strategy from global `fetch` stubbing to match the hook's `AbortController` usage (still intercepts `globalThis.fetch`; just asserts calls happen once per `selectedCompany` change, not twice).

**Done when:**
- `npm run type-check` green
- `npm test -- hooks/useFetchWithStatus pages/QAPage` green
- Assert `fetch` mock is called with a `signal` argument and that switching `selectedCompany` aborts the in-flight request
- QAPage's 3 `useState` + `useEffect` fetch lifecycles reduced to 2 `useFetchWithStatus` calls
- Coverage for `hooks/useFetchWithStatus.ts` >=90%; `pages/QAPage/QAPage.tsx` no regression

**Migration risk:** LOW. QAPage is dev-only, not production-critical. The trigger-scrape flow intentionally stays hand-rolled because it's a user-action mutation with specific response-shape handling (202 vs 200, HTTP error branch that returns JSON error details).

---

### Unit 4 — createFilterSlice type hygiene (remove `as any` without behavior change)

**Status:** DONE
**Prerequisites:** none (orthogonal to Units 1–3, but ordered here so it runs after primitives are stable)
**Owned files (modify):**
- `src/frontend/src/features/filters/slices/createFilterSlice.ts` — replace the 10 `as any` casts on `state.filters` with a conditional type / type-guard approach:
  - Introduce `type FiltersWithDepartments = GraphFilters | ListFilters` and `type FiltersWithCompany = RecentJobsFilters`.
  - Narrow via helper functions `hasDepartmentField<T>` / `hasCompanyField<T>` that assert the field's presence on the slice type. No runtime change (these are `is`-guard returns).
  - The computed-property-name dispatches on `capitalizedName` stay — TS can't narrow those without per-slice discriminants, so that file's `as any` in the returned `actions` export stays, with a tightened JSDoc explaining why.
- `src/frontend/src/features/filters/slices/graphFiltersSlice.ts` — keep `as any` on the destructured action exports (TS limitation documented in the existing JSDoc). No change needed unless the factory return type becomes inferable.
- Same note for `listFiltersSlice.ts` and `recentJobsFiltersSlice.ts` — no edits expected unless Unit-4 generics work lets TS infer the action creators (stretch goal; if not, leave those 3 `as any` with comments).

**Shared-file edits:** none.

**Owned files (create):** none; changes are in-place.

**Done when:**
- `npm run type-check` green
- `npm test -- features/filters` green (all 3 slices behaviorally unchanged)
- `grep -c "as any" src/frontend/src/features/filters/slices/createFilterSlice.ts` shows reduction from 10 to <=3 (company and department helpers factored out; remaining casts documented)
- Coverage for `createFilterSlice.ts` stays at 100% (already fully tested)

**Migration risk:** MEDIUM. This file is the heart of filter behavior. Keep edits additive: introduce helpers, then swap call sites one at a time; do not change the reducer body's logic. If a type guard becomes too invasive, document and keep the `as any` — this is the **"if you find something that's actually fine, don't invent a unit for it"** escape hatch.

---

### Unit 5 — Eliminate the react-hooks ESLint disables

**Status:** DONE
**Prerequisites:** Unit 1 (exhaustive-deps escalated to error)
**Owned files (modify):**
- `src/frontend/src/hooks/useCompanyLoader.ts` — the `// eslint-disable-next-line react-hooks/exhaustive-deps` on line 39 papers over an intentional "only re-run on page change, not selectedCompanyId change" choice. Refactor: split the effect into two: (a) an `isCompaniesPage` transition effect that reads URL once, (b) RTK Query's `{ skip }` already handles the fetch lifecycle. Remove the disable.
- `src/frontend/src/components/layout/RootLayout.tsx` — line 50's `set-state-in-effect` disable is syncing `drawerOpen` with `isMobile` breakpoint. Keep this one: the disable has a clear comment, the pattern is a documented React idiom for external sync, and refactoring to `useSyncExternalStore` against a media-query listener would be a visual-regression risk. Leave as-is; document in `src/frontend/CLAUDE.md` (Unit 10) why.
- `src/frontend/src/components/companies-page/MetricsDashboard/hooks/useTimeBasedJobCounts.ts` — line 19's `react-hooks/purity` disable is on `Date.now()`. Correct behavior; keep with comment. No change.
- `src/frontend/src/components/companies-page/FetchProgressBar/FetchProgressBar.tsx` — line 65's `set-state-in-effect` disable. Similar "external prop sync" pattern. Keep if behaviorally correct; otherwise refactor to derive `expanded` from props. Investigate during the unit and decide.

**Shared-file edits:** none.

**Done when:**
- `npm run lint` green with `exhaustive-deps` at `error` (guaranteed by Unit 1)
- `npm test -- hooks/useCompanyLoader components/companies-page/FetchProgressBar components/layout/RootLayout` green
- At most 2 of the 4 disables remain, each with an expanded comment citing why

**Migration risk:** MEDIUM. `useCompanyLoader` is on the Companies page hot path. Do not change timing of the initial URL read — tests must confirm `getInitialCompanyId` is called exactly once on first mount to `/companies`.

---

### Unit 6 — AccountPage + EnabledCompaniesSection: adopt shared primitives

**Status:** DONE
**Prerequisites:** Unit 2, Unit 1
**Owned files (modify):**
- `src/frontend/src/pages/AccountPage/AccountPage.tsx` — replace the inline `<Container ...><CircularProgress /></Container>` loading blocks with `<LoadingState fullPage />`. Replace the `<Alert severity="error">` + retry `<Button>` block with `<ErrorState inline message={error} onRetry={loadProfile} />`. Replace the `err instanceof Error ? err.message : 'Failed...'` in `handleSave` with `extractErrorMessage(err, 'Failed to save changes')`.
- `src/frontend/src/components/account/EnabledCompaniesSection.tsx` — replace `<Paper sx={{ p: 4, mt: 3, textAlign: 'center' }}><CircularProgress /></Paper>` with a centered `<LoadingState />` inside a `Paper`. Replace the `err instanceof Error ? err.message : 'Failed...'` in `handleSave` with `extractErrorMessage(err)`.

**Shared-file edits:** none.

**Owned files (create):** none (existing tests cover these components).

**Done when:**
- `npm run type-check` green
- `npm test -- pages/AccountPage components/account/EnabledCompaniesSection` green with no snapshot regressions; update tests to assert on the new component's DOM (spinner role="progressbar" still present; alert role="alert" still present)
- `git diff --stat src/frontend/src` shows only the 2 modified files plus their tests
- Coverage for both files >=85%

**Migration risk:** LOW. Both files have thorough existing tests; the swaps are semantically identical.

---

### Unit 7 — RecentJobPostingsPage + CompaniesPage: shared primitives, page tests

**Status:** DONE
**Prerequisites:** Unit 2, Unit 1
**Owned files (modify):**
- `src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx` — replace the inline `<Alert severity="error" sx={{ mb: 2 }}>{ERROR_MESSAGES.LOAD_JOBS_FAILED}</Alert>` with `<ErrorState inline message={ERROR_MESSAGES.LOAD_JOBS_FAILED} />`. No behavior change.
- `src/frontend/src/pages/CompaniesPage/CompaniesPage.tsx` — replace the inline `<Alert severity="error" action={...}>` block with `<ErrorState inline message={\`Failed to load job data: ${error}\`} onRetry={handleRetry} />`.
- `src/frontend/src/pages/CompaniesPage/CompaniesPageContent.tsx` — replace the hand-rolled `<Box><Stack>...<CircularProgress size={60} />...</Stack></Box>` loading block with `<LoadingState size={60} minHeight={400} caption={selectedATS === ATSConstants.Workday ? 'Workday source requires more loading time...' : undefined} />`.

**Owned files (create):**
- `src/frontend/src/__tests__/pages/RecentJobPostingsPage/RecentJobPostingsPage.test.tsx` — covers: initial render with no data, error alert shows on query error, metrics render when data present, `FetchProgressBarSkeleton` renders while preferences unready, `FetchProgressBar` renders when ready, enabled-ids filter passes through to progress bar.
- `src/frontend/src/__tests__/pages/CompaniesPage/CompaniesPage.test.tsx` — covers: loading shows `LoadingState`, error shows `ErrorState` with retry, retry calls `handleRetry`, loaded state shows `GraphSection` + `ListSection`.
- `src/frontend/src/__tests__/pages/CompaniesPage/CompaniesPageContent.test.tsx` — covers: Workday caption appears only for Workday ATS, otherwise bare spinner.

**Shared-file edits:** none.

**Done when:**
- `npm run type-check` green
- `npm test -- pages/RecentJobPostingsPage pages/CompaniesPage` green (new tests + no regression on existing integration test)
- `npm test -- integration/fullWorkflow` green (highest-signal guard against visual regression on Recent Jobs flow)
- Coverage for the 3 page files >=85%

**Migration risk:** MEDIUM-HIGH for `CompaniesPage` — it drives the graph render loop. Assert retry button behavior and loading-state transitions via the new tests before merging.

---

### Unit 8 — WhyPage test backfill

**Status:** DONE
**Prerequisites:** Unit 2
**Owned files (modify):**
- `src/frontend/src/pages/WhyPage/WhyPage.tsx` — no refactor to sections (they render unique content). Only `sectionPaperSx` lives there; leave as-is. Purpose of this unit is test backfill.

**Owned files (create):**
- `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx` — covers: heading renders, correct company count, ATS groups, coming-soon scrapers list, each group header has correct count, external links have `rel="noopener noreferrer"`.

**Shared-file edits:** none.

**Done when:**
- `npm test -- pages/WhyPage` green
- Coverage for `pages/WhyPage/WhyPage.tsx` >=85% (currently 0%)

**Migration risk:** LOW. Test-only unit.

---

### Unit 9 — Filter-component test backfill (Graph / List / RecentJobs filter bars and shared controls)

**Status:** DONE
**Prerequisites:** Unit 2 (test helpers) — Units 3–7 are unrelated, but running this near the end lets it pick up any test-helper improvements and keeps the earlier units bounded.
**Owned files (create):**
- `src/frontend/src/__tests__/components/companies-page/GraphFilters.test.tsx`
- `src/frontend/src/__tests__/components/companies-page/ListFilters.test.tsx`
- `src/frontend/src/__tests__/components/recent-jobs-page/RecentJobsFilters.test.tsx`
- `src/frontend/src/__tests__/components/shared/filters/MultiSelectAutocomplete.test.tsx`
- `src/frontend/src/__tests__/components/shared/filters/SearchTagsInput.test.tsx`
- `src/frontend/src/__tests__/components/shared/filters/SoftwareOnlyToggle.test.tsx`
- `src/frontend/src/__tests__/components/shared/filters/TimeWindowSelect.test.tsx`
- `src/frontend/src/__tests__/components/shared/filters/SyncFiltersButton.test.tsx`

**Owned files (modify):** none — test-only.

**Shared-file edits:** none.

**Details:** For each filter bar, assert that: the bar renders given a seeded store, each control change dispatches the right action, and the bar does not re-render unrelated sibling controls (shallow assertion via `toHaveBeenCalledTimes(0)` on unrelated dispatched actions). For each shared filter control, test: controlled value, `onAdd`/`onRemove`/`onToggleMode` callbacks, accessibility (label association, role correctness), edge cases (empty options list, duplicate selections).

**Done when:**
- `npm test -- components/companies-page/GraphFilters components/companies-page/ListFilters components/recent-jobs-page/RecentJobsFilters components/shared/filters` green
- Coverage for all 8 touched files >=85%
- No change to `src/frontend/src/__tests__` setup or helpers beyond what Unit 1 added

**Migration risk:** NONE. Test-only.

---

### Unit 10 — Docs + guardrails

**Status:** TODO
**Prerequisites:** Units 1–9 merged
**Owned files (modify):**
- `src/frontend/CLAUDE.md` — add a **"Frontend Foundations"** section under "Architecture Quick Reference" documenting: the shared primitives (`LoadingState`, `ErrorState`, `EmptyState`, `extractErrorMessage`, `useFetchWithStatus`), the rule that all Redux consumers use typed hooks from `app/hooks.ts`, the rule that page-level fetch lifecycles use `useFetchWithStatus` or RTK Query (never inline `useState`+`useEffect`+`fetch`), and the explicit list of remaining `eslint-disable` comments with justifications.
- `src/frontend/docs/architecture.md` — add a short paragraph pointing at the new shared primitives and `lib/errors.ts`. Don't rewrite Mermaid diagrams.

**Owned files (create):** none.

**Shared-file edits:** none.

**Done when:**
- Both docs read correctly with a fresh-eyes pass
- `git diff --stat` shows only the 2 doc files changed
- No code changes in this unit

**Migration risk:** NONE. Docs-only.

---

## Critical files (reference table)

| File | Purpose | Touched by |
|---|---|---|
| `src/frontend/src/lib/errors.ts` | `extractErrorMessage` utility (new) | Unit 1 |
| `src/frontend/src/test/testUtils.tsx` | Test helper — add `initialEntries` param | Unit 1 |
| `src/frontend/eslint.config.js` | Escalate `react-hooks/exhaustive-deps` to `error` | Unit 1 |
| `src/frontend/src/components/shared/LoadingIndicator.tsx` | Loading primitive — add `caption`, `fullPage`, alias | Unit 2, 6, 7 |
| `src/frontend/src/components/shared/ErrorDisplay.tsx` | Error primitive — add `ErrorState`/`EmptyState` aliases | Unit 2, 6, 7 |
| `src/frontend/src/hooks/useFetchWithStatus.ts` | Abortable fetch-lifecycle hook (new) | Unit 3 |
| `src/frontend/src/pages/QAPage/QAPage.tsx` | Migrate hand-rolled fetch blocks | Unit 3 |
| `src/frontend/src/features/filters/slices/createFilterSlice.ts` | Filter-slice factory — reduce `as any` casts | Unit 4 |
| `src/frontend/src/hooks/useCompanyLoader.ts` | Companies-page data hook — remove exhaustive-deps disable | Unit 5 |
| `src/frontend/src/pages/AccountPage/AccountPage.tsx` | Account UX — adopt LoadingState/ErrorState | Unit 6 |
| `src/frontend/src/components/account/EnabledCompaniesSection.tsx` | Prefs UX — adopt shared primitives | Unit 6 |
| `src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx` | Recent jobs shell — adopt ErrorState + page tests | Unit 7 |
| `src/frontend/src/pages/CompaniesPage/CompaniesPage.tsx` | Companies shell — adopt LoadingState/ErrorState + page tests | Unit 7 |
| `src/frontend/src/pages/CompaniesPage/CompaniesPageContent.tsx` | Loading view — adopt LoadingState with caption | Unit 7 |
| `src/frontend/src/pages/WhyPage/WhyPage.tsx` | No refactor; test backfill | Unit 8 |
| `src/frontend/CLAUDE.md` | Document new foundations | Unit 10 |

---

## Non-goals

- **No visual redesign.** Every change must render pixel-equivalent output.
- **No behavior changes.** No new features, no routing changes, no copy changes, no new URLs.
- **No backend changes.** Pure frontend refactor.
- **No state-management migration.** Redux Toolkit + RTK Query stays. No Zustand, no Jotai, no switching to React Query.
- **No React Router upgrade.** Stay on v7 with the current pattern.
- **No MUI upgrade.** v7 stays.
- **No charting library change.** Recharts stays.
- **No new ATS provider.** No new API client work.
- **No changes to the auth bypass dispatch.** Module-level `useAuth` selection stays.
- **No removal of the 3 documented `as any` casts** in `graphFiltersSlice.ts`/`listFiltersSlice.ts`/`recentJobsFiltersSlice.ts` (computed-property-name TS limitation — the JSDoc already explains why, and Unit 4 attempts but does not commit to eliminating them).
- **No fetch-level filtering in `jobsApi.ts`.** Keep shared cache between Recent Jobs and Companies page.
- **No conversion of `useCurrentUser`/`useEnabledCompanies` to `useFetchWithStatus`.** They have specialized auth-aware behavior worth keeping separate.
- **No removal of `RootLayout`'s documented `set-state-in-effect` disable.** Media-query sync is a React idiom; see Unit 5 decision.
- **No new storybook, no new e2e framework.** Playwright is already a devDependency; if the team wants e2e coverage later, that's a separate plan.
