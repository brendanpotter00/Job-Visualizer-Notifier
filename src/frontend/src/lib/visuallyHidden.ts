/**
 * `sx` that hides an element visually but keeps it in the accessibility tree
 * (the classic "sr-only" recipe). Use it for text a screen reader must hear
 * and a sighted reader must not see: a hidden field label, a live region, the
 * spoken form of a visual counter.
 */
export const VISUALLY_HIDDEN_SX = {
  border: 0,
  clip: 'rect(0 0 0 0)',
  height: '1px',
  margin: '-1px',
  overflow: 'hidden',
  padding: 0,
  position: 'absolute',
  whiteSpace: 'nowrap',
  width: '1px',
} as const;
