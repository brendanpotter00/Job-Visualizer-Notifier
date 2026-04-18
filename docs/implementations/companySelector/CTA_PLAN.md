# Recent Jobs → Account Page CTA Plan

## Context

The Recent Jobs page at `src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx` filters the feed to the companies a signed-in user has enabled on their Account page. Today there is no visible hint that this filter exists, and nothing nudges signed-out users toward signing in to customize the feed. Users who look at the `FetchProgressBar` and wonder *"why only these companies?"* or *"can I add more?"* have to guess.

This plan adds a small, contextual call-to-action that:

1. Signed-in — links to `/account` so users can edit their enabled companies.
2. Signed-out — invites sign-in so a new user discovers that personalization exists at all.
3. Stays quiet. It sits next to the progress bar, uses a text-button visual weight, and never draws the eye away from the jobs list itself.

No data-layer changes. Pure UI insertion + a tiny new component.

---

## Design direction

**Tone**: refined, utilitarian, *information-dense dashboard* — matching the rest of the app (MUI default palette, Paper-based sections, chip-heavy surfaces). This is not a moment for a hero banner. The CTA should feel like a caption beneath the progress bar, not an ad.

**Visual weight**:
- `variant="text"` button with a small leading icon. No filled button, no alert/banner, no dismissible toast.
- Sits flush-right under the progress bar accordion, aligned with the same horizontal edges so it reads as belonging to it.
- Signed-in state uses `color="primary"` (quietly inviting).
- Signed-out state uses `color="inherit"` with `text.secondary` to read as a gentle hint, not a marketing push.

**Icon**:
- Signed-in: `TuneIcon` (sliders) — universally understood as "adjust settings". Imported from `@mui/icons-material/Tune`.
- Signed-out: `LoginIcon` — matches the existing sign-in affordance pattern in `UserMenu.tsx`. Imported from `@mui/icons-material/Login`.

**Copy** (final choices, after considering alternatives):

