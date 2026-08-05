import { describe, it, expect } from 'vitest';
import { createTestStore } from '../../../test/testUtils';
import type { RootState } from '../../../app/store';
import type { Job } from '../../../types';
import { jobsApi } from '../../../features/jobs/jobsApi';
import { selectAllJobsFromQuery } from '../../../features/filters/selectors/recentJobsSelectors';
import {
  selectCompleteHorizon,
  selectHasMoreJobs,
} from '../../../features/jobs/jobsSelectors';

/**
 * The ragged-chunk bug, end to end.
 *
 * The batched load is three independent keyset walks. On prod, page 1 of the
 * three chunks cut off at 07-30 / 07-28 / 07-21 — so a naive merge is complete
 * only down to 07-30 and increasingly biased below it (chunk A's companies
 * simply stop appearing). These tests pin that the Recent page renders only the
 * provably-complete prefix.
 */

const CHUNK_A = 'a1,a2';
const CHUNK_B = 'b1,b2';
const CHUNK_C = 'c1,c2';

function job(company: string, id: string, firstSeenAt: string): Job {
  return {
    id,
    source: 'backend-scraper',
    company,
    title: `${company} ${id}`,
    location: 'Remote',
    createdAt: firstSeenAt,
    firstSeenAt,
    url: `https://example.com/${id}`,
    raw: { sourceId: 'greenhouse' },
  };
}

/** Chunk A reaches 07-30, B reaches 07-28, C reaches 07-21. */
const RAGGED_BY_COMPANY: Record<string, Job[]> = {
  a1: [job('a1', 'a-aug02', '2026-08-02T00:00:00.000Z'), job('a1', 'a-jul30', '2026-07-30T00:00:00.000Z')],
  b1: [job('b1', 'b-aug01', '2026-08-01T00:00:00.000Z'), job('b1', 'b-jul28', '2026-07-28T00:00:00.000Z')],
  c1: [job('c1', 'c-aug03', '2026-08-03T00:00:00.000Z'), job('c1', 'c-jul21', '2026-07-21T00:00:00.000Z')],
};

const RAGGED_FLOORS = {
  [CHUNK_A]: '2026-07-30T00:00:00.000Z',
  [CHUNK_B]: '2026-07-28T00:00:00.000Z',
  [CHUNK_C]: '2026-07-21T00:00:00.000Z',
};

async function seed(
  cursors: Record<string, string>,
  chunkFloors: Record<string, string> = RAGGED_FLOORS,
  byCompanyId: Record<string, Job[]> = RAGGED_BY_COMPANY
) {
  const store = createTestStore();
  await store.dispatch(
    jobsApi.util.upsertQueryData('getAllJobs', undefined, {
      byCompanyId,
      metadata: {},
      errors: {},
      progress: { completed: 3, total: 3, companies: [] },
      isStreaming: false,
      cursors,
      chunkFloors,
      windowKey: '90d',
      since: '2026-05-07T00:00:00.000Z',
    })
  );
  return store;
}

const ids = (jobs: Job[]) => jobs.map((j) => j.id).sort();

describe('complete-prefix clamp on the Recent page', () => {
  it('renders exactly the rows at or above the shallowest ACTIVE cutoff', async () => {
    const store = await seed({ [CHUNK_A]: 'ca', [CHUNK_B]: 'cb', [CHUNK_C]: 'cc' });
    const state = store.getState() as RootState;

    expect(selectCompleteHorizon(state)).toBe('2026-07-30T00:00:00.000Z');
    // Everything below 07-30 is withheld — including chunk C's 07-21 row, which
    // is exactly the biased tail that would otherwise render.
    expect(ids(selectAllJobsFromQuery(state))).toEqual(['a-aug02', 'a-jul30', 'b-aug01', 'c-aug03']);
    expect(selectHasMoreJobs(state)).toBe(true);
  });

  it('extends the horizon after a next page deepens the shallowest chunk', async () => {
    // Chunk A walked on to 07-25; B is now the shallowest active chunk (07-28).
    const store = await seed(
      { [CHUNK_A]: 'ca2', [CHUNK_B]: 'cb', [CHUNK_C]: 'cc' },
      { ...RAGGED_FLOORS, [CHUNK_A]: '2026-07-25T00:00:00.000Z' },
      {
        ...RAGGED_BY_COMPANY,
        a1: [...RAGGED_BY_COMPANY.a1, job('a1', 'a-jul26', '2026-07-26T00:00:00.000Z')],
      }
    );
    const state = store.getState() as RootState;

    expect(selectCompleteHorizon(state)).toBe('2026-07-28T00:00:00.000Z');
    // The previously-withheld 07-28 row surfaces; 07-26 and 07-21 stay cached
    // but withheld because chunk B has not reached them yet.
    expect(ids(selectAllJobsFromQuery(state))).toEqual([
      'a-aug02',
      'a-jul30',
      'b-aug01',
      'b-jul28',
      'c-aug03',
    ]);
  });

  it('stops bounding once a chunk exhausts its cursor', async () => {
    // Chunk A is DONE at 07-30. It cannot be missing rows, so its shallow floor
    // must no longer hold the horizon back.
    const store = await seed({ [CHUNK_B]: 'cb', [CHUNK_C]: 'cc' });
    const state = store.getState() as RootState;

    expect(selectCompleteHorizon(state)).toBe('2026-07-28T00:00:00.000Z');
    expect(ids(selectAllJobsFromQuery(state))).toEqual([
      'a-aug02',
      'a-jul30',
      'b-aug01',
      'b-jul28',
      'c-aug03',
    ]);
  });

  it('clamps nothing once the whole walk is exhausted', async () => {
    const store = await seed({});
    const state = store.getState() as RootState;

    expect(selectCompleteHorizon(state)).toBeNull();
    expect(selectHasMoreJobs(state)).toBe(false);
    expect(ids(selectAllJobsFromQuery(state))).toEqual([
      'a-aug02',
      'a-jul30',
      'b-aug01',
      'b-jul28',
      'c-aug03',
      'c-jul21',
    ]);
  });

  it('withholds nothing from a company whose chunk is still active but shallow', async () => {
    // Sanity: the clamp is by DATE, not by chunk membership — a chunk-C row
    // above the horizon still renders even though chunk C is the deepest.
    const store = await seed({ [CHUNK_A]: 'ca' });
    const state = store.getState() as RootState;
    expect(selectCompleteHorizon(state)).toBe('2026-07-30T00:00:00.000Z');
    expect(ids(selectAllJobsFromQuery(state))).toContain('c-aug03');
    expect(ids(selectAllJobsFromQuery(state))).not.toContain('c-jul21');
  });
});
