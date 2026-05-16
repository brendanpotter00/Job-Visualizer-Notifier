# Admin Users Redesign PR Review Audit Log

**Purpose:** Running log of review findings and fixes on PR #109 (`feat/admin-users-redesign`). Read this before proposing changes — decisions here may override the original PR description. Update when you apply a fix so the next reviewer has context.

**PR:** https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/109
**Base branch:** `main`
**Diff scope command:** `git diff origin/main...HEAD`

**Important guardrails for every review pass:**
- Read this file first. Honor any **Do not revert** entries from prior passes.
- This branch was cut from `feature/admin-dashboard` and includes three carry-over cleanup commits (`15d87ef`, `203078b`, `4131880`). They are in-scope for review.
- Each pass runs with fresh context — your job is to find what previous passes missed, not to re-litigate landed decisions.

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
