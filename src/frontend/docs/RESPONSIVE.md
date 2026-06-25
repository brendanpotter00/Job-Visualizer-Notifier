# Responsive / Mobile — the agent dock

**Read this before adding or restyling any page or component.** It is the single
source of truth for how this app stays usable on an iPhone in portrait (~390px)
**without** changing the desktop/tablet (>= 600px) look. Every mobile fix in the
app routes through the tokens described here — do not hand-roll new pixel sizes.

> The rule, in one line: **consume `RESPONSIVE` tokens (and `useIsMobile`) — never
> hard-code a px size, font, or padding for mobile.** A reviewer will reject a new
> magic number that should be a token.

## The breakpoint

`MOBILE_BREAKPOINT = 'sm'` (`config/responsive.ts`) → the compact mobile layout is
everything **below 600px**. This is the *content* breakpoint. (The app **shell** —
`RootLayout` drawer/appbar — intentionally switches at `md`/900px instead; that is a
separate, deliberate split for the tablet drawer and is documented in `RootLayout`.)

## The two token shapes

Everything lives in the `RESPONSIVE` object in **`config/responsive.ts`**.

### 1. `{ xs, sm }` sx tokens — for `sx` props (the default, preferred shape)

```tsx
import { RESPONSIVE } from '../config/responsive';

<Paper sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}>
<Typography sx={{ fontSize: RESPONSIVE.fontSize.pageTitle }}>
```

MUI `sx` is **mobile-first**: an `xs` value applies at every width unless a larger
breakpoint overrides it. So **every token's `sm` slot restates the current desktop
value** → applying a token is a *no-op at >= 600px* by construction. This invariant
is compiler-enforced (`satisfies Record<string, ResponsiveValue>`) and asserted in
`__tests__/config/responsive.test.ts`. When you add an `{ xs, sm }` token, the `sm`
slot **must** equal whatever the call site renders today.

### 2. `{ compact, default }` numbers — for raw-number/object props

Some props take a raw number or object, not `sx` (e.g. a Recharts `height`, a chart
`margin`, `CompanyLogo`'s `size`, a chip `height`). For those, pick the value with
the `useIsMobile()` hook:

```tsx
import { useIsMobile } from '../hooks/useIsMobile';
import { RESPONSIVE } from '../config/responsive';

const isMobile = useIsMobile();
<JobPostingsChart height={isMobile ? RESPONSIVE.chart.height.compact : RESPONSIVE.chart.height.default} />
```

### 3. Mobile-only gated `sx` blocks — only when the desktop default is fragile

When MUI's desktop default is *variant-dependent* (small-chip label padding, small-button
padding) and can't be safely restated in an `sm` slot, override **nothing** on desktop:
gate the whole block on `useIsMobile()`. See the `jobCard` group and `JobListingCard`.

```tsx
sx={{ ...(isMobile && { '& .MuiChip-root': { height: RESPONSIVE.jobCard.chipHeight } }) }}
```

## What's in the box (token groups)

| Group | Use it for |
| --- | --- |
| `spacing.*` | page margins, paper/card padding, stack gaps, section margins |
| `fontSize.*` | page title, metric value/label, card title |
| `control.*` | compact filter controls (inputs, selects, Reset button) — see `RecentJobsFilters` / `GraphFilters` |
| `jobCard.*` | the shared `JobListingCard` (logo, chips, Apply button) |
| `chart.*` | the company hiring-trend `JobPostingsChart` (height, margins, axis font, dot radii) |
| `adminChart.*` | admin signup charts height |
| `curatedCard.*` | curated-companies 2-up mobile card (grid size, wordmark, padding) |
| `keywordCard.*` | saved-filters keyword-list card (padding + +/- chips) |
| `statTile.*` | admin stat tiles |
| `logoSize` | `CompanyLogo` numeric `size` |
| `TABLE_SCROLL_SX` (named export) | wrap any wide `<TableContainer>` so it scrolls on mobile only |

## Recurring patterns

- **Wide table** → wrap the `<TableContainer>` with `sx={TABLE_SCROLL_SX}` (admin/users,
  qa, feedback, location-normalization). Mobile gets horizontal swipe; desktop unchanged.
- **Tall chart squished on mobile** → drive `height` (and margins/ticks) from the `chart`
  tokens via `useIsMobile()` so the aspect ratio stays landscape.
- **Card eats the screen** → compact `CardContent` padding + smaller title/logo via tokens,
  and shrink long secondary text on mobile (the curated card keeps its full description but
  drops to a smaller font — shrink text, don't truncate it).
- **Metrics/numbers stack tall** → keep them a horizontal dense row on mobile (see
  `MetricCard`'s `dense` prop + `RecentJobsMetrics`), not a vertical column.

## Checklist — making a page mobile-friendly

1. Screenshot the route at **390×844** (iPhone portrait) and find what eats the screen,
   overflows horizontally, or is too big.
2. Reuse an existing token for every size you change. **Need a size with no token?**
   Add one to `RESPONSIVE` in `config/responsive.ts` (with its `sm`/`default` slot set to
   the *current desktop value*) and a doc comment — then consume it. Never inline the number.
3. Keep desktop a **no-op**: `{ xs, sm }` with `sm` = today's value, or `useIsMobile()`-gated.
4. Add/extend a test: assert the new token's `sm` equals the desktop value, and (where it
   matters) assert the component's mobile branch (`vi.mock('@mui/material/useMediaQuery')`).
5. Re-screenshot at **390** (fixed) **and 1280** (must match the before). Gates: `npm run
   type-check`, `npm run lint`, `npm test`.

## How to add a token

```ts
// config/responsive.ts — inside RESPONSIVE
myGroup: {
  /** What it styles + which call site. sm restates the CURRENT desktop value. */
  somePadding: { xs: 1, sm: 3 },           // sx token  → 24px on desktop today
  someRawSize: { compact: 22, default: 32 }, // useIsMobile token → 32px desktop today
},
```

Then consume it at the call site (`sx={{ p: RESPONSIVE.myGroup.somePadding }}` or
`isMobile ? RESPONSIVE.myGroup.someRawSize.compact : …default`). That's it — one
definition, used everywhere.
