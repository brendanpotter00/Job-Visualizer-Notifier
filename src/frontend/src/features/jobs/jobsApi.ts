import { createApi, fakeBaseQuery } from '@reduxjs/toolkit/query/react';
import type { Job, FetchProgress } from '../../types';
import { getCompanyById, COMPANIES } from '../../config/companies';
import type { FetchJobsResult } from '../../api/types';
import { getClientForATS } from '../../api/utils';
import { calculateJobDateRange } from '../../lib/date';
import { updateCompanyProgress } from './progressHelpers';
import { logger } from '../../lib/logger';

interface JobsQueryResult {
  jobs: Job[];
  metadata: {
    totalCount: number;
    softwareCount: number;
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
      softwareCount: number;
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
    // Individual company endpoint
    getJobsForCompany: builder.query<JobsQueryResult, { companyId: string }>({
      async queryFn({ companyId }, { signal }) {
        try {
          const company = getCompanyById(companyId);

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

    // All companies endpoint (parallel fetch with streaming progress updates)
    getAllJobs: builder.query<AllJobsQueryResult, void>({
      async queryFn() {
        // Return initial skeleton data immediately
        return {
          data: {
            byCompanyId: {},
            metadata: {},
            errors: {},
            progress: {
              completed: 0,
              total: COMPANIES.length,
              companies: COMPANIES.map((c) => ({
                companyId: c.id,
                status: 'pending' as const,
              })),
            },
            isStreaming: true,
          },
        };
      },

      async onCacheEntryAdded(_arg, { updateCachedData, cacheDataLoaded, cacheEntryRemoved }) {
        try {
          // Wait for initial data to be in cache
          await cacheDataLoaded;

          // Start parallel fetches for all companies
          const fetchPromises = COMPANIES.map(async (company) => {
            const client = getClientForATS(company.ats);

            try {
              // Mark as loading
              updateCachedData((draft) => {
                updateCompanyProgress(draft.progress, company.id, { status: 'loading' });
              });

              // Fetch data
              const result: FetchJobsResult = await client.fetchJobs(company.config, {});

              // Calculate date range
              const dateRange = calculateJobDateRange(result.jobs);

              // Update cache with successful company fetch
              updateCachedData((draft) => {
                draft.byCompanyId[company.id] = result.jobs;
                draft.metadata[company.id] = {
                  ...result.metadata,
                  ...dateRange,
                };

                updateCompanyProgress(draft.progress, company.id, {
                  status: 'success',
                  jobCount: result.jobs.length,
                });
              });

              return { companyId: company.id, success: true };
            } catch (error) {
              const errorMessage = error instanceof Error ? error.message : 'Unknown error';

              // Update cache with error
              updateCachedData((draft) => {
                draft.byCompanyId[company.id] = [];
                draft.metadata[company.id] = {
                  totalCount: 0,
                  softwareCount: 0,
                  fetchedAt: new Date().toISOString(),
                };
                draft.errors[company.id] = errorMessage;

                updateCompanyProgress(draft.progress, company.id, {
                  status: 'error',
                  error: errorMessage,
                });
              });

              return { companyId: company.id, success: false };
            }
          });

          // Wait for all fetches to complete
          await Promise.allSettled(fetchPromises);

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

      providesTags: ['Jobs'],
    }),
  }),
});

export const { useGetJobsForCompanyQuery, useGetAllJobsQuery } = jobsApi;
