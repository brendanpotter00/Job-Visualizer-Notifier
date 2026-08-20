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
import { ERROR_MESSAGES } from '../../constants/messages';
import { extractErrorMessage } from '../../lib/errors';
import { logger } from '../../lib/logger';

interface JobsQueryResult {
  jobs: Job[];
  metadata: {
    totalCount: number;
    oldestJobDate?: string;
    newestJobDate?: string;
    fetchedAt: string;
  };
}

/**
 * The only statuses whose `detail` is written FOR the reader.
 *
 * `/api/jobs/search` rejects a filter set the client can fix with a 400 (too many
 * keywords / locations / companies, an empty value, control characters) or a 422
 * (a cursor replayed under different filters). Those messages name the thing to
 * change and are worth putting on screen.
 *
 * Every OTHER status carries FastAPI's or the proxy's stock text, and showing it
 * is strictly worse than the generic fallback: the deploy-race 404 the hook waits
 * out for ~4 minutes on every release would end at the words "Not Found", and a
 * backend crash would read "Internal Server Error" — neither tells the reader
 * anything, and both look like the page is broken in a way they caused.
 */
const READER_FACING_ERROR_STATUSES: ReadonlySet<number> = new Set([400, 422]);

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
  if (!READER_FACING_ERROR_STATUSES.has(response.status)) {
    return ERROR_MESSAGES.LOAD_JOBS_FAILED;
  }
  try {
    const body: unknown = await response.json();
    // Wrapped as `{ data }` because that is the shape `extractErrorMessage`
    // decodes: it owns the `detail` / `message` precedence and the "a 422's LIST
    // detail is developer output, not reader output" rule, and re-implementing
    // either here is exactly the duplication rule 3 in `src/frontend/CLAUDE.md`
    // forbids. What stays local is the STATUS gate above, which is a different
    // decision entirely — see `READER_FACING_ERROR_STATUSES`.
    return extractErrorMessage({ data: body }, ERROR_MESSAGES.LOAD_JOBS_FAILED);
  } catch {
    // Empty or non-JSON body — nothing more specific to say than the fallback.
    return ERROR_MESSAGES.LOAD_JOBS_FAILED;
  }
}

/**
 * An abort is not a failure.
 *
 * RTK Query aborts this `signal` whenever the cache entry is unsubscribed or
 * refetched — which the Recent page does on every filter change — so logging
 * these would drown the log in events that mean "the reader changed their mind".
 * The returned error is discarded by RTK for the same reason.
 */
function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
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
            // The body's `detail` is preserved too — but only for the statuses
            // that mean "your filter set", and that is not cosmetic: the endpoint
            // has several client-FIXABLE rejections (too many keywords /
            // locations / companies, a malformed slug, an empty value, control
            // characters, a stale cursor) and the page's only affordance is a
            // Retry that reissues the identical request. Without the reason on
            // screen the reader cannot know which chip to remove. Server-side and
            // deploy-race statuses fall back instead — see
            // `READER_FACING_ERROR_STATUSES`.
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
          // NOTHING that lands here was written for a reader.
          // `validateSearchJobsResponse` throws shape diagnostics ("bad job row
          // shape"), a non-JSON 200 body throws a SyntaxError about position 0,
          // and a dropped connection throws a browser-specific TypeError. All
          // three used to be returned as `data`, which `extractErrorMessage`
          // renders verbatim in `ErrorState` — the same leak
          // `READER_FACING_ERROR_STATUSES` closed for the status branch above —
          // while the actual reason went nowhere at all. So the reason is LOGGED
          // (the convention in `api/jobs.ts` and `backendScraperClient.ts`) and
          // the reader gets the same line every other unattributable failure gets.
          if (!isAbortError(error)) {
            logger.error('[jobsApi] /api/jobs/search request failed:', error);
          }
          return {
            error: { status: 'CUSTOM_ERROR', data: ERROR_MESSAGES.LOAD_JOBS_FAILED },
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
