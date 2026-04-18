# Per-User Company Selector Plan

## Context

The Recent Job Postings page (`src/frontend/src/pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx`) currently fetches jobs from every company in the hardcoded `COMPANIES` array (~100 companies, `src/frontend/src/config/companies.ts`) via `useGetAllJobsQuery()` (`src/frontend/src/features/jobs/jobsApi.ts`). A signed-in user has no way to scope this feed to the companies they care about.

**Goal:** Add a section on the Account page where a signed-in user picks the companies they want to follow. Persist the selection in a new per-user table (FK to users). The Recent Jobs page filters to only those companies. Empty selection means "show all" so existing users and first-time users see the unchanged default experience.

**Deployment:** Backend runs on **Railway** (auto-deploys from GitHub `main`). Railway has the Railway CLI + MCP available. Schema creation rides along with the backend deploy via the existing `init_schema()` call in the FastAPI lifespan — no separate migration step. Frontend auto-deploys via Vercel.

**Execution model:** This plan is designed for **multiple agents working in parallel**. The "Shared Contracts" section below freezes the HTTP wire format, Redux state shape, and hook signature so every unit can be built independently. Units list explicit **Prerequisites**, **Owned files**, **Shared-file edits** (minimize conflicts), and **Done when** criteria. Agents should pick one unit, stay inside its owned files, and verify against the contract before opening a PR.

---

## Shared Contracts (frozen — all units must match)

### HTTP API

```
GET  /api/users/enabled-companies
     → 200 { "companyIds": string[] }
     → 401 if unauthenticated

PUT  /api/users/enabled-companies
     body { "companyIds": string[] }
     → 200 { "companyIds": string[] }   # echoes saved list, canonicalized (deduped, sorted)
     → 400 if body is malformed (not a JSON array of strings)
     → 401 if unauthenticated
```

- Full-replace semantics (PUT overwrites the entire set for the user). Simpler than per-item POST/DELETE and matches the existing `PUT /api/users` display-name endpoint.
- Backend does NOT validate that IDs exist in the frontend `COMPANIES` config — the company list is owned by the frontend. Backend just persists strings. Unknown IDs on the frontend are simply ignored when filtering.
- Backend deduplicates and sorts the list before writing/returning. This makes the round-trip idempotent and gives clients a stable equality check for "is form dirty?".
- Routing already works: `vercel.json` rewrites `/api/users/:path(.*)` → `/api/users?path=:path`, and `api/users.ts` joins the path onto `${BACKEND_URL}/api/users/` and forwards `Authorization`. No new Vercel function or rewrite rule is needed.

### Redux state shape

```ts
// Slice name: "enabledCompanies"
interface EnabledCompaniesState {
  ids: string[] | null;   // null = not-yet-loaded (treat as "all enabled")
  loading: boolean;
  error: string | null;
  // dirty flag lives in local component state, not the slice
}
```

Semantics:
- `ids === null` → **treat as "all enabled"**. Covers not-loaded, signed-out, and fetch-failed states. The Recent Jobs selector MUST NOT drop companies when `ids === null`.
- `ids === []` → **treat as "all enabled"** too. Empty selection is the opt-out default for users who have never saved preferences.
- `ids: [id1, id2, ...]` → **filter to only those**. Unknown IDs are ignored by the selector (no match in `byCompanyId`).

### Hook signature

```ts
// src/frontend/src/features/preferences/useEnabledCompanies.ts
function useEnabledCompanies(): {
  ids: string[] | null;
  loading: boolean;
  error: string | null;
  save: (companyIds: string[]) => Promise<void>;
  reload: () => void;
};
```

The hook is responsible for loading on auth change (signed-in → fetch, signed-out → reset to `null`). Components never call `fetchEnabledCompanies` / `updateEnabledCompanies` directly.

### Database table

```sql
CREATE TABLE IF NOT EXISTS user_enabled_companies_{env} (
    user_id TEXT NOT NULL REFERENCES users_{env}(id) ON DELETE CASCADE,
    company_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, company_id)
);
CREATE INDEX IF NOT EXISTS idx_user_enabled_companies_{env}_user_id
    ON user_enabled_companies_{env}(user_id);
```

Rationale: junction table (one row per selection) rather than JSONB array on users. More normalized, trivial `ON DELETE CASCADE`, room to add per-row metadata later (e.g. notification prefs). Composite PK on `(user_id, company_id)` prevents duplicates without a separate UNIQUE constraint.

