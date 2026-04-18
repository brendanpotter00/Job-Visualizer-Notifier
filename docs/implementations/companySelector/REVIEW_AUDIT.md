# Company Selector PR Review Audit Log

**Purpose:** Running log of review findings on PR #67 (per-user "Recent Jobs Companies" preference) and the fixes applied. **Read this before proposing changes to the enabled-companies slice, the `useEnabledCompanies` hook, the `user_enabled_companies` schema, or the Recent Jobs selector pre-filter.** Update this file when you apply a review fix so the next reviewer has context.

---

## 2026-04-18 — Round 1 review (PR #67)

Review run via the `/code-review` skill at head SHA `8357868310afb1ef2946888c7e417c9e859c6c80`. Five parallel reviewers (CLAUDE.md compliance, shallow bug scan, git-history context, past-PR comments, code-comment compliance) produced three candidate issues. Each was scored 0–100 for real-vs-false-positive; only issues ≥80 made the posted comment.

Comment posted: https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/67#issuecomment-4273046171

### Finding 1 — `loading` stuck on aborted load

**Problem:** `loadEnabledCompanies.rejected` returned early (`if (action.meta.aborted || action.error.name === 'AbortError') return;`) without clearing `state.loading`. The intent was correct — don't clobber `error` with an abort-noise message. But the early return also skipped the `state.loading = false` assignment on the line below it, so any aborted load (sign-out mid-fetch, component unmount, or rapid `reload()`) left the slice pinned at `loading: true`.

The mirrored `useCurrentUser.ts` pattern (added in the auth0 second-review pass, commit `1832e61`) avoided this by scoping the abort handling to the error side only — the `loading` flag was always cleared. This slice accidentally regressed that invariant.

**Fix:** Move `state.loading = false` above the abort early-return so it runs unconditionally; the error write remains gated on non-abort. See `src/frontend/src/features/preferences/enabledCompaniesSlice.ts:47-54`.

**Tests updated:** The two "rejected … is ignored" cases in `__tests__/features/preferences/enabledCompaniesSlice.test.ts` previously asserted the entire state snapshot was equal before/after the abort. That was too strong; they now assert `loading === false`, `error === null`, `ids === null` after the aborted rejection. 15 slice tests pass; 1000 frontend tests + type-check clean.

**Do not revert** this to `return` before clearing `loading` — the stuck-spinner bug is real on sign-out.

### Scored but below threshold (intentionally not fixed in Round 1)

These are tracked so the next reviewer doesn't re-flag them without new evidence:

- **Env-name interpolation bypass (scored 50).** `scripts/shared/database.py:235` and `src/backend/api/services/user_preferences_service.py:13` build the `user_enabled_companies_{env}` table name via raw f-string instead of routing through the `_get_table_name(env, …)` helper that calls `_is_valid_env`. Every other table in the codebase goes through that helper. In practice `env` is validated at app startup by Pydantic config, so the SQL-injection risk is theoretical and no CLAUDE.md explicitly mandates the helper. Worth unifying for consistency/defense-in-depth if this file is touched again, but not blocking.
- **`reload()` race on rapid successive calls (scored 25).** `useEnabledCompanies.ts` aborts the current promise and then awaits `getToken().then(...)` before setting `activePromise.current`. Two rapid `reload()` calls can both reach `dispatch(loadEnabledCompanies(token))` because the first `getToken()` promise is not abortable. Only matters for external callers invoking `reload()` manually — no such caller exists today; the only internal caller is the `useEffect`, which fires once per auth-state change.

### Tests added / changed

- `__tests__/features/preferences/enabledCompaniesSlice.test.ts` — rewrote "rejected with aborted meta is ignored" and "rejected with AbortError name is ignored" to explicitly assert `loading === false` after abort, matching the corrected reducer semantics.

**1000 frontend tests passing, type-check clean.**

---

## 2026-04-18 — Round 2 review (PR #67)

