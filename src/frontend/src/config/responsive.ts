/**
 * Responsive design tokens — the single source of truth for the app's compact
 * mobile layout. As more pages are made mobile-friendly, add tokens here and
 * consume them instead of hard-coding sizes at call sites.
 *
 * Three token shapes:
 *  - MUI responsive sx objects (`{ xs, sm }`) for use directly in `sx` props.
 *  - `{ compact, default }` numeric pairs for props that take a raw number
 *    (e.g. `CompanyLogo`'s `size`), selected via the `useIsMobile` hook.
 *  - Flat mobile-only values applied via `sx` blocks gated on `useIsMobile()`,
 *    used where the MUI/Recharts desktop default is variant-fragile and can't be
 *    safely restated in an `sm` slot (e.g. the `jobCard` group and
 *    `chart.axisFontSizeCompact` / `chart.yAxisWidthCompact`) — desktop passes
 *    the inherited default (`undefined` / no override) and gets no override at all.
 *
 * Regression-safety convention: the `sm` slot ALWAYS restates the current
 * desktop value, so applying a token never changes layout at >= 600px. MUI sx
 * is mobile-first, so an `xs`-only value would otherwise leak up into desktop.
 */

import type { Breakpoint } from '@mui/material';

/**
 * Breakpoint below which the UI switches to its compact mobile layout.
 *
 * `satisfies Breakpoint` makes a typo (e.g. `'sn'`) fail to compile at this
 * definition site, while `as const` preserves the literal `'sm'` type that
 * `theme.breakpoints.down(MOBILE_BREAKPOINT)` relies on.
 */
export const MOBILE_BREAKPOINT = 'sm' as const satisfies Breakpoint;

/**
 * Shape of an MUI responsive `{ xs, sm }` sx token. Applying it via
 * `satisfies Record<string, ResponsiveValue>` per group compiler-enforces the
 * Ledger #1 invariant: every token MUST carry both slots, so a future token
 * that omits `sm` (which would leak its `xs` value up into desktop, since MUI
 * sx is mobile-first) fails to compile instead of silently regressing >= 600px.
 *
 * NOTE: only the HOMOGENEOUS groups (`spacing`, `fontSize`, `control`, `statTile`)
 * carry that `satisfies` annotation. The mixed-shape groups (`chart`,
 * `curatedCard`, `keywordCard`, `jobCard`, `adminChart`) hold a blend of
 * `{ xs, sm }`, `{ compact, default }`, and flat tokens, so they CANNOT carry it
 * and are therefore NOT compiler-guarded. Their `{ xs, sm }` tokens are instead
 * guarded by the reflective pin-completeness test in
 * `__tests__/config/responsive.test.ts`, which fails if any `{ xs, sm }` (or
 * `{ compact, default }`) token is missing from the desktop-value pin map.
 */
type ResponsiveValue = { xs: number | string; sm: number | string };

