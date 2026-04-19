# New Feature Callout Signed-Out Fix Plan

## Context

**Observed bug.** On the Recent Job Postings page (`/`), a signed-out user on a fresh page load sees the blue "New! Pick your companies" callout pill, but the accompanying caption — "Sign in to customize this feed to the companies you care about" — is missing during the initial Auth0 resolution window, and in some mobile sessions fails to appear at all until interaction. The attached screenshot (`/Users/brendanpotter/Downloads/IMG_6986.PNG`) shows the **desired** state, where both the caption and the pill are visible side-by-side (or stacked on mobile). Live signed-out behavior diverges from that screenshot.

**Root cause.** In `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx`, the render body short-circuits to a blank height-reservation Box whenever `isLoading` is true, regardless of whether the final resolved state will be authenticated or unauthenticated:

```tsx
// EditCompanyPreferencesLink.tsx lines 14-17 (current)
if (isLoading || (isAuthenticated && enabledIds === null)) {
  return <Box sx={{ height: 20 }} aria-hidden />;
}
```

Meanwhile, its sibling in `EditCompanyPreferencesRow.tsx` — the `NewFeatureCallout` pill — has no such gating. It reads `localStorage` inside a `useState` initializer and renders on the very first paint. Consequence: during the entire Auth0 "still loading" window (and permanently, in auth-bypass or auth-disabled builds where `AUTH_CONFIG.isEnabled` is false and `isLoading` is structurally `false` but the signed-in branch logic still runs — see `useAuth.ts` line 29), the wrapper renders **only** the callout next to an invisible placeholder. The caption then either pops in late (layout-shift flash) or, on slow mobile networks, the user dismisses or scrolls past before the caption ever paints.

A secondary concern: the placeholder `Box` reserves `height: 20` but the signed-out caption wraps to two lines on narrow viewports (iPhone portrait, ~375 CSS px) because "Sign in to customize this feed to the companies you care about" is ~60 chars. When the caption finally renders it expands past 20px, shoving the callout pill down — a visible layout shift even for users who do notice the caption appearing.

**In scope.** Fix the render-timing bug so the signed-out caption renders as soon as `isAuthenticated` is known to be false, without waiting for a signed-in-only data dependency (`enabledIds`) that will never arrive. The placeholder should only gate on the signed-in branch's missing data, not on the signed-out branch. Add regression test coverage that would have failed on `main`.

**Out of scope.** Layout-shift height-matching heroics on the placeholder Box are not in scope — once the caption renders synchronously for signed-out users, the height mismatch no longer causes a user-visible flash for that cohort. Signed-in users still hit the placeholder briefly, which is the existing behavior and is fine (they already have the "Showing jobs from…" caption coming behind it).

**References.**
- Original callout implementation PR #75 (commit `8065067` "New Feature Callout: dismissible pointer to Company Preferences") and its plan at `docs/implementations/newFeatureCallout/PLAN.md`.
- User-attached mobile screenshot at `/Users/brendanpotter/Downloads/IMG_6986.PNG` (desired state).
- `useAuth` hook at `src/frontend/src/features/auth/useAuth.ts`.

---

## Shared Contracts (frozen)

The fix must preserve every behavior locked in by PR #75 and by the existing Recent Jobs page:

1. **Signed-in captions unchanged.** Users with `isAuthenticated=true` and loaded `enabledIds` continue to see `"Showing jobs from <descriptor> · Customize"` or `"… · Choose your companies"` with the same copy and `data-testid="edit-company-preferences-link"` on the inner Link.
2. **Signed-in loading still has a spacer.** While `isAuthenticated=true` and `enabledIds === null`, the component still renders a non-interactive placeholder (no "Sign in" flash for users who are actually signed in). The existing `EditCompanyPreferencesLink` test case "renders a spacer while preferences are still loading" continues to pass under that exact condition.
3. **Callout storage + expiry unchanged.** The `storageKey="companyPreferences-2026-04"` and `expiresAt="2026-05-02T00:00:00Z"` in `EditCompanyPreferencesRow.tsx` stay exactly as written. Dismissal persistence, `localStorage` key format (`newFeatureCallout:<key>:dismissed`), and the `role="status"` / `aria-label="Dismiss"` contracts all survive.
4. **`EditCompanyPreferencesRow` structure unchanged.** Flex wrapper, `data-testid="edit-company-preferences-row"`, mobile column / desktop row layout, `gap: 1`, `mb: 2` — none of this moves. The fix is contained inside `EditCompanyPreferencesLink.tsx` (plus tests).
5. **No layout-shift budget regression.** Signed-out users must see the caption on the first meaningful paint at parity with — or earlier than — the callout pill. Specifically: there must be no render path where the callout is mounted while the signed-out caption is not.
6. **Hook-rules safety.** The `NewFeatureCallout` does `Date.now()` inside a `useState` initializer precisely to avoid the `react-hooks/purity` rule (see PR #75 plan, §"Render-nothing conditions"). The fix must not reintroduce non-pure render-body checks elsewhere.

---

## Work Units

### Unit 1 — Render the signed-out caption immediately when auth resolution is pending

**Status:** TODO
**Prerequisites:** none

**Owned files (modify):**
- `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx`
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesLink.test.tsx`
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesRow.test.tsx`

**Shared-file edits:** none.

**Implementation notes:**

1. Rewrite the early-return gate in `EditCompanyPreferencesLink.tsx` so the placeholder is only rendered when we genuinely cannot yet decide which caption to show. The new gate should be: only return the placeholder when the signed-in branch is still waiting on its data. If auth has not yet resolved, bias toward rendering the signed-out caption, because (a) it's the correct outcome for everyone who isn't signed in, which is the majority of new visitors, and (b) if auth later resolves to signed-in, the component re-renders and swaps to the "Showing jobs from…" caption — the worst case is a one-time caption swap, which is strictly better than a missing caption.

   Concretely, replace the current gate:

   ```tsx
   if (isLoading || (isAuthenticated && enabledIds === null)) {
     return <Box sx={{ height: 20 }} aria-hidden />;
   }
   ```

   with a gate that keys only on the signed-in-with-missing-ids condition:

   ```tsx
   if (isAuthenticated && enabledIds === null) {
     return <Box sx={{ height: 20 }} aria-hidden />;
   }
   ```

   When `isLoading=true` and `isAuthenticated` has not resolved yet, `isAuthenticated` is `false` by the `useAuth0` contract, so control falls through to the signed-out branch and the caption renders. When Auth0 later flips `isAuthenticated` to `true`, the signed-in-with-missing-ids guard catches it (loading state: `enabledIds === null`), swapping to the placeholder until `enabledIds` resolves, then to the signed-in caption. This is exactly the acceptable one-time swap described above.

2. Leave the signed-out return branch and the signed-in return branch untouched. `login`, `navigate`, `data-testid` values, copy strings — all frozen.

3. Update `EditCompanyPreferencesLink.test.tsx`:
   - Delete or rewrite the current `when auth is loading > renders a non-interactive spacer` case. It asserts the buggy behavior. Replace it with: **"when auth is loading and not yet authenticated, renders the Sign-in prompt"** — set `mockAuthState.isLoading = true` and `mockAuthState.isAuthenticated = false`, then assert `screen.getByTestId('sign-in-to-edit-preferences-link')` is present and has the full expected caption text. This is the test that would have failed on `main` and passes after the fix.
   - Add a new case **"when auth is loading AND authenticated, still renders a spacer while enabledIds load"** — `isLoading=true`, `isAuthenticated=true`, `mockEnabledIds=null`. Asserts no link is rendered (contract 2 above).
   - The existing `when signed in > renders a spacer while preferences are still loading` case stays exactly as-is — that's contract 2.

4. Update `EditCompanyPreferencesRow.test.tsx`:
   - Add a regression case **"renders both caption and callout when auth is still loading and user is not yet authenticated"** — set `mockAuthState.isLoading = true` and `mockAuthState.isAuthenticated = false`, render the row, and assert both `screen.getByTestId('sign-in-to-edit-preferences-link')` AND `screen.getByRole('status')` (the callout) are in the document. This is the end-to-end regression test for the reported bug; it would fail on `main` (caption missing) and pass after Unit 1.
   - The existing `still renders the callout when the user is signed out` case stays as-is.

**Done when:**

- `npm test -- EditCompanyPreferencesLink` passes, including the new "signed-out prompt renders while loading" case and the updated "signed-in spacer while enabledIds load" case.
- `npm test -- EditCompanyPreferencesRow` passes, including the new "loading + unauthenticated shows both caption and callout" regression.
- `npm test` is clean across the whole suite.
- `npm run type-check` is clean.
- `npm run lint` is clean.
- `npm run build` completes without errors.
- **Manual signed-out check** on `npm run dev:vercel` at mobile width (~375 CSS px): hard-reload `/`, observe that the "Sign in to customize this feed to the companies you care about" caption appears on the first paint alongside the "New! Pick your companies" pill. No flash of callout-only state.
- **Manual signed-in check**: sign in through the real Auth0 flow, hard-reload `/`, observe that the "Showing jobs from…" caption still renders (possibly after a brief spacer while `enabledIds` load).
- **Manual dismiss check**: click the callout's X, reload, confirm the callout stays gone and the signed-out caption still renders. Clear `localStorage` key `newFeatureCallout:companyPreferences-2026-04:dismissed`, reload, confirm the callout is back.

---

## Critical files

| File | Role |
|---|---|
| `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx` | Site of the render-gate fix. Only substantive change in this PR. |
| `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesLink.test.tsx` | Update the "auth is loading" case to assert the new behavior; add a signed-in-loading case to protect contract 2. |
| `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesRow.test.tsx` | Add the end-to-end regression that would have failed on `main` (loading + unauthenticated → both caption and callout present). |
| `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesRow.tsx` | Read-only reference — confirms the callout is an unconditional sibling of the link, which is why the link's render-gate is the sole bug surface. |
| `src/frontend/src/features/auth/useAuth.ts` | Read-only reference — confirms `isAuthenticated` is `false` while `isLoading` is `true`, so falling through to the signed-out branch is correct. |

---

## Non-goals

- **No backend, DB, or serverless-function changes.** This is a frontend-only render-timing fix. The Postgres `user_enabled_companies_*` tables, Railway backend, and Vercel `api/*.ts` proxies are all untouched. Reviewers should expect the production verifiers to be **Vercel only** — Postgres and Railway are N/A for this PR.
- **No migrations.** Zero schema changes. Alembic is not invoked.
- **No new feature flags.** No `VITE_*` env var changes, no `AUTH_CONFIG` changes. The fix is unconditional and ships to all environments (prod, preview, auth-bypass QA builds) the same way.
- **No re-theming of the callout.** Copy ("New! Pick your companies"), color (`primary.light` / `primary.contrastText`), pill shape (`borderRadius: '999px'`), icon (`CloseIcon`), elevation, and `role="status"` are all unchanged.
- **No change to the callout's `storageKey` or `expiresAt`.** `"companyPreferences-2026-04"` and `"2026-05-02T00:00:00Z"` stay exactly as committed in PR #75.
- **No edits to `src/frontend/src/components/account/SelectedCompaniesPanel.tsx`.** The bug is confined to the Recent Jobs page's header row; the Account page's selected-companies panel is not implicated by the root cause.
- **No animation or transition polish.** If the one-time caption swap (signed-out-prompt → signed-in-caption) turns out to be visually noisy for users who actually sign in, that's a follow-up cosmetic PR, not this fix.
- **No change to the `NewFeatureCallout` component itself.** `NewFeatureCallout.tsx` and `dismissalStorage.ts` are not modified. All fixes live in the caller (`EditCompanyPreferencesLink.tsx`) and tests.
