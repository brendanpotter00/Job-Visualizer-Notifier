import { createApi, fakeBaseQuery } from '@reduxjs/toolkit/query/react';
import type { Job, FetchProgress, Company, JobFacets } from '../../types';
import { getCompanyById, COMPANIES } from '../../config/companies';
import type { FetchJobsResult } from '../../api/types';
import { getClientForATS } from '../../api/utils';
import { chunkCompanyIds, fetchJobsPage } from '../../api/clients/backendScraperClient';
import { calculateJobDateRange } from '../../lib/date';
import { updateCompanyProgress } from './progressHelpers';
import { logger } from '../../lib/logger';
import {
  RECENT_JOBS_DEFAULT_WINDOW,
  RECENT_JOBS_PAGE_SIZE,
  chunkKey,
  jobKey,
  oldestFirstSeenAt,
  parseChunkKey,
  sinceForWindow,
} from './keysetWalk';
import type { JobsWindowKey } from './keysetWalk';

export {
  RECENT_JOBS_DEFAULT_WINDOW,
  RECENT_JOBS_PAGE_SIZE,
  jobsWindowForTimeWindow,
  sinceForWindow,
} from './keysetWalk';
export type { JobsWindowKey } from './keysetWalk';

/**
 * Page-size rationale (`RECENT_JOBS_PAGE_SIZE`, defined in `keysetWalk.ts`).
 *
 * The page size is what actually bounds first paint — the window barely
 * matters. At prod scale a 90-day window covers 22.2k of the 32.0k OPEN rows
 * (measured 2026-08-19), so even the widest possible bound only adds ~44% to
 * what a *fully walked* set would hold, and nothing at all to page 1. That is
 * why the default window can be all-time without moving first paint. With 3
 * chunks a 1000-row page caps the first load at ~3k rows instead of the 32.0k
 * that `limit=50000` pulled — an order of magnitude less JSON to parse and
 * transform — while still being far more than a virtualized viewport needs.
 * Well under the backend's `le=50000` cap.
 *
 * Load-bearing for paging: the backend emits `X-Next-Cursor` iff
 * `rows.length === limit`, so the same limit must be replayed on every page of
 * a walk or the end-of-walk signal shifts.
 */

/** Ids of every company served by the batched backend-scraper endpoint. */
function backendScraperCompanyIds(): string[] {
  return COMPANIES.filter((c) => c.ats === 'backend-scraper').map((c) => c.id);
}

/** Outcome of one `fetchNextJobsPage` advance. */
export interface FetchNextJobsPageResult {
  /** Rows newly appended to the cache (already-present rows are not counted). */
  added: number;
  /** Whether any chunk still has an outstanding cursor after this advance. */
  hasMore: boolean;
}

/**
 * Merge one page's rows for a company into the cache draft.
 *
 * APPENDS and de-duplicates on the composite PK — it never replaces. That
 * matters in both directions: a later page must not drop rows already on
 * screen, and a page-1 response that lands *after* a widen already appended
 * rows must not stomp them.
 *
 * Always materializes the company's key, so every requested company has an
 * entry even when it contributed zero rows.
 *
 * @returns how many rows were genuinely new
 */
function mergeCompanyJobsIntoDraft(
  draft: AllJobsQueryResult,
  companyId: string,
  incoming: Job[]
): number {
  const existing = draft.byCompanyId[companyId] ?? [];
  const seen = new Set(existing.map(jobKey));
  const appended = incoming.filter((job) => !seen.has(jobKey(job)));
  const next = appended.length === 0 ? existing : [...existing, ...appended];

  draft.byCompanyId[companyId] = next;
  draft.metadata[companyId] = {
    ...calculateJobDateRange(next),
    // Keep the first page's timestamp — it is when this company's data started
    // being fetched, not when the latest page happened to land.
    fetchedAt: draft.metadata[companyId]?.fetchedAt ?? new Date().toISOString(),
    totalCount: next.length,
  };
  return appended.length;
}