---

## Work Units

### Unit 1 — Backend: schema, service, router, models, tests

**Status:** TODO
**Prerequisites:** none (can start immediately)
**Blocks:** Unit 2 end-to-end verification, Unit 5 deploy
**Can run in parallel with:** Unit 2, Unit 3, Unit 4 (contracts above are frozen)

**Owned files (create):**
- `src/backend/api/services/user_preferences_service.py` — CRUD
- `src/backend/api/tests/test_user_preferences_service.py` — service tests

**Shared-file edits (coordinate, small):**
- `scripts/shared/database.py` — extend `init_schema()` (append ~15 lines after the `users` table block around line 222)
- `src/backend/api/models.py` — add two Pydantic models
- `src/backend/api/routers/users.py` — add two endpoints to the existing router
- `src/backend/api/tests/test_users_router.py` — add cases for the new endpoints
- `src/backend/api/tests/conftest.py` — extend the users cleanup fixture to also truncate `user_enabled_companies_{env}`

**Schema addition (`scripts/shared/database.py`, inside `init_schema`):**

```python
# Immediately after the users table + indexes block
enabled_companies_table = f"user_enabled_companies_{env}"
users_table = _get_table_name(env, "users")
cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS {enabled_companies_table} (
        user_id TEXT NOT NULL REFERENCES {users_table}(id) ON DELETE CASCADE,
        company_id TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (user_id, company_id)
    )
""")
cursor.execute(f"""
    CREATE INDEX IF NOT EXISTS idx_{enabled_companies_table}_user_id
    ON {enabled_companies_table}(user_id)
""")
```

**Service (`src/backend/api/services/user_preferences_service.py`):**

```python
from psycopg2 import sql
from psycopg2.extensions import connection as Connection

def _table(env: str) -> str:
    return f"user_enabled_companies_{env}"

def list_enabled_companies(conn: Connection, env: str, user_id: str) -> list[str]:
    cursor = conn.cursor()
    cursor.execute(
        sql.SQL("SELECT company_id FROM {} WHERE user_id = %s ORDER BY company_id")
           .format(sql.Identifier(_table(env))),
        (user_id,),
    )
    return [row["company_id"] for row in cursor.fetchall()]

def set_enabled_companies(
    conn: Connection, env: str, user_id: str, company_ids: list[str]
) -> list[str]:
    # Canonicalize: dedupe + sort
    canonical = sorted(set(company_ids))
    cursor = conn.cursor()
    table = sql.Identifier(_table(env))
    try:
        cursor.execute(
            sql.SQL("DELETE FROM {} WHERE user_id = %s").format(table),
            (user_id,),
        )
        if canonical:
            cursor.executemany(
                sql.SQL("INSERT INTO {} (user_id, company_id) VALUES (%s, %s)").format(table),
                [(user_id, cid) for cid in canonical],
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return canonical
```

**Router endpoints (`src/backend/api/routers/users.py`, additions):**

```python
from ..services.user_preferences_service import (
    list_enabled_companies,
    set_enabled_companies,
)
from ..services.user_service import get_user_by_email  # new helper; add to user_service.py if absent
from ..models import EnabledCompaniesResponse, EnabledCompaniesUpdateRequest


@router.get("/enabled-companies", response_model=EnabledCompaniesResponse)
async def get_enabled_companies(
    request: Request,
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    env = request.app.state.env
    email = user.get("email")
    if not email:
        raise HTTPException(401, "Token missing required 'email' claim")
    row = get_user_by_email(conn, env, email)
    if row is None:
        # Not seen before — return empty; first GET /api/users will create the user
        return EnabledCompaniesResponse(company_ids=[])
    try:
        ids = list_enabled_companies(conn, env, row["id"])
    except psycopg2.Error:
        logger.exception("Failed to list enabled companies for user=%s", row["id"])
        raise HTTPException(500, "Failed to load enabled companies")
    return EnabledCompaniesResponse(company_ids=ids)


@router.put("/enabled-companies", response_model=EnabledCompaniesResponse)
async def update_enabled_companies(
    request: Request,
    body: EnabledCompaniesUpdateRequest,
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    env = request.app.state.env
    email = user.get("email")
    if not email:
        raise HTTPException(401, "Token missing required 'email' claim")
    row = get_user_by_email(conn, env, email)
    if row is None:
        raise HTTPException(404, "User not found")
    try:
        saved = set_enabled_companies(conn, env, row["id"], body.company_ids)
    except psycopg2.Error:
        logger.exception("Failed to save enabled companies for user=%s", row["id"])
        raise HTTPException(500, "Failed to save enabled companies")
    return EnabledCompaniesResponse(company_ids=saved)
```

