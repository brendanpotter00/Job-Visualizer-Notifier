import { useCallback, useEffect, useMemo, useState } from 'react';
import { skipToken } from '@reduxjs/toolkit/query';
import { useAppSelector } from '../../../app/hooks.ts';
import { useAuth } from '../../auth/useAuth.ts';
import {
  selectEnabledCompanyIds,
  selectEnabledCompaniesSettled,
} from '../../preferences/enabledCompaniesSlice.ts';
import { selectDemoModeEnabled } from '../../ui/uiSlice.ts';
import { selectRecentJobsFilters } from '../../filters/selectors/recentJobsSelectors.ts';
import { selectRecentJobsFilterSignature } from '../../filters/selectors/recentJobsFilterSignature.ts';
import { selectLocationCatalog } from '../../locations/locationCatalogSlice.ts';
import { filterJobsByFilters } from '../../filters/utils/jobFilteringUtils.ts';
import { filterJobsByHours } from '../../../lib/date.ts';
import { extractErrorMessage } from '../../../lib/errors.ts';
import { ERROR_MESSAGES } from '../../../constants/messages.ts';
import type { Job } from '../../../types';
import { useSearchJobsInfiniteQuery } from '../jobsApi.ts';
import { DEMO_JOBS } from '../demoJobs.ts';
import { buildSearchJobsArgs, sinceForTimeWindow } from '../searchJobsArgs.ts';
import type { SearchJobsCounts } from '../searchJobsTypes.ts';

/** Quiet period before a filter edit becomes a request. House convention. */
const FILTER_DEBOUNCE_MS = 300;

/**
 * Backoff schedule for retrying a 404 from the search endpoint, one entry per
 * attempt. Its LENGTH is the whole budget: once the attempts are spent, a 404 is
 * treated as a genuine failure and surfaces as an error.
 *
 * Frontend and backend ship in one PR but deploy independently — Vercel
 * typically publishes in 2-4 minutes while Railway rebuilds a container and runs
 * migrations in 6-12 — so the new bundle can briefly call an endpoint the old
 * backend does not serve. This schedule spans ~4 minutes of patient waiting
 * across seven attempts, which covers the usual overlap.
 */
const DEPLOY_RETRY_DELAYS_MS = [5_000, 10_000, 20_000, 40_000, 60_000, 60_000, 60_000];

export type RecentJobsErrorScope = 'initial' | 'nextPage';

export interface RecentJobsSearch {
  /** Every row fetched so far for the CURRENT filters, newest first. */
  jobs: Job[];
  /** Header metrics from page 1; null until it lands. */
  counts: SearchJobsCounts | null;
  /** No data at all yet — render skeletons. */
  isInitialLoading: boolean;
  /** Filters changed and the new first page is in flight; previous rows still shown. */
  isRefreshing: boolean;
  isFetchingNextPage: boolean;
  /** Whether the walk holds another page. False means provably terminal. */
  hasNextPage: boolean;
  fetchNextPage: () => void;
  error: string | null;
  errorScope: RecentJobsErrorScope | null;
  /** The deploy-race grace window is active: show loading, not an error. */
  isAwaitingDeploy: boolean;
  retry: () => void;
  /** The filter set provably matches nothing, so no request was made. */
  isSkippedEmpty: boolean;
}

/**
 * The Recent page's entire relationship with `GET /api/jobs/search` — the only
 * module in the tree that knows the endpoint exists.
 *
 * Everything the old client-side walk needed (window widening, a completeness
 * horizon, an empty-fetch budget, a manual "search older jobs" affordance) is
 * gone, because the server now returns only matching rows: an empty page means
 * there are no more, so the list never has to guess how much deeper to dig. That
 * guess is what deadlocked production on 2026-08-10.
 */
