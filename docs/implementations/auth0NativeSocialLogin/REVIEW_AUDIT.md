# Auth0 Native Social Login PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-04-18 — Review pass 1

Five reviewers ran in parallel: code-reviewer, silent-failure-hunter, pr-test-analyzer, type-design-analyzer, comment-analyzer. Diff scope: `git diff origin/main...HEAD` covering Unit 1's four code/test files plus the PLAN.md additions (PLAN edits intentionally not reviewed as code).

### Findings

**Critical:**
- (none across any reviewer)

**Important:**
- `src/frontend/src/features/auth/exchangeGoogleToken.ts:71` — Success-path `await response.json()` is not wrapped in try/catch, asymmetric with the 4xx branch. A 200 with empty/non-JSON body would throw a raw `SyntaxError` without the `[exchangeGoogleToken]` prefix the rest of the function maintains. (agent: silent-failure-hunter)
- `src/frontend/src/__tests__/features/auth/GoogleOneTap.test.tsx` — Exchange-failure test does not explicitly assert `await config.onSuccess(...)` resolves without throwing. Google's One Tap library treats a thrown/rejected `onSuccess` as fatal (no re-prompt). Add `await expect(...).resolves.toBeUndefined();`. (agent: pr-test-analyzer, rating 7)
- `src/frontend/src/__tests__/features/auth/GoogleOneTap.test.tsx` — Success-path test should add an explicit negative assertion `expect(mockSetGoogleCredential).not.toHaveBeenCalledWith('google-jwt-token')` to lock the contract that the raw Google JWT never leaks past the One Tap callback (this PR's whole reason for existing). (agent: pr-test-analyzer, rating 7)
- `src/frontend/src/__tests__/features/auth/exchangeGoogleToken.test.ts` — Missing two tests for the `error_description ?? error ?? '(no body)'` fallback chain: 4xx with JSON containing only `error`, and 4xx with empty `{}` body. The thrown message is a production diagnostic surface; lock its format. (agent: pr-test-analyzer, rating 5)

**Deferred (not fixing this pass):**
- UX gap: on systemic exchange failure (Auth0 misconfig like `unauthorized_client`), the user sees endless silent re-prompts with no actionable feedback. Adding a toast/snackbar or fallback-to-Universal-Login would expand scope beyond Unit 1's PLAN-frozen contract ("On exchange failure, console.warn and do not store any credential — the user sees the One Tap prompt re-appear"). The lightweight mitigation per the reviewer's "absolute minimum" is to verify the failure UX in Unit 2's manual E2E checklist. **Action this pass:** add a failure-path step to PLAN.md Unit 2's tasks. Full UX rework is a follow-up. (agent: silent-failure-hunter)
- Type-design: return a richer shape `{ accessToken, expiresAt, tokenType }` instead of `Promise<string>`. Conflicts with the frozen Shared Contract in PLAN.md ("Auth0 `id_token` and `expires_in` from the response are not stored — the access token's own `exp` claim is the source of truth"). Storage layer wants a single string today. (agent: type-design-analyzer)
- Type-design: branded `Auth0AccessToken` type. High-value but requires touching `setGoogleCredential` in `GoogleCredentialContext.tsx`, which is explicitly out of Unit 1's owned-files scope. Suitable as a follow-up after the cutover stabilizes. (agent: type-design-analyzer)
- Suggestions: `AbortController` timeout on the fetch; ordering test for "exchange must complete before setGoogleCredential"; identity (vs `objectContaining`) check for `AUTH_CONFIG`; tighter regex on the 4xx error message. All real but lower priority — deferred to keep this pass focused on the Important items. (agents: code-reviewer, pr-test-analyzer, silent-failure-hunter)
- Comment style: trim the `exchangeGoogleToken` JSDoc to drop WHAT-restatement and the PLAN.md reference; remove the inline `// body wasn't JSON` comment. Style debate, not load-bearing. (agent: comment-analyzer)

### Conflicts with prior audit

(none — pass 1)

### Implementation applied

Commit: `37ce7f2` — "Review pass 1: harden exchange JSON parse and test assertions"

Files changed:
- `src/frontend/src/features/auth/exchangeGoogleToken.ts` — wrapped success-path `response.json()` in try/catch, mirroring the 4xx branch so empty/non-JSON 200 responses surface with the `[exchangeGoogleToken]` prefix.
- `src/frontend/src/__tests__/features/auth/exchangeGoogleToken.test.ts` — added 3 tests (15 total): non-JSON 200 body, 4xx with `error` only, 4xx with empty `{}` body. Locks the `error_description ?? error ?? '(no body)'` fallback chain.
- `src/frontend/src/__tests__/features/auth/GoogleOneTap.test.tsx` — added `await expect(...).resolves.toBeUndefined()` to the exchange-failure test so the One Tap callback contract (must not throw) is locked, plus a negative assertion that `setGoogleCredential` is never called with the raw Google JWT.
- `docs/implementations/auth0NativeSocialLogin/PLAN.md` — Unit 2 manual E2E checklist gained a failure-path step (Auth0 misconfig → verify `[GoogleOneTap]` warning + no credential stored). Original task 8 renumbered to 9.

Verification: `npm run type-check` ✓, `npm test` (exchangeGoogleToken 15/15, GoogleOneTap 10/10) ✓, `npm run build` ✓.

### Do not revert (new in this pass)

- The success-path JSON try/catch in `exchangeGoogleToken.ts` is load-bearing: it ensures every error thrown from this function carries the `[exchangeGoogleToken]` prefix that `GoogleOneTap.tsx` logs as `[GoogleOneTap] Auth0 token exchange failed: <msg>`. Future cleanup that "simplifies" by collapsing the two try/catches loses the prefix on a class of failures.
- The negative assertion `expect(mockSetGoogleCredential).not.toHaveBeenCalledWith('google-jwt-token')` in the success-path test encodes the entire reason this PR exists — the raw Google JWT must never be stored. Do not delete it as "redundant with the positive assertion."
- The new Unit 2 failure-path E2E task is the deferred mitigation for the silent-re-prompt UX gap. Removing it without replacing the mitigation reopens that finding.

---

## 2026-04-18 — Review pass 2

Four reviewers ran in parallel: code-reviewer, silent-failure-hunter, pr-test-analyzer, comment-analyzer. (type-design-analyzer skipped — no new types introduced or modified since pass 1.) Diff scope: `git diff origin/main...HEAD` covering Unit 1's four code/test files + the pass-1 fix commit.

### Findings

**Critical:**
- (none)

**Important:**
- `src/frontend/src/__tests__/features/auth/exchangeGoogleToken.test.ts` — No 5xx test; the only non-2xx coverage is 4xx. Auth0 503/504 during outages hits the same `!response.ok` branch and the `Auth0 returned 5xx: ...` diagnostic format is a production surface that should be locked. (agent: pr-test-analyzer, rating 7)
- `src/frontend/src/__tests__/features/auth/exchangeGoogleToken.test.ts:157` — Network-error test uses `Error('boom')`, but real `fetch` throws `TypeError` (DNS/CORS/offline). Switch to `new TypeError('Failed to fetch')` and assert the thrown message contains `Network error:` so the prefix contract is locked against future refactors. (agent: pr-test-analyzer, rating 7)
- `src/frontend/src/__tests__/features/auth/exchangeGoogleToken.test.ts:117` — `exchangeGoogleToken.ts:78` guards `typeof json.access_token !== 'string'` but tests only cover the `undefined` case. `{ access_token: null }` or `{ access_token: 123 }` would silently pass through if the typeof check were removed. Add cases for both to lock the guard. (agent: pr-test-analyzer, rating 6)
- `src/frontend/src/__tests__/features/auth/GoogleOneTap.test.tsx:138` — The "missing credential" test asserts `setGoogleCredential` and `exchangeGoogleToken` are not called, but does not `await expect(config.onSuccess({})).resolves.toBeUndefined()`. The same One Tap re-prompt contract that pass 1 locked on the exchange-failure branch applies here; without this assertion a future "throw on missing credential" refactor would silently break re-prompt. Symmetric with pass 1's fix. (agent: silent-failure-hunter)

**Deferred (not fixing this pass):**
- Domain foot-gun: if `VITE_AUTH0_DOMAIN` is misconfigured with a leading `https://`, the URL becomes `https://https://...` and fails as an opaque network error. Real but a config-validation concern, not a code-correctness concern; cleaner mitigation belongs in `AUTH_CONFIG` parsing. (agent: code-reviewer)
- Failure-path doesn't clobber prior credential: the existing `not.toHaveBeenCalled()` assertion already covers this; only a comment articulating the broader invariant is missing. Style-only. (agent: code-reviewer)
- Ordering test (exchange resolves before setGoogleCredential): repeating from pass 1 deferred list. Real but lower priority. (agents: code-reviewer, pr-test-analyzer)
- `console.warn` two-arg vs template literal: behavior-equivalent, console rendering quirk. Style debate. (agent: silent-failure-hunter)
- 4xx body parse silently discards parse error (could surface a truncated raw body for HTML error pages from CDNs/proxies): valid debugging-quality polish, but the current `(no body)` fallback is honest enough — adding `text()`-then-parse would expand the function's responsibility. (agent: silent-failure-hunter)
- 4xx-non-JSON test should assert `(no body)` appears in the message: covered indirectly by the existing `/401/` matcher on a non-JSON body; a tighter regex is a nit. (agent: silent-failure-hunter)
- `AUTH_CONFIG` identity vs `objectContaining`: repeating from pass 1 deferred list. (agent: pr-test-analyzer)
- Repeated rapid invocations test (last-write-wins documentation): nice-to-have for documenting current behavior, but no bug to fix today. (agent: pr-test-analyzer)
- Comment style: delete `// body wasn't JSON` inline comment. Re-raised from pass 1 deferred list with no stronger reason; staying deferred. (agent: comment-analyzer)
- Nits: `mockAuthConfig` typing as `Partial<AuthConfig>`; `body as URLSearchParams` cast fragility; bare `catch {}` doc comment; mock `Content-Type` header for fidelity; test-name length. All real, all low-priority. (agents: code-reviewer, silent-failure-hunter, pr-test-analyzer)

### Conflicts with prior audit

(none — all pass-1 "Do not revert" items were honored by pass-2 reviewers)

### Implementation applied

Commit: `c4cb5a7` — "Review pass 2: lock 5xx, network-error, non-string token, and missing-credential test contracts"

Files changed (test-only — zero production code touched):
- `src/frontend/src/__tests__/features/auth/exchangeGoogleToken.test.ts` — +4 tests (15 → 19): 5xx (503), `TypeError` network error, `access_token: null`, `access_token: 123`.
- `src/frontend/src/__tests__/features/auth/GoogleOneTap.test.tsx` — added `await expect(config.onSuccess({})).resolves.toBeUndefined()` to the missing-credential test, symmetric with the pass-1 fix on the exchange-failure path.

Verification: `npm run type-check` ✓, `npm test -- exchangeGoogleToken` (19/19) ✓, `npm test -- GoogleOneTap` (10/10) ✓.

### Do not revert (new in this pass)

- The 5xx test locks the `Auth0 returned 503: ...` diagnostic format. If a future refactor changes that prefix shape, this test should fail loudly — do not "fix" the test by loosening the regex.
- The `TypeError`-specific network-error test sits alongside (not replacing) the generic-`Error('boom')` test. Both shapes are intentionally covered. Removing either narrows the contract.
- The `access_token: null` and `access_token: 123` tests lock the production `typeof json.access_token !== 'string'` guard at `exchangeGoogleToken.ts:78`. Deleting the guard will fail these tests — that's the point.
- The missing-credential `resolves.toBeUndefined()` assertion is the same load-bearing One Tap re-prompt contract as the pass-1 fix on the exchange-failure path. Both must remain.

---

## 2026-04-18 — Review pass 3

Four reviewers ran in parallel: code-reviewer, silent-failure-hunter, pr-test-analyzer, comment-analyzer. (type-design-analyzer skipped — no new types since pass 1.) Diff scope: `git diff origin/main...HEAD`.

### Findings

**Critical:**
- (none across any reviewer)

**Important:**
- (none across any reviewer)

All four pass-3 reviewers explicitly verified that pass-1 and pass-2 "Do not revert" items remain in place and reached the same verdict: the PR is clean.

Cross-cutting verifications performed (all pass):
- `useAuth.getToken()` (`src/frontend/src/features/auth/useAuth.ts`) prefers `getAccessTokenSilently()` when `isAuth0Authenticated`, consulting `googleCredential` only as fallback — Auth0 token stored in `googleCredential` is safe coexistence.
- `GoogleOneTap`'s `disabled` predicate already includes `isAuthenticated`, so a Universal-Login user won't trigger an unnecessary exchange.
- `GoogleCredentialContext.readStoredCredential()` parses `exp` from a JWT payload; Auth0 access tokens carry `exp`, so rehydration semantics are unchanged.
- `useAuth.logout()` clears `googleCredential` regardless of source.
- All `getToken()` consumers (`AccountPage`, `useEnabledCompanies`, `useCurrentUser`) treat the token as opaque Bearer; transition-window backend accepts both issuers per PLAN.
- Branch coverage walk: every reachable branch in `exchangeGoogleToken.ts` (15) and `GoogleOneTap.tsx`'s `onSuccess` (3) has at least one test. Pass-2 tests verified to exercise what their names claim.

**Deferred (not fixing this pass — repeats from earlier passes):**
- Same-tab logout race during in-flight exchange: theoretical, no cross-tab `storage` listener exists today either, so the PR doesn't introduce a new silent failure. Worth noting for a future "add storage listener" PR. (agent: silent-failure-hunter)
- `String(err)` non-`Error` fallback branches in both files are practically unreachable. (agent: pr-test-analyzer)
- Test name "does not call setGoogleCredential when credential is missing" undersells the broader contract the test now locks (resolves cleanly + exchange not called). Cosmetic. (agents: pr-test-analyzer, comment-analyzer)
- 5xx test description says "5xx prefix" but the matcher is literal `/Auth0 returned 503: /`. Slightly imprecise; harmless. (agent: comment-analyzer)
- Trim `exchangeGoogleToken` JSDoc / delete `// body wasn't JSON` comment — re-deferred for the third time. (agent: comment-analyzer)

### Conflicts with prior audit

(none — both pass-1 and pass-2 "Do not revert" lists confirmed intact)

### Implementation applied

No code changes required. All four reviewers reached "no Critical, no Important" independently. The test suite is now load-bearing for the Shared Contract. Pass 3 is a clean exit.

### Do not revert (new in this pass)

- (none — pass 3 added no code or tests)