Review run via the `/code-review` skill reviewer pattern (manual, 5 parallel perspectives: CLAUDE.md compliance, shallow bug scan, git-history context, past-PR comments, code-comment compliance) at head SHA `a836d20200d96f45eb57df66cc33a7b7c450381c`. No findings scored ≥80 — **no review comment posted** (per skill step 6, skip posting when the filtered set is empty). This Round 2 entry documents the sub-threshold candidates so Round 3 does not re-flag them without new evidence.

### No findings above threshold

All candidate issues surfaced during Round 2 scored below the 80 posting threshold. The slice, hook, selector, router, and service code are all consistent with the Round 1 fixes and the design docs in `docs/implementations/companySelector/`.

### Scored but below threshold (intentionally deferred from Round 2)

- **`EditCompanyPreferencesLink` invisible on failed load (scored 55).** The CTA renders a 20px spacer while `isLoading || (isAuthenticated && enabledIds === null)`. If `loadEnabledCompanies` rejects for a non-abort reason (API 500, network down), `enabledIds` stays `null` and the link silently never appears for the signed-in user. The slice sets `state.error` in that path, but `EditCompanyPreferencesLink` does not surface it. Users can still navigate via the account menu, and the Recent Jobs page itself degrades gracefully (full company list shows when `enabledIds === null`). Worth adding an error-state affordance if this file is touched again, but not a Round 2 blocker.
- **Dead abort check in `saveEnabledCompanies.rejected` (scored 25).** The reducer checks `action.meta.aborted || action.error.name === 'AbortError'` but no caller threads an `AbortSignal` into the save thunk (`useEnabledCompanies.save()` does not abort in-flight saves). The check is harmless and future-proofs against a later abort-on-unmount addition. Leave as-is.
- **Stale-token risk in `useEnabledCompanies.save()` (scored 30).** `save()` calls `getToken()` once and dispatches `saveEnabledCompanies(ids, token)`. On very slow networks the token could expire mid-flight; on 401 the backend returns an error and the user sees a save failure. Auth0 SDK typically returns a cached-valid token, so the realistic window is small. No retry/refresh today by design.
- **`saveError` persistence across edits (scored 35).** `EnabledCompaniesSection` shows `saveError` after a failed save. Subsequent draft edits don't clear it until another save attempt. Minor UX polish; not blocking.
- **Silent `getToken()` rejection in `useEnabledCompanies` (scored 30).** The hook's `useEffect` calls `getToken().then(dispatch).catch(() => {})`. If token acquisition fails (Auth0 popup blocked, refresh-token revoked), the load silently never happens and `loading` stays `false`. Acceptable because the Auth0 `isAuthenticated` gate upstream ensures we only reach this path when a token should exist.
- **Env-name interpolation bypass (scored 50, carried from Round 1).** No new evidence — same defense-in-depth consideration as Round 1. `env` is Pydantic-validated at startup. Unify with `_get_table_name()` only if the file is touched again.
- **`reload()` race on rapid successive calls (scored 25, carried from Round 1).** No new evidence — no external `reload()` callers exist.

### Confirmations (Round 1 invariants re-verified)

- **`loading=false` always clears on abort** — verified at `src/frontend/src/features/preferences/enabledCompaniesSlice.ts:51`. The reducer still assigns `state.loading = false` unconditionally before the `if (action.meta.aborted || action.error.name === 'AbortError') return;` early-return. The two aborted-rejection tests in `__tests__/features/preferences/enabledCompaniesSlice.test.ts` still assert `loading === false` post-abort.
- **Abort path does not clobber `state.error`** — the early-return still skips the error write, so an aborted load does not replace a legitimate prior error with `"aborted"` noise.
- **Round 1 deferrals remain deferred** — env-interpolation and `reload()` race have not accrued new evidence.

### Tests run

- `npm test -- --run` — 1000 frontend tests pass.
- `npm run type-check` — clean.
- Focused subsets re-verified: slice + hook (21 tests), `EnabledCompaniesSection` + `EditCompanyPreferencesLink` + `recentJobsSelectors` (57 tests), `AppEnabledCompaniesGlobalLoad` (2 tests).
- Backend tests not run — `src/backend` untouched in Round 2 (docs-only change).

