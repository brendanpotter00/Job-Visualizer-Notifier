# Company Selector UI Redesign Plan

## Context

The company selector on the Account page was built in Unit 4 of `docs/implementations/companySelector/PLAN.md` as a single `MultiSelectAutocomplete` dropdown plus a chip panel. With ~100 companies the dropdown feels like a haystack: adding five companies means clicking the combobox, scrolling, clicking, clicking again, and repeating. This redesign replaces it with two complementary affordances:

1. A **fast search-add input** that auto-adds the top match on Enter and clears itself, enabling a "type three letters, Enter, repeat" workflow.
2. A **collapsed-by-default accordion** that reveals every company as a toggleable chip grid for users who prefer browsing.

A clearly separated **selected companies panel** shows the current draft regardless of which affordance was used. Data layer, backend, Redux slice, and hook are unchanged — this is pure frontend UX refactor inside `EnabledCompaniesSection`.

**Scope boundaries**
- No changes to `useEnabledCompanies`, `enabledCompaniesSlice`, `authService`, backend routes, or `recentJobsSelectors`.
- No new npm dependencies — all needed primitives (`Autocomplete`, `Accordion`, `Chip`, `TextField`) already ship with `@mui/material`.
- `MultiSelectAutocomplete` is NOT modified or deleted — it's still used by `ListFilters.tsx` for locations/departments. The Account section simply stops importing it.

---

## Shared contracts (unchanged)

```ts
// From useEnabledCompanies.ts — still the source of truth
const { ids, loading, error, save, reload } = useEnabledCompanies();
// ids: string[] | null   (company IDs as stored in COMPANIES[].id)
// save(canonicalDraft: string[]): Promise<void>   (must be sorted + deduped)
```

The Save Changes button still calls `save(sortedDedupedIds)`; dirty detection still compares canonicalized draft vs saved. Tests at the hook/slice level continue to work as-is.

---

## Component decomposition

Five components in a single new subfolder, composed top-down:

```
EnabledCompaniesSection (orchestrator Paper)
├─ CompanySearchAddInput          // fast keyboard flow
├─ SelectedCompaniesPanel         // chip list w/ delete affordance
└─ BrowseCompaniesAccordion       // collapsed-by-default wrapper
   └─ CompanyChipGrid             // full toggleable chip grid
```

Each subcomponent is dumb (props in, callbacks out). `EnabledCompaniesSection` owns the draft state so the search input, selected panel, and accordion grid stay in sync regardless of which one you touch.

### `EnabledCompaniesSection` — orchestrator

Keeps today's responsibilities:

- Pulls `{ ids, loading, error, save }` from `useEnabledCompanies`.
- Syncs `draft` from `ids` via `useEffect`.
- Owns `isSaving`, `saveSuccess`, `saveError`.
- Computes `isDirty` via `canonicalDraft.join('|') !== canonicalSaved.join('|')` (this logic is already correct — keep it).
- Renders the Paper + heading + helper text + alerts + Save button exactly like today, mirroring `AccountPage.tsx`'s display-name Paper.
- Delegates input/browsing/selection rendering to the three child components.

**State shape choice:** Keep `draft` as `string[]` for API parity, but **derive a `Set<string>` via `useMemo`** and pass that set down to `CompanyChipGrid` and `CompanySearchAddInput` for O(1) membership checks. The grid iterates all ~100 companies on every render, so `.includes()` lookups would be O(n²); a memoized Set keeps it O(n).

```ts
const draftSet = useMemo(() => new Set(draft), [draft]);
```

Handlers exposed to children:
- `onToggleId(id: string)` — add if absent, remove if present. Used by the chip grid.
- `onAddId(id: string)` — used by the search input.
- `onRemoveId(id: string)` — used by the selected-panel delete clicks.
- `onSelectAll()`, `onClear()` — wired to the existing buttons.

Every handler clears `saveSuccess` so the success alert disappears the moment the user edits again (matches current behavior).

### `CompanySearchAddInput` — fast keyboard flow

**Recommended implementation:** MUI `Autocomplete` with `freeSolo={false}`, `autoHighlight`, `clearOnBlur={false}`, `blurOnSelect={false}`, controlled `inputValue`. Using `Autocomplete` instead of a bare `TextField + List` gives us the dropdown, keyboard navigation, highlight, and accessible option roles for free — and already works in the existing test assertions (`findByRole('option', { name: /airbnb/i })`).

