import type { Job } from '../../types';
import type { BackendJobListing } from '../../api/types';
import { APIError } from '../../api/types';
import { transformBackendJob } from '../../api/transformers/backendScraperTransformer';
import { logger } from '../../lib/logger';

/**
 * The owner-scoped half of the Recent Jobs feed.
 *
 * `GET /api/jobs` is unauthenticated and excludes `visibility='user'` companies
 * UNCONDITIONALLY — that guard is load-bearing and is deliberately not relaxed
 * (the backend carries named leak tests for it). So a user's own private boards
 * reach the feed through a SECOND, authenticated request, which the page merges
 * into the same keyset walk. See `GET /api/users/companies/jobs`.
 *
 * **Why a plain function and not an endpoint on `userCompaniesApi`.** The
 * public half of the walk is a plain `fetchJobsPage`, and the whole design of
 * the walk is that `getAllJobs` owns the cursors and the completeness horizon
 * for every chunk. Modelling this half as an RTK Query endpoint would split
 * that ownership in two — a second cache holding pages that `getAllJobs` has
 * already copied into `byCompanyId`, keyed per-cursor so every page of a scroll
 * leaves a dead entry behind. A function that mirrors `fetchJobsPage` keeps one
 * walk with one set of cursors.
 */

const CUSTOM_JOBS_URL = '/api/users/companies/jobs';

/** `X-Next-Cursor`; header names are case-insensitive per `Headers.get`. */
const NEXT_CURSOR_HEADER = 'X-Next-Cursor';

/** The `source_id` namespace every custom company's rows carry (`custom:<id>`). */
const CUSTOM_SOURCE_PREFIX = 'custom:';

export interface FetchMyCustomJobsPageOptions {
  /**
   * ISO-8601 timestamp **with a UTC offset**. Inclusive lower bound on
   * `first_seen_at`, and — exactly as on `/api/jobs` — its presence is what puts
   * the endpoint in keyset mode at all.
   */
  since: string;
  /** Opaque keyset token, verbatim from a previous page's `X-Next-Cursor`. */
  cursor?: string;
  /** Rows per page. The backend caps this endpoint at 5000 (not 50000). */
  limit?: number;
  signal?: AbortSignal;
}

export interface CustomJobsPage {
  /** Every row in the page, in server order (`first_seen_at` DESC). */
  jobs: Job[];
  /**
   * The same `Job` objects grouped by custom-company id. Unlike the public
   * client's equivalent there is no "requested ids" list to seed from — the
   * company set is derived server-side from `user_companies`, so the keys here
   * are exactly the boards that returned a row on this page.
   */
  byCompanyId: Record<string, Job[]>;
  /**
   * `X-Next-Cursor`, or `null` at the end of the walk. Its **absence is the
   * only end-of-walk signal**; the backend emits it iff the page came back
   * full. `api/users.ts` has to re-emit it explicitly because the shared
   * `forwardResponse` helper copies status + body only.
   */
  nextCursor: string | null;
}

/**
 * Whether `companyId` is a user-added board rather than one of the curated
 * compile-time companies.
 *
 * The backend mints these as `u-<base36>` (`new_custom_company_id`), and the
 * shape is the ONLY signal available downstream: by the time a row reaches the
 * Recent selectors its `custom:` source-id namespace has already been stripped
 * to the runtime id the rest of the custom-company UI keys on.
 *
 * Exported because the enabled-companies prefilter needs it: `enabledCompanies.ids`
 * is the curated PUBLIC roster (built from `COMPANIES`, and the backend's
 * auto-enroll query excludes `visibility='user'`), so a `u-<id>` can never appear
 * in it. Without this check a user who has saved a company set would silently see
 * none of their own private boards — the preference is about which public
 * companies to show, not a reason to hide the user's own.
 */
export function isCustomCompanyId(companyId: string): boolean {
  return /^u-[0-9a-z]+$/.test(companyId);
}

/**
 * The company id a custom row belongs to.
 *
 * Derived from `source_id` rather than trusted from the `company` column
 * because `custom:<id>` is the namespace the row is *keyed* by — it is what the
 * endpoint's authorization is expressed in and what the backend's per-company
 * isolation is enforced on — whereas `company` is a value the harvest writes
 * alongside it. They agree today (`fetch_custom_company` writes both), and
 * `company` is the fallback if a row ever arrives under a namespace this build
 * does not recognize.
 *
 * The result must be the `u-<...>` runtime id, because that is the key the rest
 * of the custom-company UI (the Add Companies list, the trend page, the job
 * card's company lookup) already uses.
 */
function companyIdForRow(row: BackendJobListing): string {
  return row.sourceId?.startsWith(CUSTOM_SOURCE_PREFIX)
    ? row.sourceId.slice(CUSTOM_SOURCE_PREFIX.length)
    : row.company;
}

/**
 * One keyset page of the signed-in caller's own custom-company jobs.
 *
 * `token` is a REQUIRED non-null string rather than an optional header, so
 * "signed out means no request" is enforced by the type system at every call
 * site instead of by a runtime check that a later edit could drop. An anonymous
 * caller has no token to pass, and the endpoint would answer 401 anyway.
 *
 * Speaks the same `since`/`cursor`/`X-Next-Cursor` contract as
 * `fetchJobsPage`, so both halves of the feed are driven by one walk.
 */
export async function fetchMyCustomJobsPage(
  token: string,
  options: FetchMyCustomJobsPageOptions
): Promise<CustomJobsPage> {
  const params = new URLSearchParams({
    // Mirrors the public page fetch: the feed only ever shows OPEN roles.
    status: 'OPEN',
    since: options.since,
    limit: (options.limit ?? 1000).toString(),
  });
  // Sent on presence, mirroring `fetchJobsPage`: silently dropping an empty
  // cursor would restart the walk at page 1 instead of surfacing the 422.
  if (options.cursor !== undefined) params.set('cursor', options.cursor);
  const url = `${CUSTOM_JOBS_URL}?${params}`;

  let rows: BackendJobListing[];
  let nextCursor: string | null;
  try {
    const response = await fetch(url, {
      signal: options.signal,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
      },
    });

    if (!response.ok) {
      const retryable = response.status >= 500 || response.status === 429;
      throw new APIError(
        `Custom jobs API error: ${response.statusText || response.status}`,
        response.status,
        'backend-scraper',
        retryable
      );
    }

    nextCursor = response.headers?.get(NEXT_CURSOR_HEADER) || null;
    rows = await response.json();
  } catch (error) {
    logger.error('[Custom Jobs Client] Keyset page fetch error:', error);
    if (error instanceof APIError) throw error;
    throw new APIError(
      `Failed to fetch custom jobs page: ${(error as Error).message}`,
      undefined,
      'backend-scraper',
      true
    );
  }

  const jobs: Job[] = [];
  const byCompanyId: Record<string, Job[]> = {};
  for (const row of rows) {
    const companyId = companyIdForRow(row);
    const job = transformBackendJob(row, companyId);
    jobs.push(job);
    (byCompanyId[companyId] ??= []).push(job);
  }

  logger.debug(
    `[Custom Jobs Client] Keyset page: ${rows.length} rows across ${Object.keys(byCompanyId).length} custom companies, nextCursor=${nextCursor ? 'present' : 'absent'}`
  );

  return { jobs, byCompanyId, nextCursor };
}
