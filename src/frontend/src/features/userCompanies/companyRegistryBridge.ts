import type { Company } from '../../types';
import { COMPANIES } from '../../config/companies';

/**
 * Module-level bridge that exposes the current user's runtime-added companies to
 * non-React, module-scope code — specifically the `getAllJobs` RTK Query
 * endpoint in `features/jobs/jobsApi.ts`, whose `queryFn` / `onCacheEntryAdded`
 * run outside React and therefore cannot call `useCompanyRegistry()`.
 *
 * This mirrors the established `getTokenOrNull` token bridge
 * (`features/features/getTokenOrNull.ts`): a single hook registered once at the
 * app root (`useSyncRuntimeCompanies`) keeps this holder in sync, and it stays
 * empty for anonymous users so `getEffectiveCompanies()` returns the exact same
 * static `COMPANIES` reference — preserving logged-out behavior byte for byte.
 *
 * Why a bridge here (rather than a query arg, as `getJobsForCompany` uses): the
 * aggregated `getAllJobs` cache entry is read by many no-arg consumers
 * (`getAllJobs.select()` in `recentJobsSelectors`, `useAllJobsProgress`) whose
 * cache key must stay stable. Threading a per-user company list through its
 * query arg would either change that key (breaking those readers) or freeze to
 * the first arg via RTK's `originalArgs`. The bridge keeps the endpoint arg-free
 * while still letting the fetch universe grow; `useSyncRuntimeCompanies`
 * triggers a targeted refetch when the runtime set changes.
 */
let runtimeCompanies: Company[] = [];

/**
 * Replace the registered runtime companies. Called only by
 * `useSyncRuntimeCompanies`. Passing `[]` (the anonymous / logged-out state)
 * makes `getEffectiveCompanies()` return the static `COMPANIES` reference.
 */
export function registerRuntimeCompanies(companies: Company[]): void {
  runtimeCompanies = companies;
}

/**
 * The full fetch universe for `getAllJobs`: static `COMPANIES` plus any runtime
 * companies not already present (static wins on id collision). Returns the exact
 * `COMPANIES` reference when there are no extra runtime companies, so anonymous
 * users hit the identical code path as before.
 */
export function getEffectiveCompanies(): Company[] {
  if (runtimeCompanies.length === 0) return COMPANIES;
  const staticIds = new Set(COMPANIES.map((c) => c.id));
  const extra = runtimeCompanies.filter((c) => !staticIds.has(c.id));
  return extra.length === 0 ? COMPANIES : [...COMPANIES, ...extra];
}
