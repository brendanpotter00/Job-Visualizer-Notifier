import type { JobAPIClient, FetchJobsOptions, FetchJobsResult, BackendJobListing } from '../types';
import type { ATSCompanyConfig } from './baseClient';
import type { BackendScraperConfig } from '../../types';
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

  const chunks = chunk(companyIds, _COMPANIES_PER_REQUEST);
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

  // Group rows by company id and transform.
  const grouped: Record<string, BackendJobListing[]> = {};
  for (const row of data) {
    const cid = row.company;
    if (!grouped[cid]) grouped[cid] = [];
    grouped[cid].push(row);
  }

  const fetchedAt = new Date().toISOString();
  const result: Record<string, FetchJobsResult> = {};
  // Seed every requested id, even ones the backend returned zero rows for,
  // so the caller can dispatch a per-company cache update for each.
  for (const companyId of companyIds) {
    const rows = grouped[companyId] ?? [];
    const jobs = rows.map((row) => transformBackendJob(row, companyId));
    result[companyId] = {
      jobs,
      metadata: {
        totalCount: jobs.length,
        fetchedAt,
      },
    };
  }
  return result;
}