| State | Copy | Reasoning |
|---|---|---|
| Signed-in | **"Modify company preferences"** | Matches the verb the Account page uses (`EnabledCompaniesSection`'s "Save Changes"); "preferences" is the term already used in the FRONTEND_REDESIGN plan ("`preferencesReady`", "Preferences saved."). |
| Signed-out | **"Sign in to choose your companies"** | Action-forward and concrete. Tested alternatives: "Sign in to modify company preferences" (too long, mirrors signed-in copy too closely — blurs the two states), "Sign in to personalize this feed" (vague), "Sign in to customize" (abstract). "Choose your companies" is what users are actually doing — naming the noun makes the value clear to a first-time visitor. |
| Signed-in (loading profile) | render nothing (or the same CTA — CTA is cheap, don't flicker). See *Loading behavior* below. |

**Contextual placement** — directly under the `FetchProgressBar` accordion, before `RecentJobsFilters`:

```
┌─────────────────────────────────────────┐
│ RecentJobsMetrics  (4 metric cards)     │
├─────────────────────────────────────────┤
│ FetchProgressBar  (accordion)           │
│        ↳ Modify company preferences  →  │   ← NEW
├─────────────────────────────────────────┤
│ RecentJobsFilters                       │
│ RecentJobsList                          │
└─────────────────────────────────────────┘
```

Right-aligned inside the same content column (`Container maxWidth="xl"`). No left-aligned heading, no accompanying explanatory text — the button IS the explanation.

---

## Component decomposition

One new component, `EditCompanyPreferencesLink`, colocated with the recent-jobs components:

```
src/frontend/src/components/recent-jobs-page/
├── EditCompanyPreferencesLink.tsx   ← NEW
├── RecentJobCard/
├── RecentJobsFilters.tsx
├── RecentJobsList/
└── RecentJobsMetrics/
```

**Why a dedicated component**: keeps the `useAuth` + `useNavigate` + conditional-copy logic out of `RecentJobPostingsPage.tsx`, which today is a clean orchestrator. Easy to unit-test in isolation. If a future iteration wants the same CTA on `/companies` (plausible — that page hits the same fetch path), it's a one-line import.

**Why not a shared/generic component**: the copy is specific to *this* surface. Making it configurable would be premature abstraction for a single caller.

### Props

None. The component reads auth state internally and navigates on click.

```ts
// No props — self-contained.
export function EditCompanyPreferencesLink(): JSX.Element | null;
```

### Internals

```tsx
import { Box, Button } from '@mui/material';
import TuneIcon from '@mui/icons-material/Tune';
import LoginIcon from '@mui/icons-material/Login';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../features/auth/useAuth';
import { ROUTES } from '../../config/routes';

export function EditCompanyPreferencesLink() {
  const { isAuthenticated, isLoading, login } = useAuth();
  const navigate = useNavigate();

  // While auth resolves, render a zero-height spacer to prevent layout shift
  // when the button pops in. See Loading behavior below for the tradeoff.
  if (isLoading) {
    return <Box sx={{ height: 36, mb: 1 }} aria-hidden />;
  }

  if (isAuthenticated) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
        <Button
          size="small"
          variant="text"
          color="primary"
          startIcon={<TuneIcon fontSize="small" />}
          onClick={() => navigate(ROUTES.ACCOUNT)}
          data-testid="edit-company-preferences-link"
        >
          Modify company preferences
        </Button>
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
      <Button
        size="small"
        variant="text"
        color="inherit"
        startIcon={<LoginIcon fontSize="small" />}
        onClick={() => { void login(); }}
        sx={{ color: 'text.secondary' }}
        data-testid="sign-in-to-edit-preferences-link"
      >
        Sign in to choose your companies
      </Button>
    </Box>
  );
}
```

Notes on the implementation:

- **`void login()`** — `login` returns a promise (Auth0 redirect); the void cast satisfies the linter rule against floating promises and matches the `UserMenu.tsx` pattern.
- **Signed-out click calls `login()` directly**, not `navigate('/account')`. Why: the Account page's own signed-out view is already a dead-end "Sign in to view your account" screen. Routing there is a useless detour. Calling `login()` kicks off the Auth0 redirect immediately, and on successful return the user lands back on `/` (the default post-login redirect), sees their (empty) filtered feed, and the CTA flips to its signed-in state. If product later decides the redirect should land on `/account`, that's a one-line `appState` tweak in `login()` — out of scope here.
- **`data-testid`s differ between the two states** — keeps tests explicit about which branch is exercised, rather than pattern-matching by label string.

---

## Wiring into `RecentJobPostingsPage.tsx`

One import + one JSX line, placed between `FetchProgressBar`/`Skeleton` and `RecentJobsFilters`:

```tsx
import { EditCompanyPreferencesLink } from '../../components/recent-jobs-page/EditCompanyPreferencesLink';

// …inside the data-loaded branch…
{data && (preferencesReady ? (
  <FetchProgressBar companyIdFilter={progressFilter} />
) : (
  <FetchProgressBarSkeleton />
))}
<EditCompanyPreferencesLink />   {/* ← NEW */}
<RecentJobsFilters />
<RecentJobsList />
```

**Why outside the `{data && ...}` block?** The CTA is about *personalization*, not *jobs data*. Showing it while jobs load (or even if jobs fail to load) still makes sense — the user can always go tweak their preferences, even if the current feed is broken. Rendering it unconditionally also avoids the CTA popping in late after jobs arrive, which would be a jarring second layout shift. Exception: we still return `null` / skeleton while *auth* is loading, because that's the one signal the component itself depends on.

**Why above `RecentJobsFilters`?** Preferences (which companies you see) are conceptually upstream of the per-session filters (search, location, department) applied to that set. Reading top-to-bottom, the visual order matches the data pipeline: progress → preferences CTA → session filters → list.

---

## Styling decisions

| Choice | Rationale |
|---|---|
| `variant="text"` (no background) | Banner/filled button would outshout the jobs list. Text button reads as secondary. |
| Right-aligned via `justifyContent: 'flex-end'` | Puts the CTA where toolbars/actions live in the rest of the app. Left-alignment would compete with the progress-bar chip alignment and look like a section heading. |
| `size="small"` | Matches the chip density of the progress bar above it. |
| `mb: 1` (not `mb: 2`) | Tight coupling to the progress bar; pushes the filters area down by only 8px. |
| No border, no Paper wrapper | The surrounding surface already provides structure; another border would be visual noise. |
| No trailing arrow icon (`>`) | MUI's text button with an icon is already directional enough. Chevron would over-decorate. |
| Distinct icon per state | Tune = settings; Login = sign-in. Different shapes telegraph the difference at a glance even before copy is read. |
| Signed-out: `color: text.secondary` | Signals "this is a hint, not a demand". Users who don't care can ignore it. |
| Signed-in: `color="primary"` | The user has opted in; they should have an easy-to-find way back to their settings. |

---

## Loading behavior

`useAuth().isLoading` is true for a brief window on cold page loads while Auth0's SDK rehydrates the session. Three options:

1. **Render nothing** — the button pops in late, causing a small vertical layout shift of `RecentJobsFilters` / `RecentJobsList` below it.
2. **Render a zero-height spacer** — reserves the 36px of vertical space; the button fades in without shifting anything below. ✅ *Chosen.*
3. **Render a skeleton** — overkill for a single text button; draws attention for no reason.

The spacer approach is one line (`<Box sx={{ height: 36, mb: 1 }} aria-hidden />`) and kills the layout shift. 36px = MUI `size="small"` Button height (`1.625rem` + vertical padding). The `mb: 1` matches the real button to keep the gap below identical.

---

## Accessibility

- `Button` is the right semantic element (interactive, keyboard-focusable, Enter/Space activate). Not a styled `<a>`, not a `<div>` with `onClick`.
- Icons are decorative (`fontSize="small"`, no standalone role). The visible label is the accessible name — no `aria-label` override needed.
- Copy is a full, readable sentence in both states; screen readers announce "Modify company preferences, button" / "Sign in to choose your companies, button". Both states convey purpose without the icon.
- Keyboard flow: the button falls naturally into tab order between the progress bar's accordion-summary (if expanded, the chips inside) and the filters below. No `tabIndex` override.
- Color contrast: `color="primary"` on the paper background is already 4.5:1+ per MUI defaults. `text.secondary` is ~4.6:1 — at the AA threshold but within compliance; acceptable for a non-essential hint, but note it in case design review asks.
- `aria-hidden` on the loading spacer prevents screen readers from announcing an empty element.

---

## Files to create / edit / leave alone

### Create

| Path | Purpose |
|---|---|
| `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx` | The new CTA component |
| `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesLink.test.tsx` | Unit tests (see *Test plan*) |

### Edit

| Path | Change |
|---|---|
| `src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx` | Import the new component; render it between `FetchProgressBar`/`Skeleton` and `RecentJobsFilters` |

### Leave alone

- `FetchProgressBar.tsx` — structure unchanged; we compose *around* it.
- `RecentJobsFilters.tsx`, `RecentJobsList.tsx`, `RecentJobsMetrics.tsx` — untouched.
- `AccountPage.tsx`, `EnabledCompaniesSection.tsx` — receiving page is unchanged.
- `useAuth.ts`, `useEnabledCompanies.ts`, `authService.ts`, any Redux slice — no data-layer touches.

---

## Test plan

Test file: `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesLink.test.tsx`

Mock pattern mirrors `AccountPage.test.tsx` (which already mocks `useAuth` at module level).

### Cases

1. **Signed-in renders the "Modify" variant**
   - `useAuth()` → `{ isAuthenticated: true, isLoading: false }`.
   - Assert `getByTestId('edit-company-preferences-link')` is visible, has text `/Modify company preferences/`, and is a `<button>`.

2. **Signed-in click navigates to `/account`**
   - Wrap in `MemoryRouter`; mock `useNavigate` to return a spy.
   - Fire `userEvent.click` on the button.
   - Assert the spy was called with `'/account'`.

3. **Signed-out renders the "Sign in" variant**
   - `useAuth()` → `{ isAuthenticated: false, isLoading: false }`.
   - Assert `getByTestId('sign-in-to-edit-preferences-link')` is visible with text `/Sign in to choose your companies/`.

4. **Signed-out click calls `login()`, not `navigate()`**
   - Fire click.
   - Assert `login` spy called once; `navigate` spy NOT called.

5. **Auth-loading renders a non-interactive spacer**
   - `useAuth()` → `{ isLoading: true, isAuthenticated: false }`.
   - Assert neither `data-testid` is present.
   - Assert no `<button>` is rendered in the component's subtree.

6. **No crash when `login()` rejects**
   - Mock `login` to reject. Click the signed-out button. Assert no uncaught error surfaces (`void` discard handles this); the component stays mounted.

### Also add to existing `RecentJobPostingsPage` test (if one exists — currently no test file)

Skipping page-level test additions since there's no `RecentJobPostingsPage.test.tsx` today. If/when one is added, it should assert the link component is rendered; that's beyond this PR's scope. Unit coverage on the isolated component is sufficient given how narrow the integration is (one import, one JSX line).

### Manual smoke test

1. Start dev server: `npm run dev:vercel`.
2. Signed-out: load `/` → CTA says "Sign in to choose your companies" → click → Auth0 redirect flow runs.
3. Signed-in: reload `/` → CTA flips to "Modify company preferences" → click → lands on `/account` with the `EnabledCompaniesSection` visible.
4. Visual check on a mobile-width viewport (~375px): button right-edge aligned with progress-bar content, no overflow.
5. With auth loading artificially slowed (throttle network to Slow 3G, or mutate `isLoading` in devtools): spacer reserves height; filters below don't jump when the button fades in.

---

## Edge cases & non-issues

1. **User clicks "Modify" while jobs are still loading.** `navigate('/account')` fires; the jobs fetch is cached by RTK Query and resumes on return. No special handling needed.
2. **User is signed-in but on a profile that failed to load.** The Account page handles its own profile-error state; this CTA just points them at the door.
3. **Bypass mode (`AUTH_CONFIG.bypassEnabled`).** `useAuthBypass` always returns `isAuthenticated: true`, so the CTA always shows the signed-in variant in QA/dev. Correct behavior — QA can exercise the flow.
4. **Auth disabled globally (`AUTH_CONFIG.isEnabled === false`).** Then `isAuthenticated` is always false and we show "Sign in…" forever. Correct: if auth is off, the CTA is inert, which matches the rest of the app's degraded state in that mode.
5. **A screen reader user navigating by landmarks.** The button sits in the main content region; not a landmark itself, which is fine — it's not a navigation anchor, it's an inline action.
6. **Future: CTA on `/companies`.** The component is already importable from elsewhere with zero changes. Defer the move to `shared/` unless/until a second caller materializes.
7. **Dark mode.** MUI `color="primary"` and `text.secondary` both respect the active palette. No custom `sx` color overrides that would break a theme switch.

---

## Anticipated pitfalls

- **`useNavigate` inside a component that gets rendered outside a router.** Not a risk in `RecentJobPostingsPage` (the app is wrapped in `BrowserRouter`), but tests MUST wrap with `MemoryRouter` — see the AccountPage test pattern.
- **Button ref/event races when `login()` triggers a full-page redirect.** The component unmounts cleanly via React's normal teardown; the rejected-promise test (#6 above) guards against any lingering thrown-error regression from `useAuth`.
- **Icon packaging.** `@mui/icons-material/Tune` and `.../Login` are already in the bundle (`Login` is used in `UserMenu.tsx`, `Tune` may or may not be — if it isn't, adding it pulls in ~1KB; negligible). Worst case we can swap to `SettingsIcon` which is certainly present.
- **Layout shift from the loading spacer mismatch.** If MUI ever changes its small-button default height, the 36px spacer drifts. Mitigation: the spacer would just be slightly off and the layout shift would be 1–2px, not visible. Not worth measuring dynamically.

---

## Done when

- [ ] `EditCompanyPreferencesLink.tsx` exists and compiles (`npm run type-check` clean).
- [ ] `RecentJobPostingsPage.tsx` renders it between `FetchProgressBar`/`Skeleton` and `RecentJobsFilters`.
- [ ] Signed-in copy: "Modify company preferences" with a `TuneIcon`, navigates to `/account` on click.
- [ ] Signed-out copy: "Sign in to choose your companies" with a `LoginIcon`, calls `login()` on click.
- [ ] Auth-loading state renders a 36px spacer with `aria-hidden` and no interactive element.
- [ ] All six unit tests pass: `npm test -- EditCompanyPreferencesLink`.
- [ ] `npm run lint`, `npm run type-check`, `npm test` all green.
- [ ] Manual smoke: signed-out and signed-in flows both work end-to-end in `npm run dev:vercel`.
- [ ] Visual check: CTA sits right-aligned flush under the progress bar, reads as a secondary hint not a banner.

---

## Out of scope

- Redirecting signed-in users to `/account` with a deep-link hash (e.g., `/account#companies`) to scroll the section into view. Possible future polish; `EnabledCompaniesSection` currently renders right below the display-name form on Account, so no scrolling is needed for an xl-viewport user.
- A "You have X of Y companies enabled" subtitle next to the CTA. Nice-to-have, but the `FetchProgressBar` header already shows `Loaded X/Y companies`, so duplicating the count here would be noisy.
- Adding the same CTA to `/companies` page. Easy follow-up if/when product asks.
- Dismissible/snoozable CTA for signed-out users. The button is already near-invisible by design; snoozing it would be overengineering.
