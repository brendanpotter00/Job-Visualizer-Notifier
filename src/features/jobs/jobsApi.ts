import { createApi, fakeBaseQuery } from '@reduxjs/toolkit/query/react';
import type { Job } from '../../types';
import { getCompanyById, COMPANIES } from '../../config/companies';
import { greenhouseClient } from '../../api/greenhouseClient';
import { leverClient } from '../../api/leverClient';
import { ashbyClient } from '../../api/ashbyClient';
import { workdayClient } from '../../api/workdayClient';
import type { FetchJobsResult } from '../../api/types';

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
          const client =
            company.ats === 'greenhouse'
              ? greenhouseClient
              : company.ats === 'lever'
                ? leverClient
                : company.ats === 'ashby'
                  ? ashbyClient
                  : workdayClient;

          // Fetch ALL jobs (ignore timeWindow - filter client-side)
          const result: FetchJobsResult = await client.fetchJobs(company.config, {
            signal,
          });

          // Calculate date range
          const dates = result.jobs.map((job) => new Date(job.createdAt).getTime());
          const oldestJobDate =
            dates.length > 0 ? new Date(Math.min(...dates)).toISOString() : undefined;
          const newestJobDate =
            dates.length > 0 ? new Date(Math.max(...dates)).toISOString() : undefined;

          return {
            data: {
              jobs: result.jobs,
              metadata: {
                ...result.metadata,
                oldestJobDate,
                newestJobDate,
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

    // All companies endpoint (parallel fetch with Promise.allSettled)
    getAllJobs: builder.query<AllJobsQueryResult, void>({
      async queryFn(_, { signal }) {
        try {
          // Fetch all companies in parallel
          const results = await Promise.allSettled(
            COMPANIES.map(async (company) => {
              const client =
                company.ats === 'greenhouse'
                  ? greenhouseClient
                  : company.ats === 'lever'
                    ? leverClient
                    : company.ats === 'ashby'
                      ? ashbyClient
                      : workdayClient;

              const result = await client.fetchJobs(company.config, { signal });

              // Calculate date range
              const dates = result.jobs.map((job) => new Date(job.createdAt).getTime());
              const oldestJobDate =
                dates.length > 0 ? new Date(Math.min(...dates)).toISOString() : undefined;
              const newestJobDate =
                dates.length > 0 ? new Date(Math.max(...dates)).toISOString() : undefined;

              return {
                companyId: company.id,
                jobs: result.jobs,
                metadata: {
                  ...result.metadata,
                  oldestJobDate,
                  newestJobDate,
                },
              };
            })
          );

          // Organize results
          const byCompanyId: Record<string, Job[]> = {};
          const metadata: Record<string, any> = {};
          const errors: Record<string, string> = {};

          results.forEach((result, index) => {
            const companyId = COMPANIES[index].id;

            if (result.status === 'fulfilled') {
              byCompanyId[companyId] = result.value.jobs;
              metadata[companyId] = result.value.metadata;
            } else {
              errors[companyId] = result.reason?.message || 'Unknown error';
              byCompanyId[companyId] = [];
              metadata[companyId] = {
                totalCount: 0,
                softwareCount: 0,
                fetchedAt: new Date().toISOString(),
              };
            }
          });

          return {
            data: {
              byCompanyId,
              metadata,
              errors,
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
      providesTags: ['Jobs'],
    }),
  }),
});

export const { useGetJobsForCompanyQuery, useGetAllJobsQuery } = jobsApi;
