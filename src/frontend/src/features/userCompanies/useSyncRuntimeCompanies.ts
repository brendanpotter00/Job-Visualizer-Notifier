import { useEffect, useRef } from 'react';
import { useAuth } from '../auth/useAuth';
import { useAppDispatch } from '../../app/hooks';
import { useGetUserCompaniesQuery, userCompaniesApi } from './userCompaniesApi';
import { companyFromDto } from './useCompanyRegistry';
import { registerRuntimeCompanies } from './companyRegistryBridge';
import { jobsApi, ALL_JOBS_TAG } from '../jobs/jobsApi';

/**
 * Keeps the module-level runtime-company bridge in sync with the signed-in
 * user's `/api/users/companies` and refetches the aggregated `getAllJobs` feed
 * whenever the runtime set changes, so runtime-added companies appear in the
 * Recent Job Postings feed. Mount ONCE at the app root (mirrors
 * `useHydrateSavedFilters` / `useEnabledCompanies`).
 *
 * Anonymous users: the query is skipped, the bridge stays empty, and no
 * invalidation ever fires — so `getAllJobs` fetches the static `COMPANIES` set
 * exactly once, identical to prior behavior.
 */
export function useSyncRuntimeCompanies(): void {
  const { isAuthenticated } = useAuth();
  const dispatch = useAppDispatch();

  const { data } = useGetUserCompaniesQuery(undefined, { skip: !isAuthenticated });

  // The runtime id-set we last registered. Starts empty so an authenticated
  // user with zero runtime companies (empty -> empty) never triggers a refetch.
  const registeredIdsRef = useRef('');
  const wasAuthenticated = useRef(false);

  useEffect(() => {
    if (isAuthenticated) {
      wasAuthenticated.current = true;
      if (!data) return;

      const companies = data.map(companyFromDto);
      const idsKey = companies
        .map((c) => c.id)
        .sort()
        .join(',');
      if (idsKey === registeredIdsRef.current) return;

      registeredIdsRef.current = idsKey;
      registerRuntimeCompanies(companies);
      // Pull the newly-known runtime companies into the aggregated feed. Scoped
      // to the getAllJobs entry (ALL_JOBS tag) so per-company caches are untouched.
      dispatch(jobsApi.util.invalidateTags([ALL_JOBS_TAG]));
      return;
    }

    // Logged out: drop the previous user's runtime companies from the bridge and
    // the cache, and refresh the feed back to the static set — but only on the
    // actual authenticated -> anonymous transition, so anonymous sessions never
    // pay for an invalidation.
    if (wasAuthenticated.current) {
      wasAuthenticated.current = false;
      if (registeredIdsRef.current !== '') {
        registeredIdsRef.current = '';
        registerRuntimeCompanies([]);
        dispatch(jobsApi.util.invalidateTags([ALL_JOBS_TAG]));
      }
      dispatch(userCompaniesApi.util.resetApiState());
    }
  }, [isAuthenticated, data, dispatch]);
}
