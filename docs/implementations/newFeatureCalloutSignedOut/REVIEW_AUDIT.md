# New Feature Callout Signed-Out Fix PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

---

## 2026-04-19 — Review pass 1

Agents dispatched (parallel): `pr-review-toolkit:code-reviewer`, `pr-review-toolkit:silent-failure-hunter`, `pr-review-toolkit:pr-test-analyzer`, `pr-review-toolkit:comment-analyzer`.

Production verifiers not dispatched:
- `vercel-prod-verifier`: not dispatched (no matching diff signal — no `api/*.ts`, `vercel.json`, `next.config.*`, or env-var changes; component-only fix).
- `postgres-prod-verifier`: not dispatched (no matching diff signal — no migrations, models, or SQL).
- `railway-prod-verifier`: not dispatched (no matching diff signal — no backend / Dockerfile / railway.toml changes).

### Code-review findings

**Critical:**
- (none)

**Important:**
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesLink.test.tsx:159-162` — regression comment references "Unit 1" and will rot on merge (agent: comment-analyzer). Rewrite to state the invariant without PR vocabulary.
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesRow.test.tsx:94-97` — regression comment references "Unit 1" and "on `main`" which rot immediately after merge (agent: comment-analyzer). Rewrite as a self-contained description of the guarded regression.
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesRow.test.tsx` — the row-level regression asserts `getByTestId('sign-in-to-edit-preferences-link')` but not the surrounding caption text, so a future regression that wrapped the link in a hidden Box would still pass (agent: pr-test-analyzer). Add a `screen.getByText(/Sign in to customize this feed/)` assertion and/or an assertion on the link's closest `<p>` element's text content.
- Missing coverage: the loading→authenticated rerender transition (the "one-time caption swap" that PLAN.md explicitly sanctions as acceptable behavior) has no test — a future refactor could accidentally regress it without being caught (agent: pr-test-analyzer). Add an `it(...)` that mounts with `isLoading=true, isAuthenticated=false`, asserts the sign-in prompt, then rerenders with `isLoading=false, isAuthenticated=true, enabledIds=null`, asserts the spacer, then rerenders with `enabledIds=[...]` and asserts the signed-in caption.

**Suggestion:**
- `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx:13-18` — the 6-line gate comment mentions "callout rendering with no adjacent caption" but doesn't name the sibling component `NewFeatureCallout`, so a grep for that component name misses this file (agent: comment-analyzer).
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesLink.test.tsx:178-182` — "Contract 2 from PLAN.md" is a dangling pointer that breaks once PLAN.md is archived (agent: comment-analyzer). Inline the contract statement.
- Auth-bypass build shape (`isEnabled=true, isAuth0Loading=false, isAuth0Authenticated=true`) has no explicit labeled test, though it's covered incidentally (agent: pr-test-analyzer).

**Nit:**
- `EditCompanyPreferencesLink.test.tsx:182` — `mockEnabledIds = null` is redundant since `beforeEach` resets it to `null`; reading as documentation of intent is fine (agent: code-reviewer).
- Row regression doesn't click the sign-in link to assert `login` wiring (agent: silent-failure-hunter S3).
- Useful tightening in the source gate comment: the load-bearing `useAuth` invariant is implicit; could reference `useAuth.ts` or the `useAuth0` loading contract directly (agent: silent-failure-hunter N1).

### Production-environment findings

- `vercel-prod-verifier`: not dispatched (no matching diff signal).
- `postgres-prod-verifier`: not dispatched (no matching diff signal).
- `railway-prod-verifier`: not dispatched (no matching diff signal).

### Deferred (not fixing this pass)

- **silent-failure-hunter I1** (`EditCompanyPreferencesLink.tsx:19` placeholder-indefinitely if `googleCredential` restored while `isAuth0Loading=true`): the new gate behaves identically to the old gate in that exact state — both render the placeholder while `enabledIds === null`. This is not a regression introduced by this PR, and addressing it (Sentry-logged timeout, or reintroducing `!isLoading` which reintroduces the original bug) is out of scope. Noted for a future ticket.
- **silent-failure-hunter I2 / S1** (`void login()` eats errors; test locks in the swallow): pre-existing pattern, unrelated to this PR's scope.
- **pr-test-analyzer S1** (explicit auth-bypass build test): covered incidentally by the existing "when signed in" cases; labeling it separately is documentation polish only. Defer.
- **pr-test-analyzer N1** (redundant "spacer while preferences loading" vs. "loading AND authenticated but enabledIds have not arrived"): keeping both as living documentation of intent. No action.
- **silent-failure-hunter S3 / N1** (click-through for login wiring; naming useAuth0 contract in comment): nice-to-haves, defer to pass 2 if still open.

