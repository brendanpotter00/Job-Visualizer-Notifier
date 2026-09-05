/**
 * How many jobs the current filter set holds — as far as anyone can honestly say.
 *
 * There are three genuinely different answers and they must not be flattened into
 * one number. Since Wave-1 B1 (#277) the server no longer computes
 * `filtered_total` on page 1 — an owner decision that fast searches beat exact
 * counts, because that count re-ran the whole keyword predicate a second time on
 * the same pooled connection (see the COST WARNING in `services/job_search.py`).
 * It sends `null`, and the rows the reader has walked are then a LOWER BOUND, not
 * a total.
 *
 * That distinction is the whole point of this module. The header tile and the
 * list's `aria-setsize` both need it and each renders it differently — a tile can
 * say "50+", ARIA has no way to express a lower bound and must say "unknown" — so
 * the DERIVATION lives here once and only the rendering differs. They used to
 * disagree: after #277 the tile rendered an em-dash for every real search while
 * the list was already counting the same rows perfectly well.
 */

import type { SearchJobsCounts } from './searchJobsTypes.ts';

export type ResultTotal =
  /** Nothing has measured the set: page 1 has not landed, or it failed. */
  | { kind: 'unknown' }
  /** The whole result set is accounted for. */
  | { kind: 'exact'; value: number }
  /** At least this many, and the walk can still turn up more. */
  | { kind: 'atLeast'; value: number };

/**
 * @param counts Page 1's header metrics, or `null` when unknown.
 * @param displayedCount Rows the reader can actually see right now (already
 *   capped for signed-out readers).
 * @param walkExhausted Whether every matching row has been fetched. A signed-out
 *   reader is CAPPED, never exhausted — their dozen cards are a floor under
 *   thousands, so passing `true` there would announce "12" for the whole corpus.
 */
export function resolveResultTotal(
  counts: SearchJobsCounts | null,
  displayedCount: number,
  walkExhausted: boolean
): ResultTotal {
  if (counts === null) return { kind: 'unknown' };
  // An exact server total (demo mode still sends one) is floored at the rows on
  // screen for the one case the two disagree: the corpus can gain rows between
  // page 1 and page N, and "item 51 of 50" is worse than either number alone.
  if (counts.total !== null) {
    return { kind: 'exact', value: Math.max(counts.total, displayedCount) };
  }
  return walkExhausted
    ? { kind: 'exact', value: displayedCount }
    : { kind: 'atLeast', value: displayedCount };
}

/** What an unknown count renders as in the header tile. An em-dash, never a zero. */
export const UNKNOWN_TOTAL = '—';

export function formatResultTotal(total: ResultTotal): string {
  switch (total.kind) {
    case 'unknown':
      return UNKNOWN_TOTAL;
    case 'exact':
      return String(total.value);
    case 'atLeast':
      // "50+" — a lower bound stated as one. The reader is mid-walk and more rows
      // arrive as they scroll, so a bare "50" would read as a total and then tick
      // upwards for no visible reason.
      return `${total.value}+`;
  }
}

/**
 * What assistive tech hears as `aria-setsize`. ARIA has no spelling for a lower
 * bound, so a mid-walk count must be announced as unknown (`-1`) rather than as a
 * size — telling a screen-reader user they are at the end of a list they are
 * twenty rows into is worse than telling them the length is unknown.
 */
export function ariaSetSizeFor(total: ResultTotal): number | null {
  return total.kind === 'exact' ? total.value : null;
}