/** Push a chunk's floor deeper (floors only ever move older). */
function extendChunkFloor(draft: AllJobsQueryResult, key: string, floor: string | null): void {
  if (!floor) return;
  const prev = draft.chunkFloors[key];
  if (!prev || new Date(floor).getTime() < new Date(prev).getTime()) {
    draft.chunkFloors[key] = floor;
  }
}

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
  /**
   * Keyset walk state for the batched backend-scraper load: chunk key (the
   * comma-joined company ids of that chunk) -> the cursor for that chunk's
   * NEXT page.
   *
   * There is one cursor per HTTP request, and the batched load spans several
   * chunks, so a "next page" is several independent cursors advanced together.
   * A chunk whose last page came back short has **no entry** — the backend
   * omits `X-Next-Cursor` at the end of a walk, and that absence is the only
   * end-of-walk signal. An empty object therefore means the walk is complete
   * (`selectHasMoreJobs` is exactly `Object.keys(cursors).length > 0`).
   */
  cursors: Record<string, string>;
  /**
   * chunk key -> the OLDEST `firstSeenAt` fetched for that chunk so far.
   *
   * Chunks reach different depths (measured on prod, page 1 of the three chunks
   * cut off at 07-30 / 07-28 / 07-21), so the merged set is only provably
   * complete down to the shallowest still-walking chunk's floor. These floors
   * feed `computeCompleteHorizon`, which the Recent selectors clamp to.
   */
  chunkFloors: Record<string, string>;
  /**
   * The window every cursor above was minted under, as a **logical key**.
   *
   * A cursor is only meaningful under the filter set that minted it, so the
   * walk must notice a window change. Comparing logical keys (not raw ISO
   * strings) is what makes that check stable: a caller that recomputes
   * "90 days ago" on every scroll tick produces a different `since` each time
   * but the same `windowKey`, so it does not restart the walk.
   */
  windowKey: JobsWindowKey;
  /** The ISO `since` derived from `windowKey`; replayed verbatim on every page. */
  since: string;
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
            cursors: {},
            chunkFloors: {},
            windowKey: RECENT_JOBS_DEFAULT_WINDOW,
            since: sinceForWindow(RECENT_JOBS_DEFAULT_WINDOW),
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
          const { data: initialData } = await cacheDataLoaded;
          // The skeleton owns the walk's window; every request in this load —
          // and every later page fetched by `fetchNextJobsPage` — replays it.
          // `requestWindowKey` is captured here so the apply step can detect a
          // widen that superseded this request while it was in flight.
          const requestWindowKey = initialData.windowKey;
          const since = initialData.since;

          // Partition: backend-scraper companies share a single batched
          // backend call (one /api/jobs?companies=... request) to avoid
          // exhausting the API's 15-slot Postgres pool. All other ATS
          // companies hit external Vercel proxies and still fan out.
          const backendScraperCompanies = COMPANIES.filter((c) => c.ats === 'backend-scraper');
          const otherCompanies = COMPANIES.filter((c) => c.ats !== 'backend-scraper');

          const batchedFetch = (async () => {
            if (backendScraperCompanies.length === 0) return;

            // Mark every backend-scraper company as loading up front.
            updateCachedData((draft) => {
              for (const company of backendScraperCompanies) {
                updateCompanyProgress(draft.progress, company.id, { status: 'loading' });
              }
            });

            try {
              // Page 1 of the keyset walk: one request per company-chunk, each
              // bounded by `since` + the page size instead of a 50k row cap.
              const chunks = chunkCompanyIds(backendScraperCompanies.map((c) => c.id));
              const pages = await Promise.all(
                chunks.map((ids) => fetchJobsPage(ids, { since, limit: RECENT_JOBS_PAGE_SIZE }))
              );

              // One recipe applies every chunk, so all backend-scraper
              // companies still flip pending -> success at the same moment
              // (progress-bar semantics unchanged).
              //
              // Deliberately NOT seeding the per-company `getJobsForCompany`
              // caches here: these rows are a bounded PAGE, not the company's
              // full result set, and seeding them would park a truncated slice
              // in a cache marked fresh for `keepUnusedDataFor` (10 min). The
              // /companies click-through refetches on its own — one company,
              // cheap, and correct.
              updateCachedData((draft) => {
                // In-flight safety: `fetchNextJobsPage({ window })` may have
                // widened the walk while this request was airborne. These rows,
                // floors and cursors all describe the *previous* window, so the
                // payload is dropped wholesale rather than mixed in — stale
                // cursors would page the wrong window, and a stale floor would
                // claim a completeness horizon the new window has not reached.
                // No data is lost: a widen re-walks every chunk from page 1.
                const superseded = draft.windowKey !== requestWindowKey;
                if (superseded) {
                  logger.debug(
                    `[getAllJobs] dropping page-1 payload minted under superseded window ${requestWindowKey} (entry is now ${draft.windowKey})`
                  );
                }

                chunks.forEach((chunkIds, i) => {
                  const page = pages[i];
                  for (const companyId of chunkIds) {
                    mergeCompanyJobsIntoDraft(
                      draft,
                      companyId,
                      superseded ? [] : (page.byCompanyId[companyId]?.jobs ?? [])
                    );
                    updateCompanyProgress(draft.progress, companyId, {
                      status: 'success',
                      // Rows loaded so far, NOT a claim about the company's
                      // total — the walk may still have pages outstanding.
                      jobCount: draft.byCompanyId[companyId]?.length ?? 0,
                    });
                  }

                  if (superseded) return;
                  // Record where each chunk's walk stands. A chunk that came
                  // back short gets no cursor entry, so `hasMore` is false once
                  // all are short.
                  const key = chunkKey(chunkIds);
                  if (page.nextCursor) draft.cursors[key] = page.nextCursor;
                  extendChunkFloor(draft, key, oldestFirstSeenAt(page.jobs));
                });
              });
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

      providesTags: ['Jobs'],
    }),

    /**
     * Advance the Recent page's keyset walk by one page and APPEND the result
     * to the existing `getAllJobs` cache entry.
     *
     * Shape rationale — the batched load spans several company-chunks, so one
     * logical "next page" is several independent cursors. Rather than exposing
     * that to callers, this advances **every chunk that still holds a cursor**
     * in parallel, merges the responses into the same cache entry, and drops
     * the cursors of chunks that came back short. A caller therefore needs no
     * backend knowledge at all: dispatch it, and read `selectHasMoreJobs` to
     * know whether another call is worthwhile. It is a mutation rather than a
     * query precisely because it mutates an existing cache entry instead of
     * owning one — and that gives ticket 1.4's scroll trigger `isLoading` for
     * free to guard against double-firing.
     *
     * Never replaces: rows are appended and de-duplicated on `(source_id,
     * company, id)`, so a concurrent re-scrape that reshuffles a page cannot
     * drop rows already on screen.
     *
     * Optional `window` re-bounds the walk. It is a **logical key**, not a
     * timestamp, on purpose: the walk restarts only when the key changes, so a
     * caller that recomputes "90 days ago" on every scroll tick keeps paging
     * instead of restarting forever. A genuine window change **restarts the walk
     * from page 1** under the new bound and appends from there — it never
     * replays cursors minted under the old window.
     *
     * Dormant in this PR: no component dispatches it yet (ticket 1.4 wires the
     * scroll trigger).
     */
    fetchNextJobsPage: builder.mutation<
      FetchNextJobsPageResult,
      { window?: JobsWindowKey } | void
    >({
      async queryFn(arg, { dispatch, getState, signal }) {
        try {
          const selectAllJobs = jobsApi.endpoints.getAllJobs.select();
          const cached = selectAllJobs(
            getState() as Parameters<typeof selectAllJobs>[0]
          ).data;

          // No first page yet — nothing to advance. Not an error: 1.4's scroll
          // trigger can fire before the initial load has settled.
          if (!cached) {
            return { data: { added: 0, hasMore: false } };
          }

          // Logical-key comparison, never raw ISO. This is what stops an
          // F5 restart loop when the caller recomputes `since` per call.
          const widenedWindow =
            arg?.window && arg.window !== cached.windowKey ? arg.window : undefined;
          const windowKey = widenedWindow ?? cached.windowKey;
          const since = widenedWindow ? sinceForWindow(widenedWindow) : cached.since;

          // A window change invalidates every outstanding cursor -> plan a fresh
          // walk over the full chunk partition. Otherwise resume only the chunks
          // that still have somewhere to go.
          const plan: { ids: string[]; cursor?: string }[] = widenedWindow
            ? chunkCompanyIds(backendScraperCompanyIds()).map((ids) => ({ ids }))
            : Object.entries(cached.cursors).map(([key, cursor]) => ({
                ids: parseChunkKey(key),
                cursor,
              }));

          if (plan.length === 0) {
            return { data: { added: 0, hasMore: false } };
          }

          // Claim the new window BEFORE awaiting, so a page-1 request still in
          // flight from the initial load sees the entry has moved on and drops
          // its now-stale payload instead of stomping ours.
          if (widenedWindow) {
            dispatch(
              jobsApi.util.updateQueryData('getAllJobs', undefined, (draft) => {
                draft.windowKey = widenedWindow;
                draft.since = since;
                draft.cursors = {};
                draft.chunkFloors = {};
              })
            );
          }

          let pages: Awaited<ReturnType<typeof fetchJobsPage>>[];
          try {
            pages = await Promise.all(
              plan.map((p) =>
                fetchJobsPage(p.ids, {
                  since,
                  cursor: p.cursor,
                  limit: RECENT_JOBS_PAGE_SIZE,
                  signal,
                })
              )
            );
          } catch (error) {
            // The widen path CLAIMED the new window (cursors/floors cleared)
            // before this await. A failure here must not strand that claim:
            // with windowKey already reading as the new window, `needsWidening`
            // goes false and `hasCursors` is false, so the caller concludes the
            // walk is EXHAUSTED — a terminal "no jobs found" (or "all N
            // loaded") over a transient network error, with retry a silent
            // no-op. Roll the claim back so the widen stays pending: the error
            // latches as usual and retrying re-attempts the same widen.
            if (widenedWindow) {
              dispatch(
                jobsApi.util.updateQueryData('getAllJobs', undefined, (draft) => {
                  // A newer widen owns the entry now; leave its claim alone.
                  if (draft.windowKey !== widenedWindow) return;
                  draft.windowKey = cached.windowKey;
                  draft.since = cached.since;
                  draft.cursors = { ...cached.cursors };
                  draft.chunkFloors = { ...cached.chunkFloors };
                })
              );
            }
            throw error;
          }

          // Merge against the LIVE draft rather than the pre-fetch snapshot, so
          // a first load still streaming in cannot be clobbered.
          let added = 0;
          let hasMore = false;

          dispatch(
            jobsApi.util.updateQueryData('getAllJobs', undefined, (draft) => {
              // Another widen may have landed while these pages were in flight;
              // ours is the stale one now, so drop it (same rule as page 1).
              if (draft.windowKey !== windowKey) {
                hasMore = Object.keys(draft.cursors).length > 0;
                return;
              }

              plan.forEach((p, i) => {
                const page = pages[i];
                const key = chunkKey(p.ids);
                if (page.nextCursor) {
                  draft.cursors[key] = page.nextCursor;
                } else {
                  delete draft.cursors[key];
                }
                extendChunkFloor(draft, key, oldestFirstSeenAt(page.jobs));

                for (const companyId of p.ids) {
                  const incoming = page.byCompanyId[companyId]?.jobs ?? [];
                  if (incoming.length === 0) continue;
                  added += mergeCompanyJobsIntoDraft(draft, companyId, incoming);
                  updateCompanyProgress(draft.progress, companyId, {
                    status: 'success',
                    // Rows loaded so far, not a completeness claim.
                    jobCount: draft.byCompanyId[companyId]?.length ?? 0,
                  });
                }
              });

              hasMore = Object.keys(draft.cursors).length > 0;
            })
          );

          // Deliberately NOT seeding `getJobsForCompany` here — see the note on
          // the page-1 apply. These rows are a page, not a company's full set.

          return { data: { added, hasMore } };
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
  useGetAllJobsQuery,
  useGetFacetsQuery,
  useFetchNextJobsPageMutation,
} = jobsApi;