### Implementation applied

Commit `ba4ab93` — `Review pass 1: de-rot test comments, strengthen row regression, add rerender coverage`.

Files changed:
- `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx` — gate comment now names `NewFeatureCallout` sibling explicitly (Fix D).
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesLink.test.tsx` — two comment rewrites (no more "Unit 1" / "Contract 2 from PLAN.md"); added `swaps from Sign-in prompt to spacer, then to the signed-in caption as auth resolves` rerender test (Fix A + C).
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesRow.test.tsx` — comment rewrite (no more "Unit 1" / "on main"); added `closest('p').toHaveTextContent(...)` assertion (Fix A + B).

Gates: `npm run type-check` clean, `npm run lint` clean, targeted tests 17/17, full suite 1110/1110 across 72 files.

**Do not revert (new in this pass):**
- The rerender test in `EditCompanyPreferencesLink.test.tsx` (`swaps from Sign-in prompt to spacer, then to the signed-in caption as auth resolves`) — locks in PLAN.md's sanctioned one-time caption swap. Removing it would let a future refactor silently persist the signed-out caption after auth resolves to signed-in.
- The `closest('p').toHaveTextContent(...)` assertion in `EditCompanyPreferencesRow.test.tsx` — protects against a regression that wraps the link in a hidden Box.

**Manual action required before merge:** (none)

---

## 2026-04-19 — Review pass 2

Agents dispatched (parallel): `pr-review-toolkit:code-reviewer`, `pr-review-toolkit:silent-failure-hunter`, `pr-review-toolkit:pr-test-analyzer`, `pr-review-toolkit:comment-analyzer`.

Production verifiers:
- `vercel-prod-verifier`: not dispatched (no matching diff signal).
- `postgres-prod-verifier`: not dispatched (no matching diff signal).
- `railway-prod-verifier`: not dispatched (no matching diff signal).

### Code-review findings

**Critical:** (none)

**Important:**
- `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx:13-19` — gate comment overstates the `useAuth` invariant. The comment asserts `isAuthenticated=false during loading`, but in `useAuth.ts:28` `isAuthenticated = AUTH_CONFIG.isEnabled && (isAuth0Authenticated || !!googleCredential)` — a returning Google user whose credential rehydrates from localStorage synchronously can land on `{isLoading:true, isAuthenticated:true}` on first paint. The placeholder branch handles that case correctly (spacer until `enabledIds` arrives), but the comment's stated reason is false, which risks a future maintainer removing the `isAuthenticated &&` clause on the mistaken belief that loading implies unauthenticated (agent: silent-failure-hunter I1). Rewrite to describe what the gate actually does across all loading shapes, not a false invariant.

**Suggestion:**
- `EditCompanyPreferencesRow.test.tsx:94-97` — "A prior version reserved a blank placeholder instead" has mild temporal-rot vocabulary ("prior version") that loses its referent post-merge (agent: comment-analyzer). Rewrite as a timeless description of what goes wrong without the fix.
- `toHaveTextContent(string)` does substring matching — a regression that appends diagnostic text to the caption (e.g. `"...you care about Sign in"`) would silently pass both the Link and Row caption assertions (agent: silent-failure-hunter S1). Tighten the caption pin to `textContent === '...'` equality or a full-string regex.
- `EditCompanyPreferencesLink.test.tsx` rerender test step 3 — asserts the signed-in caption is present but does not positively assert the sign-in testid is absent at that step (agent: silent-failure-hunter S2). Add a symmetric `queryByTestId('sign-in-to-edit-preferences-link')` negative assertion for symmetry with step 2.
- State matrix gap: `(isLoading=true, isAuthenticated=true, enabledIds=[...])` is untested (criticality 5); `(isLoading=false, isAuthenticated=false, enabledIds=[...])` is untested (criticality 3) (agent: pr-test-analyzer). Consider pinning the warm-cache-rehydrate case at least.

**Nit:**
- `closest('p')` in the row assertion is MUI-version-coupled (code-reviewer, pr-test-analyzer) — low risk, leave as-is.
- Duplicated "spacer while loading" vs. "spacer while preferences loading" test — kept intentionally in pass 1 as living documentation; no change.
- Add comment to rerender test noting `mockAuthState` mutation-by-field-assignment is load-bearing (code-reviewer S2) — low value, defer.

### Production-environment findings

- `vercel-prod-verifier`: not dispatched (no matching diff signal).
- `postgres-prod-verifier`: not dispatched (no matching diff signal).
- `railway-prod-verifier`: not dispatched (no matching diff signal).

### Deferred (not fixing this pass)

