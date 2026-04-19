# New Feature Callout PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-04-18 — Review pass 1

### Code-review findings

**Critical:**
- None.

**Important:**
- None. All four reviewers (code-reviewer, silent-failure-hunter, pr-test-analyzer, type-design-analyzer) reported no Critical or Important code-review issues. The only Important-rated items came from pr-test-analyzer and are captured under "Test-coverage findings" below.

**Suggestion / Nit:**
- `NewFeatureCallout.tsx` — `data-testid` is extracted via `...rest` + `rest['data-testid']` instead of destructured directly (code-reviewer + type-design-analyzer).
- `NewFeatureCallout.tsx` — `placement` is a single-member union that is declared, ignored (`_placement`), and destructured but not consumed (type-design-analyzer). Keep for now; add a `switch` if/when a second variant lands.
- `EditCompanyPreferencesRow.test.tsx` — `useAppSelector` mock ignores its selector argument; works today because the child only reads one slice (code-reviewer S1).
- `dismissalStorage.ts` — `raw.length > 0` treats any non-empty string as dismissed (silent-failure-hunter S4). Matches PLAN contract; no change needed.
- `NewFeatureCallout.tsx` — `parseExpiry` silently treats invalid input as "expired forever" (silent-failure-hunter S4). Consider a dev-mode `console.warn` later.
- Missing error boundary around `<NewFeatureCallout>` in the page (silent-failure-hunter S3). Helper is already defensive; defer.

### Test-coverage findings

**Important:**
- `EditCompanyPreferencesRow` does not cover dismissal persistence across unmount + remount. The row is the *only* consumer that wires `storageKey="companyPreferences-2026-04"` into the real callout; a regression renaming that prop would not be caught by the `NewFeatureCallout` tests (which use a different key). Rating 6 (pr-test-analyzer #4).

**Suggestion:**
- Add a dismissed-AND-expired test to lock short-circuit ordering (pr-test-analyzer #1, rating 6). Ordering is already tested in two separate tests; defer.
- Add expiry boundary test at `Date.now() === expiryMs` (pr-test-analyzer #2, rating 6). Marginal; defer.
- Tighten the component-level dismiss test to assert stored value is ISO-shaped (pr-test-analyzer #3, rating 5). Already covered at the helper layer; defer.
- Non-ISO garbage behavior — no contract disagreement; impl behavior (any non-empty string = dismissed) is consistent with the PLAN's frozen error-path contract (pr-test-analyzer #5, rating 5). Skip.

### Type-design findings

**Ratings (type-design-analyzer):** encapsulation 7/10, invariant expression 7/10, usefulness 8/10, enforcement 8/10.

**Positives (locked in — do not revert):**
- `expiresAt` is **required** (not optional with a default). This is the single strongest invariant in the file and the one that prevents stale "New!" tags from lingering indefinitely. Preserve it in all future edits.
- `'data-testid'?: string` typed explicitly instead of accepting arbitrary `data-*` via `...rest`. Keep it explicit.

### Production-environment findings

- `vercel-prod-verifier`: not dispatched (no matching diff signal — pure frontend component + tests, no `api/*.ts`, `vercel.json`, `vercel.ts`, or `process.env.*` changes).
- `postgres-prod-verifier`: not dispatched (no matching diff signal — no migrations, models, SQL, or ORM queries changed).
- `railway-prod-verifier`: not dispatched (no matching diff signal — no backend, Dockerfile, or railway config changed).

### Plan to apply this pass

Fix the one Important test-coverage gap plus one polish item that multiple reviewers flagged:

1. Add a dismissal-persistence test to `EditCompanyPreferencesRow.test.tsx` that unmounts + re-renders and asserts the callout stays hidden. This locks the row's `storageKey` wiring.
2. Refactor `NewFeatureCallout.tsx` to destructure `'data-testid': testId` directly instead of `...rest` + `rest['data-testid']`. Removes the "someone will spread `...rest` onto `Paper` one day" footgun.

All other suggestions/nits are deferred — they're polish items that don't block shipping the small feature.

### Deferred (not fixing this pass)

- `placement` single-member union cleanup.
- Selector-aware mocking in `EditCompanyPreferencesRow.test.tsx`.
- Dev-mode `console.warn` on malformed `expiresAt`.
- Dev-mode assertion for empty `storageKey`.
- Error boundary around the callout in the page.
- Stricter ISO-8601 regex in `parseExpiry`.
- Expiry-boundary (`===`) and dismissed-AND-expired tests.
- Tighten component-level dismiss test to assert ISO-shaped stored value.

### Implementation applied

- **Commit:** `daf900f Review pass 1: add row dismissal persistence test + tighten data-testid destructure`
- **Files changed:**
  - `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesRow.test.tsx` — new "stays dismissed across unmount + remount" test locks the row's `storageKey="companyPreferences-2026-04"` wiring.
  - `src/frontend/src/components/shared/NewFeatureCallout/NewFeatureCallout.tsx` — dropped `...rest` spread, destructured `'data-testid': testId` directly.
- **Full test suite:** 1107 tests across 72 files, all green. Type-check clean.

### Do not revert (new in this pass)

- The `'data-testid': testId` direct destructure is load-bearing. Do not reintroduce `...rest` on the component props — the risk is that a future refactor spreads `{...rest}` onto the `Paper` and leaks caller props onto the DOM. If more props need test-infra passthrough, add them explicitly by name.
- The `EditCompanyPreferencesRow.test.tsx` persistence test does NOT clear `localStorage` between unmount and re-render on purpose — that is the contract being tested.

### Manual action required before merge

- None.

