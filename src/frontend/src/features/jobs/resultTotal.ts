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
 * That distinction is the whole point of this module, and `aria-setsize` is now
 * its only consumer: ARIA needs a SET SIZE, so it may be told an exact total or
 * "unknown" (-1) and nothing in between — announcing a lower bound would tell a
 * screen-reader user they are at the end of a list they are twenty rows into.
 *
 * A header tile shared this derivation briefly and rendered the third case as
 * "50+". It was removed at the owner's request (2026-09-05) — see the header
 * comment on `RecentJobsMetrics` — which is why a module this size has one
 * caller. The three-way split is kept rather than collapsed into
 * `number | null`, because the two nulls are NOT the same fact ("nothing has
 * measured this" vs "at least this many"), and flattening them is how the tile
 * came to render a permanent em-dash in the first place.
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

/**
 * What assistive tech hears as `aria-setsize`. ARIA has no spelling for a lower
 * bound, so a mid-walk count must be announced as unknown (`-1`) rather than as a
 * size — telling a screen-reader user they are at the end of a list they are
 * twenty rows into is worse than telling them the length is unknown.
 */
export function ariaSetSizeFor(total: ResultTotal): number | null {
  return total.kind === 'exact' ? total.value : null;
}
