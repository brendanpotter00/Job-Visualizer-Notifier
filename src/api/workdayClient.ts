import type { JobAPIClient, FetchJobsOptions, FetchJobsResult } from './types';
import type { ATSCompanyConfig } from './baseClient';
import type { WorkdayConfig } from '../types';
import type { WorkdayJobsResponse, WorkdayJobPosting } from './types';
import { APIError } from './types';
import { logger } from '../utils/logger';
import { transformWorkdayJob } from './transformers/workdayTransformer';

/**
 * Workday ATS client - implements JobAPIClient for Workday career sites
 *
 * Unlike Greenhouse/Lever/Ashby, Workday requires:
 * - POST requests (not GET)
 * - Pagination via limit/offset in request body
 * - Relative date parsing (WARNING: insufficient for historical trends)
 *
 * This client implements the same patterns as createAPIClient but handles
 * the POST + pagination requirements manually.
 */
export const workdayClient: JobAPIClient = {
  async fetchJobs(
    config: ATSCompanyConfig,
    options: FetchJobsOptions = {}
  ): Promise<FetchJobsResult> {
    // 1. Validate config type
    if (config.type !== 'workday') {
      throw new Error(
        `Invalid config type for Workday client. Expected 'workday', got '${config.type}'`
      );
    }

    const workdayConfig = config as WorkdayConfig;

    // 2. Construct jobs API URL
    // Use proxy since Workday does NOT support CORS
    const apiBase = workdayConfig.apiBaseUrl || '/api/workday';
    const baseUrl = workdayConfig.baseUrl.replace(/\/+$/, ''); // Remove trailing slashes (for URL generation)
    const jobsUrl = `${apiBase}/wday/cxs/${workdayConfig.tenantSlug}/${workdayConfig.careerSiteSlug}/jobs`;

    logger.debug('[Workday Client] Fetching jobs from:', jobsUrl);

    // 3. Initialize pagination
    // IMPORTANT: Workday API has a maximum page size of 20
    const pageSize = workdayConfig.defaultPageSize ?? 20;
    let offset = 0;
    let total: number | undefined;
    const allPostings: WorkdayJobPosting[] = [];
    const maxIterations = 100; // Safety guard against infinite loops
    let iteration = 0;

    // 4. Pagination loop - fetch all pages
    while (iteration < maxIterations) {
      iteration++;

      // 4.1 Build request body
      const requestBody = {
        appliedFacets: workdayConfig.defaultFacets || {}, // Use config or empty object for job-agnostic fetching
        limit: pageSize,
        offset,
        searchText: '', // Empty for fetching all jobs
      };

      logger.debug(`[Workday Client] Request (page ${iteration}):`, {
        offset,
        limit: pageSize,
        fetchedSoFar: allPostings.length,
      });

      // 4.2 Perform fetch
      let response: Response;
      try {
        response = await fetch(jobsUrl, {
          method: 'POST',
          signal: options.signal,
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        });
      } catch (err) {
        // Network error - retryable
        const message = err instanceof Error ? err.message : 'Network request failed';
        logger.error('[Workday Client] Network error:', message);
        throw new APIError(
          `Failed to fetch Workday jobs: ${message}`,
          undefined,
          'workday',
          true // retryable
        );
      }

      // 4.3 Handle HTTP errors
      if (!response.ok) {
        const message = `HTTP ${response.status}: ${response.statusText}`;
        logger.error('[Workday Client] HTTP error:', message);

        // Determine if error is retryable
        const retryableStatuses = [500, 503, 429];
        const retryable = retryableStatuses.includes(response.status);

        throw new APIError(
          `Failed to fetch Workday jobs: ${message}`,
          response.status,
          'workday',
          retryable
        );
      }

      // 4.4 Parse JSON response
      let data: WorkdayJobsResponse;
      try {
        data = (await response.json()) as WorkdayJobsResponse;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'JSON parse error';
        logger.error('[Workday Client] Failed to parse JSON:', message);
        throw new APIError(
          `Failed to parse Workday response: ${message}`,
          undefined,
          'workday',
          true // retryable - might be temporary server issue
        );
      }

      logger.debug(`[Workday Client] Page ${iteration} received:`, {
        jobsInPage: data.jobPostings.length,
        totalAvailable: data.total,
      });

      // 4.5 Store total on first iteration
      if (total === undefined) {
        total = data.total;
        logger.debug(`[Workday Client] Total jobs available: ${total}`);
      }

      // 4.6 Aggregate job postings
      allPostings.push(...data.jobPostings);

      // 4.7 Check stopping conditions
      const fetchedSoFar = allPostings.length;
      const requestedLimit = options.limit ?? Infinity;

      // Stop if:
      // - We've fetched all available jobs (fetchedSoFar >= total)
      // - We've satisfied the requested limit
      // - Current page returned no jobs (edge case)
      if (
        fetchedSoFar >= total ||
        fetchedSoFar >= requestedLimit ||
        data.jobPostings.length === 0
      ) {
        logger.debug('[Workday Client] Pagination complete:', {
          totalFetched: fetchedSoFar,
          totalAvailable: total,
          requestedLimit,
        });
        break;
      }

      // 4.8 Advance to next page
      offset += pageSize;
    }

    if (iteration >= maxIterations) {
      logger.error('[Workday Client] Max iterations reached - possible infinite loop');
    }

    logger.debug(`[Workday Client] Total postings fetched: ${allPostings.length}`);

    // 5. Transform postings into Job objects
    const identifier = `${workdayConfig.tenantSlug}/${workdayConfig.careerSiteSlug}`;

    // Use jobsUrl from config for proper job detail URLs
    // Fallback to baseUrl for backwards compatibility
    const jobDetailBaseUrl = workdayConfig.jobsUrl || baseUrl;

    const jobs = allPostings.map((posting) =>
      transformWorkdayJob(posting, identifier, jobDetailBaseUrl)
    );

    // 6. Apply 'since' filter if provided (client-side filtering)
    let filteredJobs = jobs;
    if (options.since) {
      const sinceDate = new Date(options.since);
      filteredJobs = jobs.filter((job) => {
        const jobDate = new Date(job.createdAt);
        return jobDate >= sinceDate;
      });
      logger.debug(
        `[Workday Client] Filtered by 'since': ${filteredJobs.length}/${jobs.length} jobs`
      );
    }

    // 7. Apply 'limit' if provided (client-side limiting)
    if (options.limit !== undefined && filteredJobs.length > options.limit) {
      filteredJobs = filteredJobs.slice(0, options.limit);
      logger.debug(`[Workday Client] Applied limit: ${filteredJobs.length} jobs`);
    }

    // 8. Calculate metadata
    const softwareCount = filteredJobs.filter(
      (job) => job.classification.isSoftwareAdjacent
    ).length;

    const result: FetchJobsResult = {
      jobs: filteredJobs,
      metadata: {
        totalCount: filteredJobs.length,
        softwareCount,
        fetchedAt: new Date().toISOString(),
      },
    };

    logger.debug('[Workday Client] Fetch complete:', result.metadata);

    return result;
  },
};
