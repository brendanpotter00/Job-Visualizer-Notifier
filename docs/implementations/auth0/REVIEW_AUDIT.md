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

## Guidance for subsequent review agents

- Do not "simplify" by re-adding `UNIQUE(auth0_id)` or switching the upsert back to `ON CONFLICT (auth0_id)` — you will re-introduce the bug tracked above.
- Do not drop the `get_normalized_subject` indirection just because Auth0 tokens work without it — Google One Tap tokens need it.
- Do not relax the missing-email 401 back to a `""` default — empty-string collisions on `UNIQUE(email)` are worse than a 401.
- If you want to revert any decision here, write a new entry in this file explaining why the original reasoning no longer holds. Don't silently flip it.
- When adding a new review pass, append a new dated section rather than editing prior entries; this is an audit log.
