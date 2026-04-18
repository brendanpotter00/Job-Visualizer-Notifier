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
