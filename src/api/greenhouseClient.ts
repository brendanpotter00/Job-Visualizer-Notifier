import type { JobAPIClient, GreenhouseAPIResponse } from './types';
import { APIError } from './types';
import { transformGreenhouseJob } from './transformers/greenhouseTransformer';

/**
 * Greenhouse job board API client
 */
export const greenhouseClient: JobAPIClient = {
  async fetchJobs(config, options = {}) {
    if (config.type !== 'greenhouse') {
      throw new Error('Invalid config type for Greenhouse client');
    }

    const baseUrl = config.apiBaseUrl || '/api/greenhouse';
    const url = `${baseUrl}/v1/boards/${config.boardToken}/jobs?content=true`;
    console.log('[Greenhouse Client] Fetching from URL:', url);

    try {
      const response = await fetch(url, {
        signal: options.signal,
        headers: {
          Accept: 'application/json',
        },
      });

      console.log('[Greenhouse Client] Response status:', response.status);

      if (!response.ok) {
        console.error('[Greenhouse Client] Response not OK:', response.statusText);
        throw new APIError(
          `Greenhouse API error: ${response.statusText}`,
          response.status,
          'greenhouse',
          response.status >= 500 || response.status === 429
        );
      }

      const data: GreenhouseAPIResponse = await response.json();
      console.log('[Greenhouse Client] Received jobs:', data.jobs.length, 'jobs');

      // Transform to internal model
      const jobs = data.jobs.map((job) => transformGreenhouseJob(job, config.boardToken));

      // Apply 'since' filter if provided
      const filteredJobs = options.since
        ? jobs.filter((job) => new Date(job.createdAt) >= new Date(options.since!))
        : jobs;

      // Apply limit if provided
      const limitedJobs = options.limit
        ? filteredJobs.slice(0, options.limit)
        : filteredJobs;

      return {
        jobs: limitedJobs,
        metadata: {
          totalCount: limitedJobs.length,
          softwareCount: limitedJobs.filter((j) => j.classification.isSoftwareAdjacent).length,
          fetchedAt: new Date().toISOString(),
        },
      };
    } catch (error) {
      console.error('[Greenhouse Client] Error:', error);
      if (error instanceof APIError) {
        throw error;
      }
      throw new APIError(
        `Failed to fetch Greenhouse jobs: ${(error as Error).message}`,
        undefined,
        'greenhouse',
        true
      );
    }
  },
};
