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
  CUSTOM_JOBS_CHUNK_KEY,
  RECENT_JOBS_DEFAULT_WINDOW,
  RECENT_JOBS_PAGE_SIZE,
  chunkKey,
  jobKey,
  oldestFirstSeenAt,
  parseChunkKey,
  sinceForWindow,
} from './keysetWalk';
import type { JobsWindowKey } from './keysetWalk';
import { CUSTOM_COMPANIES_CONFIG } from '../../config/customCompanies';
import {
  fetchMyCompanyJobs,
  fetchMyCustomJobsPage,
  isCustomCompanyId,
} from '../userCompanies/customJobsClient';
import type { CustomJobsPage } from '../userCompanies/customJobsClient';
import { APIError } from '../../api/types';
import { extractErrorMessage } from '../../lib/errors';

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

/** The store's thunk `extraArgument`, as far as this module needs it. */
interface JobsApiExtra {
  getTokenOrNull?: () => Promise<string | null>;
}

/**
 * The caller's bearer token, or `null` when there is no signed-in user.
 *
 * This is THE gate on the private half of the feed: no token means the
 * custom-jobs request is never issued at all. That is deliberately stronger
 * than "issue it and tolerate the 401" — an anonymous visitor must see exactly
 * what they see today, with no extra round trip and no 401 in their console.
 *
 * `getTokenOrNull` already resolves to `null` (never throws) on the signed-out
 * path; it swallows `NotAuthenticatedError` precisely so anonymous page loads
 * stay quiet. The `typeof` guard covers a store configured without the thunk
 * `extraArgument` — every existing `jobsApi` unit-test store is one, and they
 * must keep testing only the public walk.
 */
async function tokenFromExtra(extra: unknown): Promise<string | null> {
  const getToken = (extra as JobsApiExtra | undefined)?.getTokenOrNull;
  if (typeof getToken !== 'function') return null;
  return getToken();
}

/**
 * One page of the caller's own custom-company jobs, or `null` when there is
 * nothing to merge.
 *
 * `null` covers four cases the feed must survive identically — the feature being
 * flagged off, signed out, no private boards, and the request having FAILED. A
 * private-companies failure is swallowed here rather than propagated because the
 * public feed is the page: letting a 500 / expired token / dropped connection on
 * this second request reject would blank the whole Recent list (in
 * `fetchNextJobsPage` it would also latch the paging error and stop the public
 * walk). It is logged, not silent.
 */
async function fetchCustomJobsPageOrNull(
  extra: unknown,
  options: { since: string; cursor?: string; signal?: AbortSignal }
): Promise<CustomJobsPage | null> {
  // Flag-off contract (`src/frontend/CLAUDE.md`): with
  // `VITE_CUSTOM_COMPANIES_ENABLED` off this feature does not exist and the app
  // makes NO network calls for it. It also protects the common half-off
  // deployment — the backend owns a separate flag and answers 503 while it is
  // off, which would otherwise be a 503 on every signed-in page load.
  if (!CUSTOM_COMPANIES_CONFIG.isEnabled) return null;
  const token = await tokenFromExtra(extra);
  if (!token) return null;
  try {
    return await fetchMyCustomJobsPage(token, {
      ...options,
      limit: RECENT_JOBS_PAGE_SIZE,
    });
  } catch (error) {
    logger.warn(
      '[getAllJobs] custom-company jobs page failed; the Recent feed keeps its public rows:',
      error
    );
    return null;
  }
}

/**
 * The whole of ONE user-added board, for the Company Hiring Trends page.
 *
 * This is the entire integration: `getJobsForCompany` is the single cache entry
 * the whole `/companies` chain reads (`selectCurrentCompanyJobsRtk` →
 * `selectGraphFilteredJobs*` → chart, list, metrics, bucket modal), so
 * branching here delivers filters, graph, list and metrics for a custom board
 * with no change to any of them.
 *
 * Three refusals, in order, each of which must stay exactly this shape:
 *
 * - **Flag off → the same 404 the page has always answered for an unknown id.**
 *   With `VITE_CUSTOM_COMPANIES_ENABLED` off the feature does not exist, and a
 *   `u-<id>` is simply a company we do not have. No request is constructed.
 * - **No token → 401, without a request.** An anonymous visitor cannot see a
 *   private board and must not pay a round trip to be told so; the page renders
 *   a sign-in prompt instead.
 * - **A real failure keeps its HTTP status**, unlike the public branch's blanket
 *   `CUSTOM_ERROR`, because the page distinguishes them: 403 is "not yours"
 *   (the endpoint checks ownership before reading anything) and 503 is the
 *   backend's own flag being off, which must render an error, never a blank chart.
 */
async function fetchCustomCompanyJobs(
  companyId: string,
  extra: unknown,
  signal: AbortSignal
): Promise<
  { data: JobsQueryResult; error?: undefined } | { error: { status: unknown; data: string } }