If `get_user_by_email` is not already in `user_service.py`, add it (mirror the `UPDATE ... WHERE email` pattern in `update_user`).

**Models (`src/backend/api/models.py`, additions):**

```python
class EnabledCompaniesResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    company_ids: list[str]

class EnabledCompaniesUpdateRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
    company_ids: list[str]
```

**Test coverage:**
- Service: empty → set → list round-trip; set over existing set (replace); cascade delete when user row deleted; idempotence of `set_enabled_companies(same_list)` returns canonicalized
- Router: `GET` with no saved prefs returns `{companyIds: []}`; `PUT` then `GET` round-trips; `PUT` with dupes returns deduped+sorted; 401 without token; 400 on malformed body

**Done when:**
- `pytest src/backend/api/tests/test_user_preferences_service.py src/backend/api/tests/test_users_router.py -v` passes
- Local backend restart creates `user_enabled_companies_local` (verify via `mcp__postgres__query`)
- Manual `curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/users/enabled-companies` returns `{"companyIds": []}` for a fresh user

---

### Unit 2 — Frontend data layer: fetch helpers, slice, hook, store wiring

**Status:** TODO
**Prerequisites:** none (contract above is frozen; can start in parallel with Unit 1 against a stubbed backend)
**Blocks:** Unit 3 (needs slice state shape), Unit 4 (needs `useEnabledCompanies` hook)
**Can run in parallel with:** Unit 1

**Owned files (create):**
- `src/frontend/src/features/preferences/enabledCompaniesSlice.ts`
- `src/frontend/src/features/preferences/useEnabledCompanies.ts`
- `src/frontend/src/__tests__/features/preferences/enabledCompaniesSlice.test.ts`
- `src/frontend/src/__tests__/features/preferences/useEnabledCompanies.test.ts`

**Shared-file edits (coordinate):**
- `src/frontend/src/features/auth/authService.ts` — add `fetchEnabledCompanies` and `updateEnabledCompanies`
- `src/frontend/src/app/store.ts` — register the new reducer under key `enabledCompanies`

**Fetch helpers (`authService.ts` additions — mirror the existing `fetchCurrentUser` / `updateCurrentUser` pattern):**

```typescript
export async function fetchEnabledCompanies(
  token: string,
  signal?: AbortSignal
): Promise<string[]> {
  const response = await fetch('/api/users/enabled-companies', {
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
    signal,
  });
  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    throw new Error(detail || `Failed to fetch enabled companies (${response.status})`);
  }
  const body = await response.json();
  return body.companyIds as string[];
}

export async function updateEnabledCompanies(
  token: string,
  companyIds: string[]
): Promise<string[]> {
  const response = await fetch('/api/users/enabled-companies', {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ companyIds }),
  });
  if (!response.ok) {
    const detail = await extractErrorDetail(response);
    throw new Error(detail || `Failed to save enabled companies (${response.status})`);
  }
  const body = await response.json();
  return body.companyIds as string[];
}
```

**Slice (`enabledCompaniesSlice.ts`) — plain Redux Toolkit slice with async thunks:**

```typescript
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { fetchEnabledCompanies, updateEnabledCompanies } from '../auth/authService';

interface EnabledCompaniesState {
  ids: string[] | null;
  loading: boolean;
  error: string | null;
}

const initialState: EnabledCompaniesState = { ids: null, loading: false, error: null };

export const loadEnabledCompanies = createAsyncThunk<string[], string>(
  'enabledCompanies/load',
  async (token) => fetchEnabledCompanies(token)
);

export const saveEnabledCompanies = createAsyncThunk<
  string[],
  { token: string; companyIds: string[] }
>(
  'enabledCompanies/save',
  async ({ token, companyIds }) => updateEnabledCompanies(token, companyIds)
);

const slice = createSlice({
  name: 'enabledCompanies',
  initialState,
  reducers: {
    reset: (state) => { state.ids = null; state.loading = false; state.error = null; },
  },
  extraReducers: (b) => {
    b.addCase(loadEnabledCompanies.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(loadEnabledCompanies.fulfilled, (s, a) => { s.loading = false; s.ids = a.payload; });
    b.addCase(loadEnabledCompanies.rejected, (s, a) => {
      s.loading = false; s.error = a.error.message ?? 'Failed to load';
      // Leave ids as null so selector treats as "all enabled"
    });
    b.addCase(saveEnabledCompanies.fulfilled, (s, a) => { s.ids = a.payload; });
    b.addCase(saveEnabledCompanies.rejected, (s, a) => {
      s.error = a.error.message ?? 'Failed to save';
    });
  },
});

export const { reset: resetEnabledCompanies } = slice.actions;
export default slice.reducer;

// Selector — export here; Unit 3 imports it
export const selectEnabledCompanyIds = (state: { enabledCompanies: EnabledCompaniesState }) =>
  state.enabledCompanies.ids;
```

