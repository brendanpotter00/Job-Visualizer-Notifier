import type {
  JobAPIClient,
  FetchJobsOptions,
  FetchJobsResult,
  BackendJobListing,
  JobsPage,
} from '../types';
import type { ATSCompanyConfig } from './baseClient';
import type { BackendScraperConfig, Job } from '../../types';
import { APIError } from '../types';
import { logger } from '../../lib/logger';
import { transformBackendJob } from '../transformers/backendScraperTransformer';

const DEFAULT_BACKEND_JOBS_URL = '/api/jobs';

/**
 * Backend scraper client - fetches jobs from backend API for scraped companies
 *
 * Works for any company whose jobs are scraped and stored in PostgreSQL
 * (e.g., Google, Apple, etc.). Uses config.companyId to determine which
 * company's jobs to fetch.
 */
export const backendScraperClient: JobAPIClient = {
  async fetchJobs(
    config: ATSCompanyConfig,
    options: FetchJobsOptions = {}
  ): Promise<FetchJobsResult> {
    // 1. Validate config type
    if (config.type !== 'backend-scraper') {
      throw new Error(
        `Invalid config type for Backend Scraper client. Expected 'backend-scraper', got '${config.type}'`
      );
    }

    const backendConfig = config as BackendScraperConfig;

    // 2. Build API URL - uses Vercel proxy to backend
    const apiBase = backendConfig.apiBaseUrl || DEFAULT_BACKEND_JOBS_URL;
    const params = new URLSearchParams({
      company: backendConfig.companyId,
      status: 'OPEN',
      limit: (options.limit ?? 5000).toString(),
    });
    const url = `${apiBase}?${params}`;

    logger.debug(`[Backend Scraper Client] Fetching ${backendConfig.companyId} jobs from:`, url);

    try {
      // 3. Fetch from backend API
      const response = await fetch(url, {
        signal: options.signal,
        headers: {
          Accept: 'application/json',
        },
      });

      logger.debug('[Backend Scraper Client] Response status:', response.status);

      // 4. Handle HTTP errors
      if (!response.ok) {
        logger.error('[Backend Scraper Client] Response not OK:', response.statusText);

        // Determine if error is retryable
        const retryable = response.status >= 500 || response.status === 429;

        throw new APIError(
          `Backend Scraper API error: ${response.statusText}`,
          response.status,
          'backend-scraper',
          retryable
        );
      }

      // 5. Parse JSON response
      const data: BackendJobListing[] = await response.json();
      logger.debug('[Backend Scraper Client] Received jobs:', data.length);

      // Enhanced diagnostic logging for debugging zero-results issues
      if (data.length === 0) {
        logger.warn(
          `[Backend Scraper Client] Zero jobs returned for ${backendConfig.companyId} from ${url}`
        );
      }

      // 6. Transform to internal model (passing companyId for dynamic source)
      const jobs = data.map((job) => transformBackendJob(job, backendConfig.companyId));

      // 7. Apply 'since' filter if provided
      let filteredJobs = jobs;
      if (options.since) {
        const sinceDate = new Date(options.since);
        filteredJobs = jobs.filter((job) => new Date(job.createdAt) >= sinceDate);
        logger.debug(
          `[Backend Scraper Client] Filtered by 'since': ${filteredJobs.length}/${jobs.length} jobs`
        );
      }

      // 8. Return result
      const result: FetchJobsResult = {
        jobs: filteredJobs,
        metadata: {
          totalCount: filteredJobs.length,
          fetchedAt: new Date().toISOString(),
        },
      };

      logger.debug('[Backend Scraper Client] Fetch complete:', result.metadata);

      return result;
    } catch (error) {
      logger.error('[Backend Scraper Client] Error:', error);

      if (error instanceof APIError) {
        throw error;
      }

      throw new APIError(
        `Failed to fetch ${backendConfig.companyId} jobs: ${(error as Error).message}`,
        undefined,
        'backend-scraper',
        true // Network errors are retryable
      );
    }
  },
};

export interface FetchJobsForCompaniesOptions {
  signal?: AbortSignal;
  limit?: number;
  apiBaseUrl?: string;
}

// Chunk size for /api/jobs?companies=. Backend caps at 150 (defense-in-depth);
// 50 keeps each URL well under cap + query-string limits and leaves room to
// add backend-scraper companies without hitting either bound again.
const _COMPANIES_PER_REQUEST = 50;

