import { createApi, fakeBaseQuery } from '@reduxjs/toolkit/query/react';
import type { Job, JobFacets } from '../../types';
import { getCompanyById } from '../../config/companies';
import type { FetchJobsResult } from '../../api/types';
import { getClientForATS } from '../../api/utils';
import { calculateJobDateRange } from '../../lib/date';
import { transformBackendJob } from '../../api/transformers/backendScraperTransformer';
import { CUSTOM_COMPANIES_CONFIG } from '../../config/customCompanies';
import { fetchMyCompanyJobs, isCustomCompanyId } from '../userCompanies/customJobsClient';
import { APIError } from '../../api/types';
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
 * The endpoint's "your cursor is stale — restart the walk from page 1" status.
 *
 * Deliberately NOT in `READER_FACING_ERROR_STATUSES`. It is the one rejection on
 * this endpoint whose `detail` is addressed to the CLIENT rather than the reader:
 * nobody can carry out "drop the cursor and restart the walk" by editing a filter
 * chip, and the next-page error box's only affordance is a Retry that replays the
 * same rejected cursor — so surfacing that sentence produces an error that can
 * never clear. `useRecentJobsSearch` keys its recovery on this status instead
 * (retry restarts the walk), which is the whole reason it has its own code.
 *
 * Unreachable from THIS client today — RTK Query's per-arg cache isolation means
 * a cursor and the filters that minted it always travel together — but reachable
 * the first time a backend deploy moves `_SEARCH_CURSOR_VERSION` or the
 * fingerprint inputs mid-session, which is exactly when nobody is watching.
 */
export const STALE_CURSOR_STATUS = 409;

/**
 * The only statuses whose `detail` is written FOR the reader.
 *
 * `/api/jobs/search` rejects a filter set the client can fix with a 400 (too many
 * keywords / locations / companies, an empty value) or a 422 (a malformed
 * `since`, a bad slug, a value with control characters in it). Those messages
 * name the thing to change and are worth putting on screen.
 *
 * Every OTHER status carries FastAPI's or the proxy's stock text, and showing it
 * is strictly worse than the generic fallback: the deploy-race 404 the hook waits
 * out for ~4 minutes on every release would end at the words "Not Found", and a
 * backend crash would read "Internal Server Error" — neither tells the reader
 * anything, and both look like the page is broken in a way they caused. The
 * stale-cursor 409 is excluded for a different reason — see
 * `STALE_CURSOR_STATUS`.
 */
const READER_FACING_ERROR_STATUSES: ReadonlySet<number> = new Set([400, 422]);

/**
 * A failed `/api/jobs/search` response, decoded ONCE for two different audiences.
 *
 * A `Response` body is a stream and can be consumed exactly once, so the read
 * happens here and yields both halves:
 *
 * - `message` is the line the reader sees, gated by
 *   `READER_FACING_ERROR_STATUSES`. FastAPI puts the reason in `detail`, and it
 *   survives the Vercel proxy intact (`forwardResponse` copies status + body).
 * - `diagnostic` is the verbatim payload for the log, ungated.
 *
 * They differ on purpose, and the gap between them IS the point of the gate: on
 * a 500 the reader gets the generic line while the log keeps "Internal Server
 * Error"; on a proxy 502 the log keeps the HTML. Nothing here rethrows — an
 * unreadable body must still produce an error the page can render.
 */
interface SearchErrorResponse {
  message: string;
  diagnostic: string;
}

/**
 * Cap on the body text that reaches `console.error`.
 *
 * The reader-facing half of this response is a short `detail` string, but the
 * DIAGNOSTIC half is whatever answered — and the things that answer instead of
 * FastAPI are exactly the verbose ones: a CDN or WAF block page, a proxy 502
 * with an inlined stack trace, an HTML error document with a base64 logo in it.
 * Logging one of those verbatim floods the console (and any error-reporting
 * transport reading it) with megabytes for a single failed request. 4 KB is far
 * more than any `detail` and enough of an HTML page to recognize which layer
 * produced it, which is the only thing the log is asked to answer.
 */
const MAX_DIAGNOSTIC_LENGTH = 4096;

/**
 * Turn a raw error body into the string the log gets.
 *
 * An empty body is spelled out rather than passed through: `logger.error` with
 * `''` as its second argument renders as a bare trailing colon with nothing
 * after it, which is indistinguishable from a formatting bug in the log line
 * itself. It is the same reason the unreadable case below is marked — the log
 * has to say WHICH kind of nothing it got.
 */
function toDiagnostic(raw: string): string {
  if (raw === '') return '<empty body>';
  if (raw.length <= MAX_DIAGNOSTIC_LENGTH) return raw;
  return `${raw.slice(0, MAX_DIAGNOSTIC_LENGTH)} <truncated: ${raw.length} chars total>`;
}

