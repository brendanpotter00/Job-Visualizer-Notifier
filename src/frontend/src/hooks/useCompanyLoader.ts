import { useEffect, useCallback, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../app/hooks';
import { setSelectedCompanyId } from '../features/app/appSlice';
import { useGetJobsForCompanyQuery } from '../features/jobs/jobsApi';
import { getInitialCompanyId, getRawCompanyParam } from '../lib/url';
import { ROUTES } from '../config/routes';
import { extractErrorMessage } from '../lib/errors';
import { useAuth } from '../features/auth/useAuth';
import { CUSTOM_COMPANIES_CONFIG } from '../config/customCompanies';
import { useGetUserCompaniesQuery } from '../features/userCompanies/userCompaniesApi';
import { selectUserCompanyIdSet } from '../features/userCompanies/effectiveCompanies';
import { isCustomCompanyId } from '../features/userCompanies/customJobsClient';

/** RTK Query's numeric HTTP status, when the error carries one. */
function statusOf(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null || !('status' in error)) return undefined;
  const status = (error as { status: unknown }).status;
  return typeof status === 'number' ? status : undefined;
}

/**
 * Custom hook for managing company selection initialization and job loading
 *
 * Responsibilities:
 * - Initialize selected company from URL on mount (Companies page only)
 * - Load jobs whenever the selected company changes (Companies page only)
 * - Provide retry functionality for failed requests
 *
 * Note: This hook only runs on the Companies page to prevent
 * unnecessary API calls on other pages. Uses RTK Query for automatic
 * caching and request deduplication.
 *
 * @returns Object containing loading state, error message, retry handler, jobs, and metadata
 */
export function useCompanyLoader() {
  const location = useLocation();
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);

  // Only run on Companies page
  const isCompaniesPage = location.pathname === ROUTES.COMPANIES;

  const { isAuthenticated, isLoading: authLoading } = useAuth();
  // The subscription that puts the caller's own boards in the store, so
  // `/companies` has them even for a user who never opens `/add-companies`.
  // BOTH skips are load-bearing, for the reasons documented at
  // `RecentJobsFilters.tsx`: signed out the endpoint is authed and would 401 on
  // every anonymous load, and flag-off means the feature makes no network calls.
  const ownedCompanies = useGetUserCompaniesQuery(undefined, {
    skip: !isAuthenticated || !CUSTOM_COMPANIES_CONFIG.isEnabled,
  });
  const userCompanyIds = useAppSelector(selectUserCompanyIdSet);
  // Read by the mount effect below WITHOUT being one of its dependencies. The
  // effect must fire exactly once per arrival on the page — re-running it when
  // the id set changes (a board added or removed mid-session) would re-read the
  // URL and overwrite whatever the user has since selected.
  const userCompanyIdsRef = useRef(userCompanyIds);
  useEffect(() => {
    userCompanyIdsRef.current = userCompanyIds;
  }, [userCompanyIds]);

  // THE COLD-LOAD GATE, and the reason it keys off the RAW parameter.
  //
  // `?company=u-abc123` cannot be validated until an authenticated query
  // resolves, so the initial selection has to wait for it — otherwise
  // `getInitialCompanyId` answers `spacex`, `useURLSync` rewrites the URL, and
  // the deep link is destroyed before it could ever work. But making EVERY
  // visitor wait on an authed query before `/companies` picks a company would
  // slow down the page for everyone, including signed-out ones. So the wait is
  // scoped to the only case that needs it: a `?company=` value that is shaped
  // like a custom board id. Every public deep link keeps today's exact timing.
  const rawCompanyParam = isCompaniesPage ? getRawCompanyParam() : null;
  const needsOwnedIds =
    CUSTOM_COMPANIES_CONFIG.isEnabled &&
    rawCompanyParam !== null &&
    isCustomCompanyId(rawCompanyParam);
  const ownedIdsReady =
    !needsOwnedIds ||
    (!authLoading && (!isAuthenticated || ownedCompanies.isSuccess || ownedCompanies.isError));

  // Initialize selected company from the URL on transition onto the Companies
  // page. We intentionally do NOT read `selectedCompanyId` inside this effect:
  // dispatching `setSelectedCompanyId` with the already-selected id is
  // idempotent for subscribers (useAppSelector returns the same string, so no
  // component re-renders), and reading `selectedCompanyId` would force the
  // effect to re-run on every company change and undo the user's selection.
  // Adding `dispatch` to deps is safe because `dispatch` has stable identity
  // (react-redux guarantee).
  useEffect(() => {
    if (!isCompaniesPage) return;
    if (!ownedIdsReady) return;
    dispatch(setSelectedCompanyId(getInitialCompanyId(userCompanyIdsRef.current)));
  }, [isCompaniesPage, ownedIdsReady, dispatch]);

  // RTK Query hook - automatically fetches on mount and when companyId changes
  // Skip fetching if not on Companies page, or while the gate above is still
  // holding the selection: firing the default company's request during that
  // window would be a wasted round trip for a company we are about to replace.
  const { data, isLoading, error, refetch } = useGetJobsForCompanyQuery(
    { companyId: selectedCompanyId },
    { skip: !isCompaniesPage || !ownedIdsReady }
  );

  // Memoized retry handler
  const handleRetry = useCallback(() => {
    refetch();
  }, [refetch]);

  return {
    // The gate window is a load, not an empty page: without this the chart
    // would render with zero jobs for a beat before the real company is picked.
    isLoading: isLoading || (isCompaniesPage && !ownedIdsReady),
    error: error ? extractErrorMessage(error, 'Unknown error') : undefined,
    /** HTTP status behind `error`, so the page can tell 401/403 from a failure. */
    errorStatus: statusOf(error),
    handleRetry,
    jobs: data?.jobs || [],
    metadata: data?.metadata,
  };
}
