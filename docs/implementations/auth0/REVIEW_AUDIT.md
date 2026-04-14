# Auth0 PR Review Audit Log

**Purpose:** Running log of review findings on PR #56 (Auth0 + Google One Tap) and the fixes applied. **Read this before proposing changes to the identity model, upsert logic, or JWT routing.** Several decisions here overrode the original PLAN.md design — do not revert them unless you have a concrete new reason. Update this file when you apply a review fix so the next reviewer has context.

---

## 2026-04-13 — Initial review (PR #56)

### Finding 1 — Google One Tap `sub` collided with Auth0 `sub`

**Problem:** `routers/users.py` stored the raw JWT `sub` claim in the DB's `auth0_id` column. Auth0 already prefixes `sub` (`auth0|…`, `google-oauth2|…`), but Google One Tap emits a bare numeric `sub` like `"12345"`. PLAN.md §"Identity resolution challenge" calls for normalizing these to `google|{sub}`, but the implementation didn't do it — so Google One Tap users got bare numeric `auth0_id`s that could collide across providers.

**Fix:** Added `get_normalized_subject(claims)` helper in `src/backend/api/auth/jwt.py`. Router uses it instead of raw `claims["sub"]`. Auth0 subs pass through unchanged; Google One Tap subs (detected by `iss in GOOGLE_ISSUERS`) get a `google|` prefix.

**Do not revert to raw `sub`** — the PLAN's identity-normalization contract depends on this.

### Finding 2 — `email UNIQUE` would 500 on legitimate cross-provider login

**Problem:** `scripts/shared/database.py` declared `auth0_id UNIQUE` and `email UNIQUE`. `user_service.get_or_create_user` only handled `ON CONFLICT (auth0_id)`. A user who first logged in via Auth0 (`sub=auth0|a`) then via Google One Tap (`sub=google|x`) with the same verified email would hit `psycopg2.errors.UniqueViolation` on email → 500.

**Initial bad fix proposed and rejected:** Drop `UNIQUE(email)` so both rows could coexist. **Rejected** because it silently fragments one human across rows — hides a real identity-model bug behind "no crash." See memory: `feedback_correctness_over_dont_crash.md`.

**Final fix (correctness-first):**
- `email` stays `UNIQUE NOT NULL`. Email (verified by the identity provider) is the stable human identifier. One row per human.
- `auth0_id` **loses `UNIQUE`**. It now tracks the most-recent login provider's subject — which legitimately changes when a user switches providers or updates their email in their provider account. The `idx_users_{env}_auth0_id` index remains (non-unique) for `update_user` lookups.
- `get_or_create_user` upsert key changed from `ON CONFLICT (auth0_id)` → `ON CONFLICT (email)`. SET clause now updates `auth0_id`, `given_name`, `family_name`, `picture_url`, `updated_at`. `display_name` is still excluded — user customizations survive provider switches.
- Router (`GET /api/users`) now returns **401 if the token is missing `email`** (in addition to missing `sub`). Previously defaulted to `""`, which would collide on the UNIQUE constraint for every tokenless user.

**Consequence — intentional:** The DB only records the *most recent* provider. There is no per-row history of "this user has both Auth0 and Google identities." If that history is ever needed (e.g., "sign in with the method you used last time" UX), add a `user_identities` join table; do **not** re-introduce `UNIQUE(auth0_id)` or duplicate rows per provider.

**Do not revert** any of: `ON CONFLICT (email)`, dropped `UNIQUE(auth0_id)`, or the missing-email 401, without a concrete replacement design.

### Schema delta vs PLAN.md

PLAN.md §"Database schema" (line ~60) shows `auth0_id TEXT NOT NULL UNIQUE`. **Current code drops the UNIQUE.** PLAN.md is out of date on this point. Either update the PLAN or treat this audit log as the source of truth for the schema decision.

### Tests added

