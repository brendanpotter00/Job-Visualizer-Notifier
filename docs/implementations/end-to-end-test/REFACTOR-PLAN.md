# REFACTOR-PLAN — "Dune"-ifying onesecondswe (the strict rails)

Refactor plan for the Dune architecture described in `.lavish/dune-strict-plan.html`
(rules **R1–R10**) and `dune-contract.md`. Senior-architect stage. **No code changes here** —
this doc is the ordered spec the implementation stages follow.

Worktree root (all paths below are relative to it):
`/Users/bpotter/developer/personal/Job-Visualizer-Notifier/.claude/worktrees/end-to-end-tests/`

---

## Result — read this first

- **Scope = the strict rails + one proof-of-pattern pilot, NOT the 20-file feature migration.** The rails
  (dependency boundaries, coverage gate, `no-explicit-any`, useEffect ban, ruff, husky, import-linter,
  eslint promotions) are high-value, small-diff, and independently reviewable. The physical relocation of
  existing features is **deferred** — it is the big-diff, green-threatening part, and it **collides with the
  concurrent WebMCP e2e stage** (RUN1-SPEC hard-codes current paths like `features/jobs/keysetWalk.ts`,
  `features/filters/selectors/recentJobsSelectors.ts`). Moving those files now breaks that stage.
- **Every work unit stays GREEN** (`type-check` + `lint` + `test` + `build` + the `add-companies` e2e all pass)
  because I grounded every rule against the real tree first. The green-critical facts:
  - **Feature↛feature is already clean** — the only 3 "cross-feature" hits are inside *comments*, zero real import edges.
  - **Only 3 `no-explicit-any` live in product code** (`api/clients/baseClient.ts` ×2, `lib/logger.ts` ×1); the other 79 are in 6 test files.
  - **`features/` useEffect is confined to 8 allow-list hooks** (analytics, auth, saved-filters hydrate, enabled-companies) — all "external-store sync", all kept.
  - **No raw `useDispatch`/`useSelector` leak** outside `app/hooks.ts` — the Redux door already holds.
- **`foundation↛features` can only be enforced for the PURE base today** (`lib`, `config`, `constants`, `types`).
  `app/store.ts`, `components/shared`, `components/layout`, `hooks/`, `api/` all import features right now, so the
  full kernel rule is **deferred** behind slice auto-registration + the migration (WU-list §Deferred).
- **The pilot is `why`, not Recent Jobs.** It is the one user-facing feature with **zero WebMCP path-contract
  overlap**, so it proves R1 (folder) + R3 (reserved `feature.route.tsx` entrypoint) end-to-end at near-zero blast
  radius. Recent Jobs' exact-move mapping is fully specified but **deferred** (§Exact moves — deferred).
- **Two rules ship "grandfathered-green"**: R6 (`no-explicit-any=error`) exempts the 6 legacy test files; R7
  (import-linter) grandfathers the current `scripts → src.backend` back-edges. New violations are blocked; the
  backlog shrinks visibly. Breaking the backend↔scripts cycle is **deferred** (highest blast radius — strict-plan agrees).

### What you (Brendan) need to decide — 3 things, ordered
1. **Confirm the scope line**: rails + `why` pilot in this PR; all feature relocation (incl. Recent Jobs) in follow-ups. If you want Recent Jobs collocated *now*, it must be sequenced **after** the WebMCP e2e stage lands, or done jointly — say which.
2. **Confirm R6 test-file exemption** (product code = hard error; the 79 test-file `any`s stay `warn`/off as a shrinking backlog) vs. cleaning all 82 up front.
3. **Confirm ruff's one-time autoformat** is acceptable as its own mechanical, review-light commit (the only broad-touch diff in scope).

---

## Ground truth that shaped this plan

