import { describe, it, expect } from 'vitest';
import {
  MATRIX_COLUMNS,
  matrixCellSpans,
} from '../../../pages/LandingPage/sections/matrixLayout';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';

/** Every index of a `count`-cell tier, as [index, spans] pairs. */
function spansFor(count: number) {
  return Array.from({ length: count }, (_, i) => matrixCellSpans(count, i));
}

describe('matrixCellSpans', () => {
  it('never widens a cell that is not the last one', () => {
    for (const count of [1, 2, 3, 4, 5, 6, 7, 8, 9]) {
      for (const spans of spansFor(count).slice(0, -1)) {
        expect(spans).toEqual({ xs: false, sm: false });
      }
    }
  });

  // The rule in both grids: widen only when the trailing cell would be ALONE.
  it.each([
    // count, xs (2-up), sm (3-up)
    [1, true, true],
    [2, false, false],
    [3, true, false],
    [4, false, true],
    [5, true, false],
    [6, false, false],
    [7, true, true],
    [8, false, false],
    [9, true, false],
  ])('a %i-cell tier ends with spans xs=%s sm=%s', (count, xs, sm) => {
    expect(matrixCellSpans(count, count - 1)).toEqual({ xs, sm });
  });

  // A widened trailing cell must exactly close its row, never overflow it.
  it('only ever widens a cell to a full row of its grid', () => {
    for (let count = 1; count <= 12; count += 1) {
      const spans = matrixCellSpans(count, count - 1);
      if (spans.xs) expect((count - 1) % MATRIX_COLUMNS.xs).toBe(0);
      if (spans.sm) expect((count - 1) % MATRIX_COLUMNS.sm).toBe(0);
    }
  });

  // The invariant that actually matters on the page: whatever the two tiers
  // currently hold, neither leaves a lone cell drawing a stub rule.
  it('leaves no orphan cell in either shipped tier, at either breakpoint', () => {
    const { features, comingSoon } = LANDING_CONTENT.featureMatrix;
    for (const tier of [features, comingSoon]) {
      for (const [key, columns] of Object.entries(MATRIX_COLUMNS)) {
        const cellsInLastRow = tier.length % columns;
        const lastSpans = matrixCellSpans(tier.length, tier.length - 1);
        // Either the last row has more than one cell, or the trailing cell was
        // widened to fill it.
        expect(
          cellsInLastRow !== 1 || lastSpans[key as keyof typeof MATRIX_COLUMNS],
          `${tier.length} cells orphans one at ${key}`
        ).toBeTruthy();
      }
    }
  });
});
