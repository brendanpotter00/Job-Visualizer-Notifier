# Feature Voting Page Plan

## Context

- Add a new "Vote for features" page under a new nav item in `NavigationDrawer.tsx` with two columns: (1) a hardcoded changelog with a multi-select tag filter, and (2) an auth-gated voting column where signed-in users upvote candidate features.
- Changelog is pure frontend config — a TypeScript array in `src/frontend/src/config/changelog.ts`. No backend table, no API. New changelog entries ship via code change.
- Voting is backed by two new Postgres tables: `features` (catalog of candidate features) and `feature_upvotes` (per-user, per-feature upvote rows). The schema records `user_id` for every upvote so the product owner can audit who voted for what.
- Upvote is a toggle: signed-in users can add an upvote (POST) and remove their own upvote (DELETE). There are no downvotes. Unsigned-in clicks surface the existing sign-in prompt (refactored into a shared primitive so one sign-in UX serves all sign-in prompts across the app).
- Mirrors the `auth0` + `companySelector` plans for shape. Ordering is strictly sequential: backend schema → backend API → Vercel proxy → frontend config → frontend data layer → page UI → nav/route wiring.
- Each unit is independently committable — compiles, type-checks, tests pass.

---

## Implementation rules

1. **Alembic autogenerate only.** Schema changes go in `src/backend/api/db_models.py` followed by `alembic revision --autogenerate`. **Never hand-write or hand-edit a revision file under `src/backend/alembic/versions/`.** The `features`/`feature_upvotes` ORM classes are the source of truth; the migration is a derived artifact.
2. **Changelog is frontend-only.** All changelog entries are hardcoded in `src/frontend/src/config/changelog.ts`. No backend.
3. **Voting requires a valid JWT on the backend.** Mutations use `get_current_user` (not `get_optional_user`). The frontend's sign-in modal check is UX convenience — a hand-crafted unauthenticated request must still 401.
4. **Schema records the upvoter.** `feature_upvotes.user_id` is a `NOT NULL` FK to `users(id)`. No anonymous upvote rows.
5. **One upvote per user per feature.** Enforced by composite PK `(feature_id, user_id)`.
6. **Toggle semantics.** `POST /api/features/{id}/upvote` is idempotent add; `DELETE /api/features/{id}/upvote` is idempotent remove. An already-upvoted user clicking the arrow un-upvotes.
7. **Frozen two-tag taxonomy.** `feature` and `technical` only for v1. Extending the enum is a deliberate code change in `config/changelog.ts` + filter-UI label update.
8. **Reuse existing sign-in UX.** The existing `SignInOverlay` (`src/frontend/src/components/shared/SignInOverlay.tsx`) is the app's sign-in entry point. Unit 6 extracts its core (`useAuth().login()` trigger + messaging + styled CTA button) into a shared primitive and adds a modal presentation mode — **do not build a new sign-in path**.

---

## Shared Contracts (frozen — all units must match)

### HTTP API

```
GET  /api/features
     → 200 { "features": [
         {
           "id": "string",              // short slug
           "title": "string",
           "description": "string",
           "createdAt": "ISO-8601",
           "upvoteCount": 0,
           "hasUpvoted": false          // true iff the authed user has upvoted; false for anonymous
         }
       ] }
     (works for anonymous AND authed — uses get_optional_user)

POST /api/features/{feature_id}/upvote
     → 200 { "featureId": "...", "upvoteCount": 12, "hasUpvoted": true }
     → 404 if feature_id does not exist
     → 401 if unauthenticated
     (idempotent; inserting a duplicate (feature_id, user_id) row is a no-op)

DELETE /api/features/{feature_id}/upvote
     → 200 { "featureId": "...", "upvoteCount": 11, "hasUpvoted": false }
     → 404 if feature_id does not exist
     → 401 if unauthenticated
     (idempotent; deleting a non-present row is a no-op)
```