Props:

```ts
interface CompanySearchAddInputProps {
  companies: Array<{ id: string; name: string }>; // full COMPANIES sorted by name
  selectedIds: Set<string>;
  onAdd: (id: string) => void;
}
```

Key wiring:

| Concern | Implementation |
|---|---|
| Hide already-selected from dropdown | `options = companies.filter(c => !selectedIds.has(c.id))` |
| Show "no matches" when filtered to zero | `noOptionsText="No companies match"` |
| Enter picks top highlighted match | `autoHighlight` + `onChange={(_, value) => { if (value) { onAdd(value.id); setInputValue(''); } }}` |
| Clear search after add | controlled `inputValue` state, reset in `onChange` |
| Keep focus on the input after Enter | `blurOnSelect={false}` + the input stays focused because the user never left it |
| Arrow keys navigate | default `Autocomplete` behavior |
| Escape closes dropdown | default `Autocomplete` behavior |
| Tab commits top match | `autoSelect={true}` commits highlighted on blur (optional; call out in tests if enabled) |
| Option label | `getOptionLabel={(c) => c.name}` |
| Stable key | `isOptionEqualToValue={(a, b) => a.id === b.id}` |
| Placeholder | `"Type a company name and press Enter"` |
| No chips inside the input | omit `multiple` — this is single-select-per-commit; the chips live in `SelectedCompaniesPanel` |

**Search filter:** use `Autocomplete`'s default `createFilterOptions({ matchFrom: 'any', trim: true, ignoreCase: true })`. This handles special characters, case folding, and partial matches without custom code. Names like `"Base Power Company"`, `"Apex Technology Inc"`, and `"happyrobot.ai"` (yes, with dot) work out of the box — default filtering does substring match.

**Edge behavior:**
- If the user types text that matches no company, pressing Enter is a no-op because `autoHighlight` has nothing to highlight and `Autocomplete.onChange` only fires for a selected option.
- If the user types and the input exactly matches one company (e.g. `"Vercel"` exact), `autoHighlight` still highlights the first (only) option, Enter commits it.
- If multiple match, `autoHighlight` highlights the first alphabetically (options come pre-sorted by name), Enter commits it. Arrow keys walk the list.
- After commit, controlled `inputValue` resets to `''`, the dropdown stays open or re-opens on next keypress depending on MUI version — either is acceptable.

### `SelectedCompaniesPanel` — current draft with delete

Props:

```ts
interface SelectedCompaniesPanelProps {
  selectedCompanies: Array<{ id: string; name: string }>; // sorted by name
  onRemove: (id: string) => void;
}
```

Renders the subtitle + count `Chip` + the box of chips with delete icons (`<Chip onDelete={() => onRemove(id)} color="primary" variant="filled" />`). The empty-state dashed box and copy (`"No companies selected. You'll see postings from all companies."`) port directly from today's code — keep the exact copy so help-docs / screenshots stay stable.

`data-testid` attributes are preserved to minimize test churn:
- `selected-count` on the count chip
- `selected-chip-{name}` on each selected chip

### `BrowseCompaniesAccordion` — collapsed-by-default wrapper

Pure presentational wrapper around MUI `Accordion`. The repo already uses `Accordion` in `FetchProgressBar.tsx`, so the imports and `ExpandMoreIcon` pattern are precedented.

Props:

```ts
interface BrowseCompaniesAccordionProps {
  selectedCount: number;
  totalCount: number;
  children: ReactNode; // the CompanyChipGrid
}
```

Renders:

```tsx
<Accordion disableGutters elevation={0} sx={{ border: '1px solid', borderColor: 'divider' }}>
  <AccordionSummary expandIcon={<ExpandMoreIcon />}>
    <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
      Browse all companies
    </Typography>
    <Typography variant="body2" color="text.secondary" sx={{ ml: 1 }}>
      {selectedCount} of {totalCount} selected
    </Typography>
  </AccordionSummary>
  <AccordionDetails>{children}</AccordionDetails>
</Accordion>
```

