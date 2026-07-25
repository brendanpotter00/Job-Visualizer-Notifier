import { createApi, fakeBaseQuery, defaultSerializeQueryArgs } from '@reduxjs/toolkit/query/react';
import type { Job, FetchProgress, Company, JobFacets } from '../../types';
import { getCompanyById } from '../../config/companies';
import { getEffectiveCompanies } from '../userCompanies/companyRegistryBridge';
import type { FetchJobsResult } from '../../api/types';
import { getClientForATS } from '../../api/utils';
import { fetchJobsForCompanies } from '../../api/clients/backendScraperClient';
import { calculateJobDateRange } from '../../lib/date';
import { updateCompanyProgress } from './progressHelpers';
import { logger } from '../../lib/logger';

/**
 * Tag that scopes cache invalidation to the aggregated `getAllJobs` entry only
 * (not the per-company `getJobsForCompany` entries, which are keyed by
 * `{ type: 'Jobs', id: <companyId> }`). `useSyncRuntimeCompanies` invalidates
 * this when the runtime company set changes so the Recent feed refetches with
 * the wider universe without disturbing open per-company trend pages.
 */
export const ALL_JOBS_TAG = { type: 'Jobs' as const, id: 'ALL_JOBS' };

interface JobsQueryResult {
  jobs: Job[];
  metadata: {
    totalCount: number;
    oldestJobDate?: string;
    newestJobDate?: string;
    fetchedAt: string;
  };
}

interface AllJobsQueryResult {
  byCompanyId: Record<string, Job[]>;
  metadata: Record<
    string,
    {
      totalCount: number;
      oldestJobDate?: string;
      newestJobDate?: string;
      fetchedAt: string;
    }
  >;
  errors: Record<string, string>;
  progress: FetchProgress;
  isStreaming: boolean;
}