> {
  if (!CUSTOM_COMPANIES_CONFIG.isEnabled) {
    return { error: { status: 404, data: `Company not found: ${companyId}` } };
  }
  const token = await tokenFromExtra(extra);
  if (!token) {
    return { error: { status: 401, data: 'Sign in to view companies you track.' } };
  }
  try {
    const jobs = await fetchMyCompanyJobs(token, companyId, { signal });
    return {
      data: {
        jobs,
        metadata: {
          totalCount: jobs.length,
          fetchedAt: new Date().toISOString(),
          ...calculateJobDateRange(jobs),
        },
      },
    };
  } catch (error) {
    if (error instanceof APIError && error.statusCode !== undefined) {
      return { error: { status: error.statusCode, data: error.message } };
    }
    return {
      error: {
        status: 'CUSTOM_ERROR',
        data: extractErrorMessage(error, 'Unknown error'),
      },
    };
  }
}

/**
 * Merge one custom-jobs page into the cache draft: its rows, its cursor and its
 * floor.
 *
 * Rows land in the same `byCompanyId` map as the public ones — under their
 * `u-<id>` company ids — which is what makes them interleave by date instead of
 * arriving as a lump: the Recent selectors flatten that map and sort the whole
 * set by `firstSeenAt`, so a custom row's position is decided by its timestamp
 * and nothing else.
 *
 * Deliberately does NOT touch `draft.progress`. That is the public fan-out's
 * progress bar, sized from the compile-time `COMPANIES` roster and filtered by
 * the user's enabled set; adding runtime `u-<id>` entries would move its total
 * and show chips for companies the roster has never heard of.
 *
 * @returns how many rows were genuinely new
 */