- pr-test-analyzer state matrix gaps (S1, S2): criticality 5 and 3; would pin warm-cache rehydrate and stale-ids signed-out paths. Defer — the current 10/12 matrix coverage is strong for a bug-fix PR.
- code-reviewer / comment-analyzer nits (MUI coupling; rerender-mutation note): low value.

### Implementation applied

Commit `0a0d64b` — `Review pass 2: correct gate comment, tighten caption assertions, symmetric rerender guard`.

Files changed:
- `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx` — gate comment rewritten (Fix A): no longer asserts the false `isAuthenticated=false during loading` invariant; now describes gate behavior across all loading shapes including returning-Google-user credential rehydration.
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesLink.test.tsx` — caption assertion switched from substring-matching `toHaveTextContent` to `textContent` full-string equality (Fix C); symmetric `queryByTestId(...).not.toBeInTheDocument()` added to rerender step 3 (Fix D).
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesRow.test.tsx` — regression comment rewritten as timeless description (Fix B); caption assertion tightened to `textContent` equality (Fix C).

Gates: `npm run type-check` clean, `npm run lint` clean, targeted tests 17/17, full suite 1110/1110 across 72 files.

**Do not revert (new in this pass):**
- The corrected gate comment in `EditCompanyPreferencesLink.tsx` — it accurately describes the `useAuth` shape including the returning-Google-user edge case. Reverting to the older comment would reintroduce the false invariant that a future maintainer could act on.
- `textContent` equality assertions on both test files — substring-matching was silently permissive; a regression that appended text to the caption would now be caught.

**Manual action required before merge:** (none)

---

## 2026-04-19 — Review pass 3

Agents dispatched (parallel): `pr-review-toolkit:code-reviewer`, `pr-review-toolkit:silent-failure-hunter`, `pr-review-toolkit:pr-test-analyzer`, `pr-review-toolkit:comment-analyzer`.

Production verifiers:
- `vercel-prod-verifier`: not dispatched (no matching diff signal — component-only fix, no `api/*.ts`, `vercel.json`, `next.config.*`, or env-var changes).
- `postgres-prod-verifier`: not dispatched (no matching diff signal — no migrations, models, or SQL).
- `railway-prod-verifier`: not dispatched (no matching diff signal — no backend / Dockerfile / railway.toml changes).

### Code-review findings

**Critical:** (none)

**Important:** (none)

**Suggestion:**
- `EditCompanyPreferencesLink.test.tsx` rerender step 3 — the signed-in caption check still uses `toHaveTextContent(/Showing jobs from/)` substring match (criticality 3); the loading-phase caption was tightened to `textContent` equality in pass 2 but the post-auth-resolve assertion wasn't updated in lockstep (agent: pr-test-analyzer).
- `EditCompanyPreferencesLink.tsx:13-21` — 9-line gate comment could be tightened; the "strictly better than the sibling NewFeatureCallout pill rendering with no adjacent caption" clause is a value judgment rather than a machine-checkable invariant (agent: comment-analyzer).

**Nit:**
- `EditCompanyPreferencesRow.test.tsx` could share a `getCaption` helper with the Link test for symmetry (agent: silent-failure-hunter). Diagnostic quality only, low value.
- Gate-comment first sentence could harmonize with the "sign-in caption is the default" framing used in the Row test's regression comment (agent: code-reviewer). Low value.

### Production-environment findings

- `vercel-prod-verifier`: not dispatched (no matching diff signal).
- `postgres-prod-verifier`: not dispatched (no matching diff signal).
- `railway-prod-verifier`: not dispatched (no matching diff signal).

### Deferred (not fixing this pass)

All pass 3 findings are Suggestions/Nits only — nothing Critical or Important surfaced. All four reviewers returned a verdict of "ready to merge."

- **pr-test-analyzer S1** (tighten rerender step-3 signed-in caption from substring to `textContent` equality): low value — the symmetric step-2 tightening was about guarding the sign-in caption (the core regression surface); step 3 asserts the caption post-auth-resolve, which is not the regression this PR defends. Defer.
- **comment-analyzer S1** (trim 9-line gate comment; drop "strictly better" value judgment): the comment is load-bearing per pass 2's do-not-revert rationale (names the `useAuth` edge case). Trimming risks re-introducing ambiguity. Leave as-is.
- **silent-failure-hunter / code-reviewer nits**: diagnostic polish only.

### Implementation applied

No fix commit this pass. No Critical or Important findings to address; all four agents returned "ready to merge"; Suggestions/Nits are explicitly deferred per the rationale above.

Gates (unchanged since pass 2): `npm run type-check` clean, `npm run lint` clean, targeted tests 17/17, full suite 1110/1110 across 72 files.

**Do not revert (new in this pass):** (none — no changes this pass)

**Manual action required before merge:** (none)