- Response shapes use camelCase (matches existing `users` router via `to_camel` alias generator).
- Proxy path: `vercel.json` rewrites `/api/features/:path(.*)` → `/api/features?path=:path`, and `api/features.ts` forwards to `${BACKEND_URL}/api/features/...` with the `Authorization` header — same shape as `api/users.ts`.

### Database schema (ORM-defined in `db_models.py`)

```sql
-- features_{env}: catalog of candidate features users vote on
CREATE TABLE features_{env} (
    id           TEXT PRIMARY KEY,                                  -- slug, e.g. "resume-match-ai"
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- feature_upvotes_{env}: one row per (feature, user) upvote
CREATE TABLE feature_upvotes_{env} (
    feature_id  TEXT NOT NULL REFERENCES features_{env}(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users_{env}(id)    ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (feature_id, user_id)
);
CREATE INDEX idx_feature_upvotes_{env}_feature_id ON feature_upvotes_{env}(feature_id);
CREATE INDEX idx_feature_upvotes_{env}_user_id    ON feature_upvotes_{env}(user_id);
```

- Table names carry the existing `_{env}` suffix — the post-`envAgnosticTables` convention has **not** landed on main, so new tables must match the current suffix pattern used by every other class in `db_models.py` (`job_listings_{_ENV}`, `users_{_ENV}`, etc.). When `envAgnosticTables` eventually lands, it will rename these two tables alongside the existing set in one sweep.
- `features.id` is a short human-readable slug (TEXT), not a UUID — stable, deep-linkable, and referenceable in SQL reviews.
- Seed data (starter candidate features) is inserted from a FastAPI lifespan startup routine using `INSERT ... ON CONFLICT (id) DO NOTHING`. **Do not hand-edit the Alembic revision to add seeds** (Rule 1).
- Starter features seeded in `features_seed.py` (Unit 2):
  1. `resume-match-ai` — "AI resume matching notifications" — "Upload your resume and get notifications when recently posted jobs match your background."
  2. `location-normalization` — "Location normalization" — "Normalize job-posting locations so 'SF / Bay Area / San Francisco, CA' collapses into one filter value."
  3. `mcp-server` — "Hosted MCP server" — "A deployed MCP server so Claude, Codex, and other agents can query job-posting data as a tool."

### Redux / RTK Query slice shape

Use **RTK Query** (`createApi`), matching the `jobsApi.ts` pattern.

```ts
// src/frontend/src/features/features/featuresApi.ts
export interface FeatureListItem {
  id: string;
  title: string;
  description: string;
  createdAt: string;
  upvoteCount: number;
  hasUpvoted: boolean;
}

export interface UpvoteMutationResult {
  featureId: string;
  upvoteCount: number;
  hasUpvoted: boolean;
}

export const featuresApi = createApi({
  reducerPath: 'featuresApi',
  baseQuery: fetchBaseQuery({
    baseUrl: '/api/features',
    prepareHeaders: async (headers, { extra }) => {
      const token = await (extra as { getTokenOrNull: () => Promise<string | null> })
        .getTokenOrNull();
      if (token) headers.set('Authorization', `Bearer ${token}`);
      return headers;
    },
  }),
  tagTypes: ['Features'],
  endpoints: (builder) => ({
    listFeatures: builder.query<FeatureListItem[], void>({
      query: () => '',
      transformResponse: (res: { features: FeatureListItem[] }) => res.features,
      providesTags: ['Features'],
    }),
    upvoteFeature: builder.mutation<UpvoteMutationResult, string>({
      query: (featureId) => ({ url: `${featureId}/upvote`, method: 'POST' }),
      async onQueryStarted(featureId, { dispatch, queryFulfilled }) {
        const patch = dispatch(
          featuresApi.util.updateQueryData('listFeatures', undefined, (draft) => {
            const f = draft.find((x) => x.id === featureId);
            if (f && !f.hasUpvoted) { f.hasUpvoted = true; f.upvoteCount += 1; }
          })
        );
        try { await queryFulfilled; } catch { patch.undo(); }
      },
    }),
    removeUpvote: builder.mutation<UpvoteMutationResult, string>({
      query: (featureId) => ({ url: `${featureId}/upvote`, method: 'DELETE' }),
      async onQueryStarted(featureId, { dispatch, queryFulfilled }) {
        const patch = dispatch(
          featuresApi.util.updateQueryData('listFeatures', undefined, (draft) => {
            const f = draft.find((x) => x.id === featureId);
            if (f && f.hasUpvoted) { f.hasUpvoted = false; f.upvoteCount = Math.max(0, f.upvoteCount - 1); }
          })
        );
        try { await queryFulfilled; } catch { patch.undo(); }
      },
    }),
  }),
});
```