function mergeCustomPageIntoDraft(draft: AllJobsQueryResult, page: CustomJobsPage): number {
  let added = 0;
  for (const [companyId, jobs] of Object.entries(page.byCompanyId)) {
    added += mergeCompanyJobsIntoDraft(draft, companyId, jobs);
  }
  if (page.nextCursor) {
    draft.cursors[CUSTOM_JOBS_CHUNK_KEY] = page.nextCursor;
  } else {
    delete draft.cursors[CUSTOM_JOBS_CHUNK_KEY];
  }
  extendChunkFloor(draft, CUSTOM_JOBS_CHUNK_KEY, oldestFirstSeenAt(page.jobs));
  return added;
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
        { updateCachedData, cacheDataLoaded, cacheEntryRemoved, dispatch, extra }
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

          // Page 1 of the PRIVATE half of the feed, running beside the public
          // chunks. It is a separate request because `/api/jobs` is anonymous
          // and excludes `visibility='user'` companies unconditionally — see
          // `customJobsClient.ts`. Signed out, it never leaves the browser.
          const customFetch = (async () => {
            const page = await fetchCustomJobsPageOrNull(extra, { since });
            // Nothing to merge (signed out / no private boards / the request
            // failed) => do not touch the cache entry at all. Skipping the
            // update, rather than applying an empty one, is what keeps the
            // Recent selectors returning their existing array BY IDENTITY, so
            // an anonymous visitor's page does not re-render for a feature they
            // are not using.
            if (!page || (page.jobs.length === 0 && !page.nextCursor)) return;

            updateCachedData((draft) => {
              // Same in-flight rule as the public chunks: a widen may have
              // landed while this was airborne, and a cursor/floor minted under
              // the old window would page the wrong window and claim a horizon
              // the new one has not reached.
              if (draft.windowKey !== requestWindowKey) {
                logger.debug(
                  `[getAllJobs] dropping custom-jobs page minted under superseded window ${requestWindowKey} (entry is now ${draft.windowKey})`
                );
                return;
              }
              mergeCustomPageIntoDraft(draft, page);
            });
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

          await Promise.allSettled([batchedFetch, customFetch, ...otherFetches]);

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
     * The signed-in caller's OWN custom companies are one more walk advanced
     * alongside the public chunks, under the reserved `CUSTOM_JOBS_CHUNK_KEY`.
     * It is a second request because `/api/jobs` is anonymous and excludes
     * private companies unconditionally; signed out it is never issued, and a
     * failure of it can never fail this mutation (see
     * `fetchCustomJobsPageOrNull`).
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
      async queryFn(arg, { dispatch, getState, signal, extra }) {
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
          //
          // `CUSTOM_JOBS_CHUNK_KEY` is filtered out because it is a reserved key,
          // not a comma-joined list of company ids: feeding it to
          // `parseChunkKey` + `fetchJobsPage` would request a company literally
          // named "custom:jobs" from the public endpoint.
          const plan: { ids: string[]; cursor?: string }[] = widenedWindow
            ? chunkCompanyIds(backendScraperCompanyIds()).map((ids) => ({ ids }))
            : Object.entries(cached.cursors)
                .filter(([key]) => key !== CUSTOM_JOBS_CHUNK_KEY)
                .map(([key, cursor]) => ({
                  ids: parseChunkKey(key),
                  cursor,
                }));

          // The private half advances under the same two rules as a public
          // chunk: a widen restarts it from page 1 under the new bound, and
          // otherwise it advances only while it still holds a cursor.
          const customCursor = widenedWindow ? undefined : cached.cursors[CUSTOM_JOBS_CHUNK_KEY];
          const walkCustom = Boolean(widenedWindow) || customCursor !== undefined;

          if (plan.length === 0 && !walkCustom) {
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

          // Both halves advance together so one logical "next page" is one
          // round trip's worth of latency, and so their floors land in the same
          // cache update (a horizon computed from half-applied floors would
          // clamp rows away for a frame).
          let pages: Awaited<ReturnType<typeof fetchJobsPage>>[];
          let customPage: CustomJobsPage | null;
          try {
            [pages, customPage] = await Promise.all([
              Promise.all(
                plan.map((p) =>
                  fetchJobsPage(p.ids, {
                    since,
                    cursor: p.cursor,
                    limit: RECENT_JOBS_PAGE_SIZE,
                    signal,
                  })
                )
              ),
              // Inside the try, but it can never reach the catch:
              // `fetchCustomJobsPageOrNull` resolves `null` on every failure
              // and never rejects (its own token lookup is total too). The
              // rollback below therefore stays a public-walk concern, and a
              // private-jobs failure still fails soft — it cannot roll back a
              // widen the public half completed, nor fail this mutation.
              walkCustom
                ? fetchCustomJobsPageOrNull(extra, { since, cursor: customCursor, signal })
                : Promise.resolve(null),
            ]);
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

              // `null` means flagged off, signed out, no private boards, or a
              // failed request. All four leave the public walk as it was —
              // the private half must never be able to stall or blank the feed.
              // The custom cursor is deliberately LEFT in place on a failure so
              // a transient one (502, a token refresh mid-flight) heals on the
              // next page; a permanently failing one is bounded by the list's
              // `MAX_EMPTY_AUTO_FETCHES` stop, exactly like an empty page.
              if (customPage) added += mergeCustomPageIntoDraft(draft, customPage);

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

    /**
     * Keep the Recent feed honest after the user adds or removes a board.
     *
     * WHY THIS IS NOT `invalidateTags(['Jobs'])`. `getAllJobs` is not an
     * ordinary query: its cache entry is filled by `onCacheEntryAdded`, which
     * RTK Query runs **once per cache entry**, not per fetch. Invalidating it
     * re-runs only `queryFn` — which returns the empty skeleton — and the
     * streaming lifecycle never runs again, so the whole Recent feed goes blank
     * for the rest of the session and stays that way. (That is exactly what the
     * regression test in `jobsFeedCacheCoherence.test.ts` catches.) The feed has
     * to be corrected in place instead.
     *
     * Two corrections, both narrow enough that they cannot break the walk:
     *
     * - `removedCompanyId` — delete exactly that board's rows and metadata. No
     *   network and no guessing: the user just told the server to stop tracking
     *   it, and its jobs must not sit in the feed for the rest of the session.
     * - Then top up from the private half's first page, so a board that already
     *   has jobs when it is added shows up without a reload.
     *
     * Cursors and chunk floors are deliberately untouched. This is an
     * out-of-band top-up, not a step of the keyset walk — moving a cursor here
     * would make the next `fetchNextJobsPage` skip a page. The merge appends and
     * de-duplicates, so it can only ever add rows.
     */
    syncCustomJobsIntoFeed: builder.mutation<
      { added: number },
      { removedCompanyId?: string } | void
    >({
      async queryFn(arg, { dispatch, getState, signal, extra }) {
        const selectAllJobs = jobsApi.endpoints.getAllJobs.select();
        const cached = selectAllJobs(getState() as Parameters<typeof selectAllJobs>[0]).data;
        // No feed loaded in this session — nothing to correct, and the next load
        // reads the server's current answer anyway.
        if (!cached) return { data: { added: 0 } };

        const removedCompanyId = arg?.removedCompanyId;
        if (removedCompanyId) {
          dispatch(
            jobsApi.util.updateQueryData('getAllJobs', undefined, (draft) => {
              delete draft.byCompanyId[removedCompanyId];
              delete draft.metadata[removedCompanyId];
            })
          );
          // The per-company trend cache for that board is stale too. A
          // COMPANY-SCOPED tag, never the bare `Jobs` type — the bare type is
          // what `getAllJobs` provides, and invalidating it is the blanking bug
          // described above.
          dispatch(jobsApi.util.invalidateTags([{ type: 'Jobs' as const, id: removedCompanyId }]));
        }

        const page = await fetchCustomJobsPageOrNull(extra, { since: cached.since, signal });
        if (!page) return { data: { added: 0 } };

        let added = 0;
        dispatch(
          jobsApi.util.updateQueryData('getAllJobs', undefined, (draft) => {
            for (const [companyId, jobs] of Object.entries(page.byCompanyId)) {
              // A page served before the delete committed must not resurrect the
              // board the user just removed.
              if (companyId === removedCompanyId) continue;
              added += mergeCompanyJobsIntoDraft(draft, companyId, jobs);
            }
          })
        );
        return { data: { added } };
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
