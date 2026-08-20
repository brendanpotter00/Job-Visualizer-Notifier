import { createApi, fakeBaseQuery } from '@reduxjs/toolkit/query/react';
import type { Job, JobFacets } from '../../types';
import { getCompanyById } from '../../config/companies';
import type { FetchJobsResult } from '../../api/types';
import { getClientForATS } from '../../api/utils';
import { calculateJobDateRange } from '../../lib/date';
import { transformBackendJob } from '../../api/transformers/backendScraperTransformer';
import { buildSearchJobsQuery } from './searchJobsArgs';
import { validateSearchJobsResponse } from './validateSearchJobsResponse';
import type { SearchJobsArgs, SearchJobsPage } from './searchJobsTypes';

interface JobsQueryResult {
  jobs: Job[];
  metadata: {
    totalCount: number;
    oldestJobDate?: string;
    newestJobDate?: string;
    fetchedAt: string;
  };
}

/** Shown when the response carried no usable reason of its own. */
const SEARCH_JOBS_FALLBACK_ERROR = 'Failed to load jobs';

/**
 * The reason a `/api/jobs/search` response failed, as text fit to show a reader.
 *
 * FastAPI puts it in `detail`, and it survives the Vercel proxy intact
 * (`forwardResponse` copies status + body). A 422 from Pydantic's own validation
 * puts a LIST there instead — useful to a developer, not to a reader — so only a
 * non-empty string is taken and everything else falls back. The body is read at
 * most once and never rethrows: a proxy 502 with an HTML body must still produce
 * an error the page can render.
 */
async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string' && detail.length > 0) return detail;
  } catch {
    // Empty or non-JSON body — nothing more specific to say than the fallback.
  }
  return SEARCH_JOBS_FALLBACK_ERROR;
}

export const jobsApi = createApi({
  reducerPath: 'jobsApi',
  baseQuery: fakeBaseQuery(),
  tagTypes: ['Jobs'],
  keepUnusedDataFor: 600, // 10 minutes TTL
  endpoints: (builder) => ({
    // Individual company endpoint
    getJobsForCompany: builder.query<JobsQueryResult, { companyId: string }>({
      async queryFn({ companyId }, { signal, extra }) {
        // A user-added board is the ONE case that does not go through
        // `getClientForATS`. It has no `Company` entry, so it has no `ats` to
        // dispatch on — and that is deliberate: the public backend-scraper
        // client asks `/api/jobs`, which excludes `visibility='user'` rows
        // unconditionally, so routing a `u-<id>` there would be both a wrong
        // request and a silently empty page. See `fetchCustomCompanyJobs`.
        if (isCustomCompanyId(companyId)) {
          return fetchCustomCompanyJobs(companyId, extra, signal);
        }
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

    /**
     * The Recent Jobs page's read path: `GET /api/jobs/search`, which applies
     * the user's whole filter set server-side and pages the RESULT.
     *
     * A native `infiniteQuery`, unlike everything else in this file. The old
     * walk needed a hand-rolled query + `onCacheEntryAdded` + a companion
     * mutation because one logical page was N chunk cursors plus a completeness
     * horizon — a shape RTK has no primitive for. This endpoint is one cursor
     * per page, which is exactly what `infiniteQuery` models, and taking it
     * gives page accumulation, `hasNextPage`, and per-arg cache isolation
     * without re-deriving any of it.
     *
     * Cache key is the full `SearchJobsArgs`, so changing any filter addresses a
     * different entry and no page from the old filter set can leak into the new
     * one. `keepUnusedDataFor` (10 min, inherited) means flipping a filter back
     * is instant.
     */
    searchJobs: builder.infiniteQuery<SearchJobsPage, SearchJobsArgs, string | null>({
      infiniteQueryOptions: {
        initialPageParam: null,
        // `undefined` — not null — is RTK's "no more pages" signal; null is a
        // legitimate page param here (it is what page 1 uses).
        getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
      },
      async queryFn({ queryArg, pageParam }, { signal }) {
        try {
          const url = `/api/jobs/search?${buildSearchJobsQuery(queryArg, pageParam)}`;
          const response = await fetch(url, { signal });
          if (!response.ok) {
            // Status is preserved verbatim so the caller can tell a 404 (the
            // backend deploy has not landed yet — recoverable, see
            // useRecentJobsSearch) from a real failure.
            //
            // The body's `detail` is preserved too, and that is not cosmetic:
            // the endpoint has several client-FIXABLE rejections (too many
            // keywords / locations / companies, a malformed slug, an empty
            // value, control characters, a stale cursor) and the page's only
            // affordance is a Retry that reissues the identical request. Without
            // the reason on screen the reader cannot know which chip to remove,
            // so the generic text below is a fallback, never the default.
            return {
              error: { status: response.status, data: await readErrorDetail(response) },
            };
          }
          const body = validateSearchJobsResponse(await response.json());
          return {
            data: {
              // Same rows as GET /api/jobs, so the existing transformer applies
              // unchanged — no second mapping to keep in sync.
              jobs: body.jobs.map((row) => transformBackendJob(row, row.company)),
              nextCursor: body.nextCursor,
              counts: body.counts,
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

export const {
  useGetJobsForCompanyQuery,
  useGetFacetsQuery,
  useSearchJobsInfiniteQuery,
} = jobsApi;
