import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import type { ReactNode } from 'react';
import type { TimeWindow } from '../../../../types';
import type { RootState } from '../../../../app/store';

/**
 * Stands in for RTK Query's mutation trigger, including the `.unwrap()` promise
 * the hook chains onto — that chain is what turns a failed page into a latched
 * error instead of a silent retry loop, so the stub has to model it.
 */
let unwrapResult: () => Promise<unknown> = () => Promise.resolve({ added: 0, hasMore: false });
const fetchNextPage = vi.fn(() => ({ unwrap: () => unwrapResult() }));
let isFetchingNextPage = false;
let mutationError: unknown = undefined;

// Only the mutation HOOK is stubbed; `jobsApi` itself (and therefore
// `getAllJobs.select`) stays real so the selectors under test read the cache
// exactly as they do in the app. The mutation's own semantics are covered by
// __tests__/features/jobs/jobsApi.keyset.test.ts.
vi.mock('../../../../features/jobs/jobsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../../features/jobs/jobsApi')>();
  return {
    ...actual,
    useFetchNextJobsPageMutation: () => [
      fetchNextPage,
      { isLoading: isFetchingNextPage, error: mutationError },
    ],
  };
});

import {
  useRecentJobsPaging,
  selectJobsFirstPageSettled,
} from '../../../../components/recent-jobs-page/RecentJobsList/useRecentJobsPaging';

const DAY_MS = 24 * 60 * 60 * 1000;
const CHUNK = 'a,b';

interface CacheEntry {
  windowKey: string;
  isStreaming: boolean;
  cursors: Record<string, string>;
  chunkFloors: Record<string, string>;
}

/**
 * Store holding a hand-seeded `getAllJobs` cache entry. The seeding is
 * self-validating: `reads the seeded cache entry` below fails loudly if RTK
 * Query's cache-key shape ever drifts, rather than letting every other
 * assertion silently pass against an empty cache.
 */
function makeStore(timeWindow: TimeWindow, entry: CacheEntry | null) {
  return configureStore({
    reducer: {
      recentJobsFilters: () => ({ filters: { timeWindow, softwareOnly: false } }),
      jobsApi: () => ({
        queries: entry
          ? {
              'getAllJobs(undefined)': {
                status: 'fulfilled',
                endpointName: 'getAllJobs',
                data: entry,
              },
            }
          : {},
        mutations: {},
        provided: {},
        subscriptions: {},
        config: {},
      }),
    },
  });
}

function renderPaging(
  timeWindow: TimeWindow,
  entry: CacheEntry | null,
  { enabled = true }: { enabled?: boolean } = {}
) {
  const store = makeStore(timeWindow, entry);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Provider store={store}>{children}</Provider>
  );
  return { store, ...renderHook(() => useRecentJobsPaging({ enabled }), { wrapper }) };
}

/** A settled 90-day walk whose completeness horizon is 8 days back. */
const SETTLED_90D: CacheEntry = {
  windowKey: '90d',
  isStreaming: false,
  cursors: { [CHUNK]: 'cursor-1' },
  chunkFloors: { [CHUNK]: new Date(Date.now() - 8 * DAY_MS).toISOString() },
};

beforeEach(() => {
  fetchNextPage.mockClear();
  isFetchingNextPage = false;
  mutationError = undefined;
  unwrapResult = () => Promise.resolve({ added: 0, hasMore: false });
});

