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
  // Restates the body2 desktop font; the ONLY no-op { xs, sm } token whose group
  // is plain `as const` (mixed shapes), so the compiler can't guard it — pin it
  // here so dropping `sm` (shrinking the desktop description, a Ledger #1
  // violation) fails this test.
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
 * Reflectively walk a RESPONSIVE-shaped object, recording the dotted path of
 * every no-op TOKEN by shape. A plain object is treated as a leaf token (not a
 * group to recurse into) as soon as it carries any token marker key. Only the
 * two pinned shapes are collected:
 *  - `{ xs, sm }` (EXACT key set) → `xsSmPaths`   (pinned in SM_DESKTOP)
 *  - `{ compact, default }` (has `compact`) → `compactPaths` (pinned in DEFAULT_DESKTOP)
 * The multi-breakpoint `gridItemSize` (`{ xs, sm, md }`) and the
 * `{ top, right, left, bottom }` margin objects are intentionally NOT collected
 * (they have dedicated assertions / are not a pinned scalar shape). Flat scalar
 * tokens (e.g. `jobCard.*`, `chart.axisFontSizeCompact`/`minTickGapCompact`) are
 * mobile-only with no desktop counterpart, so they are skipped entirely.
 */
function collectTokenPaths(
  node: Record<string, unknown>,
  prefix: string,
  xsSmPaths: string[],
  compactPaths: string[]
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
      }
      // else: `gridItemSize` ({ xs, sm, md }) — skipped here, asserted separately.
      continue;
    }
    collectTokenPaths(value, path, xsSmPaths, compactPaths);
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
    collectTokenPaths(
      RESPONSIVE as unknown as Record<string, unknown>,
      '',
      xsSmPaths,
      compactPaths
    );

    it('finds the known no-op tokens (walk sanity check)', () => {
      // If these regress to empty, the walk is broken and the guarantees below
      // are vacuous — so assert the walk actually sees real tokens.
      expect(xsSmPaths).toContain('curatedCard.descriptionFontSize');
      expect(xsSmPaths).toContain('keywordCard.contentPadding');
      expect(compactPaths).toContain('keywordCard.chipFontSize');
      expect(compactPaths).toContain('logoSize');
      // `gridItemSize` is a multi-breakpoint Grid-size object, not a no-op
      // `{ xs, sm }` token — it must NOT be collected (asserted separately).
      expect(xsSmPaths).not.toContain('curatedCard.gridItemSize');
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
  });

  describe('TABLE_SCROLL_SX', () => {
    it('scrolls on mobile (xs) and is visible (no-op) on desktop (sm)', () => {
      expect(TABLE_SCROLL_SX.overflowX).toEqual({ xs: 'auto', sm: 'visible' });
    });
  });
});
