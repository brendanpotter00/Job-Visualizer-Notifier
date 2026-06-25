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

  describe('TABLE_SCROLL_SX', () => {
    it('scrolls on mobile (xs) and is visible (no-op) on desktop (sm)', () => {
      expect(TABLE_SCROLL_SX.overflowX).toEqual({ xs: 'auto', sm: 'visible' });
    });
  });
});