export function useRecentJobsSearch(): RecentJobsSearch {
  const filters = useAppSelector(selectRecentJobsFilters);
  const filterSignature = useAppSelector(selectRecentJobsFilterSignature);
  const enabledCompanyIds = useAppSelector(selectEnabledCompanyIds);
  const demoModeEnabled = useAppSelector(selectDemoModeEnabled);
  const locationCatalog = useAppSelector(selectLocationCatalog);
  const { isAuthenticated, isLoading: authLoading, isEnabled: authEnabled } = useAuth();

  const isSignedOut = authEnabled && !isAuthenticated;
  // Don't fetch an unfiltered page before a signed-in user's company preferences
  // arrive — it would be immediately superseded, and the flash of other people's
  // companies is exactly what the old page took care to avoid.
  //
  // SETTLED, not "loaded": a failed preferences request must also release the
  // gate. Waiting on a non-null id list would strand a signed-in reader on
  // skeletons forever when that endpoint 500s — no rows, no error, no retry —
  // which is the incident's failure shape wearing a spinner. A failure degrades
  // to "all companies", exactly what a null list has always meant downstream.
  const preferencesSettled = useAppSelector(selectEnabledCompaniesSettled);
  const preferencesReady = !authLoading && (!isAuthenticated || preferencesSettled);

  // One debounced snapshot of the filters, STAMPED with the instant it settled.
  //
  // The stamp is what freezes `since` for the lifetime of a walk. Deriving the
  // bound from a live clock instead would mint a new cache key on every
  // incidental re-render — discarding pages the reader already paid for — and
  // the server rejects a cursor whose `since` moved, so it would break paging
  // outright on page 2.
  //
  // Snapshot-with-a-stamp rather than a separate debounce + a state-setting
  // effect, because the clock may only be read where it is honest to do so: in
  // the lazy initializer (once, before the first render commits) and inside the
  // debounce timer (an event, not a render). Sampling it during render makes the
  // component impure, and re-minting it from an effect is a cascading render —
  // both are lint errors this repo enforces rather than suppresses.
  const [snapshot, setSnapshot] = useState(() => ({
    filters,
    signature: filterSignature,
    at: Date.now(),
  }));
  useEffect(() => {
    if (snapshot.signature === filterSignature) return;
    const id = setTimeout(() => {
      setSnapshot({ filters, signature: filterSignature, at: Date.now() });
    }, FILTER_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [filterSignature, filters, snapshot.signature]);

  const debouncedFilters = snapshot.filters;
  const since = useMemo(
    () => sinceForTimeWindow(debouncedFilters.timeWindow, snapshot.at),
    [debouncedFilters.timeWindow, snapshot.at]
  );

  const args = useMemo(
    () =>
      buildSearchJobsArgs({
        filters: debouncedFilters,
        enabledCompanyIds,
        since,
        isSignedOut,
      }),
    [debouncedFilters, enabledCompanyIds, since, isSignedOut]
  );

  // Demo mode serves a curated fixture, so it must not touch the network at all.
  // The old page left the real query running underneath and fired useless pages
  // against it — a documented follow-up from the 2026-08-10 incident, fixed here
  // by simply not having a request to fire.
  const skip = demoModeEnabled || !preferencesReady || args === null;

  const {
    data,
    currentData,
    error: queryError,
    isFetching,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage: rtkFetchNextPage,
    refetch,
  } = useSearchJobsInfiniteQuery(skip ? skipToken : args);

  // --- deploy-race grace -------------------------------------------------
  //
  // A 404 here almost always means Vercel published this bundle before Railway
  // finished shipping the backend that serves the endpoint — they deploy from
  // one merge but on different clocks. That is a wait, not a failure, so the
  // hook retries on a backoff and reports it as loading.
  //
  // The budget is a RETRY COUNT, not an elapsed-time window. Counting is a pure
  // function of state, so "are we still waiting" can be derived during render
  // without reading a clock there; the schedule below already spans several
  // minutes, which is the coverage that actually matters. It is also far easier
  // to test and cannot drift with a suspended tab.
  const [retryAttempt, setRetryAttempt] = useState(0);
  const status = (queryError as { status?: unknown } | undefined)?.status;
  const isDeployGap = status === 404 && retryAttempt < DEPLOY_RETRY_DELAYS_MS.length;

  useEffect(() => {
    if (!isDeployGap) return;
    const delay = DEPLOY_RETRY_DELAYS_MS[retryAttempt];
    const id = setTimeout(() => {
      // Both setState calls happen inside the timer — an event, not the effect
      // body — so this schedules the next attempt without a cascading render.
      setRetryAttempt((n) => n + 1);
      refetch();
    }, delay);
    return () => clearTimeout(id);
    // `retryAttempt` drives the schedule forward; refetch is stable per arg.
  }, [isDeployGap, retryAttempt, refetch]);

  // --- demo branch -------------------------------------------------------
  const demo = useMemo(() => {
    if (!demoModeEnabled) return null;
    const matched = filterJobsByFilters(DEMO_JOBS, filters, locationCatalog).sort(
      (a, b) => new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime()
    );
    return {
      jobs: matched,
      counts: {
        total: matched.length,
        last24h: filterJobsByHours(DEMO_JOBS, 24).length,
        last3h: filterJobsByHours(DEMO_JOBS, 3).length,
      },
    };
  }, [demoModeEnabled, filters, locationCatalog]);

  const jobs = useMemo(
    () => (data?.pages ?? []).flatMap((page) => page.jobs),
    [data]
  );

  const fetchNextPage = useCallback(() => {
    if (!hasNextPage || isFetching) return;
    rtkFetchNextPage();
  }, [hasNextPage, isFetching, rtkFetchNextPage]);

  // Scoped by whether the CURRENT arg has landed a page, not by whether `jobs`
  // is non-empty. `data` deliberately retains the previous filter's pages so the
  // list does not blank during a refetch — so keying off `jobs.length` would
  // classify a filter change that then failed as a mere "next page" error, and
  // the page would keep rendering the OLD rows and the OLD counts underneath the
  // NEW filter chips. A plausible, fully-populated, wrong result set is worse
  // than an error.
  const errorScope: RecentJobsErrorScope | null = queryError
    ? currentData !== undefined
      ? 'nextPage'
      : 'initial'
    : null;

  const retry = useCallback(() => {
    if (errorScope === 'nextPage') rtkFetchNextPage();
    else refetch();
  }, [errorScope, rtkFetchNextPage, refetch]);

  if (demo) {
    return {
      jobs: demo.jobs,
      counts: demo.counts,
      isInitialLoading: false,
      isRefreshing: false,
      isFetchingNextPage: false,
      hasNextPage: false,
      fetchNextPage: () => {},
      error: null,
      errorScope: null,
      isAwaitingDeploy: false,
      retry: () => {},
      isSkippedEmpty: false,
    };
  }

  return {
    jobs,
    counts: data?.pages[0]?.counts ?? null,
    // `!preferencesReady` counts as loading, and that clause is load-bearing:
    // while it holds we are deliberately NOT fetching, so without it the list
    // would see zero jobs, no next page, nothing in flight and no error — and
    // render the terminal "No jobs found" for a page that has not asked the
    // server anything yet. That is the 2026-08-10 failure shape exactly.
    // `args === null` is the one genuinely-terminal skip and is reported
    // separately as `isSkippedEmpty`.
    isInitialLoading:
      (!preferencesReady && !demoModeEnabled) ||
      (!skip && data === undefined && !queryError),
    // `currentData` is undefined while a NEW arg's first page is in flight, but
    // `data` still holds the previous filter's pages — that gap is exactly
    // "refreshing", and it is what keeps the terminal empty state from flashing
    // over stale rows during a filter change.
    isRefreshing: isFetching && !isFetchingNextPage && currentData === undefined && data !== undefined,
    isFetchingNextPage,
    hasNextPage: !isSignedOut && Boolean(hasNextPage),
    fetchNextPage,
    error:
      queryError && !isDeployGap
        ? extractErrorMessage(queryError, ERROR_MESSAGES.LOAD_JOBS_FAILED)
        : null,
    errorScope: isDeployGap ? null : errorScope,
    isAwaitingDeploy: isDeployGap,
    retry,
    isSkippedEmpty: args === null && !demoModeEnabled,
  };
}