**Hook (`useEnabledCompanies.ts`):**

```typescript
import { useEffect, useCallback } from 'react';
import { useAuth } from '../auth/useAuth';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import {
  loadEnabledCompanies,
  saveEnabledCompanies,
  resetEnabledCompanies,
  selectEnabledCompanyIds,
} from './enabledCompaniesSlice';

export function useEnabledCompanies() {
  const { isAuthenticated, getToken } = useAuth();
  const dispatch = useAppDispatch();
  const ids = useAppSelector(selectEnabledCompanyIds);
  const { loading, error } = useAppSelector((s) => s.enabledCompanies);

  const reload = useCallback(() => {
    if (!isAuthenticated) { dispatch(resetEnabledCompanies()); return; }
    getToken().then((token) => { dispatch(loadEnabledCompanies(token)); });
  }, [isAuthenticated, getToken, dispatch]);

  useEffect(() => { reload(); }, [reload]);

  const save = useCallback(
    async (companyIds: string[]) => {
      const token = await getToken();
      await dispatch(saveEnabledCompanies({ token, companyIds })).unwrap();
    },
    [getToken, dispatch]
  );

  return { ids, loading, error, save, reload };
}
```

**Store wiring (`src/frontend/src/app/store.ts`):**

Add the reducer under the key `enabledCompanies`. Confirm `RootState` picks it up automatically via the existing inference pattern.

**Done when:**
- `npm test -- enabledCompaniesSlice` passes (reducer cases: pending/fulfilled/rejected/reset)
- `npm test -- useEnabledCompanies` passes (signed-in triggers load; signed-out triggers reset)
- `npm run type-check` clean
- Storybook/manual: dispatching `loadEnabledCompanies` populates `state.enabledCompanies.ids` in Redux DevTools

---

### Unit 3 — Recent Jobs selector filter

**Status:** TODO
**Prerequisites:** Unit 2 (needs `selectEnabledCompanyIds`) — can start against a mocked slice, but must integrate against the real one before merge
**Blocks:** Unit 5 E2E verification
**Can run in parallel with:** Unit 4

**Owned files (edit only — keep changes tight):**
- `src/frontend/src/features/filters/selectors/recentJobsSelectors.ts` — insert pre-filter upstream of `selectAllJobsFromQuery`
- `src/frontend/src/__tests__/features/filters/recentJobsSelectors.test.ts` — add cases

**Do NOT touch:**
- `src/frontend/src/features/jobs/jobsApi.ts` — v1 keeps fetching all companies (cache sharing with Companies page). Fetch-level filtering is a future optimization, out of scope.
- `RecentJobPostingsPage.tsx` — selector handles everything; the page stays identical.

**Selector change:** `selectAllJobsFromQuery` currently does `Object.values(data.byCompanyId).flat()`. Replace with a composed selector that first picks only keys present in `selectEnabledCompanyIds`:

```typescript
const selectEnabledByCompanyId = createSelector(
  [selectByCompanyIdFromQuery, selectEnabledCompanyIds],
  (byCompanyId, enabledIds) => {
    if (!enabledIds || enabledIds.length === 0) return byCompanyId; // null or [] = all
    const enabledSet = new Set(enabledIds);
    const filtered: typeof byCompanyId = {};
    for (const [companyId, jobs] of Object.entries(byCompanyId)) {
      if (enabledSet.has(companyId)) filtered[companyId] = jobs;
    }
    return filtered;
  }
);
// selectAllJobsFromQuery now flattens selectEnabledByCompanyId instead of the raw byCompanyId
```