| Fact (verified in-tree) | Consequence for the plan |
|---|---|
| 3 layout axes: `components/` + `features/` + `pages/`; a feature is ~20 files across 8–9 dirs | Collocation is real work; do it per-feature, not big-bang |
| **0 real feature↛feature import edges** (3 hits are comments) | R2 feature-boundary rule is **green today** |
| Pure kernel today = `lib`, `config`, `constants`, `types` only | R2 `foundation↛features` enforced for the **pure base now**, full kernel **deferred** |
| `app/store.ts` imports all 14 feature slices/apis | Full kernel rule needs **slice auto-registration** first (deferred) |
| `components/shared` (14) + `components/layout` (5) import features | "shared/ui = foundation" is **aspirational**, not true yet — deferred |
| 82 lint warnings, **all** `no-explicit-any`; **only 3 in product code** | R6 flips to `error` green after a 3-line fix; tests exempted |
| `features/` useEffect = 15 uses in 8 allow-list hooks | R8 (`ban new useEffect in features/`) is **green** with those 8 exempted |
| No raw `useDispatch`/`useSelector` outside `app/hooks.ts` | R4 redux-door rule is **green today** |
| CI runs `test -- --run` (no `--coverage`); vitest thresholds already 80 | R5 = flip one CI flag; ratchet if any category is under |
| `eslint … --max-warnings 149` | R6 lowers the ceiling; product scope to 0 |
| backend imports `scripts.shared.*` ~30×; `scripts/run_scraper.py` + `scripts/one_off/*` import `src.backend` | R7 keeps `backend → scripts.shared`, **grandfathers** the back-edges, blocks new ones |
| No `.husky/`, no root `prepare`, no ruff/import-linter/pyproject at root | R9/R10 are pure additions |
| `src/backend/pyproject.toml` has mypy (`files=["api"]`, scripts silenced) | Extend mypy to scripts is **deferred** (scripts never type-gated) |
| Concurrent WebMCP stage (RUN1-SPEC) hard-codes `features/{jobs,filters,locations,companies,features,feedback,savedFilters,preferences,auth}` paths | Any feature the WebMCP tools reuse is **frozen** — pilot must avoid all of them → `why` |

---

## The foundation kernel (as enforced *now*)

`foundation/` is introduced as an **additive barrel layer** — new `index.ts` re-export modules over the
already-pure kernel. **No product file physically moves in this plan.** New/migrated code imports from
`foundation/*`; legacy imports keep working untouched.

```
src/frontend/src/foundation/          # NEW — additive barrels only
├── index.ts        # re-exports the surfaces below
├── hooks.ts        # export { useAppDispatch, useAppSelector } from '../app/hooks'
├── errors.ts       # export { extractErrorMessage } from '../lib/errors'
├── ui.ts           # export LoadingState/ErrorState/EmptyState from '../components/shared/*'
├── http.ts         # export the base fetch/client helpers from '../lib' / '../api'
└── types.ts        # export the shared model types from '../types'
```

**The dependency-cruiser "foundation" node** (for the boundary rule) = the **directly-clean** set:
`src/frontend/src/{lib,config,constants,types}/**` **plus** `app/hooks.ts` **plus** the new `foundation/**`.
Rule enforced now: *these must not have a **direct** import into `features/**`, `pages/**`, `components/**`, or `hooks/**`.*
Verified direct-clean today (`app/hooks.ts` → `app/store.ts` is a store-type edge, not a feature edge).

**The two hard rules (Dune):**
- **foundation ↛ features** — enforced for the pure base above; full kernel deferred.
- **feature ↛ feature** — enforced across all 14 `features/*`; **green today**.

`webmcp/**` is classified as a **cross-cutting tool layer** (it wraps features by design) and is exempt from
the feature-boundary rule — it may import `features/**` and `foundation/**`, nothing may import it except `main.tsx`/`app`.

---

## R1–R10 → mechanism → status

