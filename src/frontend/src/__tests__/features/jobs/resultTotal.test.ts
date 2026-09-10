import { describe, it, expect } from 'vitest';
import { resolveResultTotal, ariaSetSizeFor } from '../../../features/jobs/resultTotal';
import type { SearchJobsCounts } from '../../../features/jobs/searchJobsTypes';

const counts = (total: number | null): SearchJobsCounts => ({
  total,
  last24h: 309,
  last3h: 9,
});

describe('resolveResultTotal', () => {
  it('is unknown before page 1 has landed', () => {
    expect(resolveResultTotal(null, 0, false)).toEqual({ kind: 'unknown' });
  });

  it('stays unknown even with rows in hand, because those rows are the PREVIOUS filter set', () => {
    // `counts === null` on an initial error is the hook deliberately dropping the
    // old filter set's figures while `data` still holds its pages. Counting them
    // would put a confident number under filter chips it does not describe.
    expect(resolveResultTotal(null, 40, false)).toEqual({ kind: 'unknown' });
  });

  describe('when the server defers the exact total (the real signed-in path since #277)', () => {
    it('reports the rows walked as a LOWER BOUND while the walk can continue', () => {
      expect(resolveResultTotal(counts(null), 50, false)).toEqual({
        kind: 'atLeast',
        value: 50,
      });
    });

    it('becomes exact once the walk is exhausted — the rows in hand ARE the set', () => {
      expect(resolveResultTotal(counts(null), 50, true)).toEqual({
        kind: 'exact',
        value: 50,
      });
    });

    it('treats "capped" and "exhausted" as the caller\'s call, not its own', () => {
      // The helper never infers truncation — the hook decides, because only it
      // knows whether the signed-out cap actually withheld anything. Same rows,
      // opposite verdicts, driven purely by the flag.
      expect(resolveResultTotal(counts(null), 12, false)).toEqual({
        kind: 'atLeast',
        value: 12,
      });
      expect(resolveResultTotal(counts(null), 12, true)).toEqual({
        kind: 'exact',
        value: 12,
      });
    });

    it('is never a bare zero over a landed, empty result', () => {
      // Zero rows and an exhausted walk is a genuine "nothing matched", which the
      // list's own empty state says in words. The tile may state it as a number.
      expect(resolveResultTotal(counts(null), 0, true)).toEqual({
        kind: 'exact',
        value: 0,
      });
    });
  });

  describe('when an exact total is available (demo mode)', () => {
    it('uses it', () => {
      expect(resolveResultTotal(counts(137), 20, false)).toEqual({
        kind: 'exact',
        value: 137,
      });
    });

    it('is floored at the rows on screen, so "item 51 of 50" is impossible', () => {
      // The corpus can gain rows between page 1 and page N.
      expect(resolveResultTotal(counts(50), 51, false)).toEqual({
        kind: 'exact',
        value: 51,
      });
    });
  });
});

describe('ariaSetSizeFor', () => {
  it('announces only an exact total', () => {
    expect(ariaSetSizeFor({ kind: 'exact', value: 137 })).toBe(137);
  });

  it('refuses to announce a lower bound as the set size', () => {
    // ARIA has no spelling for "at least"; announcing 50 would tell a
    // screen-reader user they are at the end of a list they are 50 rows into.
    expect(ariaSetSizeFor({ kind: 'atLeast', value: 50 })).toBeNull();
    expect(ariaSetSizeFor({ kind: 'unknown' })).toBeNull();
  });
});
