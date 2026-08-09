# Landing Page Prototypes — Implementation Plan

> Epic 11 (`wdwb1cbnc7`) kickoff. Admin-gated, frontend-only, mock-data prototypes of 4
> landing-page directions, switchable via a browser-style tab strip at
> `/admin/landing-prototypes`. Copy traces to `docs/seo/positioning-brief.md` (11.1).
> Promotion of a winner to `/` (robots/sitemap/meta/JSON-LD, `signup_funnel_landing`
> cutover) is 11.2/11.3 — OUT of scope here.

## Architecture

- **Route**: `/admin/landing-prototypes`, registered in `App.tsx` as a **sibling** of the
  `path="/"`/`RootLayout` route → renders full-bleed (no drawer/appbar) while all
  `main.tsx` providers still wrap it. Gated with `<AdminRoute>` (client-side is sufficient —
  no privileged data). The existing `/admin/:path(.*)` rewrite in `vercel.json` covers deep
  links; **no vercel.json changes**.
- **Tab strip**: MUI `Tabs variant="scrollable" allowScrollButtonsMobile` styled
  chrome-like via sx (indicator hidden; rounded-top tabs; active tab "raised"); back-to-app
  IconButton → `ROUTES.RECENT_JOBS`. Tab persists via `?proto=` (+ `?data=sparse` fixture
  toggle); `setSearchParams(..., { replace: true })`; invalid → first tab.
- **Only the active tab mounts** (conditional render, never keep-mounted) — single-Canvas
  invariant for the 3D tabs (GL context leak prevention).
- **All 4 prototypes lazy** (`React.lazy` + `Suspense` with `LoadingState`) — first lazy
  boundaries in the codebase. Entry files export named (tests) + default (lazy) — accepted
  deviation from the named-export convention, confined to the 4 entries.
- **Shared contract** (`types.ts`):
  `LandingPrototypeProps { content: LandingContent; jobs: Job[]; stats: LandingStats; sparse: boolean }`.
- **Theme**: monochrome light everywhere (Q5) — app theme as-is; NO nested dark themes.

## File tree (under `src/frontend/src/`)

```
pages/AdminLandingPrototypesPage/
├── AdminLandingPrototypesPage.tsx   # shell: 100dvh column, strip, ?proto=/?data=, Suspense
├── PrototypeTabStrip.tsx
├── types.ts                         # PrototypeId, LandingPrototypeProps, LandingStats
├── content.ts                       # LANDING_CONTENT: claims by id, headlineVariants, CTAs, TOP_COMPANY_IDS
├── mockData.ts                      # buildMockJobs(now) ~18 / buildSparseMockJobs(now) ~6 + constants
├── prototypes/
│   ├── registry.ts                  # PROTOTYPES [{id,label,Component:lazy}], isPrototypeId
│   ├── SignalPrototype/             # tab 1 "Signal" — clean minimal (variant A hero)
│   ├── BoardPrototype/              # tab 2 "The Board" — jobs-forward (variant B hero)
│   │   └── MiniJobBoard.tsx         # JobListingCard .map(), category chips, no keyword UI
│   ├── GravityPrototype/            # tab 3 — falling logos physics
│   │   ├── GravityPrototype.tsx     # lazy entry: hero copy + sections + tier gate
│   │   ├── GravityScene.tsx         # nested-lazy: <Canvas><Physics> walls/tiles/shadows
│   │   ├── LogoTileBody.tsx
│   │   ├── spawnPlan.ts             # PURE seeded (mulberry32) spawn plan
│   │   └── useSettleGovernor.ts     # sleep counter + IO + visibility → frameloop always↔never
│   ├── DriftPrototype/              # tab 4 — particles
│   │   ├── DriftPrototype.tsx
│   │   ├── DriftScene.tsx           # nested-lazy: 2× drei Sparkles layers
│   │   └── particlesConfig.ts       # PURE per-tier counts/sizes
│   └── shared3d/
│       ├── experienceTier.ts        # PURE resolveExperienceTier / resolveFrameloop
│       ├── usePrefersReducedMotion.ts  # useSyncExternalStore over guarded matchMedia
│       ├── detectWebGL.ts           # injectable probe
│       ├── logoRoster.ts            # PURE selectLogoRoster(COMPANIES, count, seed)
│       └── LogoGridFallback.tsx     # DOM "pre-settled" logo grid (reduced/no-WebGL tiers)
└── sections/
    ├── HeroCopy.tsx                 # variant-aware (source | antiNoise)
    ├── CTAButtons.tsx               # primary "Browse jobs" → ROUTES.RECENT_JOBS
    ├── LiveActivityStats.tsx        # event-shaped stats computed from mock jobs (Q7)
    ├── LogoWall.tsx                 # CSS-keyframe marquee rows, hover-pause, PRM kill switch
    ├── FreshJobsTicker.tsx          # 48h rail from TOP_COMPANY_IDS; <6 → static 7d fallback
    └── FooterLite.tsx
```

Tests mirror under `__tests__/pages/AdminLandingPrototypesPage/`.

## Key specs

- **content.ts**: claims keyed by id (`straight_from_source`, `minutes_after_posting`,
  `no_reposts`, `curated_companies`, `thousands_weekly`, `apply_early_rolling`) each with
  `evidence` breadcrumb → brief §5. `headlineVariants: { source, antiNoise }` (brief §4);
  Signal uses `source`, The Board uses `antiNoise`, 3D tabs pick per fit. `TOP_COMPANY_IDS`
  (brief §8). Invariant tests: non-empty copy, record keys === claim.id, CTA `to` ∈ ROUTES.
