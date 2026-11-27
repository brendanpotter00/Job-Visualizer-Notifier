# Save default search: spike

A **Save default search** button next to **Reset Filters** on Recent Jobs.
It saves every current filter as the reader's default, so the page opens on it next time.

## Verdict

- **One saved filter set per user: confirmed.** Not a blocker.
- **No backend change. No Alembic migration.** Frontend only, so Vercel-before-Railway ordering does not matter.
- **Typed keywords are saved as a keyword list named "Default search"**, and both keyword pointers point at it.
- **STRATEGY.md:** no conflict. It gets a reader to their own filtered list faster; it acts only on their press.

## 1. One set per user

| Evidence | Says |
|---|---|
| `src/backend/api/db_models.py:820-826` | `user_saved_filters.user_id` is the primary key |
| `alembic/versions/20260621_052349_6df9297dcc67_...py:56` | `PrimaryKeyConstraint('user_id')` at creation |
| Later migrations `a1b2c3d4e5f6`, `c48b0f2e7d19`, `2e6f81ad4b57` | Add columns / update data only; the key never changes |
| `services/saved_filters_service.py:257`, `services/user_service.py:524` | Every write is `ON CONFLICT (user_id)` |
| `routers/saved_filters.py:94,116` | Only `GET ""` and `PUT ""`; no id, no list of sets |
| Prod (read-only, 2026-11-26) | `user_saved_filters_pkey = PRIMARY KEY (user_id)`; 37 rows |

Keyword lists are many per user, but they are keyword lists, not filter sets.

## 2. Where each Recent filter is saved today

| Recent filter | Slice field | Saved column | Shared with Companies? |
|---|---|---|---|
| Keywords | `searchTags` | `recent_active_keyword_list_id` (a pointer to a list) | Pointer is per page, but Saved Filters sets both together |
| Time window | `timeWindow` | `recent_time_window` | No (`trend_time_window` is separate) |
| Job category | `category` | `category` | Yes |
| Specialty | `subcategory` | `subcategory` | Yes |
| Level | `level` | `level` | Yes |
| Location | `location` | `locations` | Yes |
| `softwareOnly`, `employmentType` | dead fields | not saved | ignored by this feature |

**Gap: typed keywords.** Only a pointer to a keyword list is stored.

**Fix with no schema change:** keep keywords in a keyword list.

- No keywords → pointer `null`.
- Keywords already match a list exactly (the current one first, then user lists, then the built-in) → point at that list. No write.
- Otherwise → PATCH the user's list named **"Default search"**, or POST it if there is none. Point at it.
- Both `recent_active_keyword_list_id` and `trend_active_keyword_list_id` get the same id.
  - Why both: the Saved Filters page shows ONE active list "on all pages" and saves both pointers together. In prod, 0 of 37 rows have them differ. Setting only Recent would make that page's claim false.
- We never edit any list except the one named "Default search". Prod has 0 lists with that name today.

**What Saved Filters then shows:**

- Default time windows → Recent shows the saved window. Trend is unchanged.
- Category, level, locations → the saved values.
- Keyword lists → a "Default search" card holding the typed keywords, selected as the active list (or the reused list, selected).

## 3. When the button is grayed out

Disabled exactly when `isSameDefaultSearch(live, baseline)` is true.

- `live` = the Recent slice, normalized.
- `baseline`:
  - signed in → the saved row, with the Recent pointer resolved to tags;
  - signed out → the site defaults (`recentJobsFiltersSlice` initial state).

Equality rules:

- Lists compare as sets: order does not matter, duplicates collapse.
- `undefined` equals `[]`.
- A keyword is `text + mode`. Text is exact (case-sensitive), like the slice and backend dedupe.
- Time window compares exactly.
- A pointer to a missing list resolves to no keywords.
- Never saved = site defaults: the server's no-row answer (`all`, `[]`, `null`) normalizes to the same value as the slice's initial state. A unit test pins this.
- `softwareOnly` and `employmentType` are ignored.

