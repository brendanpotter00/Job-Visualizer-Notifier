# New Feature Callout Plan

## Context

We recently shipped the per-user **Company Preferences** feature. Its entry point on the Recent Job Postings page is the caption rendered by `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx` — a small "Showing jobs from … · Customize" / "Sign in to customize this feed" line that sits directly under the page heading. New or returning users have no visual cue that this caption is a *new* entry point, so we want a small, dismissible "New!" callout tag that points to it.

The callout must be **modular and reusable**. A future "new feature" callout should be able to drop in anywhere by passing a `storageKey`, an `expiresAt`, and some CTA text. For this initial usage it will point to the Company Preferences link on the Recent Jobs page, render on desktop to the **right** of the link (flex row), and stack **under** the link on mobile (flex column).

The user asked for dismissal to persist "as a session key or something … once it's dismissed it won't come back after that." Those two requirements conflict: `sessionStorage` resets per tab, so dismissing in one tab would still show the callout in a new tab or a new window. We are deliberately deviating from the literal "session key" phrasing and using **`localStorage`** so the dismissal is durable across page loads, tabs, and browser restarts. The storage key will be namespaced per callout so multiple callouts can coexist without collision.

"New for 2 weeks" refers to the lifetime of the callout feature itself, not a per-user timer. We express this with an absolute `expiresAt` prop that the caller sets. For this PR the caller passes `2026-05-02T00:00:00Z` — two weeks after today (2026-04-18). After that instant, the component unconditionally renders nothing for every user, regardless of whether they dismissed it.

Styling follows the rest of the app: MUI v5, `sx` prop, theme breakpoints. Responsive layout is achieved by wrapping the link and the callout in a small flex container (column on mobile, row on desktop) rather than absolute-positioning the callout — that avoids z-index, overflow, and sticky-header footguns.

---

## Shared Contracts (frozen — all units must match)

### Component API (TypeScript)

The new component is exported as `NewFeatureCallout` from `src/frontend/src/components/shared/NewFeatureCallout/NewFeatureCallout.tsx`.

```ts
export interface NewFeatureCalloutProps {
  /**
   * Unique identifier used to namespace the localStorage dismissal key.
   * Required. Changing this value effectively resets dismissal for all users,
   * so treat it as stable per callout instance.
   *
   * Example: "companyPreferences-2026-04"
   */
  storageKey: string;

  /**
   * Absolute expiry instant for the "new" window. Once `Date.now() >= expiresAt`
   * the component renders null for everyone (dismissed or not). Required to
   * prevent stale "New!" tags from lingering indefinitely.
   *
   * Accepts a Date instance or an ISO-8601 string.
   */
  expiresAt: Date | string;

  /**
   * Short CTA text shown inside the callout pill. Kept terse (e.g. "New!
   * Pick your companies"). Plain string for v1; if rich content is needed
   * later, widen this to ReactNode.
   */
  label: string;

  /**
   * Optional click handler for the callout body (e.g. scroll to / focus the
   * feature it points at). Clicking the explicit dismiss X does NOT invoke
   * this handler. If omitted, the callout body is non-interactive.
   */
  onClick?: () => void;

  /**
   * Positioning intent. v1 supports only the one variant we need now. The
   * prop exists so future callers can request different placements without
   * changing the default behavior.
   *
   * Default: "desktop-right-mobile-below"
   */
  placement?: 'desktop-right-mobile-below';

  /**
   * Optional test id forwarded onto the outer wrapper for RTL queries.
   */
  'data-testid'?: string;
}
```

All props are consumed by name. No positional arguments. `expiresAt` is **required** — the component intentionally does not default to "never expires" because that is the exact footgun we are trying to prevent.

### LocalStorage key format

- Key: `newFeatureCallout:<storageKey>:dismissed`
- Value: an ISO-8601 timestamp string captured at dismissal time via `new Date().toISOString()` (not the literal `"true"`, so we can audit when users dismissed each callout).
- Read/write are wrapped in `try/catch`. In every error path (missing `window`, `QuotaExceededError`, disabled storage in private browsing, non-string stored value, JSON garbage), the component **must not throw** and **must treat the callout as not-dismissed**. We would rather show the callout than crash the page.

A tiny helper module `src/frontend/src/components/shared/NewFeatureCallout/dismissalStorage.ts` exposes:

```ts
export function isDismissed(storageKey: string): boolean;
export function markDismissed(storageKey: string): void;
```

Both are pure functions over `window.localStorage` and are the only place that touches storage — the component and tests import them.

### Render-nothing conditions

The component returns `null` when **any** of the following are true:

1. `typeof window === 'undefined'` (defensive SSR guard, even though this app is a pure SPA).
2. `Date.now() >= new Date(expiresAt).getTime()` (expired).
3. `isDismissed(storageKey)` returns `true`.
4. `expiresAt` fails to parse into a finite timestamp (defensive — treat as expired).

Order matters: the expiry and parse checks happen before the storage read so an expired callout never reads from `localStorage`.

### Responsive layout contract (wrapper approach)

We pick the **wrapper** approach over absolute positioning:

- A new component, `EditCompanyPreferencesRow`, lives at `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesRow.tsx`. It renders a `Box` with `sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, gap: 1, mb: 2 }}` containing `<EditCompanyPreferencesLink />` followed by `<NewFeatureCallout ... />`.
- `EditCompanyPreferencesLink` keeps rendering a `Typography` caption but we drop its own `mb: 2` so the wrapper owns vertical rhythm. That is the only change to the existing link component.
- `RecentJobPostingsPage` swaps `<EditCompanyPreferencesLink />` for `<EditCompanyPreferencesRow />`.

The callout itself does **not** use `position: absolute`. It is a normal inline-flex pill (`Paper` with `display: 'inline-flex'`, small padding, slight elevation). No z-index, no overflow issues, no reliance on the page's sticky layout.

### Visual spec

- Outer element: `Paper` (elevation 2), `sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5, px: 1, py: 0.25, borderRadius: '999px', bgcolor: 'primary.light', color: 'primary.contrastText' }}`.
- Body: `Typography variant="caption"` rendering the `label`. If `onClick` is set, the body is wrapped in a `ButtonBase` so the whole pill (minus the X) is clickable and keyboard-focusable.
- Dismiss button: MUI `IconButton size="small"` with `<CloseIcon fontSize="inherit" />` and `aria-label="Dismiss"`.

### Accessibility

- Dismiss button: `aria-label="Dismiss"` (frozen string — tests assert on it).
- Container: `role="status"` so assistive tech announces the new-feature pill without stealing focus (we want passive notification, not an alert). We pick `status` over `region`/`alert` because (a) the content is informational, (b) we do not want an interruption.
- If `onClick` is provided, the clickable body uses `ButtonBase` which gets native keyboard focus; otherwise the body is not focusable.
- The dismiss button is the last focusable child so keyboard users can Tab past the link, hit the callout body (if interactive), then hit Dismiss.

---

## Work Units

### Unit 1 — Build the reusable `NewFeatureCallout` component and wire it into the Recent Jobs page

**Status:** DONE
**Prerequisites:** None.

**Owned files (create):**
- `src/frontend/src/components/shared/NewFeatureCallout/NewFeatureCallout.tsx`
- `src/frontend/src/components/shared/NewFeatureCallout/dismissalStorage.ts`
- `src/frontend/src/components/shared/NewFeatureCallout/index.ts` (barrel re-export of `NewFeatureCallout` + its props type)
- `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesRow.tsx` (wrapper that stacks the link and the callout responsively)
- `src/frontend/src/__tests__/components/shared/NewFeatureCallout/NewFeatureCallout.test.tsx`
- `src/frontend/src/__tests__/components/shared/NewFeatureCallout/dismissalStorage.test.ts`
- `src/frontend/src/__tests__/components/recent-jobs-page/EditCompanyPreferencesRow.test.tsx`

**Shared-file edits (keep tight):**
- `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx` — remove the `mb: 2` from each returned `Typography`/placeholder `Box` so the new row wrapper owns vertical spacing. No other behavior changes; existing tests keep passing.
- `src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx` — replace the `<EditCompanyPreferencesLink />` render at line ~55 with `<EditCompanyPreferencesRow />` and update the import.

**Implementation notes:**

1. Implement `dismissalStorage.ts` first. Two functions, all `window` access behind `try/catch`, both no-ops on failure. Key format exactly `newFeatureCallout:${storageKey}:dismissed`; value is `new Date().toISOString()`.
2. Implement `NewFeatureCallout.tsx`:
   - Parse `expiresAt` with `new Date(...)` and guard `Number.isFinite(d.getTime())`.
   - Short-circuit returns for SSR, expired, parse-fail, and storage-dismissed in that order.
   - Keep dismissal in local component state (`useState`) seeded from `isDismissed(storageKey)` inside a `useState` initializer so the first render already reflects the stored value. When the user clicks X, call `markDismissed(storageKey)` and set state to `true`, which causes the component to return `null`.
   - Respect the "render null" contract on the *very first* render (no flash of content before the effect runs).
   - Wire `onClick` on a `ButtonBase` around the `Typography` label; `IconButton` sits outside that `ButtonBase` so clicking X does not trigger the body handler. `IconButton onClick` stops propagation defensively.
   - `role="status"` on the outer `Paper`, `aria-label="Dismiss"` on the `IconButton`.