`getTokenOrNull` is a module-scope helper registered via `thunk.extraArgument` in `store.ts`. A bootstrap hook called from `AppContent` writes the current `useAuth().getToken` into it. Returns `null` when no user is authenticated or when `getToken()` rejects — `GET /api/features` must be callable anonymously.

### Frontend changelog config file shape

```ts
// src/frontend/src/config/changelog.ts

export const CHANGELOG_TAGS = ['feature', 'technical'] as const;
export type ChangelogTag = (typeof CHANGELOG_TAGS)[number];

export interface ChangelogEntry {
  id: string;             // stable slug for React key
  title: string;
  description: string;    // plain text; no markdown parser in v1
  tags: ChangelogTag[];   // non-empty; at least one tag
  date: string;           // ISO-8601 (YYYY-MM-DD); used for sort-desc
}

export const CHANGELOG: readonly ChangelogEntry[] = [
  {
    id: 'accounts',
    title: 'User accounts',
    description:
      'Sign in with Google or email to save your company preferences and personalize your view across devices.',
    tags: ['feature'],
    date: '2026-04-18',
  },
  {
    id: 'saved-company-preferences',
    title: 'Saved company preferences',
    description:
      'Choose the companies you care about on the Account page — your selection persists across sessions and drives the Recent Jobs view.',
    tags: ['feature'],
    date: '2026-04-18',
  },
];
```

### Tag taxonomy (frozen)

| Tag | Use for |
|---|---|
| `feature` | A new user-visible capability, or an improvement to an existing one. |
| `technical` | Internal refactor, architecture change, dependency upgrade, or infra/deploy change — software-engineer-interesting, no user-visible product surface. |

Two-tag set for v1. Adding a tag is a deliberate code change in `src/frontend/src/config/changelog.ts` + a label-map update in the filter UI.

---

## Work Units

### Unit 1 — Backend: `features` + `feature_upvotes` schema (ORM + Alembic autogen)

**Status:** DONE
**Prerequisites:** none
**Owned files (create):**
- `src/backend/alembic/versions/<autogen>_add_features_and_upvotes.py` — **generated only**, via `alembic revision --autogenerate -m "add features and upvotes"`. Reviewable as-is; do not hand-modify structural ops.

**Shared-file edits:**
- `src/backend/api/db_models.py` — append two ORM classes `Feature` and `FeatureUpvote`:
  - `Feature.__tablename__ = f"features_{_ENV}"`, columns per schema above.
  - `FeatureUpvote.__tablename__ = f"feature_upvotes_{_ENV}"`, `PrimaryKeyConstraint("feature_id", "user_id")`, FKs to `features_{_ENV}.id` and `users_{_ENV}.id` with `ondelete="CASCADE"`, indexes on both FK columns named `idx_feature_upvotes_{_ENV}_feature_id` / `idx_feature_upvotes_{_ENV}_user_id`.

**Done when:**
- `python -c "from src.backend.api.db_models import Feature, FeatureUpvote"` imports cleanly.
- `alembic revision --autogenerate -m "add features and upvotes"` produces a revision that only creates the two tables + indexes (no unexpected ops on other tables).
- `alembic upgrade head` against a fresh local DB creates both tables with the expected columns + constraints (verify via `mcp__postgres__query`).
- Existing backend tests still pass (`pytest src/backend/api/tests/`).

---

### Unit 2 — Backend: service + router + Pydantic models + seed + tests