- `test_auth.py::TestGetNormalizedSubject` — 5 cases (Auth0 pass-through, Google HTTPS issuer, Google bare issuer, missing sub, Auth0-federated `google-oauth2|…` pass-through).
- `test_users_router.py::TestAuthRequired::test_get_me_without_email_claim_returns_401`
- `test_users_router.py::TestGoogleOneTap::test_google_one_tap_sub_is_prefixed`
- `test_users_router.py::TestGoogleOneTap::test_second_provider_login_merges_into_one_row`
- `test_user_service.py::TestGetOrCreateUser::test_cross_provider_login_merges_to_one_row`
- `test_user_service.py::TestGetOrCreateUser::test_concurrent_first_login_is_idempotent`
- Rewrote `test_upsert_updates_token_fields_on_conflict` to reflect the email-keyed conflict and `auth0_id` update semantics.

**121 backend tests passing.**

### Medium/Low review findings deferred (follow-up)

Intentionally out of scope for the fix commit — track here so later reviewers know they were seen:
- `_jwks_client` singleton never reset on settings change (test-only concern).
- `api/utils/backendUrl.ts` — tighten `host.startsWith('localhost')` to exact match.
- `auth/dependencies.py` — `logger.warning("Invalid JWT token: %s", exc)` could echo PyJWT exception strings; prefer `type(exc).__name__`.
- `auth/jwt.py` / `google_jwt.py` — drop `exc_info=True` on per-request token-invalid warnings (log noise).
- `auth/jwt.py:65-67` — `algorithms=["RS256"]` on the unverified decode is cosmetic; simplify or comment.
- `useCurrentUser.ts` — add abort/cancel on sign-out mid-fetch.

---

## 2026-04-14 — Second review pass (PR #56, post-identity-fix)

Ran four review agents in parallel (code-reviewer, silent-failure-hunter, pr-test-analyzer, type-design-analyzer) against the state after commit `aa701b5` ("Fix identity model: email-keyed upsert, prefix Google One Tap sub"). All agents were briefed with PLAN.md and the 2026-04-13 audit entry above and told to honor the "do not revert" list. Full plan file: `~/.claude/plans/memoized-sleeping-journal.md`.

### New findings (not in prior audit)

**Critical — to fix before merge:**
- `useCurrentUser.ts:12-33` — `loadUser` has no `AbortController`. A fetch started before sign-out can resolve after and call `setUser(fetchedUser)`, repopulating stale profile onto a signed-out session. UserMenu + AccountPage both read this hook → real UX/security bug. (Previously deferred; promoted to critical by two agents independently.)
- `api/users.ts:40-48` — `fetch` rejection (Railway down, DNS) reports `500 "Failed to fetch from backend"` with no `console.error`. Should be 502/503 + server-side log.
- `vercel.json:64-82` — CORS origin is hardcoded to prod (good, not wildcard), but (a) `Access-Control-Allow-Credentials` is absent (silently breaks any future `credentials: 'include'` fetch) and (b) `*-git-*.vercel.app` previews will fail CORS. Document decision or add reflective origin.

**Important:**
- `routers/users.py:42-44, 62-64` — `except Exception` catches `HTTPException` too; will convert a future 403 into a generic 500. Narrow to `(psycopg2.Error, RuntimeError)`.
- `auth/jwt.py:72-77` — `validate_token` dispatcher: if `issuer in GOOGLE_ISSUERS` but `settings.google_client_id` is empty, silently falls through to `_validate_auth0_token` and produces a confusing `InvalidIssuer` — config error masquerades as auth error. Split the condition; fail loudly on misconfig.
- `auth/dependencies.py:37-39` — `PyJWKClientError` (IdP outage, JWKS fetch fail) wrapped as `401 "Invalid token"`. Should be 503 with `logger.exception`.
- `services/user_service.py` — `update_user` is keyed by `auth0_id`, which is now mutable/non-unique per the first audit. Works today because `GET /api/users` resyncs it first, but a client that only calls `PUT` after a cross-device provider switch will silently 404. Change key to `email` (the stable identifier per audit decision).
- `useAuth.ts:42-47` — `login()` swallows `loginWithRedirect` failure with `console.error` and resolves; caller can't surface pop-up-blocker / CSP / misconfig errors. Rethrow.
- `forwardResponse.ts:9-11` — `.json()` on an empty body with `content-type: application/json` (e.g. a 204) throws; gets mislabeled as "Failed to fetch from backend" by the outer catch in `users.ts`. Read text first, tolerant parse, preserve upstream status.
- `config/auth.ts:13` — `redirectUri: ... || window.location.origin` evaluated at module import. Non-jsdom test imports or any SSR path crashes during bundle eval. Guard or compute lazily in `AuthProviders`.