describe('useRecentJobsPaging', () => {
  it('reads the seeded cache entry (harness self-check)', () => {
    const { store } = renderPaging('90d', SETTLED_90D);
    expect(selectJobsFirstPageSettled(store.getState() as unknown as RootState)).toBe(true);
  });

  describe('window widening', () => {
    it('restarts the walk under the 180-day window when the filter exceeds the fetched bound', async () => {
      renderPaging('180d', SETTLED_90D);

      await waitFor(() => expect(fetchNextPage).toHaveBeenCalledWith({ window: '180d' }));
      expect(fetchNextPage).toHaveBeenCalledTimes(1);
    });

    it('restarts the walk under the all-time window', async () => {
      renderPaging('all', SETTLED_90D);

      await waitFor(() => expect(fetchNextPage).toHaveBeenCalledWith({ window: 'all' }));
    });

    it('widens even when the previous walk ran to completion', async () => {
      // No cursors left, but 180-day rows are still unreachable without a
      // restart — so widening must not be gated on having cursors.
      renderPaging('180d', { ...SETTLED_90D, cursors: {}, chunkFloors: {} });

      await waitFor(() => expect(fetchNextPage).toHaveBeenCalledWith({ window: '180d' }));
    });

    it('does not widen for windows already covered by the 90-day fetch', async () => {
      renderPaging('24h', SETTLED_90D);

      await waitFor(() => expect(fetchNextPage).not.toHaveBeenCalled());
    });

    it('does not re-fetch when the user narrows back down from a wider walk', async () => {
      renderPaging('30d', { ...SETTLED_90D, windowKey: 'all' });

      await waitFor(() => expect(fetchNextPage).not.toHaveBeenCalled());
    });

    it('does not widen while the first page is still streaming in', async () => {
      renderPaging('all', { ...SETTLED_90D, isStreaming: true });

      await waitFor(() => expect(fetchNextPage).not.toHaveBeenCalled());
    });

    it('does not widen before any page exists', async () => {
      renderPaging('all', null);

      await waitFor(() => expect(fetchNextPage).not.toHaveBeenCalled());
    });

    it('does not widen for signed-out visitors', async () => {
      renderPaging('all', SETTLED_90D, { enabled: false });

      await waitFor(() => expect(fetchNextPage).not.toHaveBeenCalled());
    });

    it('does not widen while another page is already in flight', async () => {
      isFetchingNextPage = true;
      renderPaging('all', SETTLED_90D);

      await waitFor(() => expect(fetchNextPage).not.toHaveBeenCalled());
    });
  });

  describe('provably-complete time windows', () => {
    // The walk is first_seen_at DESC. Once the completeness horizon has dropped
    // past the window's lower bound, every remaining page is strictly older
    // than anything the filter admits.
    it('reports no more pages when the horizon is already past the window bound', () => {
      const { result } = renderPaging('24h', SETTLED_90D);

      expect(result.current.hasMoreServer).toBe(false);
    });

    it('does not fetch for a window the walk has already passed', () => {
      const { result } = renderPaging('24h', SETTLED_90D);

      result.current.loadNextServerPage();

      expect(fetchNextPage).not.toHaveBeenCalled();
    });

    it('still fetches for a window the walk has NOT reached the bottom of', () => {
      const { result } = renderPaging('90d', SETTLED_90D);

      expect(result.current.hasMoreServer).toBe(true);
      result.current.loadNextServerPage();

      expect(fetchNextPage).toHaveBeenCalledTimes(1);
    });

    it('never treats all-time as complete while cursors remain', () => {
      // All-time has no lower bound, so only cursor exhaustion can end it.
      const { result } = renderPaging('all', { ...SETTLED_90D, windowKey: 'all' });

      expect(result.current.hasMoreServer).toBe(true);
    });
  });

  describe('loadNextServerPage', () => {
    it('advances the walk with no window argument', () => {
      const { result } = renderPaging('90d', SETTLED_90D);

      result.current.loadNextServerPage();

      expect(fetchNextPage).toHaveBeenCalledTimes(1);
      expect(fetchNextPage).toHaveBeenCalledWith(undefined);
    });

    it('fires exactly once when triggered repeatedly before the request settles', () => {
      const { result } = renderPaging('90d', SETTLED_90D);

      result.current.loadNextServerPage();
      result.current.loadNextServerPage();
      result.current.loadNextServerPage();

      expect(fetchNextPage).toHaveBeenCalledTimes(1);
    });

    it('is a no-op once every cursor is exhausted', () => {
      const { result } = renderPaging('90d', { ...SETTLED_90D, cursors: {}, chunkFloors: {} });

      result.current.loadNextServerPage();

      expect(result.current.hasMoreServer).toBe(false);
      expect(fetchNextPage).not.toHaveBeenCalled();
    });

    it('does not widen from the manual path while the first page is still streaming', () => {
      // The sentinel stays mounted at zero visible rows (2026-08-10 fix) and
      // fires immediately, so this path can race the initial stream: a widen
      // dispatched mid-stream discards the entire in-flight page-1 load. The
      // widening effect re-fires once the stream settles, so returning here
      // loses nothing.
      const { result } = renderPaging('all', { ...SETTLED_90D, isStreaming: true });

      result.current.loadNextServerPage();

      expect(fetchNextPage).not.toHaveBeenCalled();
    });

    it('is a no-op for signed-out visitors', () => {
      const { result } = renderPaging('90d', SETTLED_90D, { enabled: false });

      result.current.loadNextServerPage();

      expect(result.current.hasMoreServer).toBe(false);
      expect(fetchNextPage).not.toHaveBeenCalled();
    });
  });

  describe('failed fetches', () => {
    it('surfaces a decoded error message', () => {
      mutationError = { status: 'CUSTOM_ERROR', data: 'Backend exploded' };
      const { result } = renderPaging('90d', SETTLED_90D);

      expect(result.current.error).toBe('Backend exploded');
    });

    it('stops auto-fetching once a page has failed', () => {
      mutationError = { status: 'CUSTOM_ERROR', data: 'Backend exploded' };
      const { result } = renderPaging('90d', SETTLED_90D);

      result.current.loadNextServerPage();
      result.current.loadNextServerPage();

      expect(fetchNextPage).not.toHaveBeenCalled();
    });

    it('does not auto-retry a failed WIDENING on every render', async () => {
      mutationError = { status: 'CUSTOM_ERROR', data: 'Backend exploded' };
      const { rerender } = renderPaging('all', SETTLED_90D);

      rerender();
      rerender();

      await waitFor(() => expect(fetchNextPage).not.toHaveBeenCalled());
    });

    it('retries exactly once on an explicit user retry', () => {
      mutationError = { status: 'CUSTOM_ERROR', data: 'Backend exploded' };
      const { result } = renderPaging('90d', SETTLED_90D);

      result.current.retryServerPage();

      expect(fetchNextPage).toHaveBeenCalledTimes(1);
    });

    it('swallows the rejection rather than letting it escape unhandled', async () => {
      unwrapResult = () => Promise.reject(new Error('network down'));
      const { result } = renderPaging('90d', SETTLED_90D);

      expect(() => result.current.loadNextServerPage()).not.toThrow();
      await waitFor(() => expect(fetchNextPage).toHaveBeenCalledTimes(1));

      // The in-flight guard released, so a later retry is still possible.
      result.current.retryServerPage();
      await waitFor(() => expect(fetchNextPage).toHaveBeenCalledTimes(2));
    });
  });

  it('reports an outstanding cursor as more server pages', () => {
    const { result } = renderPaging('90d', SETTLED_90D);
    expect(result.current.hasMoreServer).toBe(true);
  });
});