**Status:** DONE
**Prerequisites:** Unit 1
**Owned files (create):**
- `src/backend/api/services/features_service.py` — `list_features_with_upvotes(conn, user_id: str | None)`, `add_upvote(conn, feature_id, user_id)`, `remove_upvote(conn, feature_id, user_id)`. All idempotent. `add_upvote` / `remove_upvote` raise `FeatureNotFound` when the `feature_id` doesn't exist.
- `src/backend/api/services/features_seed.py` — `seed_starter_features(conn)` with `INSERT ... ON CONFLICT (id) DO NOTHING` for the three starter candidates listed in Shared Contracts.
- `src/backend/api/routers/features.py` — new router with three endpoints, mirroring `users.py`:
  - `GET /` → `get_optional_user`; returns `FeatureListResponse`. Resolves `user_id` from token email when authed; passes `None` otherwise.
  - `POST /{feature_id}/upvote` → `get_current_user`; returns `FeatureUpvoteStateResponse`; 404 if feature missing.
  - `DELETE /{feature_id}/upvote` → same as POST but `remove_upvote`.
- `src/backend/api/tests/test_features_service.py` — service tests: empty state, add, remove, idempotent re-add, idempotent re-remove, count stays accurate, cascade-on-user-delete, cascade-on-feature-delete, `FeatureNotFound` on unknown id.
- `src/backend/api/tests/test_features_router.py` — router tests: anonymous GET returns `hasUpvoted=false` for all; authed POST toggles count up; authed DELETE toggles down; 401 without token; 404 on unknown feature_id; idempotent re-POST and re-DELETE.

**Shared-file edits:**
- `src/backend/api/models.py` — append `FeatureResponse`, `FeatureListResponse`, `FeatureUpvoteStateResponse` Pydantic models (camelCase aliasing, `upvote_count >= 0`).
- `src/backend/api/main.py` — `app.include_router(features.router, prefix="/api/features", tags=["features"])`. In the lifespan startup, call `seed_starter_features(conn)` after pool init. Guard with `try/except` so a partial seed failure never blocks app boot.
- `src/backend/api/tests/conftest.py` — cleanup fixture truncates `feature_upvotes` before `features` (FK order).

**Done when:**
- `pytest src/backend/api/tests/test_features_service.py src/backend/api/tests/test_features_router.py -v` passes.
- Local `curl http://localhost:8000/api/features` returns the three seeded features with `upvoteCount: 0, hasUpvoted: false`.
- Local authed `curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/features/resume-match-ai/upvote` returns `{ featureId, upvoteCount: 1, hasUpvoted: true }`, and a second POST is idempotent.

---

### Unit 3 — Vercel proxy: `api/features.ts`

**Status:** TODO
**Prerequisites:** Unit 2
**Owned files (create):**
- `api/features.ts` — copy of `api/users.ts` with the base path switched to `/api/features`. Forwards `Authorization`; forwards the request body for POST; DELETE has none. Uses `getBackendUrl(req)` + `forwardResponse(response, res)` from `api/utils/`.
- `src/frontend/src/__tests__/api/serverless/features.serverless.test.ts` — mirrors `users.serverless.test.ts`: GET without auth is proxied through, POST with auth forwards the header, upstream network failure surfaces as 502.

**Shared-file edits:**
- `vercel.json` — add two rewrites mirroring the `/api/users` pair:
  ```json
  { "source": "/api/features",            "destination": "/api/features" },
  { "source": "/api/features/:path(.*)",  "destination": "/api/features?path=:path" }
  ```
  Also add `/vote-features` → `/index.html` to the SPA-fallback rewrites.

**Done when:**
- `npm run build` succeeds.
- `npm run dev:vercel` locally: `curl http://localhost:3000/api/features` matches `curl http://localhost:8000/api/features`.
- `npm test -- features.serverless` passes.

---

### Unit 4 — Frontend changelog config + tag taxonomy

