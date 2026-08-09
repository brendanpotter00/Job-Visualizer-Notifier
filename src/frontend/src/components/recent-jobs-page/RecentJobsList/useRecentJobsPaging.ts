import { useCallback, useEffect, useRef } from 'react';
import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store.ts';
import { useAppSelector } from '../../../app/hooks.ts';
import { selectRecentJobsFilters } from '../../../features/filters/selectors/recentJobsSelectors.ts';
import {
  selectCompleteHorizon,
  selectHasMoreJobs,
  selectJobsWindowKey,
} from '../../../features/jobs/jobsSelectors.ts';
import {
  jobsApi,
  jobsWindowForTimeWindow,
  useFetchNextJobsPageMutation,
} from '../../../features/jobs/jobsApi.ts';
import type { JobsWindowKey } from '../../../features/jobs/jobsApi.ts';
import { TIME_WINDOW_DURATIONS } from '../../../constants/time.ts';
import { extractErrorMessage } from '../../../lib/errors.ts';
import { ERROR_MESSAGES } from '../../../constants/messages.ts';

/**
 * Widening order of the fetch windows.
 *
 * `jobsWindowForTimeWindow` answers "which fetch window covers this filter",
 * which is not the same question as "should we refetch". Every window change
 * that *narrows* (all-time back down to 30d) is already covered by what we
 * hold, and restarting the walk for it would throw away pages the user already
 * paid for. Only a strictly wider window earns a restart, so the two are
 * compared by rank rather than by equality.
 */
const WINDOW_RANK: Record<JobsWindowKey, number> = { '90d': 0, '180d': 1, all: 2 };

/**
 * Whether the initial multi-chunk load has finished landing.
 *
 * Distinguishes both "no cache entry at all" and "page 1 still streaming" from
 * "settled", because widening in either state races the in-flight first page:
 * its chunks finish under the OLD bound and write their cursors into an entry
 * that by then claims the new one.
 */
export const selectJobsFirstPageSettled = createSelector(
  [(state: RootState) => jobsApi.endpoints.getAllJobs.select()(state).data],
  (data) => data !== undefined && !data.isStreaming
);

/**
 * Whether the active time-window filter is provably fully fetched, so no
 * further page could produce a row it would show.
 *
 * The walk is `first_seen_at DESC` and `selectCompleteHorizon` is the point
 * above which the merged multi-chunk set is complete. Once that horizon has
 * dropped past the window's own lower bound, every row the filter admits has
 * already been fetched and every remaining page is strictly older — so paging
 * on is guaranteed waste, `hasMore` is honestly false, and "All N jobs loaded"
 * is honestly true. Without this rule a 24-hour filter would keep asking for
 * pages that provably cannot contain a 24-hour-old job.
 *
 * Two cases deliberately answer `false`:
 * - **All-time** has no lower bound, so only cursor exhaustion can end it.
 * - **A `null` horizon** means "no clamp". With cursors still outstanding that
 *   is the data layer's documented-unreachable case, and concluding
 *   "everything is fetched" from it would strand the user mid-corpus; the
 *   legitimate null (walk finished) is already covered by `selectHasMoreJobs`.
 */
export const selectWindowProvablyComplete = createSelector(
  [selectCompleteHorizon, selectRecentJobsFilters],
  (horizon, filters) => {
    if (horizon === null) return false;
    const durationMs = TIME_WINDOW_DURATIONS[filters.timeWindow];
    if (!Number.isFinite(durationMs)) return false;
    const horizonMs = new Date(horizon).getTime();
    if (Number.isNaN(horizonMs)) return false;
    return horizonMs <= Date.now() - durationMs;
  }
);

export interface RecentJobsPaging {
  /** Whether the server-side walk still holds pages this filter could show. */
  hasMoreServer: boolean;
  /** Whether a page (next page or a window-widening restart) is in flight. */
  isFetchingNextPage: boolean;
  /** Decoded message from the last failed page fetch; `null` when healthy. */
  error: string | null;
  /** Advance the walk. No-ops while in flight, and after a failure. */
  loadNextServerPage: () => void;
  /** User-initiated advance. Fetches again despite a previous failure. */
  retryServerPage: () => void;
}