**Test gaps:**
- `test_auth.py` — No test signs a token with a *different* RSA keypair and asserts rejection. This is the load-bearing security invariant of the entire auth stack. Add one.
- `test_auth.py::TestTokenDispatch` — Both validators use the same mocked JWKS client; a bug where `validate_token` wrongly routed an issuer would still pass. Use `patch` as a spy to assert which validator was called.

**Type-design suggestions (structural, not blocking):**
- `UserResponse.auth0_id` is misleading post-audit — it tracks the *most recent* provider subject, not specifically Auth0. Consider renaming to `provider_subject` / `providerSubject` at the model/boundary (DB column can stay as `auth0_id` to avoid migration).
- `useAuth()` return type doesn't express "if `isAuthenticated` then `getToken` succeeds" — currently enforced via runtime `throw new Error('Not authenticated')`. A discriminated union `{ status: 'loading' | 'anonymous' | 'authenticated', ... }` would remove the runtime guard.
- `AUTH_CONFIG.isEnabled` is a peer field to `domain`/`clientId` — doesn't narrow them to non-empty for downstream callers.
- `UserResponse` name fields typed `str | None` — leaks DB nullability. `given_name`/`family_name`/`picture_url` are effectively always present from IdPs; only `display_name` being nullable is domain-meaningful.

### Confirmations (explicitly re-reviewed, still OK)

- Missing-email 401 path in `routers/users.py:30-31` — correct, do not relax.
- `ON CONFLICT (email)` in `get_or_create_user` — correct, do not revert.
- `get_normalized_subject` — correct, Google One Tap still requires the `google|` prefix.
- `GoogleOneTap.tsx` `onError: console.warn` — intentional per PLAN.md §293.
- `get_optional_user` raising 401 on invalid token (not anonymizing) — correct: a bad token is not an anonymous user.
- JWKS singleton with double-checked locking in `jwt.py:18-36` and `google_jwt.py:19-35` — thread-safe, correct.
- Provider nesting in `main.tsx` (GoogleOAuthProvider → Auth0Provider → GoogleCredentialProvider) — correct.
- `ConfigDict(alias_generator=to_camel)` on both `UserResponse` and `UserUpdateRequest` — consistent with backend CLAUDE.md convention.
- All identity-resolution tests added in the first audit pass verified present and asserting the right invariants (`test_cross_provider_login_merges_to_one_row`, `test_concurrent_first_login_is_idempotent`, `test_get_me_without_email_claim_returns_401`, `TestGetNormalizedSubject` 5 cases).

### Already-deferred items re-surfaced (not re-adding to plan)

- `backendUrl.ts:8` `host.startsWith('localhost')` too loose — still in deferred list.
- Log noise (`exc_info=True` on per-request token-invalid, `type(exc).__name__` for PyJWT exception string echo) — still in deferred list.
- JWKS singleton reset on settings change (test-only concern) — still in deferred list.

---

## 2026-04-14 — Design reversal: restore `UNIQUE(auth0_id)`, replace email-only upsert with two-key lookup

**This entry overrides the 2026-04-13 Finding 2 decision to drop `UNIQUE(auth0_id)`.** Per the audit's own guidance ("If you want to revert any decision here, write a new entry in this file explaining why the original reasoning no longer holds"), here is that entry.

### Why the 2026-04-13 reasoning doesn't hold