Also disabled while: auth is loading, saved filters or keyword lists are still loading or failed, or a save is in flight.

## 4. What it does to the Companies page

Saving from Recent Jobs **also changes the Companies page's saved locations, job category, specialty, level, and keyword list**, because both pages share one saved copy of those.
It **does not** change the Companies page's time window.
The Companies page's live filters for those five fields update right away. Its live time window is left alone.

## 5. Signed-out flow

```
click (filters differ from site defaults)
  -> write pending search to sessionStorage (jvn.pendingDefaultSearch.v1, 30 min)
  -> signin_cta_clicked { location: 'save_default_search' }
  -> loginWithReturnTo('/jobs')            (Auth0 full-page redirect)
  -> back on /?code=&state=  (fresh page load, empty store)
  -> load: read pending once; hydrate the Recent slice from it
  -> HomeRoute -> /jobs
  -> signed in + saved filters + keyword lists + current user loaded
  -> new account? stamp onboarding with the search's answers
  -> save (same path as a signed-in click)
  -> clear pending; "Saved default search" shows
```

Why sessionStorage and not the URL: the URL sync (`features/filters/urlFilters.ts:26`) has no `subcategory` param, and would not carry feature B's company type either.

**Conflict 1: one-shot hydration.** `useHydrateSavedFilters` would apply the OLD saved default (or server defaults) over the slice.

- Fix: restore the pending search with `hydrateRecentJobsFilters` on the first effect of the page load, before saved filters arrive. Hydration is one-shot, so the later saved-filters hydration of the Recent slice becomes a no-op. This is the same trick `useRecentJobsUrlSync` uses for shared links.
- Mount the new hook in `AppContent` after `useRecentJobsUrlSync()` and before `useHydrateSavedFilters()`.
- The Companies slice still hydrates from the old row; the save then pushes the new shared fields into it (section 4).

**Conflict 2: first-sign-in questions.** A brand-new account has `onboardingCompletedAt === null`, so `OnboardingGate` would open the questions. Their answers would overwrite the search, and `OnboardingFlow`'s propagation clears the keywords.

- Fix: a pending search stands in for the questions.
  - `OnboardingGate` is not eligible for the whole page load when a pending search was found at load (`hadPendingDefaultSearchAtLoad()`, a module memo like `features/auth/returnTo.ts`). A memo, not a storage read, so clearing the pending mid-load cannot reopen the gate.
  - The apply hook sends `POST /api/users/onboarding` with the search's category, specialty, level and locations (`skipped: false`), then the full PUT. The PUT is last, so it wins.
  - If the stamp fails, the PUT still runs. The questions open on the next load, like a failed Skip today.
- `useOnboardingHold` is unchanged. It still holds until `GET /api/users` answers; the questions just never open.

**Other edges:**

- Sign-in cancelled (load resolves signed out): the search is still restored on screen, then the pending is cleared. Nothing is sent.
- Back from the sign-in page restores the page from the back/forward cache (no new load): `pageshow` with `persisted` clears the pending. Otherwise the next, unrelated sign-in in that tab would save the abandoned search over the reader's default.
- Reload mid-save: the pending is cleared only after the attempt, so a reload re-applies it. Same values, so it is safe.
- Expired or malformed pending: dropped.
- Sign-in redirect throws: clear the pending; show "Couldn't open sign-in. Try again."
- Auth not configured (`useAuth().isEnabled === false`): the button is not rendered.

## 6. After a save

- The PUT response goes into the `getSavedFilters` cache (`upsertQueryData`). A written list is patched into `getKeywordLists` (`updateQueryData`). So the button is disabled on the next render, with no flash while the refetch runs.
- Next to the button: a check and **"Saved default search"** (`role="status"`). It shows while the live filters still match what was saved. It is gone after the next change.
- Error: "Couldn't save your default search. Try again." (`role="alert"`). The button stays enabled.
- The save sends a snapshot taken at click time. An edit made during the save keeps the button enabled afterwards.
- Slices after a save:
  - Recent: untouched. It is the source, and pushing could undo an edit made during the save.
  - Companies: location, category, level, specialty, keywords set from the response. Time window untouched.