function chunk<T>(arr: T[], size: number): T[][] {
  if (size <= 0) throw new Error('chunk size must be > 0');
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

/**
 * The chunk plan for a batched `/api/jobs?companies=` load — one entry per
 * HTTP request that `fetchJobsForCompanies` / `fetchJobsPage` would issue.
 *
 * Exported because keyset pagination is **per request**: the backend mints one
 * `X-Next-Cursor` per response, so a batched load that spans N chunks holds N
 * independent cursors. Callers that walk the pages (see `fetchNextJobsPage` in
 * `features/jobs/jobsApi.ts`) need the same partition the first page used, so
 * the chunk boundary has to be a shared, deterministic function of the id list
 * rather than an implementation detail hidden inside the batched fetch.
 */
export function chunkCompanyIds(companyIds: string[]): string[][] {
  return chunk(companyIds, _COMPANIES_PER_REQUEST);
}

/**
 * Transform a flat `/api/jobs` response once and return it two ways: in
 * server order (`jobs`) and grouped per company (`byCompanyId`), sharing the
 * same `Job` object references.
 *
 * Every requested id gets a `byCompanyId` entry, even ones the backend
 * returned zero rows for, so per-company cache seeding in `getAllJobs` stays
 * uniform. Rows for companies that were not requested are ignored.
 */
function transformAndGroup(
  rows: BackendJobListing[],
  companyIds: string[]
): { jobs: Job[]; byCompanyId: Record<string, FetchJobsResult> } {
  const requested = new Set(companyIds);
  const grouped: Record<string, Job[]> = {};
  const jobs: Job[] = [];
  for (const row of rows) {
    if (!requested.has(row.company)) continue;
    const job = transformBackendJob(row, row.company);
    jobs.push(job);
    (grouped[row.company] ??= []).push(job);
  }

  const fetchedAt = new Date().toISOString();
  const byCompanyId: Record<string, FetchJobsResult> = {};
  for (const companyId of companyIds) {
    const companyJobs = grouped[companyId] ?? [];
    byCompanyId[companyId] = {
      jobs: companyJobs,
      metadata: {
        totalCount: companyJobs.length,
        fetchedAt,
      },
    };
  }
  return { jobs, byCompanyId };
}

/**
 * Batched fetch for many backend-scraper companies, chunked to stay under
 * the backend's `?companies=` cap (150) and query-string size limits.
 *
 * Fires chunks in parallel via `Promise.all` and merges the per-company
 * result maps. Each chunk is one `/api/jobs?companies=a,b,c` call — the
 * same shape as the original single-request implementation; chunking is
 * the only difference.
 *
 * Returns one entry per requested company. Companies with no rows in any
 * chunk's response get an empty `FetchJobsResult` so per-company cache
 * seeding in `getAllJobs` stays uniform. `Promise.all` rejects on the first
 * chunk failure — same blast radius as the un-chunked call.
 */
export async function fetchJobsForCompanies(
  companyIds: string[],
  options: FetchJobsForCompaniesOptions = {}
): Promise<Record<string, FetchJobsResult>> {
  if (companyIds.length === 0) {
    return {};
  }

  const chunks = chunkCompanyIds(companyIds);
  logger.debug(
    `[Backend Scraper Client] Batched fetch for ${companyIds.length} companies across ${chunks.length} chunk(s)`
  );

  const chunkResults = await Promise.all(
    chunks.map((chunkIds) => _fetchJobsChunk(chunkIds, options))
  );
  return Object.assign({}, ...chunkResults);
}

async function _fetchJobsChunk(
  companyIds: string[],
  options: FetchJobsForCompaniesOptions
): Promise<Record<string, FetchJobsResult>> {
  const apiBase = options.apiBaseUrl || DEFAULT_BACKEND_JOBS_URL;
  // Default is high enough to cover all backend-scraper companies' OPEN
  // jobs in one round trip — per-company limit (5000) was wrong here because
  // it bounds the batched response across all companies, not per-company.
  const params = new URLSearchParams({
    companies: companyIds.join(','),
    status: 'OPEN',
    limit: (options.limit ?? 50000).toString(),
  });
  const url = `${apiBase}?${params}`;

  let data: BackendJobListing[];
  try {
    const response = await fetch(url, {
      signal: options.signal,
      headers: { Accept: 'application/json' },
    });

    if (!response.ok) {
      const retryable = response.status >= 500 || response.status === 429;
      throw new APIError(
        `Backend Scraper API error: ${response.statusText}`,
        response.status,
        'backend-scraper',
        retryable
      );
    }

    data = await response.json();
  } catch (error) {
    logger.error('[Backend Scraper Client] Batched fetch error:', error);
    if (error instanceof APIError) {
      throw error;
    }
    throw new APIError(
      `Failed to fetch batched jobs: ${(error as Error).message}`,
      undefined,
      'backend-scraper',
      true
    );
  }

  // Group rows by company id and transform. Seeds every requested id, even
  // ones the backend returned zero rows for, so the caller can dispatch a
  // per-company cache update for each.
  return transformAndGroup(data, companyIds).byCompanyId;
}

export interface FetchJobsPageOptions extends FetchJobsForCompaniesOptions {
  /**
   * ISO-8601 timestamp **with a UTC offset** (`Z` or `±HH:MM`). Inclusive lower
   * bound on `first_seen_at`. Naive values are a backend 422, never assumed-UTC.
   */
  since?: string;
  /**
   * Opaque keyset token, verbatim from a previous page's `X-Next-Cursor`.
   * Only meaningful under the same filter set that minted it — change `since`
   * or the company list and the walk must restart without a cursor.
   */
  cursor?: string;
}

/** `X-Next-Cursor`; header names are case-insensitive per `Headers.get`. */
const NEXT_CURSOR_HEADER = 'X-Next-Cursor';

/**
 * One keyset-paginated page of `/api/jobs?companies=…` — the paging sibling of
 * `fetchJobsForCompanies`.
 *
 * Takes **a single chunk** of company ids (use `chunkCompanyIds` to build the
 * partition) because the backend mints exactly one cursor per response: one
 * request ⇔ one cursor. Passing `since` and/or `cursor` puts the backend in
 * keyset mode (`ORDER BY first_seen_at DESC, source_id DESC, id DESC`); passing
 * neither is the legacy path and yields no cursor.
 *
 * `nextCursor` is `null` at the end of the walk — the header's **absence is the
 * only end-of-walk signal**, and it is present iff the page came back full
 * (`rows.length === limit`), so a trailing exactly-full page costs one extra
 * round trip returning `[]`. See the keyset section of `src/backend/CLAUDE.md`.
 */
export async function fetchJobsPage(
  companyIds: string[],
  options: FetchJobsPageOptions = {}
): Promise<JobsPage> {
  if (companyIds.length === 0) {
    return { jobs: [], byCompanyId: {}, nextCursor: null };
  }

  const apiBase = options.apiBaseUrl || DEFAULT_BACKEND_JOBS_URL;
  const params = new URLSearchParams({
    companies: companyIds.join(','),
    // Load-bearing: only `status=OPEN` is served by the partial keyset index
    // `idx_job_listings_open_first_seen_keyset`. Omitting it falls back to a sort.
    status: 'OPEN',
    limit: (options.limit ?? 1000).toString(),
  });
  // Sent on presence, mirroring the Vercel proxy's `!== undefined` forwarding:
  // silently dropping an empty cursor would restart the walk at page 1 instead
  // of surfacing the backend's 422.
  if (options.since !== undefined) params.set('since', options.since);
  if (options.cursor !== undefined) params.set('cursor', options.cursor);
  // NOTE: `offset` is deliberately never sent — it is a 422 in keyset mode.
  const url = `${apiBase}?${params}`;

  let data: BackendJobListing[];
  let nextCursor: string | null;
  try {
    const response = await fetch(url, {
      signal: options.signal,
      headers: { Accept: 'application/json' },
    });

    if (!response.ok) {
      const retryable = response.status >= 500 || response.status === 429;
      throw new APIError(
        `Backend Scraper API error: ${response.statusText}`,
        response.status,
        'backend-scraper',
        retryable
      );
    }

    nextCursor = response.headers?.get(NEXT_CURSOR_HEADER) || null;
    data = await response.json();
  } catch (error) {
    logger.error('[Backend Scraper Client] Keyset page fetch error:', error);
    if (error instanceof APIError) {
      throw error;
    }
    throw new APIError(
      `Failed to fetch jobs page: ${(error as Error).message}`,
      undefined,
      'backend-scraper',
      true
    );
  }

  // `jobs` is the flat, server-ordered view (first_seen_at DESC in keyset
  // mode); `byCompanyId` groups the very same Job objects.
  const { jobs, byCompanyId } = transformAndGroup(data, companyIds);

  logger.debug(
    `[Backend Scraper Client] Keyset page: ${data.length} rows across ${companyIds.length} companies, nextCursor=${nextCursor ? 'present' : 'absent'}`
  );

  return { jobs, byCompanyId, nextCursor };
}
