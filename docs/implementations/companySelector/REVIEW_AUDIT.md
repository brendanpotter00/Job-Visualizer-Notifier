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