`defaultExpanded` is deliberately false — collapsed is the requested default.

### `CompanyChipGrid` — flex-wrap grid of toggleable chips

Props:

```ts
interface CompanyChipGridProps {
  companies: Array<{ id: string; name: string }>; // full sorted list
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
}
```

Implementation (single responsive flex-wrap, no `Grid` needed):

```tsx
<Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
  {companies.map((c) => {
    const selected = selectedIds.has(c.id);
    return (
      <Chip
        key={c.id}
        label={c.name}
        onClick={() => onToggle(c.id)}
        color={selected ? 'primary' : 'default'}
        variant={selected ? 'filled' : 'outlined'}
        size="small"
        data-testid={`browse-chip-${c.name}`}
        aria-pressed={selected}
        clickable
      />
    );
  })}
</Box>
```

- Filled+primary = selected; outlined+default = unselected.
- Click toggles — parent decides whether this is add or remove.
- `aria-pressed` makes it an accessible toggle button for screen readers.
- `size="small"` + `flexWrap: 'wrap'` gives a responsive layout on mobile automatically — chips wrap to the next line at whatever breakpoint they no longer fit.

---

## Files to create / edit / leave alone

### Create

| Path | Purpose |
|---|---|
| `src/frontend/src/components/account/CompanySearchAddInput.tsx` | Autocomplete-based search-add input |
| `src/frontend/src/components/account/SelectedCompaniesPanel.tsx` | Selected chips panel w/ delete |
| `src/frontend/src/components/account/BrowseCompaniesAccordion.tsx` | Accordion wrapper |
| `src/frontend/src/components/account/CompanyChipGrid.tsx` | Toggleable chip grid |

### Edit

| Path | Change |
|---|---|
| `src/frontend/src/components/account/EnabledCompaniesSection.tsx` | Swap `MultiSelectAutocomplete` for the new three-component layout; add `draftSet` memo; keep Paper/heading/alerts/save logic intact |
| `src/frontend/src/__tests__/components/account/EnabledCompaniesSection.test.tsx` | Rewrite interaction tests against the new DOM; keep hook-mock scaffolding, keep all data-flow assertions |

### Leave alone

- `MultiSelectAutocomplete.tsx` — still consumed by `ListFilters.tsx`.
- `useEnabledCompanies.ts`, `enabledCompaniesSlice.ts`, `authService.ts`, `store.ts` — data layer untouched.
- `AccountPage.tsx` — still renders `<EnabledCompaniesSection />` with no prop changes.
- `recentJobsSelectors.ts` — filtering behavior unchanged.

---

## MUI components used (no new deps)

All already imported elsewhere in the codebase:

- `Paper`, `Box`, `Stack`, `Typography`, `Button`, `Alert`, `CircularProgress` — already in `EnabledCompaniesSection`.
- `Chip` — already used; `onDelete`, `onClick`, `variant`, `color`, `aria-pressed` all standard.
- `Autocomplete`, `TextField` — already used in `MultiSelectAutocomplete`, `SearchTagsInput`.
- `Accordion`, `AccordionSummary`, `AccordionDetails` — already used in `FetchProgressBar.tsx`.
- `ExpandMoreIcon` from `@mui/icons-material/ExpandMore` — already used in `FetchProgressBar.tsx`.

---

## State shape inside `EnabledCompaniesSection`

```ts
const [draft, setDraft] = useState<string[]>([]);            // IDs, keeps save() signature
const [isSaving, setIsSaving] = useState(false);
const [saveSuccess, setSaveSuccess] = useState(false);
const [saveError, setSaveError] = useState<string | null>(null);

const draftSet = useMemo(() => new Set(draft), [draft]);     // O(1) for chip grid + search filter

const idToName = useMemo(() => new Map(COMPANIES.map((c) => [c.id, c.name])), []);
const sortedCompanies = useMemo(
  () => [...COMPANIES].sort((a, b) => a.name.localeCompare(b.name)),
  []
);

const selectedCompanies = useMemo(
  () =>
    sortedCompanies.filter((c) => draftSet.has(c.id)),        // already sorted by name
  [sortedCompanies, draftSet]
);

const canonicalDraft = useMemo(() => [...new Set(draft)].sort(), [draft]);
const canonicalSaved = useMemo(() => [...(ids ?? [])].sort(), [ids]);
const isDirty = canonicalDraft.join('|') !== canonicalSaved.join('|');
```

