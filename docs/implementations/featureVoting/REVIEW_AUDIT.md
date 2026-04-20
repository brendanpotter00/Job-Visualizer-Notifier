# Feature Voting PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-04-18 — Review pass 1

Dispatched 5 code-review agents + 3 production-environment verifiers in parallel.

### Code-review findings

**Critical:**
- `src/backend/api/routers/features.py:69` — `list_features` has no `try/except psycopg2.Error` around `list_features_with_upvotes`, so a DB error leaves the pooled connection in an aborted-transaction state and the next caller sees "current transaction is aborted." (silent-failure-hunter)
- `src/backend/api/routers/features.py:57` — `_resolve_optional_user_id` calls `get_user_by_email` with no error handling; a transient DB failure on the anonymous GET path produces an unlogged 500. (silent-failure-hunter)
- `src/frontend/src/pages/VoteFeaturesPage/FeatureVoteCard.tsx:42,44` — `void upvote(id)` / `void removeUpvote(id)` discards the mutation promise. Failures (500, 401, 404) silently revert via `patch.undo()` with zero user feedback and no Sentry signal. Replace with `try { await upvote(id).unwrap(); } catch (e) { logError(...); }`. (silent-failure-hunter)

**Important:**
- `src/backend/api/main.py:48-65` — lifespan `try/except Exception` wraps dynamic imports AND `seed_starter_features(...)`. Narrow the except to `psycopg2.Error` around only the seed call so unrelated boot bugs aren't swallowed. (silent-failure-hunter)
- `src/frontend/src/features/features/featuresApi.ts:56,75` — bare `catch { patch.undo() }` in optimistic update paths discards the rejection reason; no console warning, no Sentry breadcrumb. Add `logError`/`console.warn` before `patch.undo()`. (silent-failure-hunter)
- `src/frontend/src/features/features/getTokenOrNull.ts:14` — empty `catch {}` conflates "logged out" with "Auth0 SDK broke" — violates the `correctness_over_dont_crash` memory. Add `console.warn('[getTokenOrNull] token getter rejected:', e)` so the symptom is debuggable. (silent-failure-hunter)
- `src/frontend/src/components/shared/SignInPrompt/SignInPromptModal.tsx:31-35` — accessibility: Dialog relies on `slotProps.paper['aria-label']` only. Add a visually-hidden `<DialogTitle>` (or `id` on the `Typography variant="h6"` in `SignInPrompt`) and `aria-labelledby` so screen readers announce the actual title. (code-reviewer)
- `vercel.json:90` — `Access-Control-Allow-Methods` is `GET, POST, PUT, OPTIONS` (no `DELETE`). The frontend issues `DELETE /api/features/{id}/upvote`. Same-origin calls work but the CORS contract is wrong and cross-origin consumers would be blocked. Add `DELETE`. (vercel-prod-verifier)
- `src/backend/alembic/versions/20260420_014438_050b9adc98e1_add_features_and_upvotes.py` — migration upgrade/downgrade is not exercised by any test. `conftest.py::db_conn` uses `Base.metadata.create_all` + `stamp_alembic_head`, which skips `op.create_*`. `test_alembic_parity.py` only asserts autogen-diff emptiness. Add a test that runs `alembic upgrade head` → `downgrade -1` against a clean env-suffixed schema. (pr-test-analyzer)
- `src/backend/api/tests/test_features_router.py` — auth-resolution error branches untested: missing `sub` → 401, missing `email` → 401, `psycopg2.Error` → 500 in `_resolve_user_id_for_mutation`; and `_resolve_optional_user_id` path where `get_user_by_email` returns `None` (first-visit signed-in user). (pr-test-analyzer)
- `src/frontend/src/__tests__/features/features/featuresApi.test.ts` — no symmetric test for `removeUpvote` on a feature where `hasUpvoted === false` (the optimistic-no-op branch). `upvoteFeature` has it at line 235. (pr-test-analyzer)
- `src/frontend/src/pages/VoteFeaturesPage/VotingColumn.tsx` — no dedicated test file. All four branches (loading, error + retry, empty, data) are uncovered; `VoteFeaturesPage.test.tsx` mocks VotingColumn. (pr-test-analyzer)
- `src/backend/api/services/features_service.py:3-5` — module docstring makes a negative claim about `scripts.shared.database._get_table_name`'s internals that will rot. Replace with "Table names follow `{name}_{env}`; see `user_preferences_service._table`." (comment-analyzer)
- `src/backend/alembic/versions/20260420_014438_050b9adc98e1_add_features_and_upvotes.py:9-12` — header comment reads as a "we swapped autogen output" justification that contradicts the repo's autogen convention. Reword to describe the settings-driven suffix as the standard pattern. (comment-analyzer)
- `src/backend/api/services/features_seed.py:5` — docstring references `docs/implementations/featureVoting/PLAN.md` which is a PR-scope artifact and will rot post-merge. Drop the reference. (comment-analyzer)