**1000 frontend tests passing, type-check clean. No code fixes applied (docs-only audit entry).**

---

## 2026-04-18 — Round 3 review (PR #67, final)

Review run via the `/code-review` skill reviewer pattern (manual, 5 parallel perspectives: CLAUDE.md compliance, shallow bug scan, git-history context, past-PR comments, code-comment compliance) at head SHA `6626cb4377d7b367fac383e0cfed46a83e79ad51`. No findings scored ≥80 — **no review comment posted** (per skill step 6, skip posting when the filtered set is empty). This Round 3 entry documents what was re-checked and confirms the Round 1 + Round 2 invariants still hold on the current tip.

Note: the only code commits in this PR since Round 2 are docs-only (`6626cb4` appended the Round 2 entry). The on-disk frontend and backend source is the same as the Round 2 tip (`a836d20`), so no new code surface materialized between rounds. Round 3 re-ran the reviewer pattern against the same source to confirm stability before the user merges.

### No findings above threshold

All candidate issues surfaced during Round 3 scored below the 80 posting threshold and duplicate items already recorded in Round 1 or Round 2 without new supporting evidence.

### Scored but below threshold (carried from Round 1 + Round 2 — no new evidence in Round 3)

- **`EditCompanyPreferencesLink` invisible on failed load (scored 55, from Round 2).** `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx:15` still gates the CTA on `isLoading || (isAuthenticated && enabledIds === null)`; a non-abort rejection of `loadEnabledCompanies` leaves `enabledIds === null` and the caption silently never appears for the signed-in user. The Account menu still works; Recent Jobs still renders with "show all" behavior. Not a blocker; revisit if users report the spacer state.
- **Dead abort check in `saveEnabledCompanies.rejected` (scored 25, from Round 2).** Harmless; future-proofs for a later abort-on-unmount addition.
- **Stale-token risk in `useEnabledCompanies.save()` (scored 30, from Round 2).** Auth0 SDK returns cached-valid tokens; 401 surfaces via the slice's save rejection.
- **`saveError` persistence across edits (scored 35, from Round 2).** Minor UX polish.
- **Silent `getToken()` rejection in `useEnabledCompanies` (scored 30, from Round 2).** Acceptable given the upstream `isAuthenticated` gate.
- **Env-name interpolation bypass (scored 50, from Round 1 + Round 2).** `scripts/shared/database.py:235` and `src/backend/api/services/user_preferences_service.py:13` still build `user_enabled_companies_{env}` via raw f-string instead of `_get_table_name()`. `env` is Pydantic-validated at startup, so the injection risk remains theoretical. Unify only if this file is touched again.
- **`reload()` race on rapid successive calls (scored 25, from Round 1 + Round 2).** No external `reload()` callers exist; the only internal caller is the `useEffect` that fires once per auth-state change.

### Confirmations (Round 1 + Round 2 invariants re-verified)

- **`loading=false` always clears on abort** — still true at `src/frontend/src/features/preferences/enabledCompaniesSlice.ts:51`. The reducer unconditionally assigns `state.loading = false` before the early-return that guards the error write. The two aborted-rejection tests in `__tests__/features/preferences/enabledCompaniesSlice.test.ts` still assert `loading === false`, `error === null`, `ids === null` after abort.
- **Abort path does not clobber `state.error`** — the early-return still skips the `state.error` write, so a stale aborted load does not replace a real prior error with abort-noise.
- **`useEnabledCompanies` abort semantics** — the hook still aborts the in-flight load on sign-out via `activePromise.current?.abort()` and on unmount via the `useEffect` cleanup. The "aborts in-flight load when isAuthenticated flips to false" test in `__tests__/features/preferences/useEnabledCompanies.test.ts` still passes, confirming the end-to-end abort plumbing.
- **Round 1 + Round 2 deferrals remain deferred** — none of the seven sub-threshold items have accrued new supporting evidence. Re-flagging any of them in a future review requires a fresh concrete example (user report, bug ticket, or a new caller that changes the assumption).

### Tests run