Why `string[]` + memoized `Set<string>` rather than `Set<string>` directly as state:
- `save()` takes `string[]` — keeping state as an array avoids conversion at call time.
- `canonicalDraft.join('|')` for dirty detection needs an ordered collection.
- The `Set` is a derived view, not a source of truth — memoization is cheap (~100 entries, recomputed only when `draft` changes).

---

## Keyboard behavior (precise contract)

Focus is on `CompanySearchAddInput`:

| Key | Behavior |
|---|---|
| **Any printable char** | Types into the input, filters the dropdown in real time (MUI default). Dropdown opens if not already open. |
| **ArrowDown** | Moves highlight to next option; opens dropdown if closed. |
| **ArrowUp** | Moves highlight to previous option. |
| **Enter** (1+ matches) | Commits the highlighted option (top match if none explicitly moved, because `autoHighlight` pre-highlights option 0). Fires `onAdd(id)`, clears `inputValue`, leaves focus on input. |
| **Enter** (0 matches) | No-op. `Autocomplete.onChange` does not fire with no highlighted option. |
| **Escape** | Closes the dropdown, leaves `inputValue` intact. Pressing Escape twice also clears the input (MUI default). |
| **Tab** | Moves focus to the next focusable element (the accordion summary). If `autoSelect` is on, also commits the highlighted option on blur; recommended **off** so tabbing past without committing is possible. |
| **Backspace in empty input** | No-op. Unlike `multiple={true}` Autocompletes, we don't want backspace to delete the last chip — deletion happens in `SelectedCompaniesPanel` only. |

Focus on `CompanyChipGrid` chips:

| Key | Behavior |
|---|---|
| **Tab** | Focus moves between chips (each `Chip` with `onClick` is focusable). |
| **Enter / Space** | Toggles the focused chip (MUI `Chip clickable` behavior). |

Focus on `SelectedCompaniesPanel` chips:

| Key | Behavior |
|---|---|
| **Tab** | Focus moves onto the chip, then onto its delete icon (MUI's `onDelete` renders a focusable `<CancelIcon>`). |
| **Enter** on delete icon | Removes the chip. |
| **Backspace / Delete** on chip | Also removes (MUI default for chips with `onDelete`). |

---

## Test plan

Test file: `src/frontend/src/__tests__/components/account/EnabledCompaniesSection.test.tsx`

### Keep as-is (data flow, still correct against the new DOM)

- `shows a loading spinner when loading and ids are not yet loaded`
- `shows the empty-state copy and zero count when nothing is selected`
- `disables the Clear button while the draft is empty`
- `ignores unknown company ids in saved state without crashing`
- `Select All populates the draft with every company id`
- `Clear empties the draft and makes it dirty relative to a non-empty saved list`
- `treats saved and draft as equal regardless of order (not dirty when order differs)`
- `shows success alert after a successful save` (rewire selection via new input)
- `shows error alert when save rejects` (rewire selection)
- `calls save with a canonicalized (sorted, deduped) id list` (rewire selection)
- `renders saved ids as chips with display names` — still valid; `selected-chip-Airbnb` testid is preserved.
- `removes a selection when the chip delete icon is clicked` — still valid; chip-with-delete pattern is unchanged in the selected panel.

### Rewrite (DOM changed — `getByLabelText('Companies')` no longer exists)

Replace queries of `getByLabelText('Companies')` with the new search input. Recommended query: `getByRole('combobox', { name: /search companies/i })` and label the Autocomplete's TextField `"Search companies"`.

- `renders the picker with no selected chips when ids is null` — query changes to the search combobox
- `renders the picker with no selected chips when ids is empty` — same
- `updates the selected-count chip when selections change` — use type-then-Enter flow
- `enables Save button when the draft differs from saved ids` — same

### Add (new behavior)

1. **Enter adds top match and clears input**
   - Type `"air"` → dropdown shows Airbnb → press `{Enter}` → `selected-chip-Airbnb` appears → assert the combobox value is empty string.
2. **Sequential fast-add**
   - Type `"str"` + Enter → Stripe chip. Type `"air"` + Enter → Airbnb chip. Assert both chips present + `selected-count` === 2.
3. **Enter with zero matches is no-op**
   - Type `"zzzzzz"` + Enter → no chip added, Save still disabled, input retains the typed text (or is handled per MUI default — test the "no chip added" invariant, not the input retention).
4. **Already-selected companies hidden from dropdown**
   - Start with `ids: ['airbnb']` → click the combobox → assert no `option` with name `/^airbnb$/i` appears. Type `"air"` → still no Airbnb option, possibly "No companies match".
5. **Accordion collapsed by default, expands to show chip grid**
   - Assert `browse-chip-Airbnb` is not visible initially. Click the accordion summary. Assert `browse-chip-Airbnb` now visible.
6. **Clicking a chip in the grid toggles selection**
   - Expand accordion → click `browse-chip-Airbnb` → `selected-chip-Airbnb` appears, Save becomes enabled.
7. **Clicking a selected chip in the grid removes it**
   - `ids: ['airbnb']` → expand → click `browse-chip-Airbnb` → `selected-chip-Airbnb` gone, Save enabled.
8. **Grid reflects selection visually**
   - With `ids: ['airbnb']`, expand accordion, assert `browse-chip-Airbnb` has `aria-pressed="true"` and `browse-chip-Stripe` has `aria-pressed="false"`.
9. **Selected panel delete and grid stay in sync**
   - Select Airbnb via search input → expand accordion → assert grid chip shows pressed → delete from selected panel → assert grid chip is now unpressed.
10. **Keyboard: arrow-down then Enter commits second option**
    - Type `"a"` (matches Airbnb, Anthropic, Affirm, Astranis, Applied Intuition, Airtable, Anduril, Apex Technology Inc, Apple…) → press `{ArrowDown}` once → press `{Enter}` → second alphabetical option is committed. (Makes sure `autoHighlight` + arrow nav works.)
11. **Mobile/narrow viewport chip wrapping** (optional, low-value)
    - Render in a narrow container; assert the grid box has `flex-wrap: wrap` in its computed style. This is really a CSS smoke test — skip if it turns out flaky.

### Existing tests to delete

None. Every current test can either stay or be rewired.

---

## Edge cases

1. **Special characters in company names.** `COMPANIES` has `"Apex Technology Inc"`, `"Base Power Company"`, `"happyrobot.ai"`, `"General Motors"`, `"True Anomaly"`. `Autocomplete`'s default `createFilterOptions` does case-insensitive substring match on the label string, so `"happy"` matches `"happyrobot.ai"`, `"inc"` matches `"Apex Technology Inc"`, and dots/spaces don't break anything. Test at least one: typing `"happy"` + Enter adds Happyrobot.
2. **Duplicate names.** I scanned `companies.ts` — all `name` strings are unique. No collision to resolve. If a future company were added with a duplicate name, the search input would highlight the first one alphabetically by id; fine behavior, not worth defending in code today.
3. **Draft syncs when `ids` arrives late.** Existing `useEffect(() => setDraft(ids ?? []), [ids])` covers this. The chip grid derives visual state from `draftSet`, so it also refreshes automatically. No change.
4. **User toggles a chip in the grid while the search input has typed text.** The input is independent from the grid — its `inputValue` is not cleared by a grid click. Acceptable: the user was typing, clicked a grid chip, their typed text is still there. If they now press Enter, it commits whatever is highlighted in the dropdown, which might or might not be what they want. This matches every "multi-affordance picker" I've seen; don't overbuild.
5. **User opens the accordion and selects via grid, then collapses.** The selected panel above the accordion continues to show the selection. That's the whole point of the separate panel.
6. **Save during grid interaction.** If the user clicks Save with the accordion open, the grid's `draftSet` equals `canonicalDraft` (after save's success callback propagates the new `ids`) so chips remain in their "pressed" state and `isDirty` becomes false. No flicker.
7. **Mobile (narrow viewport).** The chip grid is `flex-wrap: wrap`, `gap: 1`, `size="small"` — chips are ~28px tall and wrap as needed. With ~100 chips, the accordion body can get tall; that's fine because it's collapsed by default. The search input + selected panel stay at the top of the Paper, so the primary workflow works without ever expanding the accordion.
8. **Screen readers.** `aria-pressed` on grid chips makes state audible. The `Autocomplete` has `role="combobox"` + `aria-autocomplete` by default. The accordion summary has a real `button` role. `SelectedCompaniesPanel`'s delete icons inherit MUI's built-in `aria-label="delete"`.
9. **Reduced motion.** MUI's Accordion expand animation respects `prefers-reduced-motion`; no custom handling needed.
10. **Very fast typing followed by Enter.** Because `Autocomplete`'s filter runs synchronously on every keystroke and `autoHighlight` immediately selects option 0, there's no race between typing and Enter. The only risk is if React hasn't re-rendered the dropdown yet when the Enter fires — React batches events, so the re-render always completes before Enter's `onChange` fires.

