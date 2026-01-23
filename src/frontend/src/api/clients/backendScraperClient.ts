import type { JobAPIClient, FetchJobsOptions, FetchJobsResult, BackendJobListing } from '../types';
import type { ATSCompanyConfig } from './baseClient';
import type { BackendScraperConfig } from '../../types';
import { APIError } from '../types';
import { logger } from '../../lib/logger';
import { transformBackendJob } from '../transformers/backendScraperTransformer';

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
    const apiBase = backendConfig.apiBaseUrl || '/api/jobs';
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
