# Admin Users Redesign PR Review Audit Log

**Purpose:** Running log of review findings and fixes on PR #109 (`feat/admin-users-redesign`). Read this before proposing changes — decisions here may override the original PR description. Update when you apply a fix so the next reviewer has context.

**PR:** https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/109
**Base branch:** `main`
**Diff scope command:** `git diff origin/main...HEAD`

**Important guardrails for every review pass:**
- Read this file first. Honor any **Do not revert** entries from prior passes.
- This branch was cut from `feature/admin-dashboard` and includes three carry-over cleanup commits (`15d87ef`, `203078b`, `4131880`). They are in-scope for review.
- Each pass runs with fresh context — your job is to find what previous passes missed, not to re-litigate landed decisions.

**Do not revert (from pass 1):**
- The `LastAdminError` + `SELECT … FOR UPDATE` pattern in `admin_service.revoke_admin`. The 409 with that exact body string is contract.
- `AdminRoute` now renders `ErrorState` (with retry) on `userError && !user`. Do not collapse back into a redirect.
- `is_admin_by_email` calls in `users.py` are intentionally OUTSIDE the `psycopg2.Error` catch — that's the fix, not a regression.
- `UserResponse.is_admin` has no default. Keep it required.
- `SignupProvider` is now a shared Literal/Union on both sides; the `dict[SignupProvider, int]` / `Partial<Record<SignupProvider, number>>` shapes are deliberate.
- The granter-FK vs target-FK constraint-name branch in `routers/admin.py` returns 500 vs 404 by design.
- New `AdminUsersListResponse` named type with runtime `users` array guard.
- Pass 1 commit: `cda6930`.

