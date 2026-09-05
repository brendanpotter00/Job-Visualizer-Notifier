/**
 * Column counts of the feature matrix grid, per breakpoint. Must stay in sync
 * with `MATRIX_GRID_SX` in FeatureMatrixSection — they are two halves of one
 * layout, split only so the arithmetic can be unit-tested without asserting on
 * media queries (jsdom does not resolve them, so a DOM-level assertion about a
 * responsive `gridColumn` would pass no matter what this returned).
 */
export const MATRIX_COLUMNS = { xs: 2, sm: 3 } as const;

/** Whether a cell should span its whole row, per breakpoint. */
export interface MatrixCellSpans {
  xs: boolean;
  sm: boolean;
}

/**
 * Decides whether the cell at `index` of a `count`-cell tier must widen to fill
 * its row, at each breakpoint.
 *
 * The rule is narrow on purpose: a cell fills the row only when it would
 * otherwise sit ALONE in the trailing one. A lone cell draws its top hairline
 * across a fraction of the matrix and stops, which reads as a row that failed
 * to finish rather than one that closed. A trailing row that is merely partial
 * (two cells of three) is left alone — it still draws a rule across most of the
 * width and reads as a deliberate short row, and widening one of its two cells
 * would make the pair asymmetric for no gain.
 *
 * Only the last cell can ever be the lone one, so every other index is `false`
 * at both breakpoints.
 */
export function matrixCellSpans(count: number, index: number): MatrixCellSpans {
  const isLast = index === count - 1;
  return {
    xs: isLast && count % MATRIX_COLUMNS.xs === 1,
    sm: isLast && count % MATRIX_COLUMNS.sm === 1,
  };
}