3. Implement `EditCompanyPreferencesRow.tsx`:
   - Renders `<EditCompanyPreferencesLink />` and `<NewFeatureCallout storageKey="companyPreferences-2026-04" expiresAt="2026-05-02T00:00:00Z" label="New! Pick your companies" onClick={...} />`.
   - The `onClick` is optional for v1 — we can omit it and let users click the existing "Customize" / "Sign in" link. Recommend omitting `onClick` in the first cut to keep the callout purely informational. Document this decision inline in a `// NOTE:` comment.
   - Flex container `sx`: `{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, alignItems: { xs: 'flex-start', md: 'center' }, gap: 1, mb: 2 }`. This replaces the `mb: 2` that used to live on the link.
4. Tests (Vitest + RTL):
   - `dismissalStorage.test.ts`: round-trip set/read; read returns `false` for missing key; read returns `false` when stored value is non-ISO garbage; set never throws when `localStorage.setItem` throws (simulate by stubbing).
   - `NewFeatureCallout.test.tsx`: renders label and dismiss button by default; clicking dismiss removes the callout from the DOM and writes to `localStorage`; re-mounting with the same `storageKey` after dismiss renders nothing; `expiresAt` in the past renders nothing without reading storage (spy on `getItem`); malformed `expiresAt` string renders nothing; `onClick` prop is invoked when the body is clicked and is NOT invoked when dismiss is clicked; `aria-label="Dismiss"` and `role="status"` present.
   - `EditCompanyPreferencesRow.test.tsx`: renders both the link and the callout; asserts the wrapper has the responsive `flexDirection` sx (smoke check — matching the MUI sx object is OK via `toHaveStyle` on computed styles at a known viewport, or by asserting the `data-testid` wrapper exists and the callout is a sibling of the link).

**Done when:**
- `npm test -- NewFeatureCallout` passes.
- `npm test -- dismissalStorage` passes.
- `npm test -- EditCompanyPreferencesRow` passes.
- Existing `EditCompanyPreferencesLink` tests still pass after removing `mb: 2` (update the one or two test cases that asserted on that sx value if any — otherwise untouched).
- `npm run type-check` is clean.
- `npm test` is clean across the whole suite (768+ tests still green).
- Manual: on `/` at a desktop width (>= 900px), the callout appears to the right of the "Showing jobs from …" caption; at mobile width (< 900px) it stacks under. Clicking the X removes it and a page reload keeps it gone. Setting `localStorage.removeItem('newFeatureCallout:companyPreferences-2026-04:dismissed')` brings it back. Manually setting the `expiresAt` prop to a past instant (temporarily) confirms the callout vanishes.

---

## Critical files

| File | Role |
|---|---|
| `src/frontend/src/components/shared/NewFeatureCallout/NewFeatureCallout.tsx` | New reusable component implementing the callout, dismissal, and expiry logic. |
| `src/frontend/src/components/shared/NewFeatureCallout/dismissalStorage.ts` | Isolated `localStorage` helper (`isDismissed`, `markDismissed`) with defensive error handling. |
| `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesRow.tsx` | New responsive wrapper that stacks `EditCompanyPreferencesLink` and the callout (row on desktop, column on mobile). |
| `src/frontend/src/components/recent-jobs-page/EditCompanyPreferencesLink.tsx` | Existing link component — drop the `mb: 2` so the new wrapper owns spacing; no other changes. |
| `src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx` | Page integration point — swap `<EditCompanyPreferencesLink />` for `<EditCompanyPreferencesRow />`. |

---

## Non-goals

- **No server-side "seen callouts" record.** Dismissal is per-browser via `localStorage`. A user on a different device / profile will see the callout again until it expires.
- **No animation.** v1 is a static pill; any fade-in / fade-out or attention pulse is a follow-up.
- **No callout queue / prioritization system.** One callout at a time, each caller decides when to mount it.
- **No suppression based on "user already engaged with the feature."** We do not check whether a signed-in user has already visited `/account` and picked companies — the feature is tiny and over-engineering the visibility logic is not worth it. The 2-week `expiresAt` and the dismiss X together cover 99% of the annoyance surface.
- **No new `placement` variants beyond `desktop-right-mobile-below`.** The prop exists to keep the API open but v1 only ships the one we need.
- **No fetch-level or Redux integration.** Purely presentational plus one storage read/write; no slices, no thunks.