## 7. Build plan

### Files to add

`src/frontend/src/features/defaultSearch/`

- `defaultSearch.ts` (pure)
  - `DEFAULT_SEARCH_LIST_NAME = 'Default search'`
  - `interface DefaultSearch { timeWindow; searchTags: SearchTag[]; location; category; level; subcategory: string[] }`
  - `RECENT_LIST_FIELDS`: the ONE field map. Feature B adds one row.
    ```ts
    export const RECENT_LIST_FIELDS = [
      { filter: 'location', saved: 'locations' },
      { filter: 'category', saved: 'category' },
      { filter: 'level', saved: 'level' },
      { filter: 'subcategory', saved: 'subcategory' },
    ] as const;
    ```
  - `defaultSearchFromFilters(filters: RecentJobsFilters): DefaultSearch`: `undefined` → `[]`; every list field from the table.
  - `defaultSearchFromSaved(saved: SavedFilters, lists: KeywordList[]): DefaultSearch`: `recentTimeWindow`, `resolveActiveTags(recentActiveKeywordListId, lists) ?? []`, table fields.
  - `defaultSearchKey(s)`: JSON of `[timeWindow, sortedSet(mode:text), ...sortedSet(each table field)]`.
  - `isSameDefaultSearch(a, b)`: `defaultSearchKey(a) === defaultSearchKey(b)`. The button and the save both go through these.
  - `toSavedFiltersPayload(s, current, listId): SavedFilters`: a full object (the PUT is full-replace).
    - `recentTimeWindow` ← `s.timeWindow`
    - table fields ← `s`
    - both keyword pointers ← `listId`
    - `trendTimeWindow` ← `current`
  - `toRecentFiltersPatch(s): Partial<RecentJobsFilters>`: for the restore; empty lists → `undefined`.
  - `toOnboardingAnswers(s): OnboardingAnswers`: via `toRequestAnswers` (specialty only with SWE).
  - `planKeywordList(tags, currentId, lists)`: `none | reuse(id) | update(id) | create`, in the order of section 2. Name match is trimmed and case-insensitive, user lists only.
- `pendingDefaultSearch.ts`: `writePendingDefaultSearch`, `pendingDefaultSearchAtLoad` (read once per load, validated, TTL), `hadPendingDefaultSearchAtLoad`, `clearPendingDefaultSearch`, a test reset. Every storage call is in try/catch.
- `defaultSearchSlice.ts`: `{ saving: boolean; result: { kind: 'saved' | 'error'; key: string; message?: string } | null }`. Actions: `saveStarted`, `saveSucceeded(key)`, `saveFailed({ key, message })`, `reset`. Register in `app/store.ts` AND `test/testUtils.tsx`. A new slice, not `ui`, because many tests preload a partial `ui`.
- `useSaveDefaultSearch.ts`: `save(search, { current, lists }) → Promise<boolean>`:
  1. plan the list;
  2. POST or PATCH if needed. On POST 409, force-refetch keyword lists once and take the update path. On POST 422 (list cap), message "Too many keyword lists. Delete one in Saved Filters, then try again.";
  3. PUT `toSavedFiltersPayload`;
  4. patch both caches;
  5. dispatch `defaultSearchGraphActions(saved, lists)`;
  6. `saveSucceeded(defaultSearchKey(search))`.
- `useApplyPendingDefaultSearch.ts`: restore, discard, apply (section 5). It uses `useCurrentUser()` for the stamp and `setUser` to record it.

Also add:

- `src/frontend/src/components/recent-jobs-page/SaveDefaultSearchButton.tsx`
  - Outlined, small, the same sx as Reset (pull it into one const).
  - Placed to the right of Reset in the existing row; the row gets `flexWrap` + `useFlexGap`.
  - Label "Save default search", "Saving…" while saving.
  - Status and alert text beside it. The `role="status"` box is always mounted.
  - `CheckIcon` imported by path.

### Files to change

- `components/recent-jobs-page/RecentJobsFilters.tsx`: render the button.
- `features/filters/slices/recentJobsFiltersSlice.ts`: export the initial filters (the signed-out baseline).
- `features/savedFilters/propagateSavedFilters.ts`: add `defaultSearchGraphActions(saved, lists)` (graph location/category/level/subcategory + resolved tags; no time window).
- `features/savedFilters/useHydrateSavedFilters.ts`: the logout branch also dispatches `defaultSearch/reset`.
- `features/savedFilters/savedFiltersApi.ts`: `CompleteOnboardingArgs.step` becomes optional (the backend already takes `None`).
- `components/onboarding/OnboardingGate.tsx`: `eligible` adds `&& !hadPendingDefaultSearchAtLoad()`.
- `features/analytics/events.ts`: `SignInLocation` adds `'save_default_search'`.
- `app/App.tsx`: mount `useApplyPendingDefaultSearch()` between the URL sync and the hydration.
- Docs:
  - `src/frontend/AGENTS.md`: the `/jobs` bullet, the onboarding bullet, the sign-in `location` list.
  - `e2e/onboarding/CASES.md` and `.claude/skills/e2e-gate/sections/onboarding.md`: the new cases, and gate the new files.

### Tests to add (Vitest, Node 22.14.0, `npx vitest run`)

- `__tests__/features/defaultSearch/defaultSearch.test.ts`
  - each list field: `undefined` == `[]`; order-insensitive; duplicates collapse
  - keywords: order-insensitive; same text with another mode differs; case matters; time window matters
  - dead fields ignored
  - never saved: the server no-row literal (mirror of `default_saved_filters()`) equals the slice's initial state
  - built-in pointer resolves to its tags; a missing list resolves to none
  - `toSavedFiltersPayload`: trend window kept; both pointers set; every `SavedFilters` key present
  - `planKeywordList`: each branch, and the name match
  - **table coverage**: every array-valued key of the slice's initial state, minus `searchTags`, is a row in `RECENT_LIST_FIELDS`. This fails if feature B forgets its row.
- `__tests__/features/defaultSearch/pendingDefaultSearch.test.ts`: round trip; TTL; malformed or wrong version dropped; storage that throws; the memo stays true after a clear.
- `__tests__/features/defaultSearch/defaultSearchSlice.test.ts`: reducers.
- `__tests__/features/defaultSearch/useSaveDefaultSearch.test.tsx`: mock the `savedFiltersApi` hooks like `SavedFiltersPage.categoryLevel.test.tsx`.
  - no tags → no list call, pointers `null`
  - reuse current list / built-in → no list call
  - create, then PUT with the new id
  - PATCH an existing "Default search" list
  - POST 409 → refetch, then PATCH
  - POST 422 → cap message
  - PUT failure → `saveFailed`
  - success → caches patched, graph actions dispatched, Recent slice untouched
- `__tests__/features/defaultSearch/useApplyPendingDefaultSearch.test.tsx`
  - restore beats saved-filters hydration (Recent slice shows pending; hydration a no-op)
  - stamped account: one PUT, no onboarding POST, pending cleared
  - new account: onboarding POST with the four answers, then PUT; `setUser` stamp
  - stamp failure still PUTs
  - signed out after load: cleared, no request
  - started once (no double PUT on re-render)
- `__tests__/components/recent-jobs-page/SaveDefaultSearchButton.test.tsx`
  - signed in: disabled when equal; enabled after a change; disabled again after reverting in another order
  - "Saved default search" after a save, gone after the next edit; error shown and button enabled
  - signed out: disabled at defaults; click writes pending, fires `trackSignInClick('save_default_search')`, calls `loginWithReturnTo('/jobs')`; a throwing login clears pending and shows the error
  - not rendered when `isEnabled` is false