- `npm run type-check` — clean.
- `npm test -- --run` — 1000 frontend tests pass (66 files).
- Backend tests not run — `src/backend` untouched since Round 2 (no code changes between rounds).

**1000 frontend tests passing, type-check clean. No code fixes applied (docs-only audit entry, final round).**

---

## 2026-04-18 — Round 4 review (PR #67)

Review run via the `/pr-review-toolkit:review-pr` skill at head SHA `8397644` — five parallel reviewers (code-reviewer, pr-test-analyzer, silent-failure-hunter, type-design-analyzer, comment-analyzer). Unlike Rounds 2 and 3, Round 4 surfaced several new findings that warranted code changes. Fixes applied in the same commit as this entry.

### Fixes applied

**1. `useEnabledCompanies.reload()` race + swallowed getToken error (silent-failure-hunter CRITICAL, code-reviewer IMPORTANT).** `reload()` cleared `activePromise.current` then awaited `getToken()` before dispatching. If auth flipped to signed-out while `getToken()` was pending, the cleanup effect ran but had nothing to abort; when the token resolved it still dispatched `loadEnabledCompanies` against a signed-out session, repopulating `ids`. Additionally, a `getToken()` rejection (expired session, Auth0 popup blocked, refresh-token revoked) was silently swallowed in `.catch(() => {})` — violating the "correctness over don't crash" guidance in memory.

Fix: create a local `AbortController` synchronously, wrap it in an `AbortableLoad` and stash it in `activePromise.current` *before* awaiting `getToken()`. After `getToken()` resolves, bail out if the controller is already aborted (cleanup already ran). On `getToken()` rejection for a non-abort reason, dispatch a synthetic `loadEnabledCompanies.rejected` with the error message so the slice's `error` field populates — this surfaces expired-session failures to the UI via the existing `{saveError ?? error}` alert in `EnabledCompaniesSection` and the slice `error` field available to `EditCompanyPreferencesLink`. Files: `src/frontend/src/features/preferences/useEnabledCompanies.ts:25-58`.