/** Reusable responsive design tokens (see file header). */
export const RESPONSIVE = {
  /** Spacing tokens in theme units (1 = 8px), as `{ xs, sm }` sx objects. */
  spacing: {
    /** Page wrapper vertical margin (`<Box my>`). */
    pageMarginY: { xs: 2, sm: 4 },
    /** Vertical gap below a major block (`<Box>`/`<Paper>` `mb`). */
    sectionMarginB: { xs: 2, sm: 3 },
    /** Padding inside a metrics/summary `<Paper>`. */
    paperPadding: { xs: 1.5, sm: 3 },
    /** Padding inside a larger `<Paper>` that uses 4 (32px) on desktop (e.g. the
     *  Saved-Filters / Account section papers). sm restates the current 4. */
    paperPaddingLg: { xs: 2, sm: 4 },
    /** Gap between items in the metrics row (`<Stack spacing>`). */
    rowSpacing: { xs: 1, sm: 3 },
    /** Gap between stacked filter controls (`<Stack spacing>`). */
    filterSpacing: { xs: 1, sm: 2 },
    /** `<CardContent>` padding (xs: 1 == 8px compact; sm: 2 == MUI default 16px). */
    cardPadding: { xs: 1, sm: 2 },
    /** `<CardContent>` last-child bottom padding (xs: 1 == 8px; sm: 3 == MUI default 24px). */
    cardPaddingBottom: { xs: 1, sm: 3 },
    /** Gap between cards in a list (`<Card mb>`). */
    cardMarginB: { xs: 1, sm: 2 },
    /** Gap between sections inside a card (xs: 0.25 == 2px compact; sm: 1 == 8px). */
    cardStackSpacing: { xs: 0.25, sm: 1 },
  } as const satisfies Record<string, ResponsiveValue>,
  /** Font-size tokens as `{ xs, sm }` sx objects; sm restates the theme variant. */
  fontSize: {
    /** Page `<h1>` rendered with the h3 variant (theme h3 = 1.75rem). */
    pageTitle: { xs: '1.5rem', sm: '1.75rem' },
    /** Big metric number, h3 variant (theme h3 = 1.75rem). */
    metricValue: { xs: '1.5rem', sm: '1.75rem' },
    /** Metric label, body2 variant (theme body2 = 0.875rem). */
    metricLabel: { xs: '0.75rem', sm: '0.875rem' },
    /** Job-card title, h6 variant (theme h6 = 1rem). */
    cardTitle: { xs: '0.9375rem', sm: '1rem' },
  } as const satisfies Record<string, ResponsiveValue>,
  /**
   * Compact form-control tokens for mobile filter rows. Applied as descendant
   * `sx` overrides (e.g. `& .MuiOutlinedInput-root`) so they shrink shared
   * filter controls on the consuming page only, without editing the shared
   * components. Every `sm` slot restates the current desktop value (the theme's
   * 44px min-height floor, body1 1rem input font, small-button 0.8125rem font,
   * and MUI's small outlined input padding of 8.5px) so these are no-ops at
   * >= 600px. Padding values are STRINGS with explicit `px` units: in MUI `sx`,
   * paddingTop/paddingBottom are spacing-system props that multiply bare numbers
   * by 8, so `'5px'` must be a string to mean 5px (not 5 * 8 = 40px).
   */
  control: {
    /**
     * Min-height floor for filter controls + the Reset button. Desktop keeps the
     * theme's 44px touch-target floor; mobile drops to 36px (still well above the
     * WCAG 2.5.8 AA 24px minimum). `minHeight` is a sizing prop, so numbers > 1
     * are treated as px (not multiplied).
     */
    minHeight: { xs: 36, sm: 44 },
    /** Typed text + floating label font size (sm = theme body1 1rem). */
    fontSize: { xs: '0.8125rem', sm: '1rem' },
    /** Inner input vertical padding, per side (sm = MUI small outlined default). */
    inputPaddingY: { xs: '5px', sm: '8.5px' },
    /** Reset button font size (sm = MUI small-button 0.8125rem default). */
    buttonFontSize: { xs: '0.75rem', sm: '0.8125rem' },
  } as const satisfies Record<string, ResponsiveValue>,
  /**
   * Compact job-card values for the shared JobListingCard on mobile. Unlike the
   * `{ xs, sm }` tokens above, these are FLAT mobile-only values applied via
   * `sx` blocks gated behind `useIsMobile()` — so desktop (>= 600px) receives no
   * override at all and keeps MUI's defaults byte-for-byte. MUI's small-chip
   * label padding is variant-dependent and its small-button vertical padding
   * differs by component, so we gate these overrides on `isMobile` rather than
   * restate fragile per-variant desktop baselines. Applied as descendant
   * selectors on the card's `CardContent`, so they cover every chip row
   * (location, employment-type, and JobChipsSection dept/remote) without editing
   * the chip call sites or JobChipsSection.
   *
   * Units: `chipHeight`/`applyMinHeight` are sizing props (bare number -> px).
   * `chipLabelPaddingX`/`applyPaddingY`/`applyPaddingX` are spacing-system props
   * that multiply bare numbers by 8, so they MUST be strings with explicit `px`.
   */
  jobCard: {
    /** Chip height across all rows (default small chip is 24px). */
    chipHeight: 20,
    /** Chip label font size (default chip text is 0.8125rem/13px; 0.625rem == 10px). */
    chipFontSize: '0.625rem',
    /** Chip label horizontal padding per side (string px; avoids the x8 trap). */
    chipLabelPaddingX: '5px',
    /** Apply button min-height (overrides the theme's 44px floor; >= WCAG AA 24px). */
    applyMinHeight: 36,
    /** Apply button font size (small button default is 0.8125rem/13px). */
    applyFontSize: '0.75rem',
    /** Apply button vertical padding per side (string px). */
    applyPaddingY: '4px',
    /** Apply button horizontal padding per side (string px). */
    applyPaddingX: '10px',
  },
  /**
   * Company hiring-trend chart (`JobPostingsChart`). FLAT `{ compact, default }`
   * / mobile-only values selected via `useIsMobile()`, because Recharts props
   * (`height`, `margin`, dot `r`, axis `tick.fontSize`) take raw numbers/objects,
   * not `sx`. The squish on a ~360px phone is an aspect-ratio problem: a 400px-tall
   * plot in ~360px width is portrait, so the line reads as a vertical scatter.
   * `height.compact` restores a desktop-like landscape ratio (~360×210 ≈ 1.7:1),
   * and the compact margins reclaim the narrow width for the plot.
   */
  chart: {
    /** ResponsiveContainer height. Desktop 400 = the accepted landscape look. */
    height: { compact: 210, default: 400 },
    /** LineChart margins. `default` restates the current desktop values. */
    marginDefault: { top: 5, right: 30, left: 20, bottom: 5 },
    marginCompact: { top: 5, right: 12, left: -8, bottom: 0 },
    /**
     * Axis tick font size on mobile only (px). Desktop keeps Recharts' inherited
     * default (≈12px) — we override nothing >= 600px (the `jobCard` gate pattern),
     * since restating Recharts' computed default is fragile.
     */
    axisFontSizeCompact: 11,
    /**
     * XAxis `minTickGap` on mobile only (px). Spreads the date labels apart so
     * they don't collide on the narrow phone plot. Desktop keeps Recharts'
     * default `minTickGap` of 5 (passed inline as `: 5`) — NOT overridden here.
     */
    minTickGapCompact: 28,
    /**
     * YAxis `width` on mobile only (px). Reclaims horizontal room for the plot
     * on a narrow phone. Desktop keeps Recharts' default auto-width (passed
     * inline as `: undefined`) — NOT overridden here.
     */
    yAxisWidthCompact: 28,
    /** Line dot radii. */
    dotR: { compact: 3, default: 4 },
    activeDotR: { compact: 5, default: 6 },
  },
  /** Admin dashboard charts (signup trend / per-day). Raw px via `useIsMobile`. */
  adminChart: { height: { compact: 200, default: 280 } },
  /**
   * Curated-companies card (`CompanyCard`). Stays in the single column it already
   * rendered at `xs` (xs:12, unchanged), but compacted: smaller logo, tighter
   * padding, and a smaller description font — so the cards are shorter while still
   * showing the FULL blurb (no truncation). Mixed shapes: `gridItemSize` is the
   * MUI Grid `size` object, `wordmarkHeight` is a `{ compact, default }` raw-px
   * `useIsMobile` token, and the rest are `{ xs, sm }` sx tokens (sm restates the
   * current desktop value).
   */
  curatedCard: {
    /** MUI Grid `size`: 1-up on phones (xs:12, unchanged), 2-up sm, 3-up md+. */
    gridItemSize: { xs: 12, sm: 6, md: 4 },
    /** Grid gap (sm restates the current 2 == 16px). */
    gridSpacing: { xs: 1, sm: 2 },
    /** Wordmark logo height (raw px via `useIsMobile`; default 32 unchanged). */
    wordmarkHeight: { compact: 24, default: 32 },
    /**
     * CardContent base `p` + CardActions `px`/`pb` padding. sm restates the
     * original 16px (CardContent's MUI default; CardActions' explicit `px:2`, not
     * the MUI 8px CardActions default).
     */
    contentPadding: { xs: 1.25, sm: 2 },
    /** Description font size (sm restates the body2 0.875rem desktop default). */
    descriptionFontSize: { xs: '0.78rem', sm: '0.875rem' },
  },
  /**
   * Saved-filters keyword-list cards (`KeywordListCard`). Compact padding + the
   * include/exclude keyword chips shrink on mobile so the card stops eating a
   * full screen. Mixed shapes: `contentPadding` is an `{ xs, sm }` sx token;
   * `chipHeight`/`chipFontSize` are `{ compact, default }` raw chip props
   * (selected via `useIsMobile`); and `chipLabelPaddingX`/`chipIconFontSize`/
   * `chipIconMarginL` are flat mobile-only strings (desktop keeps MUI's
   * variant-dependent chip defaults — no override).
   */
  keywordCard: {
    /**
     * `KeywordListCard` `CARD_SX` padding, applied to a `<Box>` (not a
     * CardContent). A `<Box>` has no default padding of its own, so sm restates
     * the original explicit `p: 2` (16px) that origin/main set on that `<Box>`.
     */
    contentPadding: { xs: 1.25, sm: 2 },
    /** +/- keyword chip height (raw px via `useIsMobile`; default small chip 24). */
    chipHeight: { compact: 22, default: 24 },
    /** +/- keyword chip font size (raw via `useIsMobile`; default 0.8125rem). */
    chipFontSize: { compact: '0.6875rem', default: '0.8125rem' },
    /**
     * Chip label horizontal padding on mobile only (applied via a `useIsMobile`
     * gate, like `jobCard.*`). String px to avoid MUI's spacing x8 trap. Desktop
     * keeps MUI's variant-dependent small-chip label padding — NOT overridden here.
     */
    chipLabelPaddingX: '6px',
    /**
     * Chip leading-icon font size on mobile only (`useIsMobile`-gated). Shrinks the
     * +/- icon to match the smaller chip. Desktop keeps MUI's default icon size.
     */
    chipIconFontSize: '0.85rem',
    /**
     * Chip leading-icon left margin on mobile only (`useIsMobile`-gated). String px
     * to avoid the spacing x8 trap. Desktop keeps MUI's default icon margin.
     */
    chipIconMarginL: '3px',
  },
  /** Admin stat tiles (`StatTile`). `{ xs, sm }` sx tokens (sm restates current). */
  statTile: {
    /** Paper padding (sm restates the current 2.5 == 20px). */
    padding: { xs: 1.5, sm: 2.5 },
    /** Internal vertical gap (sm restates the current 1.5 == 12px). */
    gap: { xs: 0.75, sm: 1.5 },
  } as const satisfies Record<string, ResponsiveValue>,
  /** Raw-pixel sizes for numeric props (e.g. `CompanyLogo` `size`). */
  logoSize: { compact: 32, default: 44 },
} as const;

