import { describe, it, expect } from 'vitest';
import type { Job } from '../../../types';
import {
  chunkKey,
  clampToHorizon,
  computeCompleteHorizon,
  jobKey,
  jobsWindowForTimeWindow,
  oldestFirstSeenAt,
  parseChunkKey,
  RECENT_JOBS_DEFAULT_WINDOW,
  sinceForWindow,
} from '../../../features/jobs/keysetWalk';
import recentJobsReducer from '../../../features/filters/slices/recentJobsFiltersSlice';

const DAY_MS = 24 * 60 * 60 * 1000;

function job(overrides: Partial<Job> & { firstSeenAt: string }): Job {
  return {
    id: 'j1',
    source: 'backend-scraper',
    company: 'stripe',
    title: 'Engineer',
    createdAt: overrides.firstSeenAt,
    url: 'https://example.com/j1',
    raw: { sourceId: 'greenhouse' },
    ...overrides,
  };
}

describe('sinceForWindow', () => {
  const NOW = Date.parse('2026-08-05T00:00:00.000Z');

  it('maps 90d and 180d to a UTC lower bound that many days back', () => {
    expect(sinceForWindow('90d', NOW)).toBe(new Date(NOW - 90 * DAY_MS).toISOString());
    expect(sinceForWindow('180d', NOW)).toBe(new Date(NOW - 180 * DAY_MS).toISOString());
  });

  it("maps 'all' to the epoch, not to an absent since", () => {
    // `since` is what puts the backend in KEYSET mode; omitting it would
    // silently fall back to the legacy unpaginated path.
    expect(sinceForWindow('all', NOW)).toBe('1970-01-01T00:00:00.000Z');
  });

  it('always produces a UTC-suffixed ISO string (a naive value is a backend 422)', () => {
    expect(sinceForWindow('90d', NOW)).toMatch(/Z$/);
    expect(sinceForWindow('all', NOW)).toMatch(/Z$/);
  });
});

describe('jobsWindowForTimeWindow', () => {
  it('maps the wide UI windows to their own fetch window', () => {
    expect(jobsWindowForTimeWindow('180d')).toBe('180d');
    expect(jobsWindowForTimeWindow('all')).toBe('all');
  });

  it('maps every window up to 90 days onto the 90-day fetch (already covered)', () => {
    for (const tw of ['30m', '1h', '24h', '7d', '30d', '90d'] as const) {
      expect(jobsWindowForTimeWindow(tw)).toBe('90d');
    }
  });

  it('answers coverage, not the product default — a filter never over-fetches', () => {
    // Regression guard for the all-time default: if this mapping were written
    // as "fall back to RECENT_JOBS_DEFAULT_WINDOW", a 24-hour filter would ask
    // for an all-time fetch and the caller would restart the walk to get it.
    expect(jobsWindowForTimeWindow('24h')).not.toBe(RECENT_JOBS_DEFAULT_WINDOW);
  });
});

describe('RECENT_JOBS_DEFAULT_WINDOW', () => {
  it('matches the Recent page filter default, so the first load is never a widen', () => {
    // `useRecentJobsPaging` restarts the walk whenever the filter's covering
    // window ranks wider than the fetched one. If the walk were seeded narrower
    // than the filter slice's own default, that restart would fire on every
    // fresh load of the page and every default visitor would fetch page 1 twice.
    const initial = recentJobsReducer(undefined, { type: '@@INIT' });
    expect(jobsWindowForTimeWindow(initial.filters.timeWindow)).toBe(RECENT_JOBS_DEFAULT_WINDOW);
  });
});

describe('chunkKey / parseChunkKey / jobKey', () => {
  it('round-trips a chunk key', () => {
    const ids = ['a', 'b', 'c'];
    expect(parseChunkKey(chunkKey(ids))).toEqual(ids);
  });

  it('keys jobs on the composite PK, not id alone', () => {
    const a = job({ id: 'x', firstSeenAt: '2026-08-01T00:00:00Z', raw: { sourceId: 's1' } });
    const b = job({ id: 'x', firstSeenAt: '2026-08-01T00:00:00Z', raw: { sourceId: 's2' } });
    expect(jobKey(a)).not.toBe(jobKey(b));
  });

  it('tolerates a Job whose raw carries no sourceId', () => {
    expect(jobKey(job({ id: 'x', firstSeenAt: '2026-08-01T00:00:00Z', raw: {} }))).toBe(
      '|stripe|x'
    );
  });
});

describe('oldestFirstSeenAt', () => {
  it('returns the oldest timestamp regardless of page order', () => {
    const jobs = [
      job({ id: '1', firstSeenAt: '2026-07-30T00:00:00.000Z' }),
      job({ id: '2', firstSeenAt: '2026-07-21T00:00:00.000Z' }),
      job({ id: '3', firstSeenAt: '2026-07-28T00:00:00.000Z' }),
    ];
    expect(oldestFirstSeenAt(jobs)).toBe('2026-07-21T00:00:00.000Z');
  });

  it('returns null for an empty page', () => {
    expect(oldestFirstSeenAt([])).toBeNull();
  });
});

describe('computeCompleteHorizon', () => {
  // The prod-measured raggedness this whole mechanism exists for.
  const floors = {
    a: '2026-07-30T00:00:00.000Z',
    b: '2026-07-28T00:00:00.000Z',
    c: '2026-07-21T00:00:00.000Z',
  };

  it('is the SHALLOWEST active floor (max), not the deepest', () => {
    const horizon = computeCompleteHorizon({ a: 'c1', b: 'c2', c: 'c3' }, floors);
    expect(horizon).toBe('2026-07-30T00:00:00.000Z');
  });

  it('ignores chunks whose cursor is exhausted, however shallow their floor', () => {
    // Chunk `a` (shallowest, 07-30) is done — it cannot be missing anything, so
    // it must not bound the horizon. The bound falls to the next active chunk.
    const horizon = computeCompleteHorizon({ b: 'c2', c: 'c3' }, floors);
    expect(horizon).toBe('2026-07-28T00:00:00.000Z');
  });

  it('returns null when every cursor is exhausted (whole set complete)', () => {
    expect(computeCompleteHorizon({}, floors)).toBeNull();
  });

  it('returns null when there is no walk state at all', () => {
    expect(computeCompleteHorizon(undefined, undefined)).toBeNull();
  });

  it('treats an active chunk with no floor as non-bounding', () => {
    // Unreachable per the backend contract (a cursor implies a FULL page implies
    // rows). Non-bounding on purpose: blanking the list is worse than a
    // slightly-biased tail.
    const horizon = computeCompleteHorizon({ a: 'c1', zzz: 'c9' }, floors);
    expect(horizon).toBe('2026-07-30T00:00:00.000Z');
  });
});

describe('clampToHorizon', () => {
  const jobs = [
    job({ id: 'new', firstSeenAt: '2026-08-01T00:00:00.000Z' }),
    job({ id: 'edge', firstSeenAt: '2026-07-30T00:00:00.000Z' }),
    job({ id: 'old', firstSeenAt: '2026-07-22T00:00:00.000Z' }),
  ];

  it('keeps rows at or newer than the horizon (inclusive edge)', () => {
    const kept = clampToHorizon(jobs, '2026-07-30T00:00:00.000Z');
    expect(kept.map((j) => j.id)).toEqual(['new', 'edge']);
  });

  it('is a pass-through when the horizon is null', () => {
    expect(clampToHorizon(jobs, null)).toBe(jobs);
  });
});