**Test cases to add:**
- `ids === null` → selector returns all companies unchanged (default)
- `ids === []` → selector returns all companies unchanged (empty = opt-out)
- `ids === ['airbnb', 'stripe']` → only those two keys present
- `ids === ['nonexistent-id']` → selector returns empty (unknown IDs produce empty intersection, which is correct)
- Downstream `selectRecentJobsMetadata` / `selectRecentJobsTimeBasedCounts` reflect the filtered set (metrics drop accordingly)

**Done when:**
- `npm test -- recentJobsSelectors` passes including new cases
- Manually: set `enabledCompanies.ids` to `['airbnb']` via Redux DevTools → Recent Jobs list + metrics show only Airbnb

---

### Unit 4 — Account page UI (company picker)

**Status:** TODO
**Prerequisites:** Unit 2 (uses `useEnabledCompanies` hook) — can start against a mock hook, must integrate against the real one before merge
**Blocks:** Unit 5 E2E verification
**Can run in parallel with:** Unit 3

**Owned files (create):**
- `src/frontend/src/components/account/EnabledCompaniesSection.tsx` — the new section (new subfolder `components/account/` if needed)
- `src/frontend/src/__tests__/components/account/EnabledCompaniesSection.test.tsx`

**Shared-file edits (keep small):**
- `src/frontend/src/pages/AccountPage/AccountPage.tsx` — render `<EnabledCompaniesSection />` below the existing display-name Paper in a new Paper block

**Reuse (do not re-implement):**
- `MultiSelectAutocomplete` at `src/frontend/src/components/shared/filters/MultiSelectAutocomplete.tsx` — already used in `ListFilters.tsx`. Feed it `options = COMPANIES.map(c => c.name).sort()`.
- Map name ↔ id using `COMPANIES` (name is display, id is stored). Pass id arrays to `save()`, convert to names for the widget, convert back on change.
- Success/error alert + save-button patterns already in `AccountPage.tsx` for the display-name form — mirror the same UX (disabled until dirty, "Saving…" label while in-flight).

**Component sketch:**

```tsx
// Pseudocode — actual implementation mirrors AccountPage display-name section style
export function EnabledCompaniesSection() {
  const { ids, loading, error, save } = useEnabledCompanies();
  const [draft, setDraft] = useState<string[]>([]);      // company IDs
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Sync draft when loaded state changes
  useEffect(() => { setDraft(ids ?? []); }, [ids]);

  const idToName = useMemo(() => new Map(COMPANIES.map((c) => [c.id, c.name])), []);
  const nameToId = useMemo(() => new Map(COMPANIES.map((c) => [c.name, c.id])), []);
  const allNames = useMemo(() => COMPANIES.map((c) => c.name).sort(), []);
  const selectedNames = draft.map((id) => idToName.get(id)).filter(Boolean) as string[];

  const isDirty = /* deep-equal compare draft vs (ids ?? []) */;

  const handleSave = async () => { /* mirror display-name handleSave */ };
  const handleClear = () => setDraft([]);
  const handleSelectAll = () => setDraft(COMPANIES.map((c) => c.id));

  // Render Paper with heading, helper text "Leave empty to see all.",
  // MultiSelectAutocomplete, Select all / Clear buttons, Save button, alerts.
}
```

**UX details:**
- Heading: "Recent Jobs Companies"
- Helper text: "Pick which companies show up in your Recent Job Postings feed. Leave empty to see all."
- Buttons: `Select All`, `Clear`, `Save Changes` (disabled unless dirty or saving)
- Loading skeleton while `loading && ids === null`
- Success alert: "Preferences saved."

**Done when:**
- `npm test -- EnabledCompaniesSection` passes (loads state, dirty detection, save flow success + error)
- Manual: Account page renders the new section below the existing form; selecting/deselecting companies and clicking Save persists across a page reload
- `npm run type-check` clean

---

### Unit 5 — End-to-end verification + deploy

**Status:** TODO
**Prerequisites:** Units 1, 2, 3, 4 all merged to the feature branch
**Can run in parallel with:** n/a (last)

**Tasks:**

1. **Local E2E dry run**
   - `npm run dev:vercel`; sign in; `/account` → save a 3-company subset → verify `PUT /api/users/enabled-companies` 200 in DevTools Network
   - Reload `/account` → verify 3 chips re-render from `GET`
   - Navigate to `/` → verify Recent Jobs list + metrics show only those 3 companies
   - Clear selection + save → Recent Jobs returns to showing all companies
   - Sign out → Recent Jobs falls back to the default signed-out 3-job overlay (unfiltered)