**Status:** TODO
**Prerequisites:** none (pure config)
**Owned files (create):**
- `src/frontend/src/config/changelog.ts` — `CHANGELOG_TAGS`, `ChangelogTag`, `ChangelogEntry`, `CHANGELOG` per Shared Contracts. Ships with the two real seed entries (accounts, saved-company-preferences).
- `src/frontend/src/__tests__/config/changelog.test.ts` — guards: every entry has ≥1 tag from the enum; `id`s are unique; `date`s parse; entries sort newest-first.

**Shared-file edits:** none.

**Done when:**
- `npm run type-check` clean.
- `npm test -- changelog` passes.

---

### Unit 5 — Frontend data layer: `featuresApi` RTK Query slice + store wiring

**Status:** TODO
**Prerequisites:** Unit 3
**Owned files (create):**
- `src/frontend/src/features/features/featuresApi.ts` — per Shared Contracts sketch.
- `src/frontend/src/features/features/getTokenOrNull.ts` — module-scope mutable token-getter. A bootstrap hook writes the real `getToken` into it at app start; returns `null` when no getter is registered or when `getToken()` rejects.
- `src/frontend/src/features/features/useFeaturesAuthBridge.ts` — hook called once at `AppContent` root. Registers `useAuth().getToken` into `getTokenOrNull`.
- `src/frontend/src/__tests__/features/features/featuresApi.test.ts` — mocked-fetch tests: list, upvote, remove; Authorization header sent when token available, omitted when not; optimistic update reverts on failure.
- `src/frontend/src/__tests__/features/features/useFeaturesAuthBridge.test.tsx` — verifies the hook writes `getToken` into the module helper.

**Shared-file edits:**
- `src/frontend/src/app/store.ts` — register `[featuresApi.reducerPath]: featuresApi.reducer`, concat `featuresApi.middleware`, set `thunk: { extraArgument: { getTokenOrNull } }` on `getDefaultMiddleware`.
- `src/frontend/src/app/App.tsx` — call `useFeaturesAuthBridge()` inside `AppContent` alongside `useEnabledCompanies()`.

**Done when:**
- `npm run type-check` clean.
- `npm test -- featuresApi useFeaturesAuthBridge` passes, including auth-header branches.
- Manual: `store.dispatch(featuresApi.endpoints.listFeatures.initiate())` populates `state.featuresApi.queries` in Redux DevTools under `npm run dev:vercel`.

---

### Unit 6 — Shared `SignInPrompt` primitive + modal mode (refactor `SignInOverlay`)

**Status:** TODO
**Prerequisites:** none (independent refactor that Unit 7 consumes)
**Owned files (create):**
- `src/frontend/src/components/shared/SignInPrompt/SignInPrompt.tsx` — **shared core**: headline, subtitle, lock icon, and a CTA button that calls `useAuth().login()`. Takes `title`, `subtitle`, `buttonText`, and an optional `onRequestClose` for the modal variant. Renders nothing if `!isEnabled || isLoading || isAuthenticated`.
- `src/frontend/src/components/shared/SignInPrompt/SignInPromptModal.tsx` — MUI `Dialog` wrapper around `<SignInPrompt>` with a close button. Props: `open`, `onClose`, plus the same message overrides the core accepts.
- `src/frontend/src/components/shared/SignInPrompt/index.ts` — barrel export.
- `src/frontend/src/__tests__/components/shared/SignInPrompt/SignInPrompt.test.tsx` — renders when unauth; hides when authed; renders nothing when auth loading; clicking the CTA calls `useAuth().login()`.
- `src/frontend/src/__tests__/components/shared/SignInPrompt/SignInPromptModal.test.tsx` — opens/closes via `open` prop; close button fires `onClose`; clicking the CTA calls `useAuth().login()`.

**Shared-file edits:**
- `src/frontend/src/components/shared/SignInOverlay.tsx` — refactor internals to delegate to `<SignInPrompt>` for the button + handleSignIn. The overlay retains its unique gradient + anchor-to-bottom positioning but no longer duplicates the `login()` logic or the message layout.
- `src/frontend/src/constants/messages.ts` — add `SIGN_IN_MODAL_MESSAGES` (separate keyset from `SIGN_IN_OVERLAY_MESSAGES`) so the modal's copy can differ from the overlay's without coupling them. Keep `SIGN_IN_OVERLAY_MESSAGES` as-is.

