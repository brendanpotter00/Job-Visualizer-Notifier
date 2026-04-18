import type { JobAPIClient, FetchJobsOptions, FetchJobsResult } from '../types';
import type { ATSCompanyConfig } from './baseClient';
import type { EightfoldConfig } from '../../types';
import type { EightfoldAPIResponse, EightfoldJobPosition } from '../types';
import { APIError } from '../types';
import { logger } from '../../lib/logger';
import { transformEightfoldJob } from '../transformers/eightfoldTransformer';

/**
 * Hard server-side cap on page size — verified empirically 2026-04-18.
 * Requesting num > 10 returns at most 10 positions.
 */
const EIGHTFOLD_MAX_PAGE_SIZE = 10;

/**
 * Safety guard against infinite pagination loops.
 * 200 * 10 = 2000 positions per company — safe headroom for Netflix-sized tenants.
 */
const MAX_ITERATIONS = 200;

/**
 * Eightfold AI ATS client — implements JobAPIClient for Eightfold-hosted career portals.
 *
 * Eightfold's public "apply" API (`/api/apply/v2/jobs`) requires:
 * - GET requests with `domain`, `num`, `start` query params
 * - Pagination: server caps `num` at 10 (so Netflix-size tenants require ~60+ requests)
 * - CORS proxy (response lacks Access-Control-Allow-Origin)
 *
 * Stopping conditions (any one breaks the loop):
 * - `fetchedSoFar >= total` (server-reported count)
 * - `fetchedSoFar >= options.limit`
 * - `data.positions.length === 0` (empty page — defensive)
 * - `data.positions.length < pageSize` (partial page — real-world end-of-data signal)
 */
