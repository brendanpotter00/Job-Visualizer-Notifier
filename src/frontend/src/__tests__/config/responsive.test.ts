import { describe, it, expect } from 'vitest';
import { RESPONSIVE, MOBILE_BREAKPOINT, TABLE_SCROLL_SX } from '../../config/responsive';

/**
 * The load-bearing invariant of the responsive-token system: applying a token
 * must be a NO-OP at the desktop/tablet breakpoint (>= 600px). MUI `sx` is
 * mobile-first, so for every `{ xs, sm }` token the `sm` slot MUST restate the
 * value the call site renders on desktop today; otherwise an `xs`-only value
 * leaks up and silently regresses desktop. TypeScript can enforce the SHAPE
 * (both slots present) but not the VALUE, so this test pins the desktop value
 * of every `{ xs, sm }` token. If you change a token, update the expected `sm`
 * here to the real current desktop value — never weaken the assertion.
 *
 * Same idea for `{ compact, default }` raw-number tokens: `default` is the
 * desktop value selected when `useIsMobile()` is false, so it is pinned too.
 */

// Desktop (`sm`) value expected for each `{ xs, sm }` sx token.
const SM_DESKTOP: Record<string, number | string> = {
  'spacing.pageMarginY': 4,
  'spacing.sectionMarginB': 3,
  'spacing.paperPadding': 3,
  'spacing.paperPaddingLg': 4,
  'spacing.rowSpacing': 3,
  'spacing.filterSpacing': 2,
  'spacing.cardPadding': 2,
  'spacing.cardPaddingBottom': 3,
  'spacing.cardMarginB': 2,
  'spacing.cardStackSpacing': 1,
  'fontSize.pageTitle': '1.75rem',
  'fontSize.metricValue': '1.75rem',
  'fontSize.metricLabel': '0.875rem',
  'fontSize.cardTitle': '1rem',
  'control.minHeight': 44,
  'control.fontSize': '1rem',
  'control.inputPaddingY': '8.5px',
  'control.buttonFontSize': '0.8125rem',
  'curatedCard.gridSpacing': 2,
  'curatedCard.contentPadding': 2,
  // Restates the body2 desktop font. One of the mixed-shape-group `{ xs, sm }`
  // tokens the compiler can't guard (its `curatedCard` group is plain `as const`,
  // alongside `curatedCard.contentPadding`/`gridSpacing` and
  // `keywordCard.contentPadding`) — all pinned here and backstopped by the
  // pin-completeness walk below, so dropping `sm` (shrinking the desktop
  // description, a Ledger #1 violation) fails this test.
  'curatedCard.descriptionFontSize': '0.875rem',
  'keywordCard.contentPadding': 2,
  'statTile.padding': 2.5,
  'statTile.gap': 1.5,
};

// Desktop (`default`) value expected for each `{ compact, default }` token.
const DEFAULT_DESKTOP: Record<string, number | string> = {
  'chart.height': 400,
  'chart.dotR': 4,
  'chart.activeDotR': 6,
  'adminChart.height': 280,
  'curatedCard.wordmarkHeight': 32,
  'keywordCard.chipHeight': 24,
  'keywordCard.chipFontSize': '0.8125rem',
  'logoSize': 44,
};

