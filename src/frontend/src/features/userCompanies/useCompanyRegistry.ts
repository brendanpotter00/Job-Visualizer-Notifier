import { useMemo } from 'react';
import type { Company } from '../../types';
import { COMPANIES } from '../../config/companies';
import { useAuth } from '../auth/useAuth';
import { useGetUserCompaniesQuery, type CompanyDTO } from './userCompaniesApi';

/**
 * Build a frontend `Company` from a backend `CompanyDTO`. Runtime companies all
 * flow through the backend `/api/jobs` endpoint, so `ats` is always
 * `'backend-scraper'` and the config points at that proxy keyed by the DTO id.
 * `sourceAts` is cast to the `Company` union (which now includes
 * `'custom_json'`).
 */
export function companyFromDto(dto: CompanyDTO): Company {
  return {
    id: dto.id,
    name: dto.name,
    ats: 'backend-scraper',
    config: {
      type: 'backend-scraper',
      companyId: dto.id,
      apiBaseUrl: '/api/jobs',
    },
    jobsUrl: dto.jobsUrl ?? undefined,
    sourceAts: dto.sourceAts as Company['sourceAts'],
  };
}

/**
 * Merge the static curated `COMPANIES` with the user's runtime-added companies,
 * deduped by id with the static entry winning on collision. Exported for direct
 * unit testing of the merge policy.
 */
export function mergeCompanies(staticCompanies: Company[], runtime: Company[]): Company[] {
  if (runtime.length === 0) return staticCompanies;
  const staticIds = new Set(staticCompanies.map((c) => c.id));
  const extra = runtime.filter((c) => !staticIds.has(c.id));
  return extra.length === 0 ? staticCompanies : [...staticCompanies, ...extra];
}

/**
 * Fetch the current user's runtime companies plus a readiness flag. The query is
 * skipped for anonymous users, so it never fires an unauthenticated request and
 * the runtime list is always empty when logged out (registry === static).
 *
 * `ready` is true when we can be sure the runtime set is final for the current
 * auth state: immediately for anonymous users, or once the query settles
 * (success or error) for authenticated users.
 */
function useRuntimeCompanies(): { companies: Company[]; ready: boolean } {
  const { isAuthenticated } = useAuth();
  const { data, isLoading, isUninitialized, isError } = useGetUserCompaniesQuery(undefined, {
    skip: !isAuthenticated,
  });

  const companies = useMemo(
    () => (isAuthenticated && data ? data.map(companyFromDto) : []),
    [isAuthenticated, data]
  );

  const ready = !isAuthenticated || isError || (!isUninitialized && !isLoading);
  return { companies, ready };
}

/**
 * The dynamic company registry: static `COMPANIES` merged with the current
 * user's runtime-added companies (deduped by id, static wins). For anonymous
 * users this is exactly the static list. This is the hook every jobs-UI consumer
 * should read instead of importing `COMPANIES` / `getCompanyById` directly.
 */
export function useCompanyRegistry(): Company[] {
  const { companies: runtime } = useRuntimeCompanies();
  return useMemo(() => mergeCompanies(COMPANIES, runtime), [runtime]);
}

/**
 * A stable-per-registry `getCompanyById` over the merged registry. Returns a
 * lookup function so callers resolve ids without re-scanning the array.
 */
export function useGetCompanyById(): (id: string) => Company | undefined {
  const registry = useCompanyRegistry();
  return useMemo(() => {
    const byId = new Map(registry.map((c) => [c.id, c]));
    return (id: string) => byId.get(id);
  }, [registry]);
}

/**
 * Whether the runtime-company registry has settled for the current auth state.
 * Consumers that must fetch the full company set once (e.g. gating an aggregated
 * jobs fetch) can wait on this. Always true for anonymous users.
 */
export function useCompanyRegistryReady(): boolean {
  return useRuntimeCompanies().ready;
}