- `__tests__/components/recent-jobs-page/RecentJobsFilters.test.tsx`: the button sits beside Reset Filters.
- `__tests__/components/onboarding/OnboardingGate.test.tsx`: a pending search at load keeps the questions closed with a `null` stamp. Mirror: no pending → they open.
- `__tests__/features/savedFilters/propagateSavedFilters.test.ts`: `defaultSearchGraphActions` (no time-window action).
- `__tests__/features/savedFilters/useHydrateSavedFilters.test.tsx`: logout resets the default-search slice.

### Backend tests

None. No backend code changes. The full-replace PUT and keyword-list CRUD are already covered.

### e2e (onboarding section: it owns sign-in, fresh identities and the gate)

- **OB-U14, signed-in save.**
  - Stamped account on `/jobs`: the button is disabled.
  - Add a keyword and pick `24h`: the button is enabled. Click: "Saved default search", button disabled.
  - DB: `recent_time_window='24h'`, a "Default search" list with the keyword, both pointers on it, trend window unchanged.
  - New context: the filters hydrate to it and the button is disabled.
- **OB-U15, signed-out → new account.**
  - Signed out: SWE + Backend, Entry, San Francisco, a keyword. Click (the Auth0 navigation is aborted by the fence).
  - `signInContext` with a fresh identity; `page.goto('/jobs')` on the SAME page, so sessionStorage survives.
  - No questions; the filters equal the search; the DB is stamped and holds it.
  - New context: no questions, same filters.
- **OB-U16, signed-out → existing account.** A different saved default is replaced. The Companies trend window is unchanged.
- **OB-U17, decoy.** Signed-out click, then return still signed out: the search is shown once and nothing is saved. A reload shows site defaults.

Gates to run before "ready to test": `e2e/run.sh onboarding` and `e2e/run.sh subcategories` (it gates `RecentJobsFilters.tsx`).

## Decisions made without asking

- No migration and no backend change. Keywords live in a "Default search" keyword list.
- Both keyword pointers are set, so the Saved Filters page's "active on all pages" stays true.
- Only the Recent time window is saved. The Trend window is untouched.
- An existing list with exactly the same keywords is reused instead of copied.
- Signed out: the button is enabled only when the filters differ from site defaults.
- Hidden when auth is not configured.
- Confirmation is inline text beside the button, not a toast.
- A pending search skips the first-sign-in questions and stamps the account with the search's answers (`skipped: false`).
- Pending lives in sessionStorage for 30 minutes and is dropped once a load resolves signed out.
- Reset Filters still clears to the site defaults, not to the saved default search.
- New `defaultSearch` Redux slice. New sign-in CTA location `save_default_search`.
- The e2e cases go into the existing onboarding section rather than a new one.

## Risks

- **Onboarding metrics:** these new accounts count as `onboarding_completed` without an `onboarding_viewed`.
- **Not atomic:** the list write and the PUT are two requests. If the PUT fails after a PATCH of the current "Default search" list, the saved keywords changed and the rest did not. The error shows and the caches refetch, so the button stays truthful.
- **Name collision:** a hand-made list named "Default search" would be overwritten (0 in prod).
- **Companies page side effect:** its saved and live location, category, level, specialty and keywords change (section 4).
- **Sign-in in another tab** (for example email verification) loses the pending search, because sessionStorage is per tab. So does blocked storage.
- **Merge with feature B:** both PRs touch `RecentJobsFilters.tsx`, `types/index.ts`, the Recent slice, `SavedFilters`, and the onboarding flow. Whoever lands second adds B's row to `RECENT_LIST_FIELDS` (the coverage test forces it) and B's answer to `toOnboardingAnswers`.
- **Feature B deploy:** once B's field is in `SavedFilters`, this PUT sends it. B's backend must ship before B's frontend.