function dig(path: string): Record<string, unknown> {
  return path
    .split('.')
    .reduce<Record<string, unknown>>(
      (o, k) => o[k] as Record<string, unknown>,
      RESPONSIVE as unknown as Record<string, unknown>
    );
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

// Keys that mark a plain object as a leaf TOKEN (vs. a group to descend into).
const TOKEN_MARKER_KEYS = ['xs', 'sm', 'compact', 'default'];

/**
 * Reflectively walk a RESPONSIVE-shaped object, classifying every desktop-bearing
 * leaf TOKEN by shape so NONE can slip through unaccounted-for. A plain object is
 * treated as a leaf token (not a group to recurse into) as soon as it carries any
 * token marker key. The classification is SYMMETRIC across the `xs`/`sm` and
 * `compact` axes:
 *  - `{ xs, sm }` (EXACT key set) → `xsSmPaths`   (pinned in SM_DESKTOP)
 *  - has `compact` (`{ compact, default }`) → `compactPaths` (pinned in DEFAULT_DESKTOP)
 *  - ANY OTHER leaf carrying `xs` or `sm` but NOT exactly `{ xs, sm }`
 *    (e.g. `{ xs }`-only, `{ xs, sm, md }`, `{ xs, md }`) → `otherResponsivePaths`,
 *    which the caller asserts equals a tiny known multi-breakpoint allowlist.
 * That last bucket is the key to symmetry: an `sm`-omitted no-op (`{ xs: 1 }`,
 * the canonical Ledger #1 regression) or an `md`-gated token added to a
 * mixed-shape group would otherwise match neither pinned branch and be silently
 * dropped — here it lands in `otherResponsivePaths` and fails the allowlist
 * assertion, naming the path. The `{ top, right, left, bottom }` margin objects
 * carry no marker key, so they are recursed into harmlessly (their numeric
 * leaves are scalars). Flat scalar tokens (e.g. `jobCard.*`,
 * `chart.axisFontSizeCompact`/`minTickGapCompact`) are mobile-only with no
 * desktop counterpart, so they are skipped entirely.
 */
function collectTokenPaths(
  node: Record<string, unknown>,
  prefix: string,
  xsSmPaths: string[],
  compactPaths: string[],
  otherResponsivePaths: string[]
): void {
  for (const [key, value] of Object.entries(node)) {
    if (!isPlainObject(value)) continue; // flat scalar — not a pinnable token
    const path = prefix ? `${prefix}.${key}` : key;
    const keys = Object.keys(value);
    const isLeafToken = TOKEN_MARKER_KEYS.some((k) => keys.includes(k));
    if (isLeafToken) {
      if (keys.length === 2 && keys.includes('xs') && keys.includes('sm')) {
        xsSmPaths.push(path);
      } else if (keys.includes('compact')) {
        compactPaths.push(path);
      } else if (keys.includes('xs') || keys.includes('sm')) {
        // Carries a desktop-bearing breakpoint key but isn't exactly { xs, sm }
        // (sm-omitted, or extra md/etc.). Must be an INTENTIONAL multi-breakpoint
        // token on the allowlist asserted by the caller — otherwise it's an
        // un-restated token that could leak its xs value into desktop.
        otherResponsivePaths.push(path);
      }
      continue;
    }
    collectTokenPaths(value, path, xsSmPaths, compactPaths, otherResponsivePaths);
  }
}

describe('RESPONSIVE token invariants', () => {
  it('mobile breakpoint is sm (<600px)', () => {
    expect(MOBILE_BREAKPOINT).toBe('sm');
  });

  describe('every { xs, sm } token restates the desktop value in sm', () => {
    it.each(Object.entries(SM_DESKTOP))('%s.sm === desktop value', (path, expected) => {
      const token = dig(path) as unknown as { xs: unknown; sm: unknown };
      expect(token).toHaveProperty('xs');
      expect(token).toHaveProperty('sm');
      expect(token.sm).toBe(expected);
    });
  });

  describe('every { compact, default } token keeps the desktop value in default', () => {
    it.each(Object.entries(DEFAULT_DESKTOP))('%s.default === desktop value', (path, expected) => {
      const token = dig(path) as unknown as { compact: unknown; default: unknown };
      expect(token).toHaveProperty('compact');
      expect(token).toHaveProperty('default');
      expect(token.default).toBe(expected);
    });
  });

  it('every compact value is smaller-or-equal to its default (mobile never grows)', () => {
    for (const path of Object.keys(DEFAULT_DESKTOP)) {
      const { compact, default: def } = dig(path) as unknown as {
        compact: number | string;
        default: number | string;
      };
      if (typeof compact === 'number' && typeof def === 'number') {
        expect(compact).toBeLessThanOrEqual(def);
      }
    }
  });

  // Object-shaped desktop tokens that don't fit the scalar `.sm`/`.default`
  // lookups above. Pinned with dedicated assertions so a future edit to any of
  // these desktop layout values fails a test.
  describe('object-shaped desktop layout tokens', () => {
    it('chart.marginDefault restates the desktop LineChart margins', () => {
      expect(RESPONSIVE.chart.marginDefault).toEqual({ top: 5, right: 30, left: 20, bottom: 5 });
    });

    it('curatedCard.gridItemSize restates the desktop 1-up / 2-up / 3-up layout', () => {
      expect(RESPONSIVE.curatedCard.gridItemSize).toEqual({ xs: 12, sm: 6, md: 4 });
    });
  });

  // Self-policing backstop: the SM_DESKTOP / DEFAULT_DESKTOP maps above are a
  // hand-maintained allowlist iterated by their OWN keys, so a NEW no-op token
  // added to a mixed-shape group (which carries no compile-time `satisfies`
  // guard) and forgotten in the map would compile AND pass every assertion
  // above — silently regressing desktop. This block reflectively walks the
  // whole RESPONSIVE object and fails if any `{ xs, sm }` or `{ compact, default }`
  // token is missing from its pin map, naming the unpinned path.
  describe('pin-completeness backstop (allowlist is self-policing)', () => {
    const xsSmPaths: string[] = [];
    const compactPaths: string[] = [];
    // Every leaf carrying `xs`/`sm` but NOT exactly `{ xs, sm }` lands here — the
    // symmetric catch-all that makes an sm-omitted or md-gated no-op token
    // (which matches neither pinned branch) impossible to drop silently. The
    // ONLY intentional member is the multi-breakpoint Grid-size token below.
    const otherResponsivePaths: string[] = [];
    // The known intentional multi-breakpoint tokens (NOT pinned-scalar shapes; each
    // has its own dedicated assertion). Adding a new one here is a deliberate act.
    const KNOWN_MULTI_BREAKPOINT_PATHS = ['curatedCard.gridItemSize'];
    collectTokenPaths(
      RESPONSIVE as unknown as Record<string, unknown>,
      '',
      xsSmPaths,
      compactPaths,
      otherResponsivePaths
    );

    it('finds the known no-op tokens (walk sanity check)', () => {
      // If these regress to empty, the walk is broken and the guarantees below
      // are vacuous — so assert the walk actually sees real tokens.
      expect(xsSmPaths).toContain('curatedCard.descriptionFontSize');
      expect(xsSmPaths).toContain('keywordCard.contentPadding');
      expect(compactPaths).toContain('keywordCard.chipFontSize');
      expect(compactPaths).toContain('logoSize');
      // `gridItemSize` is a multi-breakpoint Grid-size object, not a no-op
      // `{ xs, sm }` token — it must land in the `other` bucket, not xsSm.
      expect(xsSmPaths).not.toContain('curatedCard.gridItemSize');
      expect(otherResponsivePaths).toContain('curatedCard.gridItemSize');
    });

    it('every { xs, sm } token in RESPONSIVE is pinned in SM_DESKTOP', () => {
      const unpinned = xsSmPaths.filter((p) => !(p in SM_DESKTOP));
      expect(
        unpinned,
        `Unpinned { xs, sm } token(s) — add the desktop value to SM_DESKTOP: ${unpinned.join(', ')}`
      ).toEqual([]);
    });

    it('every { compact, default } token in RESPONSIVE is pinned in DEFAULT_DESKTOP', () => {
      const unpinned = compactPaths.filter((p) => !(p in DEFAULT_DESKTOP));
      expect(
        unpinned,
        `Unpinned { compact, default } token(s) — add the desktop value to DEFAULT_DESKTOP: ${unpinned.join(', ')}`
      ).toEqual([]);
    });

    it('every xs/sm leaf that is not exactly { xs, sm } is a known multi-breakpoint token', () => {
      // Symmetric catch-all: an sm-omitted no-op (`{ xs: 1 }`) or an md-gated
      // token (`{ xs, sm, md }` / `{ xs, md }`) added to a mixed-shape group —
      // neither of which matches the pinned `{ xs, sm }` or `{ compact, default }`
      // branches — surfaces HERE instead of being silently dropped. Any path not
      // on the intentional allowlist fails, naming itself.
      const unexpected = otherResponsivePaths.filter(
        (p) => !KNOWN_MULTI_BREAKPOINT_PATHS.includes(p)
      );
      expect(
        unexpected,
        `Unaccounted xs/sm token(s) that aren't exactly { xs, sm } — restate sm to make it a desktop no-op, or add it to KNOWN_MULTI_BREAKPOINT_PATHS with a dedicated assertion: ${unexpected.join(', ')}`
      ).toEqual([]);
      // And the allowlist itself must stay exactly populated (no stale entries).
      expect(otherResponsivePaths).toEqual(KNOWN_MULTI_BREAKPOINT_PATHS);
    });
  });

  describe('TABLE_SCROLL_SX', () => {
    it("restates MUI TableContainer's default overflowX:auto on all breakpoints (desktop no-op; adds only touch momentum)", () => {
      expect(TABLE_SCROLL_SX.overflowX).toBe('auto');
      expect(TABLE_SCROLL_SX.WebkitOverflowScrolling).toBe('touch');
    });
  });
});
