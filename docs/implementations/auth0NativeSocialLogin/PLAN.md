# Auth0 Native Social Login (Token Exchange) Plan

## Context

The app currently authenticates users two ways and the second one is invisible to the Auth0 dashboard:

1. **Auth0 Universal Login** (username/password and Auth0's own "Sign in with Google" social connection) — produces tokens with issuer `https://<auth0-domain>/` and `sub` like `auth0|...` or `google-oauth2|...`. These users appear in the Auth0 dashboard and the backend validates their tokens via Auth0 JWKS in `src/backend/api/auth/jwt.py`.
2. **Google One Tap directly** (`@react-oauth/google` `useGoogleOneTapLogin` in `src/frontend/src/features/auth/GoogleOneTap.tsx` → raw Google ID token sent as the Bearer token) — produces tokens with issuer `https://accounts.google.com` and a bare numeric `sub`. The backend validates these via Google's JWKS in `src/backend/api/auth/google_jwt.py`. The `validate_token` dispatcher in `jwt.py` routes by issuer; `get_normalized_subject` rewrites the bare Google sub to `google|<numeric>`. **These users never touch Auth0 and are invisible in the Auth0 dashboard.**

**Goal:** route every Google One Tap sign-in through Auth0 so all users show up in the Auth0 dashboard, while keeping the One Tap UX unchanged for the user.

**Approach — Auth0 Native Social Login (token exchange).** The frontend keeps the One Tap prompt. When the One Tap callback fires with a Google ID token, the frontend POSTs that ID token to Auth0's `/oauth/token` endpoint with the token-exchange grant. Auth0 verifies the Google token, provisions/links a user under its Google social connection (so the user appears in the dashboard), and returns Auth0-issued tokens (access token + ID token + expires_in). The frontend then uses the Auth0 access token for backend calls.

`@auth0/auth0-react` does not expose a method for the token-exchange grant — the frontend must call `/oauth/token` via `fetch` directly. The cleanest place to integrate is `GoogleOneTap.tsx`'s `onSuccess`: instead of storing the raw Google credential into the existing `GoogleCredentialProvider`, perform the exchange and store the **Auth0 access token** in the same provider (renamed conceptually to "exchanged token"). Downstream `useAuth.getToken()` and the backend stay unchanged in shape — the bytes flowing over the wire are now Auth0-issued, not Google-issued. This minimizes blast radius vs. shoehorning a parallel session into the Auth0 SDK's internal cache (which is undocumented and would break on SDK upgrade).

**Existing-user migration (NO data migration script).** Production `users_prod` currently has 5 rows. 4 have `auth0_id = "google|<numeric_google_sub>"` (the `get_normalized_subject` prefix for One Tap users). After the cutover, the same humans sign in via the new flow and Auth0 mints an access token whose `sub` is `google-oauth2|<same_numeric_google_sub>`. The existing upsert in `src/backend/api/services/user_service.py::get_or_create_user` already does `SELECT id FROM users WHERE auth0_id = %s OR email = %s`, so on the first new login the row matches by **email**, gets UPDATEd with the new `auth0_id` (`google|...` → `google-oauth2|...`), and the row's primary key `id` is preserved. Foreign keys in `user_enabled_companies_{env}` (`user_id` references `users.id`) stay intact because `id` does not change. **No data migration script is needed; first-sign-in is the migration.**

**Transition window.** Users with active sessions hold raw Google ID tokens that the backend must keep accepting until those sessions die. The cutover unit ships the new frontend exchange + Auth0 dashboard config; the Google JWKS validator removal is deliberately a separate later unit. The user can choose to merge the removal as soon as a representative window has elapsed (e.g. 24h after deploy is enough — Google ID tokens expire in ~1h and the persisted credential in `GoogleCredentialContext` is checked against `exp` on read).

**Auth0 dashboard prerequisites (manual, must be done before the cutover unit's deploy).** The plan does not automate dashboard config; it just flags it.
- **Enable Native Social Login on the tenant.** Auth0 Dashboard → Authentication → Social → Google → Settings → enable "Allow Native Social Login" (controls whether Auth0 accepts the Google subject token type for that connection).
- **Enable the token-exchange grant on the SPA application.** Auth0 Dashboard → Applications → (the SPA from `docs/implementations/auth0/PLAN.md` Deployment Step 1) → Settings → Advanced → Grant Types → enable `urn:ietf:params:oauth:grant-type:token-exchange`. Without this, `/oauth/token` returns `unauthorized_client`.
- **Confirm the Google social connection is enabled and uses the same Google Client ID as `VITE_GOOGLE_CLIENT_ID`.** Already done in `docs/implementations/auth0/PLAN.md` Deployment Step 4 — re-verify before cutover.
- **Set the API access-token lifetime to 7 days.** Auth0 Dashboard → APIs → (the audience matching `AUTH0_AUDIENCE`) → Settings → "Token Expiration (Seconds)" = `604800`. The cached One Tap token's apparent session length comes from this `exp`; the existing `GoogleCredentialContext.readStoredCredential()` honors it as-is, so no code change is needed beyond Unit 1.

**Why this plan splits cleanly into sequential units.** Backend changes (none, beyond reading) precede frontend exchange wiring; frontend exchange wiring lands behind a feature decision (always exchange in `GoogleOneTap.tsx`); test updates ride with the cutover unit; manual E2E is its own unit so an interactive verification step can be reviewed and signed off; the JWKS removal is the final independently-mergeable unit.

---

## Shared Contracts (frozen — all units must match)

### Auth0 token-exchange HTTP request (frontend → Auth0)

```
POST https://${VITE_AUTH0_DOMAIN}/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Atoken-exchange
&subject_token_type=http%3A%2F%2Fauth0.com%2Foauth%2Ftoken-type%2Fgoogle-id-token
&subject_token=<google_id_token_from_one_tap>
&audience=${VITE_AUTH0_AUDIENCE}
&scope=openid%20profile%20email
&client_id=${VITE_AUTH0_CLIENT_ID}
```

Notes:
- Body is `application/x-www-form-urlencoded`, not JSON. Use `URLSearchParams`.
- No `client_secret` — this is the public SPA client. The SPA's existing `VITE_AUTH0_CLIENT_ID` is reused; no new env var is required.
- `audience` MUST match the Auth0 API identifier (`VITE_AUTH0_AUDIENCE`), otherwise Auth0 returns an opaque token instead of a JWT and the backend will reject it with `InvalidTokenError`.
- Response on success (200):
  ```json
  {
    "access_token": "eyJ...",
    "id_token":     "eyJ...",
    "scope":        "openid profile email",
    "expires_in":   86400,
    "token_type":   "Bearer"
  }
  ```
- Response on failure (4xx): `{ "error": "...", "error_description": "..." }` — surface `error_description` to the console, do not surface to the user verbatim (may leak config detail).

### Stored token shape (frontend, replaces raw Google credential)

`GoogleCredentialContext` currently stores a raw Google ID token string. After this feature it stores the Auth0 access token returned from the exchange. The storage shape stays a single string (the Auth0 access token), because:
- `useAuth.getToken()` and downstream backend calls already treat the stored value as an opaque Bearer string.
- The `exp`-based localStorage rehydration in `GoogleCredentialContext.readStoredCredential()` continues to work — Auth0 access tokens are JWTs with an `exp` claim.
- Renaming the context/key is deferred to keep the diff small and the rollback story clean. The semantic meaning ("the bearer token to send to the backend on behalf of the One Tap user") is preserved.

The Auth0 `id_token` and `expires_in` from the response are **not stored** — the access token's own `exp` claim is the source of truth, and the ID token is only useful for displaying profile info, which the backend `/api/users` endpoint already round-trips.

### Environment variables

| Var | Side | Purpose | Status |
|---|---|---|---|
| `VITE_AUTH0_DOMAIN` | frontend | Token-exchange URL host (`https://${VITE_AUTH0_DOMAIN}/oauth/token`) | already exists |
| `VITE_AUTH0_CLIENT_ID` | frontend | `client_id` form param in the exchange | already exists |
| `VITE_AUTH0_AUDIENCE` | frontend | `audience` form param — must match backend's `AUTH0_AUDIENCE` | already exists |
| `VITE_GOOGLE_CLIENT_ID` | frontend | Google One Tap initialization (unchanged) | already exists |
| `AUTH0_DOMAIN` | backend | Auth0 JWKS URL + issuer for validation | already exists |
| `AUTH0_AUDIENCE` | backend | JWT `aud` claim verification | already exists |
| `GOOGLE_CLIENT_ID` | backend | Google JWKS validation — kept until JWKS removal unit | already exists, removed in final unit |

**No new env vars are added.** The exchange reuses the existing SPA client (`VITE_AUTH0_CLIENT_ID`).

### Backend identity contract (unchanged shape, document the mutation)

After cutover, every token reaching the backend has issuer `https://<auth0-domain>/` and `sub = "google-oauth2|<numeric>"` (Auth0's prefix for federated Google identities). The first time a previously-One-Tap user signs in:

1. `validate_token` (`src/backend/api/auth/jwt.py`) routes via the Auth0 branch (issuer match), returns claims with `sub = "google-oauth2|<numeric>"`.
2. `get_normalized_subject(claims)` returns the sub unchanged (only the Google-issuer branch rewrites; Auth0 issuer falls through).
3. `get_or_create_user(conn, env, auth0_id="google-oauth2|<numeric>", email=<user_email>, ...)` runs the lookup `WHERE auth0_id = %s OR email = %s`:
   - The `auth0_id` clause finds nothing (the row holds `google|<numeric>`, not `google-oauth2|<numeric>`).
   - The `email` clause matches the existing row (verified Google email is stable).
   - Single match → UPDATE branch runs → row's `auth0_id` flips to `google-oauth2|<numeric>` while `id`, `display_name`, and FK relations are preserved.
4. Subsequent logins find by `auth0_id` directly.

No DB schema change. No data migration script. The only behavioral guarantee that needs to hold is that the email in the Auth0-issued token equals the email previously stored — which is true because Auth0 federates the same verified Google email.

---

## Work Units

### Unit 1 — Frontend: Auth0 token exchange in GoogleOneTap (cutover, with tests)

**Status:** DONE
**Prerequisites:** Auth0 dashboard configuration completed (Native Social enabled on the Google connection; token-exchange grant enabled on the SPA application). See Context section.

**Owned files (create):**
- `src/frontend/src/features/auth/exchangeGoogleToken.ts` — the `fetch` wrapper that POSTs to `/oauth/token` and returns the Auth0 access token. Pure function, easy to unit-test.
- `src/frontend/src/__tests__/features/auth/exchangeGoogleToken.test.ts` — tests for success, 4xx error mapping, network error, missing config.

**Shared-file edits:**
- `src/frontend/src/features/auth/GoogleOneTap.tsx` — in `onSuccess`, call `exchangeGoogleToken(googleCredential, AUTH_CONFIG)` then `setGoogleCredential(<auth0_access_token>)`. Keep `auto_select`, the disabled gating, and the rest of the file shape untouched. On exchange failure, `console.warn` and do **not** store any credential — the user sees the One Tap prompt re-appear.
- `src/frontend/src/__tests__/features/auth/GoogleOneTap.test.tsx` — update the `onSuccess` test cases:
  - The current test asserts `setGoogleCredential` is called with the raw Google JWT. After this change it must be called with the Auth0 access token returned by a mocked `exchangeGoogleToken`.
  - Add: when `exchangeGoogleToken` rejects, `setGoogleCredential` is NOT called and a warning is logged.
  - Add: the existing `disabled` cases (no client id, authenticated, loading) still hold — exchange is only attempted from inside `onSuccess`, which Google will not invoke when disabled.

**Done when:**
- `cd src/frontend && npm run type-check` is clean.
- `cd src/frontend && npm test -- exchangeGoogleToken` passes.
- `cd src/frontend && npm test -- GoogleOneTap` passes including the updated assertions.
- `cd src/frontend && npm run build` succeeds.

**Implementation notes (not contract):**
- `exchangeGoogleToken` signature: `async function exchangeGoogleToken(googleIdToken: string, config: AuthConfig): Promise<string>` — returns the Auth0 access token on success, throws `Error` with the Auth0 `error_description` on failure.
- Use `URLSearchParams` to build the body. Set `Content-Type: application/x-www-form-urlencoded`.
- Surface `response.status` and the parsed `error_description` in the thrown `Error.message` for diagnostics — these go to the console, not the user.

---

### Unit 2 — Manual E2E verification in dev (cutover sign-off)

**Status:** TODO
**Prerequisites:** Unit 1 merged to the feature branch; Auth0 dashboard configuration verified; backend already accepts both Auth0 and Google tokens (no backend change required for this unit).

**Owned files:** none (verification-only).

**Tasks:**
1. `npm run dev:vercel` and start the backend per root `CLAUDE.md`.
2. Open a private window, sign out of any existing session, and clear `localStorage` for the dev origin (purges any persisted raw Google credential from before).
3. Wait for the One Tap prompt; click "Continue as <Name>".
4. Inspect DevTools → Network → confirm a `POST https://<dev-auth0-domain>/oauth/token` returns 200 with an `access_token`.
5. Inspect Application → LocalStorage → `jvn.googleCredential.v1` now contains an Auth0-issued JWT (decode at jwt.io; `iss` should be `https://<dev-auth0-domain>/`, `sub` should start with `google-oauth2|`).
6. Confirm `/api/users` request to the backend uses that Auth0 token as the Bearer and returns the user row. For a previously-One-Tap user, query the DB: `SELECT auth0_id FROM users_local WHERE email = '<that_email>'` and confirm it has flipped from `google|<numeric>` to `google-oauth2|<numeric>` while `id` is unchanged.
7. Auth0 Dashboard → User Management → Users → confirm the user is now listed (this is the whole point of the change).
8. Sign out, sign back in via the Auth0 redirect flow ("Sign In" button) — confirm same `id`, no duplicate row.

**Done when:**
- DevTools shows the exchange POST succeeding.
- The DB row's `auth0_id` migrated as expected for at least one previously-One-Tap test account.
- The user appears in the Auth0 dashboard.
- Sign-out / sign-in via the Auth0 redirect flow finds the same row (no duplicate).

---

### Unit 3 — Production cutover (deploy + smoke test)

**Status:** TODO
**Prerequisites:** Unit 1 merged to `main`; Unit 2 verification signed off; production Auth0 dashboard configured (Native Social enabled, token-exchange grant enabled on the prod SPA app, Google social connection enabled with the same Google Client ID as `VITE_GOOGLE_CLIENT_ID`).

**Owned files:** none (deploy-only).

**Tasks:**
1. Merge feature branch → `main`. Vercel auto-deploys frontend; Railway auto-deploys backend (no backend change shipped yet, but Railway redeploys on every `main` push — confirm health stays green).
2. After Vercel deploy completes, hit the production frontend in a private window. Sign in via One Tap.
3. DevTools Network: confirm the `POST` to `/oauth/token` succeeds against the production Auth0 tenant.
4. Query prod DB: `SELECT auth0_id, email FROM users_prod ORDER BY updated_at DESC LIMIT 5;` — confirm at least one row's `auth0_id` has flipped from `google|...` to `google-oauth2|...` after the test sign-in.
5. Auth0 Dashboard (production tenant) → Users → confirm the test account is listed.
6. Spot-check the other 3 prod users: as each of them signs in over the next transition window, their rows will flip. Re-run the DB query after a day to verify migration progress.

**Done when:**
- Production frontend exchange succeeds end-to-end.
- The test account's `users_prod` row migrated cleanly.
- The test account appears in the Auth0 production dashboard.
- Railway and Vercel logs are clean.

---

### Unit 4 — Remove Google JWKS validator (final, independently mergeable)

**Status:** TODO
**Prerequisites:** Unit 3 deployed AND a transition window has elapsed (recommendation: at least 24h in production — long enough that any pre-cutover persisted Google credentials have expired per their `exp` claim, since Google ID tokens are ~1h-lived). The user may merge this unit any time after the window; it is intentionally separate from cutover so a rollback to "still accept Google tokens" remains possible during the window.

**Owned files (delete):**
- `src/backend/api/auth/google_jwt.py`

**Shared-file edits:**
- `src/backend/api/auth/jwt.py`:
  - Remove the `from .google_jwt import GOOGLE_ISSUERS` import.
  - In `validate_token`, remove the issuer-routing block (the `unverified` decode + `if issuer in GOOGLE_ISSUERS:` branch + the `RuntimeError` config guard). The function body collapses to `return _validate_auth0_token(token)`. Optionally inline `_validate_auth0_token` into `validate_token` since there is now only one path.
  - In `get_normalized_subject`, remove the Google-issuer branch (the `if issuer in GOOGLE_ISSUERS: return f"google|{sub}"` block). The function returns the raw `sub` unchanged.
- `src/backend/api/config.py`: remove the `google_client_id` setting and any related comment.
- `src/backend/CLAUDE.md`: remove the `GOOGLE_CLIENT_ID` row from the env vars table and the `auth/google_jwt.py` line from the file tree.
- `src/backend/api/tests/test_auth.py`: delete Google-related test classes, fixtures, helpers, and constants (`TestValidateGoogleToken`, the `_mock_google_jwks_client` autouse fixture, `_google_payload`, `TEST_GOOGLE_CLIENT_ID`, `TEST_GOOGLE_ISSUER`, the Google cases in `TestTokenDispatch`, the `test_google_missing_client_id_raises` case in `TestEnvVarGuards`, and the `test_google_one_tap_sub_is_prefixed_*` cases in `TestGetNormalizedSubject`).

**Railway env var cleanup (post-merge):**
- After merge and successful deploy, remove `GOOGLE_CLIENT_ID` from Railway. Optional but tidy. Backend will ignore the var either way after this unit ships.

**Done when:**
- `cd src/backend && pytest api/tests/test_auth.py -v` passes (with all Google cases removed).
- `cd src/backend && pytest -v` passes (full suite — confirms nothing else imported from `google_jwt`).
- `cd src/backend && python -c "from api.auth.jwt import validate_token, get_normalized_subject"` succeeds (smoke import).
- `grep -r 'google_jwt' src/backend` returns no matches.
- `grep -r 'GOOGLE_CLIENT_ID\|google_client_id' src/backend` returns no matches.
- After Railway redeploy: a manual sign-in (One Tap → exchange → Auth0 token → backend) still succeeds end-to-end.

---

## Critical files

| File | Unit | Edit type |
|---|---|---|
| `src/frontend/src/features/auth/exchangeGoogleToken.ts` | 1 | **new file** |
| `src/frontend/src/__tests__/features/auth/exchangeGoogleToken.test.ts` | 1 | **new file** |
| `src/frontend/src/features/auth/GoogleOneTap.tsx` | 1 | edit `onSuccess` |
| `src/frontend/src/__tests__/features/auth/GoogleOneTap.test.tsx` | 1 | update `onSuccess` assertions |
| `src/backend/api/auth/google_jwt.py` | 4 | **delete** |
| `src/backend/api/auth/jwt.py` | 4 | strip Google branch |
| `src/backend/api/config.py` | 4 | remove `google_client_id` |
| `src/backend/api/tests/test_auth.py` | 4 | delete Google test classes/fixtures |
| `src/backend/CLAUDE.md` | 4 | docs update |

---

## Non-goals (explicitly out of scope)

- **Removing `@react-oauth/google` from the frontend.** One Tap UI is still served by Google Identity Services; only the bytes the backend sees change.
- **Renaming `GoogleCredentialContext` / its localStorage key.** The semantic meaning ("Bearer token for One Tap users") is preserved; rename is a follow-up if desired.
- **Renaming the DB column `auth0_id`.** The column already holds Auth0 subs for Universal-Login users today and will hold Auth0 subs for One Tap users after cutover. The name was always slightly inaccurate; this plan does not change it.
- **Linking pre-cutover `google|<sub>` rows by anything other than email.** The `OR auth0_id` lookup will find them by email on first new sign-in. If a user's verified email changed at Google between the last Google-direct sign-in and the first Auth0-mediated sign-in, they would create a duplicate row — judged not worth defending against at 5 production rows.
- **Auth0 Management API "link accounts" calls.** Auth0's Native Social provisioning creates the user under the Google connection automatically; explicit account linking is unnecessary for the migration described here.
- **Server-side token exchange.** This stays a public-client SPA flow; introducing a backend-mediated exchange would add a secret-management requirement for no benefit at this app's scale.
- **Removing `@auth0/auth0-react`.** Universal Login is unchanged; the SDK still owns its session. Only the One Tap path is rerouted.