- **mockData.ts**: factories take `now` (deterministic tests), module-load constants for the
  page. Real company ids only → `CompanyLogo` resolves committed PNGs. Verified enums:
  categories `software_engineering|hardware_engineer|product_manager|project_manager|data_scientist|growth|business_ops`;
  levels `intern|new_grad|entry|mid|senior|senior_plus|manager` (intern standalone).
  `Job` required: `id, source:'backend-scraper', company, title, createdAt=firstSeenAt,
  firstSeenAt, url, raw`. Freshness spread <3h → 7d; sparse fixture = weekend reality.
  Mock stats DERIVE from mock jobs (coherent numbers).
- **LiveActivityStats** (Q7): event-shaped — "SpaceX posted N jobs in the past hour",
  "N jobs tracked in the past 24 hours" — computed from the jobs prop via
  `filterJobsByHours`; never static vanity metrics.
- **RESPONSIVE**: new `RESPONSIVE.landingProto` token group per `docs/RESPONSIVE.md` recipe
  ({xs,sm} with sm restating desktop; pin-map entries in `responsive.test.ts`). No
  hard-coded px. No breakpoint overrides anywhere.
- **3D stack** (exact pins): `three@0.185.1`, `@types/three@0.185.4` (dev),
  `@react-three/fiber@9.7.0`, `@react-three/drei@10.7.8`, `@react-three/rapier@2.2.0`
  (compat wasm-as-base64 → zero Vite/Vercel plumbing; do NOT add rapier3d-compat directly).
- **Gravity scene**: shared BoxGeometry(1,1,0.14); per-tile face material (`useTexture`
  batch, sRGB); shared edge material; ambient + directional light, no shadow maps; drei
  ContactShadows desktop tier only; ~72 bodies desktop / ~40 mobile; shallow pile via
  front/back walls z≈±0.75, floor + side walls from viewport; `linearDamping 0.15`, `ccd`,
  `restitution 0.2`, `friction 0.8`; seeded `buildSpawnPlan` staggers drops ~2.5s with zero
  timers; rapier auto-sleep + `onSleep`/`onWake` counter → `useSettleGovernor` flips
  frameloop `always↔never` (also on scroll-away via IntersectionObserver + visibilitychange);
  pointer-repel kinematic ball on `(pointer: fine)` only; DPR clamp [1, 2] desktop /
  [1, 1.5] mobile.
- **Degradation ladder** (resolved in the lazy entry BEFORE importing the scene chunk):
  full-desktop → full-mobile (fewer bodies, no shadows) → reduced-motion OR no-WebGL →
  `LogoGridFallback` DOM grid / static CSS backdrop. Low tiers never download three/rapier.
  Chunks: three+fiber+drei shared (~220–260KB gz, auto-hoisted by Rollup), rapier only in
  Gravity's scene chunk (~1.1MB gz), no `manualChunks` unless build inspection demands it.
  Invariant: NO eager module statically imports `three`/`@react-three/*`.
- **Zero new eslint-disables**: seeded PRNG in `useMemo` passes `react-hooks/purity`
  honestly; `useSyncExternalStore` for matchMedia (hand-rolled `usePrefersReducedMotion` —
  framer-motion's singleton caches and breaks per-test toggling; jsdom has NO matchMedia,
  guard `typeof window.matchMedia === 'function'`); rapier event callbacks instead of
  state-mirroring effects.

## Wiring checklist

1. `config/routes.ts`: `ROUTES.ADMIN_LANDING_PROTOTYPES` + `ADMIN_NAV_ITEMS` entry
   (label "Landing Prototypes", icon `Palette`).
2. `NavigationDrawer.tsx`: `PaletteIcon` import + `IconName` union + `iconMap`
   (missing = runtime crash, not a type error).
3. `App.tsx`: sibling `<Route>` wrapped in `<AdminRoute>`.
4. `config/changelog.ts`: honest entry ("internal landing-page prototypes"); changelog test
   asserts link targets ∈ ROUTES.
5. Tests as mirrored above; `renderWithProviders` + `initialEntries` for URL cases;
   `vi.mock` at lazy boundaries (scene modules mocked — Vitest 4 with `coverage.include`
   unset only counts loaded files; keep scenes thin JSX plumbing).

## Ordered work units

1. Config wiring (routes/nav/changelog + tests)
2. Pure modules: types/content/mockData + invariant tests
3. Shared sections + `RESPONSIVE.landingProto` + tests
4. Shell + strip + registry + placeholder 3D stubs (page live end-to-end)
5. Signal prototype + tests
6. The Board prototype + MiniJobBoard + tests
7. 3D deps install + pure 3D modules (spawnPlan/experienceTier/logoRoster/particlesConfig) + tests
8. Drift scene (validates three/chunking/lifecycle stack without rapier)
9. Gravity scene (walls, tiles, governor, pointer ball)
10. Hardening: coverage, reduced-motion audit, mobile audit (390px), build-chunk inspection
    (three must NOT appear in main bundle), tab-flip ×20 GL-context check

## Verification

`npm run type-check` · `npm run lint` · `npm test` · `npm run test:coverage -w src/frontend`
(≥80% all metrics) · `npm run build` + chunk listing inspection. Manual: full-stack dev
(run skill — AdminRoute needs Auth0 + `/api/users`; frontend-only insufficient), signed-in
admin walk: 4 tabs, `?proto=` deep links, `?data=sparse`, reduced-motion ON → fully static,
iPhone 390×844 (scrollable strip, no horizontal overflow), real logo PNGs render (no
initials fallback). Then open in Brendan's browser for review.

## Review log

(Feedback rounds recorded here as they happen.)