| Rule | Mechanism | Status in this plan |
|---|---|---|
| **R1** Feature collocation, one folder each | Convention doc + PR template + `feature.route.tsx` glob + dep-cruiser "self-contained" check | **Convention + pilot (`why`) in scope**; bulk migration deferred |
| **R2** foundation↛features, feature↛feature | `dependency-cruiser` in CI | **feature↛feature enforcing**; foundation↛features **enforcing on pure base**, full deferred |
| **R3** Entrypoints discovered from reserved files | glob `features/*/feature.route.tsx`, additive registry alongside `routes.ts` | **In scope** (pilot uses it; `routes.ts` stays for the rest) |
| **R4** Redux only via the door; no hand-rolled fetch | eslint `no-restricted-imports` (redux) + `no-restricted-syntax` | **Redux-door half enforcing (green)**; fetch-lifecycle custom rule deferred |
| **R5** Coverage gate actually runs | CI `test -- --run --coverage` (thresholds 80) | **In scope**, ratcheted |
| **R6** `no-explicit-any=error`, drop the ceiling | eslint `error` (product) + `--max-warnings 0` | **In scope** — fix 3 product sites; 6 test files exempted |
| **R7** No backend↔scripts cycle | `import-linter` contract in CI, grandfather back-edges | **Contract enforcing (green)**; cycle-break deferred |
| **R8** No new useEffect in `features/` | eslint `no-restricted-syntax` scoped to `features/**`, 8-file allow-list | **In scope (green)** |
| **R9** Python lint on backend + scripts | `ruff check` in both CI jobs + one-time autoformat; mypy→scripts | **ruff in scope**; scripts-mypy deferred |
| **R10** Same checks locally on commit | `husky` + `lint-staged` mirroring CI | **In scope** |

---

## Work units (ordered; each independently green)

Order is **rails-before-moves** (strict-plan §Rearrange). Run the green-check after each unit:
`npm run type-check && npm run lint && npm test -- --run && npm run build` and `e2e/run.sh add-companies --fast`.
Node **22.14.0** (`export PATH="$HOME/.nvm/versions/node/v22.14.0/bin:$PATH"`).

### WU0 — `foundation/` barrel layer (additive; establishes the noun)
- **Rules:** R1 (kernel noun), enables R2/R4 to name `foundation`.
- **Create:** `src/frontend/src/foundation/{index,hooks,errors,ui,http,types}.ts` — re-export only (see §foundation).
- **Modify:** none (legacy imports untouched). Optionally add a `tsconfig` path alias `@foundation/*`.
- **Green:** pure re-exports, zero behavior change; `type-check`/`build` unaffected.
- **Risk:** NONE.