**Suggestion / Nit:**
- `src/backend/api/routers/features.py:29-48` — `get_or_create_user` in mutation path vs `get_user_by_email` in GET path is deliberate asymmetry (don't create users on anonymous page loads). Add a one-line comment explaining it so a future refactor doesn't "fix" it. (code-reviewer)
- `src/backend/api/services/features_service.py:38-69` — two near-duplicate SELECTs for anon vs authed; collapse via `BOOL_OR(u.user_id IS NOT DISTINCT FROM %s)` parameterization. (code-reviewer)
- `src/frontend/src/features/features/featuresApi.ts` — no `invalidatesTags: ['Features']` on mutations; optimistic patch is sufficient but a deliberate refetch would self-heal drift. (code-reviewer)
- `src/frontend/src/pages/VoteFeaturesPage/ChangelogColumn.tsx:31` — `new Date('YYYY-MM-DD')` treats as UTC midnight; `parseISO` + `startOfDay` would be tz-safe. (code-reviewer)
- `api/features.ts:35` — body-forward condition is `PUT||POST`. Broaden to `method !== 'GET' && method !== 'HEAD' && req.body != null` for future-safety. (code-reviewer + vercel-prod-verifier)
- `api/features.ts:35` comment `// Forward body for PUT/POST requests` restates the condition — remove. (comment-analyzer)
- `src/frontend/src/config/routes.ts:40` comment `// MUI ThumbUp icon` restates the literal — remove. (comment-analyzer)
- `src/frontend/src/__tests__/pages/VoteFeaturesPage/ChangelogColumn.test.tsx:63-76` — "newest-first" test has two entries on the same date; sort stability undefined. Add one uniquely-newest entry. (pr-test-analyzer)
- `src/frontend/src/__tests__/pages/VoteFeaturesPage/FeatureVoteCard.test.tsx:59-60` — mutation triggers mocked with bare `mockResolvedValue(undefined)`; hides contract drift if anyone switches to `.unwrap()`. Mock the full `{ unwrap }` shape. (pr-test-analyzer)
- `src/frontend/src/features/features/useFeaturesAuthBridge.ts` — re-register on `getToken` identity change untested. (pr-test-analyzer)
- Type design — `ChangelogEntry.tags` could be `readonly [ChangelogTag, ...ChangelogTag[]]` for non-emptiness; `FeatureListItem.upvoteCount: number` lacks `>= 0` invariant; Pydantic `created_at` could be `AwareDatetime` to pin tz-awareness. Defer. (type-design-analyzer)
- Type design — `hasUpvoted: boolean` → `currentUserUpvotedAt: string | null` would be strictly more information. Defer; changes HTTP contract. (type-design-analyzer)

**False positives (verified and dismissed):**
- code-reviewer claimed `api/features.ts:20` points to `/api/users` — verified in-file: correctly targets `/api/features`. No fix.
- code-reviewer flagged the Alembic revision as "hand-edited"; the `settings.scraper_environment` substitution matches the repo-wide convention established in the baseline revision. Not a violation. No fix.

### Production-environment findings

**Critical:** None.

**Important:**
- `vercel.json:90` — CORS `Access-Control-Allow-Methods` missing `DELETE`. See code-review Important list above (merged). (vercel-prod-verifier)
- `src/backend/api/main.py:49-65` — seed observability: after deploy, confirm the INFO log line `Seeded 3 starter features (env=prod)` appears exactly once on cold start; if it doesn't, `GET /api/features` returns empty. Operational, not a code change. (railway-prod-verifier)

**Suggestion:**
- Alembic revision imports `from api.config import settings` at module level — requires `api` on `sys.path`. Unrunnable outside the Docker container / uvicorn path. Note for runbook; no code change. (railway-prod-verifier)
- `list_features_with_upvotes` uses `LEFT JOIN ... GROUP BY f.id` with no `ORDER BY` index. Fine at v1 (≤50 features per PLAN non-goals); re-evaluate if that cap lifts. (postgres-prod-verifier)

**Could not verify:**
- vercel-prod-verifier — live preview smoke test of `feature-voting-page` branch: no preview deployment exists yet. Will verify after PR opens.
- postgres-prod-verifier — live EXPLAIN on `features_prod` query: tables don't yet exist in prod. Will verify after first deploy per PLAN.md Unit 8 "Deploy verification" list.

**Manual action required before merge:** None. No new env vars; `BACKEND_API_URL` + `AUTH0_*` already set in both Vercel and Railway prod environments.

### Deferred (not fixing this pass)

- Type-design improvements (branded slugs, `AwareDatetime`, non-empty tag tuples, `currentUserUpvotedAt` swap) — deferred; contract change touches wire protocol and doesn't ship regression, prefer to land this PR first.
- Collapse duplicate SELECTs in `features_service.py` — stylistic; defer.
- `invalidatesTags: ['Features']` addition — optimistic cache is correct; defer.
- `parseISO` vs `new Date` in `ChangelogColumn` — off-by-one at tz boundary only, dates display correctly in US time zones. Defer.

### Implementation applied

**Commits:**
- `2b58421` — narrow features router error handling + docstring cleanups (items 1, 2, 3, 13, 14, 15).
- `bffa7c1` — log failures instead of swallowing them in features flow (items 4, 5, 6).
- `cd0608b` — wire SignInPromptModal a11y labelledby + add DELETE to CORS (items 7, 8).
- `7bf1876` — add regression tests + refine lifespan seed guard (items 9, 10, 11, 12; plus a main.py refinement that broadens the except-guard to `psycopg2.Error, RuntimeError` around the `get_db()` pool lookup as well as the seed call, since the pool lookup can legitimately raise RuntimeError on exhaustion).

**Verification gates (post-fix):**
- `pytest` (backend full): 217 passed.
- `npm run type-check`: clean.
- `npm test`: 1374 passed across 99 files.
- `npm run lint`: 0 errors (141 pre-existing warnings unchanged).

**Do not revert (new in this pass):**
- `src/backend/api/routers/features.py` `try/except psycopg2.Error` wrappers around every DB call — closes the aborted-tx leak.
- `src/frontend/src/pages/VoteFeaturesPage/FeatureVoteCard.tsx` `.unwrap()` + `logError` pattern — fire-and-forget was masking every mutation failure.
- `src/backend/api/main.py` seed lifespan guard narrowed to `psycopg2.Error, RuntimeError` around the DB-bound seed-call path only; imports remain outside the guard so import failures surface loudly.
- `vercel.json` `DELETE` in `Access-Control-Allow-Methods` — required for the `/upvote` remove endpoint CORS posture.
- `SignInPromptModal` `aria-labelledby` + visible-or-visually-hidden `DialogTitle` — required for screen-reader accessibility; do NOT revert to paper-level `aria-label` only.

**Manual action required before merge:** None new this pass.

---

## 2026-04-20 — Review pass 3

Dispatched 3 code-review agents (code-reviewer, silent-failure-hunter, pr-test-analyzer) + 2 prod verifiers (vercel, railway) in parallel. Type-design and comment agents skipped — types deferred, comments not materially touched this pass.

### Code-review findings

**Critical:** None.

**Important:**
- `src/frontend/src/features/features/getTokenOrNull.ts:18` + `src/frontend/src/features/auth/useAuth.ts:48` — sentinel coupling is a brittle string compare (`e.message === 'Not authenticated'`). If `useAuth` ever rephrases the throw or an Auth0 SDK upgrade wraps it, anonymous page loads would spam `logger.warn`. Export a shared constant `NOT_AUTHENTICATED_ERROR_MESSAGE` (or a marker class `NotAuthenticatedError`) from `useAuth.ts` and import it in `getTokenOrNull.ts`. Compile-checks the coupling. (silent-failure-hunter)
- `src/frontend/src/features/features/useFeaturesAuthBridge.ts` — bridge has no observability. If the hook silently fails to register (render error upstream, removed call site, import failure), every authenticated mutation goes out anonymous and gets 401 — user just sees "upvote failed, revert." Add `logger.debug('[useFeaturesAuthBridge] registered getToken')` / `'...unregistered getToken'` on effect + cleanup. (silent-failure-hunter)
- `src/frontend/src/__tests__/pages/VoteFeaturesPage/FeatureVoteCard.test.tsx` — keyboard activation untested. Only `user.click` tested. A swap from MUI `IconButton` to `<div role="button">` without `onKeyDown` would silently break keyboard voting. Add Enter/Space test. (pr-test-analyzer)
- `src/frontend/src/__tests__/pages/VoteFeaturesPage/FeatureVoteCard.test.tsx` — `aria-pressed` state untested. Pre-upvote and post-upvote render branches both set the attribute but no test reads it. A polarity-flip refactor would announce the opposite state to screen readers. Assert `aria-pressed="false"` in not-upvoted branch + `"true"` in upvoted branch. (pr-test-analyzer)
- `src/frontend/src/__tests__/pages/VoteFeaturesPage/FeatureVoteCard.test.tsx` — component-layer mutation-failure `logger.error` path untested. Swap `unwrap` mock to reject, spy on `logger.error`. Pins the pass-1 fix against regression to fire-and-forget. (pr-test-analyzer)

**Suggestion / Nit:**
- `src/frontend/src/components/shared/SignInPrompt/SignInPrompt.tsx:47` — `console.error` → `logger.error` for repo convention consistency. Defer (low impact).
- `src/frontend/src/features/features/getTokenOrNull.ts:32` — `console.warn` → `logger.warn`. Defer (low impact).
- `api/features.ts:35-36` — body-forward condition could broaden to `method !== 'GET' && method !== 'HEAD' && req.body != null` + drop redundant comment. Defer (pass-1 carry-over).
- `src/frontend/src/__tests__/pages/VoteFeaturesPage/ChangelogColumn.test.tsx:25-37` — same-date entries in newest-first test; sort stability undefined. Defer (pass-1 carry-over).
- `FeatureVoteCard.test.tsx` logger.error wrapping belt-and-suspenders (silent-failure #3) — non-serializable argument to `logger.error` could throw. Probability ≈ 0, do not action.
- `conftest.py` settings restoration asymmetry with `scripts/tests/conftest.py` — deliberate, both valid. Defer.
- `test_migration_features.py` teardown `logger.exception` on broad `Exception` — correct trade-off given 2026-04-19 incident history. No action.

### Production-environment findings

**Critical / Important:** None.

**Suggestion:**
- `vercel.json:48-53` rewrite shape `/api/features/:path(.*)` verified correct against live prod `/api/users` mirror pattern. No change. (vercel-prod-verifier)
- `api/features.ts` bundle size: ~50 lines, zero new third-party deps, shared `api/utils/*` already deployed. No bloat. (vercel-prod-verifier)
- Preview env uses `VITE_AUTH_BYPASS=true` while Production uses `VITE_AUTH0_*`. Preview smoke-testing authenticated voting will 401 — verify on production after merge per PLAN Unit 8. Operational, not a code change. (vercel-prod-verifier)
- Railway service healthy; clean logs since 2026-04-19 fix deploy; no ERROR/WARN/Traceback/OOM/restart; pool stable at `min=1, max=15, timeout=5.0s`. No new memory hotspot from `conn.rollback()` usage. Migration `050b9adc98e1` is 2 small CREATE TABLEs + 2 indexes; sub-second cold boot. (railway-prod-verifier)

**Could not verify:**
- vercel-prod-verifier — live preview deploy of `feature-voting-page`: PR not yet opened. Will verify after `gh pr create`.
- vercel-prod-verifier — live `/api/features*` prod logs: route doesn't exist pre-merge (verified 404 NOT_FOUND live). Normal.
- railway-prod-verifier — live `features_prod` / `feature_upvotes_prod` schema: tables don't exist pre-merge. Per PLAN Unit 8, verify after first deploy via `mcp__postgres-prod__query`.

### Deferred (not fixing this pass)

- All `console.*` → `logger.*` swaps outside the features-flow diff (SignInPrompt, getTokenOrNull module-level warn at non-sentinel branch). Defer to a follow-up repo-wide convention-enforcement PR.
- Body-forward condition broadening in `api/features.ts`. Defer.
- Concurrency/double-click dedupe assertion — disabled-during-in-flight invariant is covered; dispatch-level dedupe is RTK Query library behavior, not this PR.
- `useFeaturesAuthBridge` re-registration on `getToken` identity change — Auth0 `getToken` identity is stable in practice. Defer.
- `VoteFeaturesPage.test.tsx` trivial composition test — low value but not broken. Leave.
- Same-date sort stability in `ChangelogColumn.test.tsx`. Defer.

### Implementation applied

**Commits:**
- `8d8c056` — Review pass 3: typed NotAuthenticated marker + bridge debug logs (items 1, 2).
- `735dc9e` — Review pass 3: FeatureVoteCard keyboard + aria-pressed + logger.error tests (items 3, 4, 5).

**Verification gates (post-fix):**
- `pytest` (backend full): 222 passed.
- `npm run type-check`: clean.
- `vitest run` (frontend): 1384 passed across 100 files.
- `npm run lint`: 0 errors (141 pre-existing warnings unchanged).

**Do not revert (new in this pass):**
- `NOT_AUTHENTICATED_ERROR_MESSAGE` / `NotAuthenticatedError` shared sentinel — replaces string-literal coupling between `useAuth.ts` and `getTokenOrNull.ts`. Do NOT re-introduce raw `e.message === 'Not authenticated'` checks.
- `useFeaturesAuthBridge` debug-log observability on register/unregister — required to debug "mutations going out anonymous" symptoms.
- `FeatureVoteCard.test.tsx` keyboard + aria-pressed + logger.error assertions — pins a11y and component-layer error logging contracts.

**Manual action required before merge:** None new this pass.

---

## 2026-04-18 — Review pass 2

Dispatched 3 code-review agents (code-reviewer, silent-failure-hunter, pr-test-analyzer) + 2 prod verifiers (vercel, railway) in parallel. Type-design and comment agents skipped — types deferred by pass-1 decision; comments already reviewed last pass.

### Code-review findings

**Critical:** None.

**Important:**
- `src/frontend/src/pages/VoteFeaturesPage/FeatureVoteCard.tsx:107` — call site passes `ariaLabel={SIGN_IN_MODAL_MESSAGES.ARIA_LABEL}`, which forces `SignInPromptModal` back onto the static `aria-label` path, effectively reverting the pass-1 a11y fix. Drop the prop so the modal uses the default `aria-labelledby` and the screen reader reads the live title. (code-reviewer)
- `src/frontend/src/features/features/getTokenOrNull.ts:18` — `console.warn` fires on every anonymous page load because `useAuth().getToken()` throws `new Error('Not authenticated')` as the normal signed-out path. The catch must distinguish the expected "Not authenticated" sentinel from real SDK failures, else noise spam masks real problems (violates `correctness_over_dont_crash`). (code-reviewer)
- `src/backend/api/routers/features.py:83-89` — `list_features` rollback branch untested. Patch `list_features_with_upvotes` to raise `psycopg2.Error` and assert 500 + `conn.rollback()` invocation. (pr-test-analyzer)
- `src/backend/api/routers/features.py:62-69` — `_resolve_optional_user_id` psycopg2 fallback untested; should log, rollback, fall back to anonymous, still return 200. (pr-test-analyzer)
- `src/backend/api/main.py:58-72` — lifespan seed-failure soft-fail guard untested. Patch `seed_starter_features` to raise `psycopg2.Error`; assert app still boots. (pr-test-analyzer)
- `src/backend/api/services/features_seed.py:68-69` — INFO log guarded by `if inserted:` means subsequent boots are silent, indistinguishable from silent crash. Emit `logger.info("seed_starter_features completed (env=%s, inserted=%d)", env, inserted)` unconditionally. (code-reviewer + railway-prod-verifier)
- `src/frontend/src/pages/VoteFeaturesPage/FeatureVoteCard.tsx:46`, `src/frontend/src/features/features/featuresApi.ts:61,84` — raw `console.error`/`console.warn` drift from repo convention. Swap to `logger.error` / `logger.warn` from `src/frontend/src/lib/logger.ts`. (silent-failure-hunter)

**Suggestion / Nit:**
- `src/backend/api/services/features_service.py:34-77` — `list_features_with_upvotes` has no try/except (siblings do); functionally safe via router + `get_db` double-rollback but asymmetric. Defer (stylistic consistency only). (silent-failure-hunter)
- `features_service.py`, `features_seed.py` — cursors not closed with `with conn.cursor() as cur:` pattern; relies on GC. Defer. (silent-failure-hunter)
- `api/features.ts` — `forwardResponse` can throw after headers sent; consider `!res.headersSent` guard. Defer (low-probability). (silent-failure-hunter)
- `useFeaturesAuthBridge.ts` — no debug-level logging on register/unregister transitions. Defer. (silent-failure-hunter)
- `main.py` seed lifespan — manual generator protocol fragile; prefer `contextmanager(get_db)()`. Defer (works correctly today). (code-reviewer)
- Router asymmetry comment between `_resolve_user_id_for_mutation` (500s) vs `_resolve_optional_user_id` (falls back to anonymous) still missing; add one-line explanation. Defer.

### Production-environment findings

**Critical / Important:** None.

**Suggestion:**
- Pass-1 CORS + proxy URL fixes re-verified in prod env — clean. (vercel-prod-verifier)
- Railway service healthy; lifespan ordering (migrate → pool → seed) confirmed in live logs; no OOM/pool-exhaustion/restart signals. (railway-prod-verifier)

**Could not verify:**
- Preview deploy of `feature-voting-page` branch — PR not yet opened. Will verify after merge prep. (vercel-prod-verifier)

**Manual action required before merge:** None new this pass.

### Deferred (not fixing this pass)

- `features_service.py` try/except/cursor-close consistency — purely stylistic, works today.
- `api/features.ts` `!res.headersSent` guard — low probability.
- `useFeaturesAuthBridge.ts` debug logging — nice-to-have.
- `main.py` generator protocol replacement — works today, refactor invites risk for zero user benefit.
- Router asymmetry comment — nice-to-have.

### Implementation applied

**Commits:**
- `5292b97` — Review pass 2: frontend a11y + observability fixes (items: drop `ariaLabel` call-site prop, `getTokenOrNull` sentinel-vs-real error distinction, `logger.error/warn` swap in `FeatureVoteCard` + `featuresApi`).
- `ea492cb` — Review pass 2: backend log + regression tests (items: `features_seed` unconditional INFO log; regression tests for `list_features` psycopg2 rollback branch, `_resolve_optional_user_id` psycopg2 fallback, and lifespan seed-failure guard).

**Verification gates (post-fix):**
- `pytest` (backend full): 222 passed (5 new tests from pass 2).
- `npm run type-check`: clean.
- `npm test`: 1379 passed across 100 files.
- `npm run lint`: 0 errors (141 pre-existing warnings unchanged).

**Do not revert (new in this pass):**
- `FeatureVoteCard.tsx` no longer passes `ariaLabel` prop to `SignInPromptModal` — the modal must use its default `aria-labelledby` path; reintroducing the prop reverts pass-1 a11y fix.
- `getTokenOrNull.ts` sentinel-vs-real error distinction — catch must stay narrow (exact-match `'Not authenticated'`); collapsing it back to bare catch or unconditional warn reintroduces either the silence OR the per-anonymous-load warn spam.
- `features_seed.py` unconditional INFO log — required for Railway log observability; do NOT re-guard behind `if inserted:`.
- `src/frontend/src/lib/logger.ts` is the repo's standard for client-side logging — new feature code should import from it rather than call `console.error` / `console.warn` directly.

**Manual action required before merge:** None new this pass.