---

## Dependencies and sequencing

This is a single-agent refactor. There is no parallelism to gain. Recommended order:

1. Create the four new files (`CompanySearchAddInput`, `SelectedCompaniesPanel`, `BrowseCompaniesAccordion`, `CompanyChipGrid`) as pure props-in/callbacks-out components. Each can be copied from its sketch above in ~30–60 lines.
2. Rewrite `EnabledCompaniesSection.tsx` to compose the four children. Keep everything outside the replaced `<Box sx={{ mb: 3 }}><MultiSelectAutocomplete ... /></Box>` + selected panel identical. Net diff is ~40–60 lines changed.
3. Rewrite interaction tests in `EnabledCompaniesSection.test.tsx`. The `vi.mock` for `useEnabledCompanies` stays identical; only the DOM queries change.
4. Run `npm run type-check`, `npm test -- EnabledCompaniesSection`, `npm run lint`.
5. Manual smoke on `/account`: fast-add five companies via Enter, open accordion, toggle one, save, reload, confirm persisted state.

No backend redeploy. No Redux/store changes. No schema changes.

---

## Anticipated pitfalls

- **`autoHighlight` vs `autoSelect`.** Easy to confuse. `autoHighlight` pre-highlights the first option without selecting it (Enter needed to commit) — this is what we want. `autoSelect` commits on blur; leave it off to avoid stealing ambiguous Tab-away moments.
- **Controlling `inputValue` vs `value`.** `Autocomplete` has both: `value` is the selected option, `inputValue` is the textbox content. We control `inputValue` (reset on add) but leave `value` uncontrolled (always `null` in effect — we fire `onChange` and ignore the persisted value). Alternative: `value={null}` controlled to always reset. Recommend controlled-null to avoid stale MUI internal state on rapid Enter presses.
- **Hidden selected options leak into `value`.** Because we filter `options` to exclude already-selected IDs, if we also tracked `value`, we'd have the "You have provided a non-existent option" warning. Solution: leave `value` controlled as `null` every render. Alternative: use `onChange` + `inputValue` only, never set `value`. Same net effect.
- **Accordion sx for borders.** `elevation={0}` + a manual border is the only way to get an accordion that doesn't look like a card-within-a-card inside the Paper. `FetchProgressBar` already does this; copy the pattern.

---

## Done when

- [ ] Four new files exist under `src/frontend/src/components/account/` and compile clean (`npm run type-check`).
- [ ] `EnabledCompaniesSection.tsx` imports zero references to `MultiSelectAutocomplete`.
- [ ] Typing `"str"` + Enter in the search input adds Stripe and clears the input.
- [ ] Typing a zero-match string + Enter adds nothing.
- [ ] Already-selected companies do NOT appear in the search dropdown suggestions.
- [ ] The accordion is collapsed on initial render and labeled `"Browse all companies"`.
- [ ] Expanding the accordion shows all ~100 companies as chips, with selected ones filled+primary and unselected outlined+default.
- [ ] Clicking a chip in the grid toggles its state and immediately reflects in the selected-chips panel above.
- [ ] Removing from the selected panel immediately updates the grid chip to unpressed.
- [ ] `Select All`, `Clear`, and `Save Changes` buttons behave exactly as today; dirty detection via canonicalized sort still works.
- [ ] Success alert (`"Preferences saved."`) and error alert still appear in the same place.
- [ ] All existing tests in `EnabledCompaniesSection.test.tsx` are either kept or rewritten to the new DOM; all new-behavior tests (search-add flow, hide-already-selected, accordion toggle, grid-sync) pass.
- [ ] `npm run lint`, `npm run type-check`, `npm test -- EnabledCompaniesSection` all green.
- [ ] `MultiSelectAutocomplete.tsx` is untouched and `ListFilters.tsx` still renders.
- [ ] Manual smoke: sign in, fast-add 3 companies via Enter, toggle one via the accordion, save, reload, confirm the selection persisted.