/**
 * The Recent list's entire relationship with the keyset walk shipped in ticket
 * 1.3 — deliberately the ONLY place in the component tree that knows the walk
 * exists.
 *
 * Three jobs:
 *
 * 1. **Widening.** The Recent time-window filter offers `180d` and all-time
 *    above the 90-day default the first page is fetched under, and a keyset
 *    walk can never reach past the bound it started with. Left unwired, picking
 *    those windows would show only the 90-day superset — the list would look
 *    fine and silently omit rows. So when the user's window ranks wider than
 *    the one the walk holds, this restarts the walk under it. The comparison is
 *    on the data layer's *logical* window key, never a recomputed ISO
 *    timestamp, so it fires exactly once per genuine widening.
 * 2. **Paging.** `loadNextServerPage` advances the walk when the list has shown
 *    everything it holds — but only while the walk can still produce a row this
 *    filter would show (`selectWindowProvablyComplete`).
 * 3. **Failing loudly.** A rejected fetch leaves the cursors untouched, so
 *    without an explicit stop the sentinel re-arms and retries the same failing
 *    request forever, silently, for as long as the user sits at the bottom of
 *    the list. An error latches auto-fetching off and is handed to the caller
 *    to render; only `retryServerPage` resumes.
 *
 * All three share one mutation instance, so `isFetchingNextPage` covers them
 * all and the caller gets a single loading affordance.
 */
export function useRecentJobsPaging({ enabled }: { enabled: boolean }): RecentJobsPaging {
  const filters = useAppSelector(selectRecentJobsFilters);
  const fetchedWindow = useAppSelector(selectJobsWindowKey);
  const firstPageSettled = useAppSelector(selectJobsFirstPageSettled);
  const hasCursors = useAppSelector(selectHasMoreJobs);
  const windowProvablyComplete = useAppSelector(selectWindowProvablyComplete);
  const [fetchNextPage, { isLoading: isFetchingNextPage, error: fetchError }] =
    useFetchNextJobsPageMutation();

  // Pure: a filter key in, a window key out — no clock, so this is stable
  // across renders and safe as an effect dependency.
  const desiredWindow = jobsWindowForTimeWindow(filters.timeWindow);
  const needsWidening = WINDOW_RANK[desiredWindow] > WINDOW_RANK[fetchedWindow];
  const error = fetchError
    ? extractErrorMessage(fetchError, ERROR_MESSAGES.LOAD_JOBS_FAILED)
    : null;

  // `isFetchingNextPage` only flips on the next render, so two triggers firing
  // in the same tick (an IntersectionObserver callback landing next to the
  // widening effect) would both see `false`. This ref closes that window.
  const inFlightRef = useRef(false);

  const dispatchPage = useCallback(
    (arg?: { window: JobsWindowKey }) => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      fetchNextPage(arg)
        .unwrap()
        // The failure is already latched into the mutation's error state and
        // surfaced as `error` above, which is what stops the auto-retry loop.
        // This only keeps it from escaping as an unhandled rejection.
        .catch(() => {})
        .finally(() => {
          inFlightRef.current = false;
        });
    },
    [fetchNextPage]
  );

  // Widening is deliberately NOT gated on `hasCursors`: a walk that ran to
  // completion under 90 days still has to restart to reach 180-day rows.
  const advance = useCallback(() => {
    if (!enabled || isFetchingNextPage) return;
    if (needsWidening) {
      dispatchPage({ window: desiredWindow });
      return;
    }
    if (!hasCursors || windowProvablyComplete) return;
    dispatchPage();
  }, [
    enabled,
    isFetchingNextPage,
    needsWidening,
    desiredWindow,
    hasCursors,
    windowProvablyComplete,
    dispatchPage,
  ]);

  useEffect(() => {
    // The `error` gate is load-bearing: without it a failed widening re-fires
    // from this effect on every render, forever.
    if (!needsWidening || !firstPageSettled || error) return;
    advance();
  }, [needsWidening, firstPageSettled, error, advance]);

  const loadNextServerPage = useCallback(() => {
    if (error) return;
    advance();
  }, [error, advance]);

  return {
    hasMoreServer: enabled && !windowProvablyComplete && (hasCursors || needsWidening),
    isFetchingNextPage,
    error,
    loadNextServerPage,
    retryServerPage: advance,
  };
}