export const jobsApi = createApi({
  reducerPath: 'jobsApi',
  baseQuery: fakeBaseQuery(),
  tagTypes: ['Jobs'],
  keepUnusedDataFor: 600, // 10 minutes TTL
  endpoints: (builder) => ({
    // Individual company endpoint.
    //
    // The caller passes the already-resolved `company` from the dynamic registry
    // (`useCompanyRegistry`), which is what lets runtime user-added companies —
    // absent from the static `COMPANIES` list — load on the trend page instead
    // of 404ing. `company` is intentionally EXCLUDED from the cache key (see
    // `serializeQueryArgs` below) so the entry stays keyed by `companyId` only,
    // matching every `getJobsForCompany.select({ companyId })` reader. It falls
    // back to the static `getCompanyById` for callers that don't resolve one.
    getJobsForCompany: builder.query<JobsQueryResult, { companyId: string; company?: Company }>({
      serializeQueryArgs: ({ queryArgs, endpointName, endpointDefinition }) =>
        defaultSerializeQueryArgs({
          queryArgs: { companyId: queryArgs.companyId },
          endpointName,
          endpointDefinition,
        }),
      async queryFn({ companyId, company: resolvedCompany }, { signal }) {
        try {
          const company = resolvedCompany ?? getCompanyById(companyId);

          if (!company) {
            return { error: { status: 404, data: `Company not found: ${companyId}` } };
          }

          // Select appropriate client based on ATS type
          const client = getClientForATS(company.ats);

          // Fetch ALL jobs (ignore timeWindow - filter client-side)
          const result: FetchJobsResult = await client.fetchJobs(company.config, {
            signal,
          });

          // Calculate date range
          const dateRange = calculateJobDateRange(result.jobs);

          return {
            data: {
              jobs: result.jobs,
              metadata: {
                ...result.metadata,
                ...dateRange,
              },
            },
          };
        } catch (error) {
          return {
            error: {
              status: 'CUSTOM_ERROR',
              data: error instanceof Error ? error.message : 'Unknown error',
            },
          };
        }
      },
      providesTags: (_result, _error, { companyId }) => [{ type: 'Jobs', id: companyId }],
    }),

    // All companies endpoint (parallel fetch with streaming progress updates).
    //
    // The fetch universe comes from `getEffectiveCompanies()` (static COMPANIES
    // + the signed-in user's runtime-added companies, via the module bridge)
    // rather than a query arg, so the cache key stays void/stable for the many
    // no-arg readers (`getAllJobs.select()`, `useAllJobsProgress`). For anonymous
    // users the bridge is empty, so this is the exact static `COMPANIES` set.
    getAllJobs: builder.query<AllJobsQueryResult, void>({
      async queryFn() {
        const companies = getEffectiveCompanies();
        // Return initial skeleton data immediately
        return {
          data: {
            byCompanyId: {},
            metadata: {},
            errors: {},
            progress: {
              completed: 0,
              total: companies.length,
              companies: companies.map((c) => ({
                companyId: c.id,
                status: 'pending' as const,
              })),
            },
            isStreaming: true,
          },
        };
      },

      async onCacheEntryAdded(
        _arg,
        { updateCachedData, cacheDataLoaded, cacheEntryRemoved, dispatch }
      ) {
        // Apply one company's successful fetch to both caches.
        const applyCompanySuccess = (company: Company, result: FetchJobsResult) => {
          const dateRange = calculateJobDateRange(result.jobs);
          const perCompanyMetadata = { ...result.metadata, ...dateRange };

          // Seed the per-company endpoint's cache so a later visit to
          // /companies?company=<id> serves this data without refetching.
          dispatch(
            jobsApi.util.upsertQueryData(
              'getJobsForCompany',
              { companyId: company.id },
              { jobs: result.jobs, metadata: perCompanyMetadata }
            )
          );

          updateCachedData((draft) => {
            draft.byCompanyId[company.id] = result.jobs;
            draft.metadata[company.id] = perCompanyMetadata;
            updateCompanyProgress(draft.progress, company.id, {
              status: 'success',
              jobCount: result.jobs.length,
            });
          });
        };

        // Apply one company's failed fetch to both caches.
        const applyCompanyError = (company: Company, errorMessage: string) => {
          const errorMetadata = {
            totalCount: 0,
            fetchedAt: new Date().toISOString(),
          };

          // Seed the per-company cache with an empty result so the
          // company page doesn't silently re-hit a known-broken ATS when
          // the user clicks through from the recent page.
          dispatch(
            jobsApi.util.upsertQueryData(
              'getJobsForCompany',
              { companyId: company.id },
              { jobs: [], metadata: errorMetadata }
            )
          );

          updateCachedData((draft) => {
            draft.byCompanyId[company.id] = [];
            draft.metadata[company.id] = errorMetadata;
            draft.errors[company.id] = errorMessage;
            updateCompanyProgress(draft.progress, company.id, {
              status: 'error',
              error: errorMessage,
            });
          });
        };

        try {
          // Wait for initial data to be in cache
          await cacheDataLoaded;

          // Partition: backend-scraper companies share a single batched
          // backend call (one /api/jobs?companies=... request) to avoid
          // exhausting the API's 15-slot Postgres pool. All other ATS
          // companies hit external Vercel proxies and still fan out. Resolve the
          // universe once (static + runtime) so it matches the skeleton above.
          const companies = getEffectiveCompanies();
          const backendScraperCompanies = companies.filter((c) => c.ats === 'backend-scraper');
          const otherCompanies = companies.filter((c) => c.ats !== 'backend-scraper');

          const batchedFetch = (async () => {
            if (backendScraperCompanies.length === 0) return;

            // Mark every backend-scraper company as loading up front.
            updateCachedData((draft) => {
              for (const company of backendScraperCompanies) {
                updateCompanyProgress(draft.progress, company.id, { status: 'loading' });
              }
            });

            try {
              const grouped = await fetchJobsForCompanies(
                backendScraperCompanies.map((c) => c.id)
              );
              for (const company of backendScraperCompanies) {
                const result = grouped[company.id];
                if (result) {
                  applyCompanySuccess(company, result);
                } else {
                  applyCompanyError(company, 'No result for company in batched response');
                }
              }
            } catch (error) {
              // Pool exhaustion / network failures hit every company at
              // once. Mirror the historical per-company error shape so
              // downstream UI keeps rendering the same error message.
              const errorMessage = error instanceof Error ? error.message : 'Unknown error';
              for (const company of backendScraperCompanies) {
                applyCompanyError(company, errorMessage);
              }
            }
          })();

          const otherFetches = otherCompanies.map(async (company) => {
            const client = getClientForATS(company.ats);
            try {
              updateCachedData((draft) => {
                updateCompanyProgress(draft.progress, company.id, { status: 'loading' });
              });
              const result: FetchJobsResult = await client.fetchJobs(company.config, {});
              applyCompanySuccess(company, result);
            } catch (error) {
              const errorMessage = error instanceof Error ? error.message : 'Unknown error';
              applyCompanyError(company, errorMessage);
            }
          });

          await Promise.allSettled([batchedFetch, ...otherFetches]);

          // Mark streaming as complete
          updateCachedData((draft) => {
            draft.isStreaming = false;
          });

          // Wait for cache to be removed before cleanup
          await cacheEntryRemoved;
        } catch (error) {
          // Handle any errors during streaming
          logger.error('getAllJobs streaming error:', error);
        }
      },

      providesTags: [ALL_JOBS_TAG],
    }),

    // Enrichment facet catalog (GET /api/jobs/facets via the Vercel proxy).
    // Tiny, effectively static payload (changes only with a taxonomy
    // migration) — cache for the session (keepUnusedDataFor override).
    getFacets: builder.query<JobFacets, void>({
      async queryFn(_arg, { signal }) {
        try {
          const response = await fetch('/api/jobs/facets', { signal });
          if (!response.ok) {
            return { error: { status: response.status, data: 'Failed to load facets' } };
          }
          const body: unknown = await response.json();
          const facets = body as JobFacets;
          if (!Array.isArray(facets?.categories) || !Array.isArray(facets?.levels)) {
            return { error: { status: 'CUSTOM_ERROR', data: 'Malformed facets response' } };
          }
          return { data: facets };
        } catch (error) {
          return {
            error: {
              status: 'CUSTOM_ERROR',
              data: error instanceof Error ? error.message : 'Unknown error',
            },
          };
        }
      },
      keepUnusedDataFor: 3600,
    }),
  }),
});

export const { useGetJobsForCompanyQuery, useGetAllJobsQuery, useGetFacetsQuery } = jobsApi;