**2. Stale load overwrites save (pr-test-analyzer Critical #3, silent-failure-hunter IMPORTANT #5).** `saveEnabledCompanies.fulfilled` unconditionally wrote `payload` into `state.ids`, and `loadEnabledCompanies.fulfilled` did the same. If a load was in flight when a save completed (e.g. user edits then saves immediately after arriving on Account page), the later-resolving load would overwrite the save. The save path also did not abort in-flight loads.

Fix: introduce a monotonically-incrementing `saveVersion` counter on the slice state. `saveEnabledCompanies.pending` increments it; `loadEnabledCompanies.pending` captures a snapshot onto `action.meta.arg` via `prepare` so the `.fulfilled` reducer can detect "a save happened while I was in flight" and skip writing stale ids. The save path also aborts the current load promise via `useEnabledCompanies.save()` before dispatching. Files: `src/frontend/src/features/preferences/enabledCompaniesSlice.ts:4-72`, `src/frontend/src/features/preferences/useEnabledCompanies.ts:60-70`.

**3. `EnabledCompaniesUpdateRequest.company_ids` accepts arbitrary strings (type-design-analyzer, pr-test-analyzer IMPORTANT #5).** The existing `COMPANY_PATTERN = r"^[a-zA-Z0-9_-]+$"` regex in `models.py:9` was defined but never applied to the new PUT endpoint payload. `PUT { companyIds: [""] }`, `PUT { companyIds: ["../../etc"] }`, and `PUT { companyIds: Array(10000).fill("x") }` were all silently accepted and persisted.

Fix: apply `Annotated[str, StringConstraints(pattern=COMPANY_PATTERN, min_length=1, max_length=64)]` per item, and `Field(max_length=200)` on the list. FastAPI now rejects malformed payloads with 422 at the HTTP boundary, before they reach the DB transaction. Files: `src/backend/api/models.py:104-114`.

**4. `saveError` persists across unrelated load errors (silent-failure-hunter IMPORTANT #8, carried from Round 2 at score 35 + new evidence).** Local `saveError` was only cleared on the next Save click. A stale save error could shadow a fresh slice `error` (e.g. an auth-expired reload failure that happens after the save error) because the Alert rendered `saveError ?? error`.

Fix: clear `saveError` via `useEffect` when `ids` or slice `error` change. Files: `src/frontend/src/components/account/EnabledCompaniesSection.tsx:25-31`.

**5. WHAT-style comments removed (comment-analyzer).** Removed comments that restated WHAT code does instead of WHY in: `BrowseCompaniesAccordion.tsx`, `CompanyChipGrid.tsx`, `SelectedCompaniesPanel.tsx`, `recentJobsSelectors.ts`, `App.tsx` (trimmed caller-specific rot), and the `FetchProgressBar.tsx` `companyIdFilter` JSDoc (trimmed "(cache shared with the Companies page)" caller reference). The WHY-only comments on `enabledCompaniesSlice.ts:48-51` and `useEnabledCompanies.ts:11-14` were kept as-is — they explain non-obvious invariants.

### Tests added

- `enabledCompaniesSlice.test.ts` — two new cases: (a) stale `loadEnabledCompanies.fulfilled` after a `saveEnabledCompanies` does **not** overwrite saved ids (locks in the save-version guard); (b) `saveEnabledCompanies.pending` increments `saveVersion`.
- `useEnabledCompanies.test.ts` — new case: `getToken()` rejection on sign-in surfaces as `state.enabledCompanies.error`, not silent hang. Confirms the "correctness over don't crash" fix.
- `FetchProgressBar.test.tsx` — three new cases for the previously-uncovered `companyIdFilter` prop: (a) `null`/`undefined`/empty Set = pass-through; (b) non-empty Set restricts visible chips/totals/percent; (c) returns `null` when the intersection is empty.
- `test_users_router.py` — new case: `PUT /api/users/enabled-companies` with malformed IDs (empty string, regex-violating, >64 chars) returns 422; oversized list (>200 items) returns 422.

### Intentionally deferred

- **`App.tsx` global load has no visible error UI (silent-failure-hunter SUGGESTION #10, score ~40).** A failed global preference load silently falls through to "show all jobs" on pages other than `/account`. Fix would require a global toast/snackbar pattern — out of scope for this PR; revisit if users report confusion about why filter toggles appear inactive.
- **Double invocation of `useEnabledCompanies()` in App + EnabledCompaniesSection (code-reviewer IMPORTANT #1, score ~60).** Each instance owns its own `activePromise` ref, so visiting `/account` fires two parallel GETs. Deduplication would require either module-level state or splitting the hook into a "read-only" variant. The cost is one extra GET per account visit and it doesn't cause correctness issues — the slice's save-version guard from fix #2 also prevents the two parallel loads from clobbering each other. Deferred.
- **Tagged-union state shape for `EnabledCompaniesState` (type-design-analyzer).** The current `{ids, loading, error}` boolean-soup has several representable-but-illegal states. A proper discriminated union is the right long-term fix, but it ripples through every consumer (selectors, tests, `useEnabledCompanies`, `EnabledCompaniesSection`, `EditCompanyPreferencesLink`). Deferred to a dedicated refactor PR.
- **Branded `CompanyId` type across layers (type-design-analyzer).** Same rationale as above — cross-cutting refactor, not a bug.
- **DB `CHECK` constraint on `company_id` column (type-design-analyzer).** Belt-and-braces with the Pydantic validator added in fix #3. Deferred — touching migrations requires a release plan, and the API validation covers the realistic attack surface.
- **Env-name interpolation bypass (carried from Round 1, score 50).** No new evidence.
- **`reload()` race on rapid successive external calls (carried from Round 1, score 25).** Superseded by fix #1 which captures a local AbortController synchronously; rapid `reload()` calls now abort the prior controller before awaiting a fresh token.

### Tests run

- `npm run type-check` — clean.
- `npm test -- --run` — all frontend tests pass (new count includes 6 new tests).
- `cd src/backend && pytest api/tests/test_users_router.py api/tests/test_user_preferences_service.py -v` — all backend tests pass (new count includes 2 new validation tests).

---