---

## Addendum: Recent Jobs progress-bar polish

While the Account-page redesign lives in `components/account/*`, the *payoff* for user preferences is the filtered FetchProgressBar on the Recent Jobs page (`/`). Three related fixes landed alongside this redesign so the two surfaces feel coherent.

### 1. Chip labels use formatted names, sorted alphabetically

`FetchProgressBar.tsx` previously rendered `company.companyId` (the raw kebab/lowercase slug — `spacex`, `andurilindustries`, `happyrobot.ai`). It now resolves the label via `getCompanyById(companyId)?.name ?? companyId` and sorts `visibleCompanies` by that display name with `localeCompare`, so chips render as `SpaceX`, `Anduril`, `Happyrobot` in A→Z order. Fallback to the raw id keeps the component resilient if progress reports a company that isn't in `COMPANIES` (e.g., a stale id).

Files touched:
- `src/frontend/src/components/companies-page/FetchProgressBar/FetchProgressBar.tsx` — import `getCompanyById`, sort in the `useMemo`, swap `company.companyId` → `displayName` in all three chip branches (success / error / pending).
- `src/frontend/src/__tests__/components/companies-page/FetchProgressBar/FetchProgressBar.test.tsx` — assertion strings updated to the formatted names (`SpaceX (100)`, `Notion`, `Palantir`, `Stripe`).

### 2. Gate the bar on preferences-ready to kill the "all companies" flash

On a cold load of `/`, `enabledCompanies.ids` starts as `null` and the recent-jobs selector semantics treat `null`/`[]` as "show all". That caused a ~200ms flash where the progress bar rendered chips for all 100+ companies before the user's preferences arrived and it collapsed to the enabled subset.

Fix: gate `FetchProgressBar` on a derived `preferencesReady` flag in `RecentJobPostingsPage.tsx`:

```ts
const { isAuthenticated, isLoading: authLoading } = useAuth();
const preferencesReady =
  !authLoading && (!isAuthenticated || enabledIds !== null);
```

Semantics:
- Signed-out (auth resolved, not authenticated) → `true` immediately; no preferences to wait for, bar renders right away with the unfiltered set.
- Signed-in → waits until `enabledIds` is non-null (load thunk fulfilled).
- Auth itself still resolving → `false`; hold everything.

### 3. Skeleton placeholder fills the `!preferencesReady` gap

Gating alone produced a jarring empty hole until preferences + jobs both landed. Added `FetchProgressBarSkeleton.tsx` — same outer box/spacing, `Skeleton` placeholders for the header text, progress bar, and ~24 chip-shaped rounded rectangles with varied widths (`CHIP_WIDTHS` cycle) so it reads as "companies loading" rather than a solid block.

Wiring in `RecentJobPostingsPage.tsx`:

```tsx
{data &&
  (preferencesReady ? (
    <FetchProgressBar companyIdFilter={progressFilter} />
  ) : (
    <FetchProgressBarSkeleton />
  ))}
```

Files:
- **Create** `src/frontend/src/components/companies-page/FetchProgressBar/FetchProgressBarSkeleton.tsx`.
- **Edit** `src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx` — import `useAuth` + `FetchProgressBarSkeleton`, add `preferencesReady`, swap the bare conditional for the skeleton/real ternary.

### Why this belongs next to the selector redesign

The selector redesign is how users *choose* their companies; the progress bar is where that choice becomes visible across the rest of the app. Shipping them together means: Account page workflow (type-Enter-Enter) → Save → navigate to `/` → immediately see a skeleton → swap to an alphabetized, named, filtered bar. No flash, no empty gap, no `spacex` slug leaking to the user.