**Do not revert (from pass 2):**
- `_signup_provider_from_auth0_id(...) -> SignupProvider` (the Literal return type, not `str`) is the producer-side guard for the Pydantic v2 closed-set validation on `AdminUsersStatsResponse.by_provider`.
- `extractErrorMessage` walks `err.error` and `err.error.message` AFTER `data.detail` / `data.message` — needed to surface RTK Query `CUSTOM_ERROR` / `FETCH_ERROR` messages (e.g. the `AdminUsersListResponse` runtime guard's thrown message).
- `revoke_admin` has a SINGLE `except Exception: conn.rollback(); raise` block — the `LastAdminError` subclass is handled identically; the dead `except LastAdminError` branch was removed by design.
- `forwardResponse.ts` short-circuits 204/304 with `res.status(...).end()`. Do not re-add the `{ error: ... }` body — RFC 9110 §15.3.5 / §15.4.5.
- `AdminUsersPage` renders TWO independent error slots (stat-tiles, roster). A single-query failure must NOT collapse the whole page.
- `NavigationDrawer` "admin status unavailable" indicator on `userError && !user && isAuthenticated`. Do not silently hide the admin section during a `/api/users` outage.
- `parseUserResponse` validates `isAdmin` is a boolean at the `/api/users` fetch boundary. Without this guard, a missing field silently demotes the admin via `AdminRoute`'s `!user.isAdmin`.
- `getAdminUsersStats` `transformResponse` runtime guard symmetric to `listAdminUsers`.
- `_row_to_user_response(row: UserRow, ...)` is the typed dict, not an opaque `dict`. Threaded from `user_service.UserRow`.
- `api/admin.ts` forwards request body for ANY method with `req.body != null` (lifted the PUT/POST-only restriction).
- Pass 2 commit: `d24b10f`.

**Do not revert (from pass 3):**
- `AdminUsersPage` per-slot loading semantics: page-level full spinner only when BOTH queries are still loading AND neither has data AND neither has errored. Each slot independently spins / errors / renders data. Do not collapse back into the old "isLoading || statsLoading" gate.
- `AdminUsersPage` header renders `"— total"` placeholder when `statsError && !stats`. Do NOT re-introduce the `stats?.totalUsers ?? users.length` silent fallback — the roster count is not authoritative as total user count.
- `extractErrorDetail` in `authService.ts` filters every candidate field by `typeof === 'string'` and reads nested `error.message`. The previous `b.detail || b.message || b.error` ladder coerced objects to `"[object Object]"` via `new Error(value)`.
- `forwardResponse` short-circuit covers 204 + 205 + 304 + 1xx informational. All four are body-less by RFC 9110.
- All four serverless proxies (`api/admin.ts`, `api/users.ts`, `api/features.ts`, `api/jobs-qa.ts`) forward `req.body` whenever `req.body != null` regardless of method. Do not re-narrow to `PUT/POST` only.
- `test_revoke_admin_uses_for_update_lock` strips comments and uses a regex matching the literal SQL pattern `SELECT user_id FROM {admins} FOR UPDATE` (no WHERE between SELECT and FOR UPDATE). A regression that scopes the lock to one row re-opens the concurrent-revoke race.
- `listAdminUsers.transformResponse` parameter is typed `unknown` (not `AdminUsersListResponse`). The annotation must say "untrusted" because the runtime guard exists for exactly that reason.
- `getAdminUsersStats` runtime guard validates `byProvider` values are numbers AND `firstSignupAt`/`latestSignupAt` are string|null. Do not relax to "exists" checks.
- `get_user_by_email` returns `UserRow | None` (not `dict | None`). Required so column renames in `db_models.User` surface at the callers.
- `QAPage.ScraperResult.isAuthError` drives `severity="warning"` + prefix `"Session expired:"` when the auth-error catch sets it. Do NOT collapse the auth case back into the generic `"Scrape failed:"` red treatment.
- `PROVIDER_LABEL` is a single named export from `features/admin/adminApi.ts`. Both `ProviderBars.tsx` and `UserRosterTable.tsx` import it. Do not re-introduce local copies — the previous divergence (`'Email / Auth0'` vs `'Email'`) was a maintenance hazard.
- The UserRosterTable `"Cannot revoke the last admin — promote another user first."` 409 Alert is pinned by an end-to-end test (not just the backend `assert "last admin" in detail.lower()`). The exact string is contract.
- Pass 3 commit: `9b1571c`.

---

## 2026-05-15 — Review pass 1

### Code-review findings

**Critical:**
- `src/backend/api/routers/admin.py:97-121` + `src/backend/api/services/admin_service.py:111-124` — no last-admin guardrail in `revoke_admin`; two admins acting concurrently can each pass the self-check and revoke the other, leaving the platform with zero admins and no API-level recovery path. (agent: silent-failure-hunter)
- `src/frontend/src/components/auth/AdminRoute.tsx:25-31` — when `useCurrentUser` errors (backend 500, JWKS outage, network failure), `AdminRoute` falls through to "not admin" and silently redirects, indistinguishable from a real unauthorized access. Admins lose visibility into auth-layer outages. (agent: silent-failure-hunter)
- `src/frontend/src/pages/QAPage/QAPage.tsx:136,171` — `getToken()` can reject with `NotAuthenticatedError` on signed-out renders; `useFetchWithStatus` surfaces that as a generic page error before `AdminRoute` redirects, producing a flash of "Not authenticated" on logout / first render. (agent: code-reviewer)
- `src/backend/api/routers/admin.py:86-89` — grant's `ForeignKeyViolation` handler maps *any* FK violation to "User not found" (404 on the target), but `admins` has two FKs (`user_id` and `granted_by`). A race where the granter user is deleted between resolve and insert returns a misleading 404 pointing at the wrong record. (agent: silent-failure-hunter)
- `src/frontend/src/features/admin/adminApi.ts:18` + `src/backend/api/models.py:173` — `by_provider` / `byProvider` are `Record<string, number>` / `dict[str, int]` even though `SignupProvider` is a `"google" | "email" | "other"` union and is enforced on the per-row field at `models.py:156`. A fourth provider added to `_signup_provider_from_auth0_id` renders raw keys to admins via `PROVIDER_LABEL[key] ?? key` with no compile error. (agent: type-design-analyzer)

**Important:**
- `src/backend/api/routers/users.py:77,103` — `is_admin_by_email` is called inside the same `try/except psycopg2.Error` block as `get_or_create_user`; the service author's stated intent (raise rather than silently deny) is undone by the router wrapping. Frontend then propagates as generic error → `AdminRoute` redirects. (agent: silent-failure-hunter)
- `src/backend/api/routers/users.py:103` — `is_admin` set via a short-circuit on `update_user` returning `None`, then the next line raises 404. The dead branch reads as if no-row is a normal response shape; clean it up. (agent: code-reviewer)
- `src/backend/api/models.py:102` — `UserResponse.is_admin: bool = False` has a default that's never used in practice; if a future endpoint constructs `UserResponse` without computing admin status, the user is silently demoted. Make the field required. (agent: type-design-analyzer)
- `src/backend/api/auth/dependencies.py:20-26` — `TokenClaims(TypedDict, total=False)` makes `email`/`sub` optional even after `require_admin` has verified them, forcing `admin.py:64` to re-narrow defensively. Introduce a `VerifiedAdminClaims` narrower so the defensive re-check is provably unreachable. (agent: type-design-analyzer)
- `src/frontend/src/features/admin/adminApi.ts:42` — `transformResponse: (res: { users: AdminUserRow[] }) => res.users` is the only place the envelope shape is described; if the backend ever wraps the response (pagination, etc.) `res.users` becomes `undefined`. Lift to a shared `AdminUsersListResponse` interface and validate. (agent: type-design-analyzer)
- `src/frontend/src/pages/AdminUsersPage/components/SignupSparkline.tsx:25-28` — `filter(NaN-timestamps)` silently shrinks the sparkline if `createdAt` becomes unparseable; no log, no banner, no test. (agent: silent-failure-hunter)
- `src/frontend/src/features/auth/authService.ts:19-24` — `extractErrorDetail`'s `.json().catch(() => null)` conflates non-JSON body / network failure / abort; users see only `Failed to fetch user (500)` with no context. (agent: silent-failure-hunter)
- `api/admin.ts:42-49`, `api/jobs-qa.ts:47-52` — every upstream failure (DNS, timeout, TLS, parse) coerces to one generic 502 message; admins can't tell whether to retry or escalate. Return a `reason` token in the body. (agent: silent-failure-hunter)
- Test gap: no test asserts that `granted_by` is **preserved** when grant is called idempotently by a different granter (`src/backend/api/tests/test_admin_router.py:212-222`). The `ON CONFLICT DO NOTHING` contract is the audit anchor. (agent: pr-test-analyzer)
- Test gap: `_resolve_granter_id` 401 (missing email claim) and 500 (granter row missing) branches at `src/backend/api/routers/admin.py:65-73` are entirely untested. (agent: pr-test-analyzer)
- Test gap: `src/frontend/src/pages/AdminUsersPage/AdminUsersPage.tsx` (page-level component) has zero tests — loading gate, error gate, `onRetry`, and `stats?.totalUsers ?? users.length` fallback are all unguarded. (agent: pr-test-analyzer)
- Test gap: `users.py` does not assert that `/api/users` actually returns `isAdmin: true` / `false` correctly — only camelCase key presence is checked. Regression to hard-coded `False` passes. (agent: pr-test-analyzer)

**Suggestion / Nit (deferred):**
- Connection-pool / autocommit pattern across admin read endpoints (existing pattern; broader refactor).
- `forwardResponse` non-JSON branch logging (minor).
- `is_admin_by_email` per-request caching to reduce DB calls (pre-existing from PR #108).
- `ProviderBars` / `SignupSparkline` / `StatTile` unit tests for sort / divide-by-zero / large-array reducer paths.
- `AdminUserRow.created_at: str` should be `datetime` (refactor — defer).
- Connection-holding analysis on `get_users_stats` / `is_admin_by_email` (relevant to existing memory pressure but pre-existing pattern).
- Inline duplication of proxy logic across `api/admin.ts`, `api/jobs-qa.ts`, `api/users.ts`, `api/features.ts` — extract `createBackendProxy` (refactor).
- `_signup_provider_from_auth0_id` returns `"other"` for unknown prefixes silently; add `log.warning` for new IdP rollouts.

### Production-environment findings

**Critical:** None.

**Important:** None.

**Suggestion:**
- `api/admin.ts:35` only forwards body for `PUT`/`POST`; current admin endpoints have no body so this is fine, but if a future `PATCH`/`DELETE` carries a body it'll break silently. (agent: vercel-prod-verifier)
- `admins.granted_by` is unindexed; `ON DELETE SET NULL` forces a seq scan if a `users` row is deleted. 1 row today, not a hot path. (agent: postgres-prod-verifier)
- `users.py` adds a per-request `is_admin_by_email` query on every `/api/users` GET/PUT — cheap (indexed) but raises per-call query count 1 → 2 on the hottest authenticated endpoint, relevant to known pool pressure. (agent: railway-prod-verifier)

**Could not verify:** None — all three verifiers ran successfully.

---

## 2026-05-15 — Review pass 2

### Code-review findings

**Critical:**
- `src/backend/api/services/admin_service.py:58` — `_signup_provider_from_auth0_id(...) -> str` is the producer; pass 1 tightened the *consumer* (`dict[SignupProvider, int]`) but left the producer wide. Adding a new IdP that returns e.g. `"github"` is NOT a compile error in Python (the `-> str` return is permissive), but Pydantic v2 DOES validate `dict[Literal[...], int]` keys at runtime — meaning every `/api/admin/users/stats` load fails with 500 in prod. Pass 1 traded "silent raw key rendering" for "admin dashboard 500s for everyone." Tighten producer return type to `SignupProvider`. (agent: type-design-analyzer)
- `src/frontend/src/lib/errors.ts` + `src/frontend/src/features/admin/adminApi.ts:62-66` — pass 1's `AdminUsersListResponse` runtime guard throws `new Error('Invalid /api/admin/users response: missing users[]')`. RTK Query wraps as `{ status: 'CUSTOM_ERROR', error: '...' }` on the `.error` field, but `extractErrorMessage` only walks `.data.detail`/`.data.message`/`.message` — never `.error`. Admin sees the generic fallback `"Failed to load admin data"`. The same masking hits `FETCH_ERROR` shapes. Pass 1's headline guard fires but its message is invisible. (agent: code-reviewer)
- `src/backend/api/tests/test_admin_router.py` (`test_revoke_last_admin_returns_409`) — single-threaded test passes even if `FOR UPDATE` is silently removed from the SQL. The lock is the entire contract; the test guards only the count check. (agent: pr-test-analyzer)
- `src/backend/api/tests/test_users_router.py` (`test_get_me_surfaces_is_admin_by_email_failure_as_500`) — only exercises the GET path. Pass 1 moved `is_admin_by_email` outside the `psycopg2.Error` catch on both GET and PUT, but only GET is tested. PUT regression would silently re-introduce the swallowed admin lookup. (agent: pr-test-analyzer)
- `src/frontend/src/features/auth/authService.ts:43` — `response.json()` is cast to `User` with no runtime validation. Symmetric backend hardening landed (`UserResponse.is_admin` required), but if the backend ever drops the field the frontend silently demotes the admin via `AdminRoute.tsx:57`'s `!user.isAdmin` check. Add a `parseUserResponse` validator mirroring the `AdminUsersListResponse` pattern. (agent: type-design-analyzer)

**Important:**
- `api/utils/forwardResponse.ts:26-27` — FastAPI's `Response(status_code=204)` from `revoke_admin` flows through `forwardResponse` which then sends `res.status(204).json({...})`. HTTP 204 MUST NOT carry a body (RFC 9110 §15.3.5). Short-circuit on 204/304 with `res.status(...).end()`. (agent: code-reviewer)
- `src/frontend/src/pages/AdminUsersPage/AdminUsersPage.tsx:50-63` — `const error = usersQuery.error ?? statsQuery.error; if (error) return ErrorState;` hides the entire page on a single-query failure. If stats fails but users succeeds, the roster vanishes — the exact conflated-failure pattern this PR is meant to prevent. Render two independent error slots. (agent: code-reviewer)
- `src/backend/api/routers/admin.py:96-99` (granter-FK 500 branch) — logs `user_id=%s` (the target) but omits `granter_id` / `granter_email`. On-call needs to know WHICH granter was deleted mid-grant. (agent: silent-failure-hunter)
- `src/frontend/src/pages/QAPage/QAPage.tsx:185-195` — `handleTriggerScrape`'s `NotAuthenticatedError` short-circuit early-returns silently. User clicks "Trigger Scrape" and sees nothing — no toast, no error, no feedback. Show "Session expired" or let the error propagate. (agent: silent-failure-hunter)
- `src/frontend/src/components/layout/NavigationDrawer.tsx:125,186` — `isAdmin = !!user?.isAdmin` evaluates false during `/api/users` outage; admin nav silently disappears. AdminRoute's ErrorState only fires when navigating TO `/admin/*`. Render a "Admin status unavailable" indicator or disabled section when `userError && !user`. (agent: silent-failure-hunter)
- `src/frontend/src/features/auth/useCurrentUser.ts:29-32` — `userError` flattened to a string with no `console.error`. Lost stack/abort/status; ops has no devtools trail. (agent: silent-failure-hunter)
- `api/admin.ts:35-37` — body-forwarding skips `PATCH`/`DELETE`. Today's endpoints have no body; the next admin endpoint with a `DELETE`-with-body will silently drop it. (agent: code-reviewer)
- `src/frontend/src/features/admin/adminApi.ts:71-74` (`getAdminUsersStats`) — symmetric blind spot of the `listAdminUsers` runtime guard. No validation; a CDN error page with `totalUsers === undefined` causes `?? users.length` to display loaded-roster-count as "Total users." Silently wrong number. (agent: type-design-analyzer)
- `src/backend/api/services/admin_service.py:165-171` — `except LastAdminError:` then `except Exception:` both call `conn.rollback(); raise` — identical behavior. The first branch is dead code at the service layer (the router does the translation). Remove. (agent: type-design-analyzer)
- `src/backend/api/routers/users.py:29` — `_row_to_user_response(row: dict, *, is_admin: bool)` — pass 1 required `is_admin` but left `row: dict` unconstrained. A field rename in `user_service` would not surface here until runtime. Thread a `UserRow` TypedDict from the service return type through this helper. (agent: type-design-analyzer)
- Test gap: `handleTriggerScrape` `NotAuthenticatedError` path is untested; only the fetch lifecycle path is. A regression flashes "Not authenticated" inside the scrape Alert. (agent: pr-test-analyzer)
- Test gap: `stats?.totalUsers ?? users.length` fallback at `AdminUsersPage.tsx:75` is unreachable in current tests (all populate `stats`). (agent: pr-test-analyzer)
- Test gap: `AdminUsersListResponse` runtime guard test only covers `{}`. Add a `{ users: null }` / `{ users: "string" }` case so a regression like `if (!res.users)` doesn't slip through. (agent: pr-test-analyzer)
- Test gap: admin serverless proxy test only covers GET. DELETE (revoke) and POST (grant) method forwarding is untested. (agent: pr-test-analyzer)

**Suggestion / Nit (deferred):**
- `_signup_provider_from_auth0_id` "other" fallback log warning (deferred from pass 1; still deferred).
- `revoke_admin` non-admin path still acquires `FOR UPDATE` on all admin rows (no perf issue at 1 admin; gate with `EXISTS` once admin count grows).
- `LastAdminError("...")` message duplicated between service and router (drop service message or thread through).
- `VerifiedAdminClaims` narrower (deferred from pass 1).
- `AdminUserRow(**r)` opaque dict unpacking (related to `_row_to_user_response` fix; defer the wider thread).
- `first_signup_at: str | None` lacks ISO-8601 contract enforcement (related to deferred `created_at: datetime` migration).
- ANALYZE `admins` post-deploy (pre-existing).
- `_resolve_granter_id` defensive 401 should `logger.error` since it's unreachable in production.

### Production-environment findings

**Critical:** None.

**Important:** None.

**Suggestion:**
- `revoke_admin`'s `SELECT user_id FROM admins FOR UPDATE` (no WHERE) acquires row locks on every admin row — fine at 1 admin, gate with EXISTS once N >> 20. (agent: postgres-prod-verifier)
- Pass-1 commit `cda6930` not yet pushed; remote tip still `9cabf79`. Vercel preview reflects pre-pass-1 state. (agent: vercel-prod-verifier) — addressed by pushing after pass 2.
- `is_admin_by_email` on `/api/users` GET+PUT remains the next pool-pressure watch (per-request memoization). (agent: railway-prod-verifier) — deferred.

**Could not verify:**
- `EXPLAIN ... FOR UPDATE` against prod — the `claude_readonly` role lacks UPDATE/DELETE privilege. Lock semantics analyzed by Postgres documentation, not by direct EXPLAIN.

### Fixes applied this pass

**Critical:**
- Last-admin guardrail in `revoke_admin` (`src/backend/api/services/admin_service.py`): added `LastAdminError` and wrapped revoke in an explicit transaction with `SELECT … FOR UPDATE` over `admins`. Router (`src/backend/api/routers/admin.py`) translates to 409 with body `"Cannot revoke the last admin — promote another user first."`. Idempotent non-admin revoke still returns 204.
- `AdminRoute` error vs. unauthorized split (`src/frontend/src/components/auth/AdminRoute.tsx`): renders `ErrorState` with retry when `useCurrentUser` returns a non-null error and no user. Redirect to `/jobs` only fires when `user.isAdmin === false`.
- `QAPage` short-circuits `NotAuthenticatedError` from `getToken()` (`src/frontend/src/pages/QAPage/QAPage.tsx`): both scrape-runs fetch and the trigger-scrape handler catch the marker class and return early instead of surfacing a generic error.
- `grant_admin` FK violation distinguishes target vs. granter constraint (`src/backend/api/routers/admin.py`): `admins_granted_by_fkey` → 500 with "Granter user record changed during grant — please retry."; default + `admins_user_id_fkey` → 404.
- `SignupProvider` typing tightened (`src/backend/api/models.py`, `src/frontend/src/features/admin/adminApi.ts`, `ProviderBars.tsx`, `UserRosterTable.tsx`): backend `by_provider` is `dict[SignupProvider, int]` with module-level alias; frontend `byProvider` is `Partial<Record<SignupProvider, number>>`; both `PROVIDER_LABEL` constants are `Record<SignupProvider, string>` so adding a new provider is a compile error.

**Important:**
- `UserResponse.is_admin` required (no default; `src/backend/api/models.py`). `_row_to_user_response` made the `is_admin` arg keyword-only with no default to match.
- `users.py:103` dead branch removed: 404 raises BEFORE `is_admin_by_email` runs; `is_admin_by_email` moved OUTSIDE the `psycopg2.Error` block on both GET and PUT so its intentional raises propagate as 500.
- RTK Query `listAdminUsers` envelope lifted to named export `AdminUsersListResponse` with runtime guard that throws `"Invalid /api/admin/users response: missing users[]"` on bad bodies (`src/frontend/src/features/admin/adminApi.ts`).

**Test gaps closed:**
- `test_revoke_last_admin_returns_409` + `test_revoke_when_multiple_admins_exist_succeeds` (admin router).
- `test_grant_admin_idempotent_preserves_original_granted_by` (admin router).
- `test_grant_admin_granter_fk_violation_returns_500_not_404` + `test_grant_admin_target_fk_violation_returns_404` (admin router, unit-level constraint-name branch).
- `TestResolveGranterIdBranches::test_grant_without_email_claim_returns_401` (admin router).
- `test_is_admin_true_when_user_has_admin_grant` + `test_is_admin_false_when_no_admin_grant` + `test_get_me_surfaces_is_admin_by_email_failure_as_500` (users router).
- `AdminUsersPage.test.tsx`: loading, error+retry, success-render coverage.
- AdminRoute error-state test + retry button assertion.
- `adminApi.test.ts`: bad-body runtime guard surfaces error.
- `QAPage.test.tsx`: `NotAuthenticatedError` short-circuits without an error banner.

**Deferred this pass (per audit log "Important" / "Suggestion" carve-outs):**
- `auth/dependencies.py` `VerifiedAdminClaims` narrower (audit pass 1 "Important" but not in critical fix list).
- `SignupSparkline` NaN-filter logging (audit pass 1 "Important" — not in critical fix list).
- `extractErrorDetail` JSON-vs-network split (audit pass 1 "Important" — not in critical fix list).
- Serverless `api/admin.ts` + `api/jobs-qa.ts` 502 `reason` token (audit pass 1 "Important" — not in critical fix list).
- All "Suggestion / Nit (deferred)" items unchanged.

### Fixes applied in pass 2

**Critical:**
- `_signup_provider_from_auth0_id(...) -> SignupProvider` (`src/backend/api/services/admin_service.py`): tightened producer return type. The pass-1 consumer (`dict[SignupProvider, int]`) would have surfaced a new IdP prefix as a runtime 500 on `/api/admin/users/stats`; the new producer type forces the closed set at mypy time. Also tightened `get_users_stats`' local `by_provider` dict typing. Added a `TestSignupProviderHelper` test class pinning the closed-set fallback.
- `extractErrorMessage` now reads `err.error` and `err.error.message` (`src/frontend/src/lib/errors.ts`): RTK Query's `CUSTOM_ERROR` (raised by the `AdminUsersListResponse` runtime guard via `transformResponse`) and `FETCH_ERROR` shapes both carry the message on `.error`. The previous decoder walked `.data.detail`/`.data.message`/`.message` only — the pass-1 guard's actionable message was invisible to the admin. Tests cover both string and nested `{ message }` shapes, plus priority vs. `data.detail`.
- `test_revoke_admin_uses_for_update_lock` (`src/backend/api/tests/test_admin_router.py`): source-level guard via `inspect.getsource(revoke_admin)` that pins the `FOR UPDATE` SQL invariant — the single-connection test suite cannot reliably reproduce the concurrent revoke race the lock guards against.
- `test_put_me_surfaces_is_admin_by_email_failure_as_500` (`src/backend/api/tests/test_users_router.py`): companion to the GET-path test from pass 1. Asserts both the 500 status AND that the body is NOT `{"isAdmin": false}`, so a regression that re-wraps the call inside the `psycopg2.Error` catch fails loudly instead of silently demoting the user.
- `parseUserResponse` runtime guard (`src/frontend/src/features/auth/authService.ts`): validates `id`, `email`, `isAdmin` at the `/api/users` fetch boundary. Symmetric to `AdminUsersListResponse`. Without it, a 2xx body missing the `isAdmin` field would coerce to `undefined` and `AdminRoute.tsx`'s `!user.isAdmin` check would silently demote the admin. Tests cover the missing-field and wrong-type cases.

**Important:**
- `forwardResponse.ts` short-circuits 204/304 with `res.status(...).end()` — RFC 9110 §15.3.5 / §15.4.5 forbid bodies on these statuses. Grant/revoke admin's `Response(status_code=204)` is the hot path that previously got wrapped in a `{ error: statusText }` body. Existing `users.serverless.test.ts` + `features.serverless.test.ts` 204 tests updated to assert `res.end()` was called and `res.json()` was not.
- `AdminUsersPage` partial-failure independence (`src/frontend/src/pages/AdminUsersPage/AdminUsersPage.tsx`): only renders the full-page `ErrorState` when BOTH queries fail. A stats-only failure leaves the roster rendered and shows an inline `ErrorState` in the stat-tile slot (with a stats-only retry); a users-only failure does the inverse. Tests cover both partial-failure directions.
- Granter-FK 500 log enriched (`src/backend/api/routers/admin.py`): now includes `granter_email` and `granter_id`; the target `user_id` is intentionally NOT logged on the granter-FK branch (the FK violation is about the granter, not the target — including the target would mislead on-call).
- `handleTriggerScrape` `NotAuthenticatedError` surfaces a session-expired warning Alert (`src/frontend/src/pages/QAPage/QAPage.tsx`): previously the catch returned silently — the user clicked Trigger Scrape and saw nothing. Now sets `scrapeResult.error = 'Your session expired — please sign back in.'` so the admin gets an actionable cue.
- `NavigationDrawer` "admin status unavailable" indicator (`src/frontend/src/components/layout/NavigationDrawer.tsx`): when `userError && !user && isAuthenticated`, renders a disabled, warning-icon affordance ("Admin status unavailable — retry") instead of hiding the admin section entirely. Clicking calls `reload()`. Admins no longer silently lose admin nav during a `/api/users` outage.
- `useCurrentUser` calls `console.error('[useCurrentUser] fetch failed', err)` before flattening to a string (`src/frontend/src/features/auth/useCurrentUser.ts`): the flattened string still goes to state for the UI, but ops now has a devtools trail with the stack / abort / status detail.
- `api/admin.ts` body-forwarding for all methods: lifted the `PUT`/`POST`-only restriction so any method with `req.body != null` forwards. Test pins this with a `PATCH` body case plus `DELETE`/`POST` method-forwarding assertions on 204 (verifies the forwardResponse short-circuit).
- `getAdminUsersStats` runtime guard (`src/frontend/src/features/admin/adminApi.ts`): symmetric to `listAdminUsers`. Validates `typeof totalUsers === 'number'` and `byProvider` is a non-array object; throws `'Invalid /api/admin/users/stats response: ...'` on bad bodies. Without this, a CDN error page with `totalUsers === undefined` would silently fall through to `users.length` as "Total users" in the dashboard.
- Removed the dead `except LastAdminError` block in `revoke_admin` (`src/backend/api/services/admin_service.py`): `LastAdminError` is an `Exception` subclass, so the subsequent `except Exception: conn.rollback(); raise` handles it identically. Docstring updated to call out the consolidation.
- `_row_to_user_response(row: UserRow, ...)` (`src/backend/api/routers/users.py` + `src/backend/api/services/user_service.py`): introduced `UserRow` `TypedDict` in `user_service` mirroring the `db_models.User` columns. `get_or_create_user` / `_lookup_and_upsert` / `update_user` return `UserRow` / `UserRow | None`. A column rename in `db_models` is now a mypy/pyright error at the per-field reads in the helper instead of a runtime `KeyError`.

**Test gaps closed:**
- `extractErrorMessage`: CUSTOM_ERROR string, FETCH_ERROR string, nested `error.message`, priority vs. `data.detail`, empty-string fallback, non-string-with-no-message fallback.
- `parseUserResponse`: missing `isAdmin` field, non-boolean `isAdmin`.
- `forwardResponse` 204 body: existing tests in users + features serverless updated to assert `res.end()` and no `res.json()`.
- `AdminUsersPage`: stats-fails-roster-succeeds + roster-fails-stats-succeeds partial-failure cases.
- QAPage: session-expired Alert via `handleTriggerScrape` NotAuthenticatedError catch.
- NavigationDrawer: "admin status unavailable" indicator on `userError && !user`; negative case when `userError` is null.
- `adminApi.test.ts`: `{ users: null }` and `{ users: 'string' }` bad-body cases (companions to the `{}` case); `getAdminUsersStats` missing-totalUsers / wrong-type-totalUsers / missing-byProvider cases.
- `admin.serverless.test.ts`: POST grant + DELETE revoke method-forwarding with 204 short-circuit assertions; PATCH-with-body forwarding case.
- `TestSignupProviderHelper`: pins the closed-set fallback for unknown prefixes (the `-> SignupProvider` Literal return).

**Deferred from pass 2 (audit log "Deferred" / "Suggestion" carve-outs):**
- `_signup_provider_from_auth0_id` "other" fallback log warning (still deferred).
- `revoke_admin` `FOR UPDATE` perf gate via `EXISTS` (no perf issue at 1 admin).
- `LastAdminError` duplicated message (cosmetic).
- `VerifiedAdminClaims` narrower (still deferred from pass 1).
- `AdminUserRow(**r)` opaque dict unpacking, `first_signup_at` ISO-8601 contract, ANALYZE post-deploy.
- `_resolve_granter_id` defensive 401 → `logger.error` (cosmetic).

---

## 2026-05-15 — Review pass 3

### Code-review findings

Pass 3 found ZERO Critical findings — the prior two passes hardened the load-bearing surfaces. The Important findings below are mostly interactions between earlier fixes (e.g. the partial-failure independence from pass 2 left a loading-gate race; the `extractErrorMessage` `.error` walk added in pass 2 didn't extend to `authService.ts`'s ad-hoc `extractErrorDetail`).

**Important fixes applied this pass:**

1. **`AdminUsersPage` partial-loading transient.** Loading gate had carve-outs for `!usersError && !statsError` — if one query errored while the other was still loading, the spinner skipped and the page rendered with an empty slot and no progress indicator. Refactored to per-slot loading: page-level full spinner only when BOTH queries are still loading AND no errors yet; each slot independently shows its own spinner if loading with no data, its inline ErrorState if errored, or its data otherwise. Test added covering the "stats errored, users still loading" case.

2. **`AdminUsersPage` header `{totalUsers} total` silent fallback removed.** `stats?.totalUsers ?? users.length` rendered the roster count as authoritative when stats failed — admins couldn't tell stats was broken. Fixed: header renders `"— total"` placeholder when stats has errored and there's no stats data. Test added asserting the dashed placeholder appears (and the silent numeric fallback does NOT).

3. **`extractErrorDetail` (authService.ts) hardened against non-string fields.** The inline `b.detail || b.message || b.error` chain returned objects directly, which `new Error(object)` coerced to `"[object Object]"`. Each field is now filtered by `typeof === 'string'`, and the top-level `error` field's nested `.message` is read if `error` is an object. Tests added for `{ error: { code, message } }` (asserts the nested `message` surfaces) and for non-string `detail` (asserts no `[object Object]`).

4. **`forwardResponse.ts` body-less short-circuit extended to 205 + 1xx.** RFC 9110 §15.3.6 (205 Reset Content), §15.2 (1xx Informational) and §15.4.5 (304) all forbid bodies. The previous gate covered 204/304 only. Now: `status === 204 || status === 205 || status === 304 || (status >= 100 && status < 200)`. 205 test added to `users.serverless.test.ts`.

5. **Body-forwarding lifted from `PUT/POST`-only to `req.body != null`** in `api/users.ts`, `api/features.ts`, `api/jobs-qa.ts` — matches `api/admin.ts` lifted in pass 2. PATCH-with-body test added to each.

6. **End-to-end 409 last-admin Alert contract test.** The pass-1 headline contract (`"Cannot revoke the last admin — promote another user first."`) had no test pinning backend response → `extractErrorMessage` → Alert text. Test added in `UserRosterTable.test.tsx` asserting the Alert contains the exact contract string (not a regex match) — so a regression in any layer of the chain fails loudly.

7. **`test_revoke_admin_uses_for_update_lock` strengthened.** The plain `"FOR UPDATE" in source` check would still pass if a regression left `FOR UPDATE` only in a comment. Now strips `#`-comments line-by-line first, then asserts via regex that the literal pattern `SELECT\s+user_id\s+FROM\s+\{admins\}\s+FOR\s+UPDATE` appears in the SQL string — no WHERE between SELECT and FOR UPDATE (which would scope locks to one row and re-open the race).

8. **PUT-path `parseUserResponse` symmetry tests.** Missing-`isAdmin` and wrong-type-`isAdmin` cases were only tested via the GET (`fetchCurrentUser`) path. `updateCurrentUser` calls `parseUserResponse` identically; symmetric tests added to lock the PUT-path contract.

9. **`listAdminUsers` `transformResponse` parameter typed `unknown`.** The annotation said `AdminUsersListResponse` (the validated envelope) but the body treated the input as untrusted. Now: `(res: unknown): AdminUserRow[]` — matches the `getAdminUsersStats` pattern, makes the runtime guard's purpose explicit at the signature.

10. **`getAdminUsersStats` runtime guard extended.** Previously checked `totalUsers` is number and `byProvider` is non-array object, but NOT that `byProvider` values are numbers or that `firstSignupAt`/`latestSignupAt` are string|null. Both checks added. Tests for `byProvider: { google: "5" }` and `firstSignupAt: 0` / `latestSignupAt: 1234567890` added.

11. **`get_user_by_email` return type tightened to `UserRow | None`.** Was `dict | None`; now matches the pass-2 threading of `UserRow` through `get_or_create_user` / `update_user`. Callers (`routers/admin.py`, `routers/users.py`, `routers/features.py`) get column-rename detection at the per-field reads.

12. **`QAPage.handleTriggerScrape` NotAuthenticatedError severity/labeling.** Previously the auth-error case rendered `severity="error"` with prefix `"Scrape failed:"` — visually identical to a real scraper crash. Added `isAuthError?: boolean` to `ScraperResult`; the auth-error branch sets it and the Alert renders `severity="warning"` with prefix `"Session expired:"`. Existing QAPage test updated to assert the warning severity and the new prefix.

13. **`PROVIDER_LABEL` lifted to a single shared constant.** `ProviderBars.tsx` used `'Email / Auth0'` while `UserRosterTable.tsx` used `'Email'` — both typed `Record<SignupProvider, string>` but with divergent values, a maintenance hazard. Moved to a named export `PROVIDER_LABEL` in `features/admin/adminApi.ts` with the more-verbose canonical `'Email / Auth0'`; both components now import it.

### Production-environment findings

Not run this pass (focused on code-review interactions surfaced in pass 3 review). The pass-2 production checks remain authoritative.

### Fixes applied this pass

**Important:**
- `AdminUsersPage` (`src/frontend/src/pages/AdminUsersPage/AdminUsersPage.tsx`): per-slot loading semantics + header em-dash placeholder when stats errors.
- `authService.ts` (`src/frontend/src/features/auth/authService.ts`): `extractErrorDetail` now filters every candidate field by `typeof === 'string'` and reads nested `error.message`.
- `forwardResponse.ts` (`api/utils/forwardResponse.ts`): short-circuit extended to 205 + 1xx + 304 + 204.
- `api/users.ts`, `api/features.ts`, `api/jobs-qa.ts`: body-forwarding lifted to `req.body != null` (parity with `api/admin.ts`).
- `test_admin_router.py::test_revoke_admin_uses_for_update_lock`: now strips comments and asserts via regex against the literal SQL string.
- `adminApi.ts` (`src/frontend/src/features/admin/adminApi.ts`):
  - `listAdminUsers.transformResponse: (res: unknown): AdminUserRow[]` (was `AdminUsersListResponse`).
  - `getAdminUsersStats.transformResponse` extended to validate `byProvider` values are numbers and `firstSignupAt`/`latestSignupAt` are string|null.
  - New named export `PROVIDER_LABEL: Record<SignupProvider, string>` with canonical `'Email / Auth0'`.
- `user_service.py::get_user_by_email`: return type `UserRow | None` (was `dict | None`).
- `QAPage.tsx` (`src/frontend/src/pages/QAPage/QAPage.tsx`): `ScraperResult.isAuthError?: boolean` + `severity="warning"` / `"Session expired:"` prefix when set.
- `ProviderBars.tsx` + `UserRosterTable.tsx`: import shared `PROVIDER_LABEL` from `adminApi.ts`; remove local copies.

**Test gaps closed:**
- `AdminUsersPage.test.tsx`: stats-errored-users-still-loading case (asserts per-slot spinner); stats-fails-roster-succeeds asserts header renders `"— total"` instead of silent `users.length` fallback.
- `authService.test.ts`: `extractErrorDetail` with `{ error: { code, message } }` body (asserts nested message surfaces); non-string `detail` falls through (asserts no `[object Object]`). Plus PUT-path `parseUserResponse` symmetric tests for missing-`isAdmin` / wrong-type-`isAdmin`.
- `users.serverless.test.ts`: 205 Reset Content short-circuit + PATCH-with-body forwarding.
- `features.serverless.test.ts` + `jobs-qa.serverless.test.ts`: PATCH-with-body forwarding (parity with `admin.serverless.test.ts` from pass 2).
- `UserRosterTable.test.tsx`: 409 last-admin Alert asserts the exact contract string (cross-layer wiring).
- `adminApi.test.ts`: `byProvider: { google: "5" }`, `firstSignupAt: 0`, `latestSignupAt: 1234567890` all reject via runtime guard.
- `QAPage.test.tsx`: `NotAuthenticatedError` Alert asserts `severity="warning"` (not `error`) and prefix `"Session expired:"` (not `"Scrape failed:"`).

**Deferred from pass 3:**
- All pass-1 / pass-2 deferred items remain deferred.
- No new deferred items introduced.

**Pass 3 commit:** see `git log` after this commit lands.