The 2026-04-13 audit dropped `UNIQUE(auth0_id)` to avoid a `UniqueViolation` when a user's email changes at the IdP:
- Existing row: `auth0_id = "auth0|aaa"`, `email = a@example.com`
- Login with new email: token has `sub = auth0|aaa`, `email = b@example.com`
- `INSERT ... ON CONFLICT (email)` → no `b@example.com` conflict → `INSERT` attempts a new row with `auth0_id = auth0|aaa` → **crash** (old row owns that auth0_id).

The prior audit chose to drop `UNIQUE(auth0_id)` so the `INSERT` would succeed and a duplicate row would be created. **That trades a loud crash for a silent duplicate**, which directly contradicts the repo's "Correctness over don't crash" principle (see `feedback_correctness_over_dont_crash.md`). One human now spans two rows and we have no signal that the model is broken.

### Replacement design

The real problem was the upsert logic, not the `UNIQUE` constraint. The email-only `ON CONFLICT` can't express "match by either stable identifier." Replace it with an explicit lookup-then-update/insert:

```python
def get_or_create_user(conn, env, auth0_id, email, given_name, family_name, picture_url):
    # Look up by EITHER stable identifier — handles both cross-provider merge
    # (same email, different auth0_id) and IdP email change (same auth0_id,
    # different email). If both match the same row, great. If they match
    # different rows, that's a real ambiguity — raise; don't silently merge.
    existing = SELECT id, auth0_id, email FROM users
               WHERE auth0_id = %s OR email = %s
    if len(existing) > 1:
        raise RuntimeError(f"Ambiguous identity: auth0_id={auth0_id} and email={email} map to different rows")
    if existing:
        UPDATE users SET auth0_id = %s, email = %s, given_name = %s, ...
        WHERE id = %s
        return that row
    # No match → INSERT new row
```

With this logic:
- **Cross-provider merge** (Auth0 → Google One Tap, same email): lookup matches by email → `UPDATE` sets new `auth0_id`. One row. Both UNIQUEs hold.
- **IdP email change** (same auth0_id, new email): lookup matches by auth0_id → `UPDATE` sets new `email`. One row. Both UNIQUEs hold.
- **Truly new user**: no match → `INSERT`. Both UNIQUEs hold.
- **Genuinely ambiguous** (two separate humans whose identities got tangled by a prior bug): `RuntimeError` — loud, diagnosable, doesn't fragment further.

### Schema changes

1. Restore `auth0_id TEXT NOT NULL UNIQUE` in `scripts/shared/database.py::init_schema`. Keep `email TEXT NOT NULL UNIQUE`.
2. Keep the non-unique `idx_users_{env}_auth0_id` index — redundant with `UNIQUE` but harmless; can drop later.
3. **Migration note for existing deployments:** If any environment has already run with the 2026-04-13 schema (no `UNIQUE(auth0_id)`), duplicate rows may exist. Before applying the `UNIQUE(auth0_id)` constraint, run a dedupe query: keep the row with the most-recent `updated_at` for each `auth0_id`, delete the rest. No production deployment yet, so local/CI can just drop-and-recreate the table.

### Upsert semantics delta vs 2026-04-13