### WU1 — dependency-cruiser + R2 (boundaries on the current layout)
- **Rules:** R2 (both halves, scoped to what's green), R1 (self-contained check).
- **Add dep:** `dependency-cruiser` (devDependency, root or `src/frontend`).
- **Create:** `src/frontend/.dependency-cruiser.cjs` (config below).
- **Modify:** `src/frontend/package.json` — add `"depcruise": "depcruise src --config .dependency-cruiser.cjs"`.
  `.github/workflows/ci.yml` frontend job — add `- run: npm run -w src/frontend depcruise` after `eslint`.
- **Green:** feature↛feature = 0 violations; foundation↛features scoped to the pure base = 0 direct violations
  (implementing agent runs `depcruise` first; any straggler is fixed or the dir dropped from the foundation node — the unit gates on a clean graph).
- **Risk:** LOW.

### WU2 — R5 coverage gate in CI (ratcheted)
- **Modify:** `.github/workflows/ci.yml` — change `- run: npm test -- --run` → `- run: npm test -- --run --coverage`.
- **Green:** thresholds already 80 in `vitest.config.ts`. Implementing agent runs coverage once; **if any category
  is < 80**, set that category's threshold to its measured floor (a ratchet — never below what passes) and note the
  gap in the deferred backlog. Never lower an already-passing bar.
- **Risk:** LOW (worst case: one threshold pinned to floor).

### WU3 — R6 `no-explicit-any = error` (product code)
- **Modify:** `src/frontend/eslint.config.js`:
  - main `src/**` block: `"@typescript-eslint/no-explicit-any": "error"`.
  - **add a second block** for test scope (`src/**/__tests__/**`, `src/**/*.test.{ts,tsx}`, `src/test/**`):
    `"@typescript-eslint/no-explicit-any": "off"` (the 79 legacy test `any`s, grandfathered as a backlog).
  - CI: `- run: npx -w src/frontend eslint src --max-warnings 0` (down from 149).
- **Fix (3 product sites):** `src/frontend/src/api/clients/baseClient.ts` (×2), `src/frontend/src/lib/logger.ts` (×1) — replace `any` with `unknown`/precise generics. Tiny, behavior-preserving.
- **Green:** after the 3 fixes, product `src/**` has 0 `any`; tests exempted; `--max-warnings 0` passes.
- **Risk:** LOW.

### WU4 — R4 redux-door + R8 useEffect ban
- **Rules:** R4 (redux half), R8.
- **Modify:** `src/frontend/eslint.config.js`:
  - **R4:** `no-restricted-imports` — ban `useDispatch`/`useSelector` from `react-redux` everywhere, with an override block that re-allows them **only in `src/app/hooks.ts`**. (0 current violations → green.)
  - **R8:** an override block scoped to `src/features/**` with
    `"no-restricted-syntax": ["error", { selector: "CallExpression[callee.name='useEffect']", message: "No new useEffect in features/. Put external-store sync in a foundation hook, or derive in render / use RTK Query." }]`,
    and a nested override **exempting the 8 allow-list files** (below) with the rule off.
- **Allow-list (R8 exemptions):** `features/analytics/{usePostHogPageview,usePostHogIdentify,useSignupFunnel}.ts`, `features/savedFilters/useHydrateSavedFilters.ts`, `features/preferences/useEnabledCompanies.ts`, `features/auth/{useCurrentUser,useRecordVisit}.ts`, `features/features/useFeaturesAuthBridge.ts`.
- **Green:** both rules have 0 non-exempt violations today.
- **Risk:** LOW.

### WU5 — R9 ruff + R10 husky/lint-staged
- **Rules:** R9 (ruff on backend + scripts), R10.
- **Create:** root `ruff.toml` (config below). `.husky/pre-commit` (runs `npx lint-staged`).
- **Modify:**
  - Root `package.json` — add `"prepare": "husky"`, `devDependencies: husky, lint-staged`, and a `lint-staged` block (below).
  - `.github/workflows/ci.yml` — add `- run: ruff check src/backend scripts` and `- run: ruff format --check src/backend scripts` to the **backend** and **scripts** jobs (or a small standalone `python-lint` job).
- **One-time autoformat commit (flagged decision #3):** run `ruff check --fix src/backend scripts` + `ruff format src/backend scripts` once; land it as its own mechanical commit so the rails commits stay reviewable. Any residual becomes an explicit `# noqa` or `per-file-ignores` entry so CI is green.
- **Green:** ruff config starts with a **safe curated set** (`E,F,I,UP,B`, line-length 100) so the autofix converges; CI clean thereafter. husky/lint-staged is additive.
- **Risk:** LOW–MEDIUM (the autoformat is broad but mechanical; isolate it).

### WU6 — R7 import-linter contract + R3 entrypoint convention + R1 docs
- **Rules:** R7 (contract, grandfathered), R3, R1.
- **Create:** root `pyproject.toml` with `[tool.importlinter]` (contract below). `.github/PULL_REQUEST_TEMPLATE.md` (Dune checklist: "new feature = one folder under `features/<name>/` with `feature.route.tsx`; touched a boundary? run `depcruise`/`lint-imports`").
- **Modify:** `.github/workflows/ci.yml` (backend or scripts job) — `pip install import-linter` + `- run: lint-imports`. `src/frontend/CLAUDE.md` — add a "Dune features" section (the two import rules, the `feature.route.tsx` convention, the eslint-disable allowlist is CI-enforced).
- **R3 entrypoint discovery (additive):** add `src/frontend/src/app/featureRoutes.ts` that `import.meta.glob('../features/*/feature.route.tsx', { eager: true })` and composes discovered routes; `App.tsx` renders the central `routes.ts` set **and** the discovered set. Existing routes stay in `routes.ts` — only the pilot uses discovery.
- **Green:** contract grandfathers `scripts.run_scraper`, `scripts.one_off.*` → `lint-imports` passes; the glob is empty until the pilot adds a file (WU7), so `featureRoutes.ts` is a no-op today.
- **Risk:** LOW.

### WU7 — Pilot collocation: `why` (proves R1 + R3, green, zero WebMCP overlap)
- **Rules:** R1, R3.
- **Exact moves** (git-mv; the only file relocation in scope):

  | From | To |
  |---|---|
  | `src/frontend/src/pages/WhyPage/WhyPage.tsx` | `src/frontend/src/features/why/ui/WhyPage.tsx` |
  | `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx` | `src/frontend/src/features/why/__tests__/WhyPage.test.tsx` |

- **Create:** `src/frontend/src/features/why/feature.route.tsx` (reserved entrypoint: exports `{ path: ROUTES.WHY, element: <WhyPage/> }`, discovered by the WU6 glob). `src/frontend/src/features/why/why.tools.ts` (documents "WebMCP tools: none — static route"; matches the noun shape).
- **Modify:** the importers of `WhyPage` (`app/App.tsx` currently imports it — switch to the discovered route or update the path) and any test path refs. Update `.dependency-cruiser.cjs` if `why` needs the self-contained check.
- **Green:** pure move + import rewrite, no behavior change; `WhyPage.test.tsx` still passes; `App.tsx` renders the same route. `why` imports only `foundation` + `config/routes` → passes feature↛feature and foundation↛features.
- **Risk:** LOW (static page, no slice/data/WebMCP dependency).
- **Why not Recent Jobs:** its files (`features/jobs/*`, `features/filters/*`) are the WebMCP stage's reuse contract — see §Exact moves (deferred).

---

## Config additions (exact)

### `src/frontend/.dependency-cruiser.cjs` (WU1)
```js
const FOUNDATION = "^src/(foundation|lib|config|constants|types)/|^src/app/hooks\\.ts$";
module.exports = {
  forbidden: [
    { name: "no-feature-to-feature", severity: "error",
      comment: "A feature may not import another feature. Share via foundation/.",
      from: { path: "^src/features/([^/]+)/" },
      to:   { path: "^src/features/([^/]+)/", pathNot: "^src/features/$1/" } },
    { name: "foundation-no-features", severity: "error",
      comment: "The kernel must not import product code.",
      from: { path: FOUNDATION },
      to:   { path: "^src/(features|pages|components|hooks)/" } },
    { name: "no-orphan-webmcp-consumers", severity: "error",
      comment: "Only app/main may import webmcp.",
      from: { pathNot: "^src/(webmcp|app|main\\.tsx)" }, to: { path: "^src/webmcp/" } },
  ],
  options: { doNotFollow: { path: "node_modules" }, tsConfig: { fileName: "tsconfig.json" },
    exclude: { path: "(__tests__|\\.test\\.)" } },
};
```

### `src/frontend/eslint.config.js` additions (WU3/WU4) — new blocks appended
```js
// R4 — Redux only via the door
{ files: ["src/**/*.{ts,tsx}"], ignores: ["src/app/hooks.ts"],
  rules: { "no-restricted-imports": ["error", { paths: [{ name: "react-redux",
    importNames: ["useDispatch","useSelector"],
    message: "Import useAppDispatch/useAppSelector from foundation/hooks (app/hooks.ts)." }] }] } },
// R6 — product code
{ files: ["src/**/*.{ts,tsx}"], rules: { "@typescript-eslint/no-explicit-any": "error" } },
// R6 — grandfather legacy test `any`
{ files: ["src/**/__tests__/**","src/**/*.test.{ts,tsx}","src/test/**"],
  rules: { "@typescript-eslint/no-explicit-any": "off" } },
// R8 — ban NEW useEffect in features/
{ files: ["src/features/**/*.{ts,tsx}"],
  rules: { "no-restricted-syntax": ["error", { selector: "CallExpression[callee.name='useEffect']",
    message: "No new useEffect in features/. Use a foundation hook, derive-in-render, or RTK Query." }] } },
// R8 — allow-list (8 existing external-store-sync hooks)
{ files: [
  "src/features/analytics/usePostHogPageview.ts","src/features/analytics/usePostHogIdentify.ts",
  "src/features/analytics/useSignupFunnel.ts","src/features/savedFilters/useHydrateSavedFilters.ts",
  "src/features/preferences/useEnabledCompanies.ts","src/features/auth/useCurrentUser.ts",
  "src/features/auth/useRecordVisit.ts","src/features/features/useFeaturesAuthBridge.ts"],
  rules: { "no-restricted-syntax": "off" } },
```
CI: `npx -w src/frontend eslint src --max-warnings 0`.

### root `ruff.toml` (WU5)
```toml
line-length = 100
target-version = "py313"
extend-exclude = ["**/__pycache__", ".venv", "scripts/output", "src/backend/api/eval/results"]
[lint]
select = ["E", "F", "I", "UP", "B"]
[lint.per-file-ignores]
"scripts/one_off/**" = ["E402"]     # documented sys.path-then-import pattern
```

### root `package.json` additions (WU5)
```json
{ "scripts": { "prepare": "husky" },
  "lint-staged": {
    "src/frontend/src/**/*.{ts,tsx}": "npx -w src/frontend eslint --max-warnings 0",
    "{src/backend,scripts}/**/*.py": ["ruff check --fix", "ruff format"] },
  "devDependencies": { "husky": "^9", "lint-staged": "^15" } }
```
`.husky/pre-commit` → `npx lint-staged`.

### root `pyproject.toml` — `[tool.importlinter]` (WU6/R7)
```toml
[tool.importlinter]
root_packages = ["src", "scripts"]
[[tool.importlinter.contracts]]
name = "scripts must not import the backend (one-way: backend -> scripts.shared only)"
type = "forbidden"
source_modules = ["scripts"]
forbidden_modules = ["src.backend"]
# Grandfathered back-edges — the deferred cycle-break removes these, then this list empties.
ignore_imports = [
  "scripts.run_scraper -> src.backend.api.migrations",
  "scripts.one_off.* -> src.backend.api.services.*",
]
```
CI (backend or scripts job): `pip install import-linter && lint-imports`.

### `.github/workflows/ci.yml` deltas (summary)
- **frontend job:** add `npm run -w src/frontend depcruise`; `eslint … --max-warnings 0` (was 149); `npm test -- --run --coverage` (was `--run`).
- **backend + scripts jobs:** add `ruff check` + `ruff format --check`; one job runs `lint-imports`.
- **deferred:** `mypy` over `scripts/` (scripts never type-gated — separate ratchet PR).

---

## Exact moves — DEFERRED (Recent Jobs full collocation)

Specified so the follow-up is turnkey. **Do not execute until the WebMCP e2e stage (RUN1-SPEC) has landed or is
migrated jointly** — these exact paths are that stage's reuse contract. Target: `src/frontend/src/features/recent-jobs/`.

| From | To (`features/recent-jobs/…`) |
|---|---|
| `pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx` | `ui/RecentJobPostingsPage.tsx` + `feature.route.tsx` |
| `components/recent-jobs-page/RecentJobsFilters.tsx` | `ui/RecentJobsFilters.tsx` |
| `components/recent-jobs-page/EditCompanyPreferences{Row,Link}.tsx` | `ui/` |
| `components/recent-jobs-page/RecentJobsList/*` (List, VirtualJobRows, LoadingSkeletons, BackToTopButton, useRecentJobsPaging) | `ui/list/` |
| `components/recent-jobs-page/RecentJobsMetrics/**` (incl. `hooks/useRecentJobsTimeBasedCounts.ts`) | `ui/metrics/` |
| `features/filters/slices/recentJobsFiltersSlice.ts` | `state/recentJobsFiltersSlice.ts` |
| `features/filters/selectors/{recentJobsSelectors,recentJobsFilterSignature}.ts` | `state/` |
| `features/jobs/{jobsApi,jobsSelectors,keysetWalk,progressHelpers,demoJobs}.ts`, `features/jobs/hooks/useAllJobsProgress.ts` | `data/` **(shared with company-trends — split, don't move wholesale)** |
| `webmcp/tools/tier1Read.ts` + `tier2DriveUi.ts` (recent-jobs tools) | `recent-jobs.tools.ts` |

**Coordination note:** `features/jobs/*` and `features/filters/*` are **co-owned** by Recent Jobs *and* Company Trends
(CLAUDE.md "two job read paths"). They belong in `foundation/` or a shared `data/` seam, **not** inside one feature —
resolve ownership before moving. This is why it is deferred, not pilot.

---

## Deferred backlog (explicit — nothing here is "done")

1. **Full `foundation↛features`** — needs slice **auto-registration** so `app/store.ts` stops importing features, plus rehoming `components/shared` + `components/layout` feature deps. HIGH value, MEDIUM risk.
2. **Migrate the other ~12 features** into `features/<name>/` folders (company-trends, saved-filters, vote-features, curated-companies, account, my-companies, admin/*). Each its own green PR; Recent Jobs first (post-WebMCP).
3. **Hub-splitting** — `types/index.ts` (310 lines) and `config/companies.ts` (952 lines) toward feature/foundation ownership; store auto-registration.
4. **Break the backend↔scripts cycle (R7 real)** — remove `scripts/run_scraper.py` → `src.backend.api.migrations` and the `scripts/one_off/*` → `src.backend` edges; empty `ignore_imports`. HIGHEST blast radius — strict-plan says last.
5. **R4 fetch-lifecycle custom eslint rule** — ban hand-rolled `useState+useEffect+fetch` (a small custom rule; `no-restricted-syntax` alone false-positives).
6. **R9 mypy over `scripts/`** — scripts never type-gated; enable module-by-module.
7. **Dune "Host" noun** — generated FE↔BE types replacing the hand-duplicated contract.
8. **`eslint-comments/no-unlimited-disable` + CI-enforced disable allowlist** (strict-plan Contract rule 5).
9. **Clean the 79 legacy test-file `any`s** (R6 backlog → then drop the test exemption).
10. **Explicit local-storage single-writer naming** (Contract rule 3: Google-credential + callout-dismissal writers).
- **Deviation kept (confirmed in strict-plan r2):** Dune's "no code comments" rule is **skipped** — JVN's comments are load-bearing rationale (incident refs, "why" narratives, up to ~53% density). Do **not** wire a comment ban.

---

## Green-at-each-step ledger

| After | type-check | lint | test | build | e2e (add-companies) | Note |
|---|---|---|---|---|---|---|
| WU0 barrels | ✅ | ✅ | ✅ | ✅ | ✅ | re-exports only |
| WU1 depcruise | ✅ | ✅ | ✅ | ✅ | ✅ | 0 boundary violations |
| WU2 coverage | ✅ | ✅ | ✅ (ratcheted) | ✅ | ✅ | pin floor if <80 |
| WU3 no-any | ✅ (3 fixes) | ✅ `--max-warnings 0` | ✅ | ✅ | ✅ | tests exempt |
| WU4 redux/useEffect | ✅ | ✅ | ✅ | ✅ | ✅ | 0 non-exempt |
| WU5 ruff/husky | ✅ | ✅ | ✅ | ✅ | ✅ | isolate autoformat commit |
| WU6 import-linter/R3 | ✅ | ✅ | ✅ | ✅ | ✅ | back-edges grandfathered |
| WU7 `why` pilot | ✅ | ✅ | ✅ | ✅ | ✅ | pure move |

Sources: `.lavish/dune-strict-plan.html` (R1–R10, rearrange plan), `dune-contract.md`, `RUN1-SPEC.md`
(WebMCP path contract — the freeze), verified against the live tree on 2026-09-03.
