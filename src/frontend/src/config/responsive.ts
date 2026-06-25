/**
 * Responsive design tokens — the single source of truth for the app's compact
 * mobile layout. As more pages are made mobile-friendly, add tokens here and
 * consume them instead of hard-coding sizes at call sites.
 *
 * Two token shapes:
 *  - MUI responsive sx objects (`{ xs, sm }`) for use directly in `sx` props.
 *  - `{ compact, default }` numeric pairs for props that take a raw number
 *    (e.g. `CompanyLogo`'s `size`), selected via the `useIsMobile` hook.
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
  /** Raw-pixel sizes for numeric props (e.g. `CompanyLogo` `size`). */
  logoSize: { compact: 32, default: 44 },
} as const;