**Done when:**
- `npm run type-check` clean.
- `npm test -- SignInPrompt SignInOverlay` passes. Existing `SignInOverlay.test.tsx` still green (no behavior regression).
- Manual: `<SignInOverlay />` in `RecentJobsList` renders identically to before.

---

### Unit 7 — Page UI: layout, changelog column with tag filter, voting column with upvote cards, sign-in modal hookup

**Status:** TODO
**Prerequisites:** Units 4, 5, and 6
**Owned files (create):**
- `src/frontend/src/pages/VoteFeaturesPage/VoteFeaturesPage.tsx` — top-level page: `Container` + two-column responsive `Grid` (`md={6}` each, stacks on `xs`). Heading: "Vote for features".
- `src/frontend/src/pages/VoteFeaturesPage/ChangelogColumn.tsx` — cards per `CHANGELOG` entry, filtered by current tag selection. Uses existing `MultiSelectAutocomplete` from `components/shared/filters/MultiSelectAutocomplete.tsx` with `options = [...CHANGELOG_TAGS]`. Empty selection → show all. Entries sort by `date` desc. Each card shows title, date, description, and a row of `<Chip>`s (one per tag) with a color map.
- `src/frontend/src/pages/VoteFeaturesPage/VotingColumn.tsx` — `useListFeaturesQuery()` + `useUpvoteFeatureMutation()` + `useRemoveUpvoteMutation()`. Uses `LoadingState` / `ErrorState` / `EmptyState` from `components/shared/`. Renders one `<FeatureVoteCard>` per feature.
- `src/frontend/src/pages/VoteFeaturesPage/FeatureVoteCard.tsx` — Reddit-comment-style card: title, description, vote control (`IconButton` with `KeyboardArrowUpIcon`, filled/highlighted when `hasUpvoted`, count below). Click logic:
  - `!isAuthenticated` → opens `<SignInPromptModal>` (from Unit 6). No mutation fires.
  - `isAuthenticated && !hasUpvoted` → `useUpvoteFeatureMutation()`.
  - `isAuthenticated && hasUpvoted` → `useRemoveUpvoteMutation()`.
  - Disabled while mutation is in-flight.
- `src/frontend/src/__tests__/pages/VoteFeaturesPage/VoteFeaturesPage.test.tsx` — both columns render.
- `src/frontend/src/__tests__/pages/VoteFeaturesPage/ChangelogColumn.test.tsx` — no selection shows all; selecting `technical` shows only technical entries; newest-first sort.
- `src/frontend/src/__tests__/pages/VoteFeaturesPage/FeatureVoteCard.test.tsx` — anonymous click opens modal and does NOT dispatch; authed click dispatches upvote mutation; authed re-click on upvoted dispatches remove mutation; count updates optimistically; failure reverts.

**Shared-file edits:** none (routing + nav live in Unit 8 so this unit merges cleanly as a pure component set).

**Done when:**
- `npm run type-check` clean.
- `npm test -- VoteFeaturesPage ChangelogColumn FeatureVoteCard` passes.

---

### Unit 8 — Route registration + side nav entry + end-to-end verification