export const eightfoldClient: JobAPIClient = {
  async fetchJobs(
    config: ATSCompanyConfig,
    options: FetchJobsOptions = {}
  ): Promise<FetchJobsResult> {
    // 1. Validate config type
    if (config.type !== 'eightfold') {
      throw new Error(
        `Invalid config type for Eightfold client. Expected 'eightfold', got '${config.type}'`
      );
    }

    const cfg = config as EightfoldConfig;

    // 2. Construct endpoint
    const apiBase = cfg.apiBaseUrl || '/api/eightfold';
    const endpoint = `${apiBase}/api/apply/v2/jobs`;

    logger.debug('[Eightfold Client] Fetching jobs from:', endpoint);

    // 3. Initialize pagination
    const requestedPageSize = cfg.defaultPageSize ?? EIGHTFOLD_MAX_PAGE_SIZE;
    const pageSize = Math.min(requestedPageSize, EIGHTFOLD_MAX_PAGE_SIZE);
    let offset = 0;
    let total: number | undefined;
    const allPositions: EightfoldJobPosition[] = [];
    let iteration = 0;

    // 4. Pagination loop
    while (iteration < MAX_ITERATIONS) {
      iteration++;

      // Check abort before issuing next request. Don't break-and-return
      // partial results — that would poison the RTK Query cache with a
      // truncated dataset that looks authoritative. Throw instead.
      if (options.signal?.aborted) {
        logger.debug('[Eightfold Client] Aborted by caller before page', iteration);
        throw new DOMException('Eightfold fetch aborted', 'AbortError');
      }

      const url = `${endpoint}?domain=${encodeURIComponent(cfg.domain)}&num=${pageSize}&start=${offset}`;

      logger.debug(`[Eightfold Client] Request (page ${iteration}):`, {
        url,
        offset,
        pageSize,
        fetchedSoFar: allPositions.length,
      });

      // 4.1 Fetch
      let response: Response;
      try {
        response = await fetch(url, {
          signal: options.signal,
          headers: {
            Accept: 'application/json',
            'X-Eightfold-Tenant-Host': cfg.tenantHost,
          },
        });
      } catch (err) {
        // Rethrow AbortError as-is so RTK Query sees a cancellation, not a
        // retryable network failure that could trigger a loop on a dead signal.
        if (err instanceof Error && err.name === 'AbortError') {
          throw err;
        }
        const message = err instanceof Error ? err.message : 'Network request failed';
        logger.error('[Eightfold Client] Network error:', message);
        throw new APIError(
          `Failed to fetch Eightfold jobs: ${message}`,
          undefined,
          'eightfold',
          true // network errors are retryable
        );
      }

      // 4.2 HTTP errors
      if (!response.ok) {
        const message = `HTTP ${response.status}: ${response.statusText}`;
        logger.error('[Eightfold Client] HTTP error:', message);
        const retryable = [500, 502, 503, 504, 429].includes(response.status);
        throw new APIError(
          `Failed to fetch Eightfold jobs: ${message}`,
          response.status,
          'eightfold',
          retryable
        );
      }

      // 4.3 Parse JSON
      let data: EightfoldAPIResponse;
      try {
        data = (await response.json()) as EightfoldAPIResponse;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'JSON parse error';
        logger.error('[Eightfold Client] Failed to parse JSON:', message);
        throw new APIError(
          `Failed to parse Eightfold response: ${message}`,
          undefined,
          'eightfold',
          true
        );
      }

      const positions = Array.isArray(data.positions) ? data.positions : [];

      logger.debug(`[Eightfold Client] Page ${iteration} received:`, {
        jobsInPage: positions.length,
        totalReported: data.count,
      });

      // 4.4 Capture total on first iteration
      if (total === undefined) {
        total = typeof data.count === 'number' ? data.count : Infinity;
        logger.debug(`[Eightfold Client] Total reported by server: ${total}`);
      }

      // 4.5 Aggregate
      allPositions.push(...positions);

      // 4.6 Stopping conditions
      const fetchedSoFar = allPositions.length;
      const requestedLimit = options.limit ?? Infinity;

      const hitTotal = fetchedSoFar >= total;
      const hitLimit = fetchedSoFar >= requestedLimit;
      const emptyPage = positions.length === 0;
      // A partial page is the real-world signal we've reached the end, because
      // Eightfold sometimes under-reports `count`. If fewer than `pageSize` rows
      // come back, there is nothing more to fetch.
      const partialPage = positions.length < pageSize;

      if (hitTotal || hitLimit || emptyPage || partialPage) {
        logger.debug('[Eightfold Client] Pagination complete:', {
          totalFetched: fetchedSoFar,
          totalReported: total,
          requestedLimit,
          reason: hitTotal
            ? 'hitTotal'
            : hitLimit
              ? 'hitLimit'
              : emptyPage
                ? 'emptyPage'
                : 'partialPage',
        });
        break;
      }

      // 4.7 Advance
      offset += pageSize;
    }

    // Hitting MAX_ITERATIONS means Eightfold's `count` over-reported AND no
    // partial page short-circuited us. Returning silently would hand the caller
    // truncated data that looks authoritative — throw instead.
    if (iteration >= MAX_ITERATIONS) {
      logger.error('[Eightfold Client] Max iterations reached', {
        iteration,
        fetched: allPositions.length,
        totalReported: total,
      });
      throw new APIError(
        `Eightfold pagination exceeded ${MAX_ITERATIONS} iterations (fetched ${allPositions.length}, reported ${total})`,
        undefined,
        'eightfold',
        false
      );
    }

    logger.debug(
      `[Eightfold Client] Total positions fetched: ${allPositions.length}`
    );

    // 5. Filter invalid/private positions
    const validPositions = allPositions.filter((p) => {
      if (p.isPrivate) return false;
      if (!p.id && !p.ats_job_id && !p.display_job_id) return false;
      if (!p.name) return false;
      if (!p.canonicalPositionUrl) return false;
      return true;
    });

    if (validPositions.length < allPositions.length) {
      logger.debug(
        `[Eightfold Client] Filtered out ${allPositions.length - validPositions.length} invalid/private positions`
      );
    }

    // 6. Transform (use the explicit companyId from the factory, not a guess
    // from cfg.domain — prevents silent mismatches with Company.id)
    const jobs = validPositions.map((p) => transformEightfoldJob(p, cfg.companyId));

    // 8. Apply `since` filter (client-side)
    const filteredJobs = options.since
      ? jobs.filter((job) => new Date(job.createdAt) >= new Date(options.since!))
      : jobs;
    if (options.since) {
      logger.debug(
        `[Eightfold Client] Filtered by 'since': ${filteredJobs.length}/${jobs.length} jobs`
      );
    }

    // 9. Apply `limit` (client-side)
    const limitedJobs = options.limit
      ? filteredJobs.slice(0, options.limit)
      : filteredJobs;
    if (options.limit && limitedJobs.length < filteredJobs.length) {
      logger.debug(`[Eightfold Client] Applied limit: ${limitedJobs.length} jobs`);
    }

    // 10. Metadata
    const result: FetchJobsResult = {
      jobs: limitedJobs,
      metadata: {
        totalCount: limitedJobs.length,
        fetchedAt: new Date().toISOString(),
      },
    };

    logger.debug('[Eightfold Client] Fetch complete:', result.metadata);

    return result;
  },
};