| Concern | 2026-04-13 decision | 2026-04-14 decision |
|---|---|---|
| `UNIQUE(auth0_id)` | Dropped | **Restored** |
| `UNIQUE(email)` | Kept | Kept (unchanged) |
| Upsert key | `ON CONFLICT (email)` | Two-key SELECT lookup, then UPDATE or INSERT |
| Email change at IdP | Silent duplicate row (bug) | `UPDATE` existing row's email (correct) |
| Cross-provider merge | `UPDATE` via email conflict | `UPDATE` via email match in lookup |
| Ambiguous identity | N/A (wouldn't be detected) | `RuntimeError` — surface the bug |

### Concurrency note

The two-key SELECT-then-UPDATE/INSERT is not atomic. Under concurrent first-login from two processes, both could SELECT empty, both could INSERT, and the second INSERT would fail on `UNIQUE(email)` or `UNIQUE(auth0_id)`. Handle by wrapping in a transaction with `SERIALIZABLE` isolation, **or** catch `psycopg2.errors.UniqueViolation` and retry the SELECT+UPDATE once. The existing `test_concurrent_first_login_is_idempotent` must be updated to assert the retry path.

### Tests to add/update

- Update `test_user_service.py::test_upsert_updates_token_fields_on_conflict` — now traverses the two-key lookup branch.
- New: `test_idp_email_change_updates_existing_row` — same `auth0_id`, new `email` → one row, new email.
- New: `test_ambiguous_identity_raises` — seed two rows, one matches by `auth0_id`, other by `email` → `RuntimeError`.
- Update `test_concurrent_first_login_is_idempotent` — assert the `UniqueViolation`-retry path produces one row.
- Backend integration: `test_users_router.py::test_second_provider_login_merges_into_one_row` should still pass (cross-provider merge still produces one row).

### Implementation applied (2026-04-14)

- `scripts/shared/database.py` — restored `auth0_id TEXT NOT NULL UNIQUE`.
- `src/backend/api/services/user_service.py` — rewrote `get_or_create_user` to use two-key SELECT lookup, UPDATE-or-INSERT, ambiguous-match `RuntimeError`, and one-retry `UniqueViolation` handler. Extracted `_lookup_and_upsert` helper for the retry loop.
- `src/backend/api/services/user_service.py` — changed `update_user` signature from `auth0_id` to `email`.
- `src/backend/api/routers/users.py` — `PUT /api/users` now passes `email` to `update_user` and 401s when the token lacks an `email` claim.
- Tests: renamed `test_upsert_updates_token_fields_on_conflict` → `test_upsert_updates_token_fields_on_email_match`; added `test_idp_email_change_updates_existing_row`, `test_ambiguous_identity_raises`, `test_unique_violation_retries_once`, `test_put_me_without_email_claim_returns_401`. Updated `TestUpdateUser` to use `email=` keyword. **125 backend tests passing** (was 121).

### Do not revert (new)

- Do not re-drop `UNIQUE(auth0_id)` — the email-change edge case is correctly handled by the two-key lookup, not by relaxing constraints.
- Do not switch back to `ON CONFLICT (email)` as the primary upsert path — it can't express the IdP-email-change case.
- Do not catch `RuntimeError` from `get_or_create_user` to paper over ambiguous-identity cases — the raise is load-bearing.

### Still do not revert (from 2026-04-13)

- `UNIQUE(email)` stays.
- `get_normalized_subject` stays — Google One Tap tokens still need the `google|` prefix.
- Missing-email 401 in `routers/users.py` stays.

---

## Guidance for subsequent review agents

**Authoritative state (as of 2026-04-14 design reversal):**
- `UNIQUE(email)` and `UNIQUE(auth0_id)` are BOTH enforced.
- `get_or_create_user` uses a two-key SELECT lookup (match by `auth0_id` OR `email`), then UPDATE-or-INSERT. Not `ON CONFLICT`.
- `get_normalized_subject` prefixes Google One Tap subs with `google|` — required; don't remove.
- `routers/users.py` 401s on missing `sub` or `email` claims — don't default to `""`.
- Ambiguous identity (two rows match the lookup) raises `RuntimeError` — don't catch-and-ignore.

**Behavior:**
- Do not switch the upsert to `ON CONFLICT (email)` or `ON CONFLICT (auth0_id)` — both single-key paths miss one of the legitimate cases (cross-provider merge vs IdP email change). The two-key lookup handles both.
- Do not drop either `UNIQUE` constraint. If you hit an unexpected `UniqueViolation` in concurrent first-login, fix it by retry-on-conflict inside `get_or_create_user`, not by relaxing the schema.
- Do not drop the `get_normalized_subject` indirection just because Auth0 tokens work without it — Google One Tap tokens need it.

**Process:**
- If you want to revert any decision here, write a new entry in this file explaining why the original reasoning no longer holds. Don't silently flip it.
- When adding a new review pass, append a new dated section rather than editing prior entries; this is an audit log.