**Status:** TODO
**Prerequisites:** Unit 7
**Owned files (create):**
- `src/frontend/src/__tests__/components/layout/NavigationDrawer.test.tsx` (new file if one doesn't already exist; otherwise extend) — asserts the "Vote for features" nav item renders and routes to `/vote-features` on click.

**Shared-file edits:**
- `src/frontend/src/config/routes.ts` — add `VOTE_FEATURES: '/vote-features'` to `ROUTES` and a `NAV_ITEMS` entry:
  ```ts
  { path: ROUTES.VOTE_FEATURES, label: 'Vote for features', icon: 'ThumbUp' }
  ```
- `src/frontend/src/components/layout/NavigationDrawer.tsx` — extend the `IconName` union + `iconMap` to include `'ThumbUp': ThumbUpIcon` (import from `@mui/icons-material/ThumbUp`).
- `src/frontend/src/app/App.tsx` — register `<Route path={ROUTES.VOTE_FEATURES} element={<VoteFeaturesPage />} />` inside the `RootLayout` group.
- `vercel.json` — confirm `/vote-features` SPA fallback from Unit 3 is in place.

**E2E verification (local, via `npm run dev:vercel`):**
1. Hard-refresh `/vote-features` — page loads (SPA fallback works).
2. Anonymous: changelog renders both seed entries; tag filter narrows to `technical` (empty) and back to "all"; clicking an upvote opens the sign-in modal; network tab shows NO POST.
3. Sign in via One Tap or Auth0 redirect; modal no longer appears; upvote click fires POST, count → 1, arrow fills. Click again → DELETE, count → 0, arrow outlines.
4. Hard-refresh the page — state round-trips from backend (`hasUpvoted: true` persists for still-upvoted features).
5. Sign out → counts remain but `hasUpvoted` reads false for all.

**Deploy verification:**
- Railway deploy applies the Alembic revision on startup; via `mcp__postgres-prod__query` confirm `features` + `feature_upvotes` exist with the expected columns, FKs, and indexes, and that the three seeded features are present.
- Vercel deploy serves `/vote-features` and proxies `/api/features/*` correctly.

**Done when:**
- Full local + prod E2E pass.
- Nav drawer shows the new item and it highlights when active.
- `npm run type-check && npm test && npm run lint` all clean.

---

## Critical files

| File | Why it matters | Unit |
|---|---|---|
| `src/backend/api/db_models.py` | Source of truth for schema; Alembic autogen diffs against it. | 1 |
| `src/backend/alembic/versions/<autogen>_add_features_and_upvotes.py` | Migration applied on boot via `apply_alembic_migrations`. Never hand-edit. | 1 |
| `src/backend/api/routers/features.py` | Defines the three endpoints + auth gates (`get_current_user` for mutations, `get_optional_user` for list). | 2 |
| `src/backend/api/services/features_seed.py` | Seeds the three starter candidate features on every lifespan boot (idempotent). | 2 |
| `api/features.ts` + `vercel.json` | Vercel proxy + rewrite rules. Must forward `Authorization` like `api/users.ts`. | 3 |
| `src/frontend/src/config/changelog.ts` | Frozen tag enum + all changelog content. Every future changelog update is a PR here. | 4 |
| `src/frontend/src/features/features/featuresApi.ts` | Only place the frontend talks to the features backend; optimistic update lives here. | 5 |
| `src/frontend/src/components/shared/SignInPrompt/*` | Shared sign-in primitive; used by the overlay (refactored) and the new voting-page modal. | 6 |
| `src/frontend/src/pages/VoteFeaturesPage/*` | The page itself: two-column layout, tag filter, vote cards, modal hookup. | 7 |
| `src/frontend/src/config/routes.ts` + `components/layout/NavigationDrawer.tsx` + `app/App.tsx` | Registers the route + nav entry — without these the page is unreachable. | 8 |

## Non-goals (explicitly out of scope for v1)

- **Downvotes.** Upvotes only.
- **Comments on features.** No discussion, replies, or reactions beyond the single upvote.
- **User-facing feature CRUD.** Candidate features are seeded from `features_seed.py`. No admin UI.
- **Pagination / infinite scroll.** Assume <50 candidate features; `GET /api/features` returns them all.
- **Real-time updates.** No WebSocket / SSE. Counts update on page load and on the local user's own actions.
- **Changelog backend.** Pure frontend config — no DB, no API, no versioning beyond git.
- **Sort / search on the changelog beyond the tag filter.** Multi-select tag filter is the only affordance.
- **Rate limiting.** Relying on Auth0 JWT + the PK constraint. Abuse mitigation beyond the PK is deferred.
- **Tag expansion beyond `feature` + `technical`.** Future tags require a deliberate code change (per Rule 7).