/**
 * `sx` for a wide MUI `<TableContainer>` so an 8-column admin table is swipeable
 * on mobile instead of bleeding past its container. origin/main rendered these
 * as bare `<TableContainer>` (no `sx`), relying on MUI's root default
 * `overflowX: 'auto'` (the container scrolls horizontally and contains its own
 * overflow at every width). This token RESTATES that exact default on every
 * breakpoint — a true no-op at all widths, including desktop/tablet (>= 600px) —
 * so its ONLY net effect is adding `WebkitOverflowScrolling: 'touch'` for iOS
 * momentum scrolling on the already-scrollable container. (A flat `overflowX`
 * is deliberate: `sm: 'visible'` would have changed desktop/tablet from `auto`
 * to `visible`, letting wide tables overflow their container — a regression.)
 * Reused by every wide admin table (admin/users, qa, feedback,
 * location-normalization) — the single source of the mobile-table-scroll rule.
 */
export const TABLE_SCROLL_SX = {
  // MUI TableContainer's default overflowX. Flat (same on every breakpoint) so
  // the container keeps containing its overflow on desktop/tablet, exactly as
  // origin's bare `<TableContainer>` did.
  overflowX: 'auto',
  // Momentum scrolling on iOS so the swipe feels native.
  WebkitOverflowScrolling: 'touch',
} as const;