async function readErrorResponse(response: Response): Promise<SearchErrorResponse> {
  let raw: string;
  try {
    raw = await response.text();
  } catch (error) {
    // The connection dropped mid-response: there is no body to decode, but the
    // status is still worth reporting and this is still a real failure.
    return {
      message: ERROR_MESSAGES.LOAD_JOBS_FAILED,
      diagnostic: `<body unreadable: ${extractErrorMessage(error, 'unknown reason')}>`,
    };
  }
  const diagnostic = toDiagnostic(raw);
  if (!READER_FACING_ERROR_STATUSES.has(response.status)) {
    return { message: ERROR_MESSAGES.LOAD_JOBS_FAILED, diagnostic };
  }
  try {
    const body: unknown = JSON.parse(raw);
    // Wrapped as `{ data }` because that is the shape `extractErrorMessage`
    // decodes: it owns the `detail` / `message` precedence and the "a 422's LIST
    // detail is developer output, not reader output" rule, and re-implementing
    // either here is exactly the duplication rule 3 in `src/frontend/CLAUDE.md`
    // forbids. What stays local is the STATUS gate above, which is a different
    // decision entirely — see `READER_FACING_ERROR_STATUSES`.
    return {
      message: extractErrorMessage({ data: body }, ERROR_MESSAGES.LOAD_JOBS_FAILED),
      diagnostic,
    };
  } catch {
    // A 400/422 whose body is not JSON is the one case worth calling out: this
    // status class is FastAPI telling the reader which filter to relax, so a
    // non-JSON body here means something in front of FastAPI (the proxy, a WAF,
    // a CDN error page) answered instead. The reader gets the fallback because
    // there is nothing actionable to show them — but the raw text reaches the
    // log, because that is a different bug from any filter they could change.
    return { message: ERROR_MESSAGES.LOAD_JOBS_FAILED, diagnostic };
  }
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
      async queryFn({ queryArg, pageParam }, { signal, extra }) {
        try {
          const url = `/api/jobs/search?${buildSearchJobsQuery(queryArg, pageParam)}`;
          // OPTIONAL auth, unlike the private-half fetch above: this endpoint
          // serves anonymous callers the public corpus, and a token only ever
          // ADDS the reader's own custom boards to the result. So a null token is
          // a normal request, not a refusal — the walk proceeds either way.
          //
          // Without it the backend cannot tell who is asking and applies the
          // blanket private-company guard, which is why a reader's own custom
          // companies were missing from their feed even after being fetched.
          //
          // The header must also survive `api/jobs.ts`, which forwards it only
          // because it was taught to; `tokenFromExtra` never throws (see above),
          // so a token failure degrades to anonymous rather than failing the page.
          const token = await tokenFromExtra(extra);
          const response = await fetch(url, {
            signal,
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          });
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
            //
            // EVERY non-2xx is logged, including the ones the gate silences for
            // the reader — especially those. The gate decides what is fit to put
            // on screen, not whether the failure happened: a 500 from a
            // `DB_POOL_MAX` checkout timeout, a proxy 502/504, and a 404 that
            // outlived the deploy-race grace window all render the same generic
            // line, so without this the console is empty and the status and body
            // are gone. Symmetric with the catch below, which logs for exactly
            // this reason.
            const { message, diagnostic } = await readErrorResponse(response);
            logger.error(
              `[jobsApi] /api/jobs/search responded ${response.status}:`,
              diagnostic
            );
            return { error: { status: response.status, data: message } };
          }
          // `pageParam === null` IS "this is page 1" — it is the endpoint's own
          // spelling of it (`initialPageParam`, and the value `buildSearchJobsQuery`
          // omits the `cursor` param for). The validator needs it because a missing
          // `meta` is correct on a cursor page and a broken contract on page 1, and
          // the body alone cannot tell those apart.
          const body = validateSearchJobsResponse(await response.json(), {
            isFirstPage: pageParam === null,
          });
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
          //
          // The one silence is a genuine abort, and it is keyed on `signal`, the
          // FACT, rather than on `error.name === 'AbortError'`, a CLAIM any
          // browser extension, polyfill or fetch interceptor can make. An
          // AbortError raised while `signal.aborted` is false is not an abort:
          // the reader is looking at the generic error line and something really
          // did fail, so it belongs in the log like any other throw.
          //
          // How often does the silence actually fire? Effectively never, and
          // that asymmetry is deliberate. In the installed RTK Query (2.11.0)
          // this signal is aborted from exactly two places, neither of which the
          // Recent page reaches: the `keepUnusedDataFor` removal timer, which
          // runs 10 minutes after the LAST subscriber leaves a cache entry and
          // so fires long after any request has settled
          // (`rtk-query.modern.mjs:2253`), and `api.util.resetApiState`, which
          // this app never dispatches. A filter change only unsubscribes, and
          // `unsubscribe()` dispatches `unsubscribeQueryResult` and nothing else
          // (`:637`) — it does not abort. So the gate errs toward LOGGING, which
          // is the safe direction: a silence that never fires costs nothing,
          // while a silence keyed on a forgeable name loses real failures.
          if (!signal.aborted) {
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