2. **Railway backend deploy**
   - Push feature branch → merge to `main` → Railway auto-deploys
   - Monitor with Railway CLI / MCP: `mcp__railway-mcp-server__get-logs` until the new build is live
   - Confirm `init_schema()` ran cleanly via `mcp__postgres-prod__query`:
     ```sql
     SELECT column_name, data_type FROM information_schema.columns
     WHERE table_name = 'user_enabled_companies_prod' ORDER BY ordinal_position;
     ```
     Expect 3 columns (`user_id TEXT`, `company_id TEXT`, `created_at TIMESTAMPTZ`) + a PK constraint + the index

3. **Prod smoke test**
   - Hit the deployed frontend; sign in with the test account; save a subset; confirm the filter works end-to-end against `users_prod` and `user_enabled_companies_prod`
   - Run a quick row-count check: `SELECT COUNT(*) FROM user_enabled_companies_prod;` to confirm rows landed

4. **Rollback plan**
   - Table is additive with `CREATE TABLE IF NOT EXISTS`, so a failed deploy is safe to retry
   - If the feature needs to be disabled hot, revert the frontend deploy on Vercel — backend endpoints are harmless when unused
   - If a data issue appears, drop and recreate: `DROP TABLE user_enabled_companies_prod;` then redeploy; init_schema will recreate an empty table

**Done when:**
- Prod smoke test round-trip passes
- Railway logs show clean startup
- No regressions on the Companies page (separate fetch path, should be untouched)

---

## Critical files (single source to avoid merge conflicts)

Tracked here so two agents don't both edit the same file blindly.

| File | Unit | Edit type |
|---|---|---|
| `scripts/shared/database.py` | 1 | append in `init_schema` |
| `src/backend/api/models.py` | 1 | append 2 models |
| `src/backend/api/routers/users.py` | 1 | append 2 endpoints |
| `src/backend/api/services/user_service.py` | 1 | add `get_user_by_email` if absent |
| `src/backend/api/services/user_preferences_service.py` | 1 | **new file** |
| `src/backend/api/tests/test_users_router.py` | 1 | append cases |
| `src/backend/api/tests/test_user_preferences_service.py` | 1 | **new file** |
| `src/backend/api/tests/conftest.py` | 1 | extend cleanup fixture |
| `src/frontend/src/features/auth/authService.ts` | 2 | append 2 fetch helpers |
| `src/frontend/src/features/preferences/enabledCompaniesSlice.ts` | 2 | **new file** |
| `src/frontend/src/features/preferences/useEnabledCompanies.ts` | 2 | **new file** |
| `src/frontend/src/app/store.ts` | 2 | register reducer |
| `src/frontend/src/features/filters/selectors/recentJobsSelectors.ts` | 3 | insert pre-filter |
| `src/frontend/src/components/account/EnabledCompaniesSection.tsx` | 4 | **new file** |
| `src/frontend/src/pages/AccountPage/AccountPage.tsx` | 4 | render new section |

## Non-goals (explicitly out of scope for v1)

- **Fetch-level filtering** in `jobsApi.ts` (skip API calls for disabled companies). Future optimization; keeps cache sharing with Companies page intact for v1.
- **Per-user defaults** (e.g. a curated "starter pack" of companies on first sign-in). v1 defaults to "all enabled" so existing signed-in users notice nothing change.
- **Backend-side company catalog validation.** Frontend owns `COMPANIES`; backend stores opaque strings.
- **Notification-per-company preferences.** The junction table is designed to accept extra columns later, but v1 only stores enablement.
- **Bulk admin UI** or cross-user analytics. Pure per-user preference.

## Reference — existing patterns this plan mirrors

- Auth + user profile endpoints (`docs/implementations/auth0/PLAN.md`, Unit 2): fetch helpers in `authService.ts`, router in `users.py`, service in `user_service.py`, schema in `init_schema`. This plan follows the same layout, same conventions.
- Redux slice shape + async thunks: see any slice under `src/frontend/src/features/filters/slices/`.
- MUI multi-select: `src/frontend/src/components/shared/filters/MultiSelectAutocomplete.tsx` + usage in `ListFilters.tsx`.
