import type { JobAPIClient, AshbyAPIResponse } from './types';
import { APIError } from './types';
import { transformAshbyJob } from './transformers/ashbyTransformer';

/**
 * Ashby job posting API client
 */
export const ashbyClient: JobAPIClient = {
  async fetchJobs(config, options = {}) {
    if (config.type !== 'ashby') {
      throw new Error('Invalid config type for Ashby client');
    }

    const baseUrl = config.apiBaseUrl || '/api/ashby';
    const url = `${baseUrl}/posting-api/job-board/${config.jobBoardName}?includeCompensation=true`;
    console.log('[Ashby Client] Fetching from URL:', url);

    try {
      const response = await fetch(url, {
        signal: options.signal,
        headers: {
          Accept: 'application/json',
        },
      });

      console.log('[Ashby Client] Response status:', response.status);

      if (!response.ok) {
        console.error('[Ashby Client] Response not OK:', response.statusText);
        throw new APIError(
          `Ashby API error: ${response.statusText}`,
          response.status,
          'ashby',
          response.status >= 500 || response.status === 429
        );
      }

      const data: AshbyAPIResponse = await response.json();
      console.log('[Ashby Client] Received jobs:', data.jobs.length, 'jobs');

      // Transform to internal model
      const jobs = data.jobs.map((job) => transformAshbyJob(job, config.jobBoardName));

      // Apply 'since' filter if provided
      const filteredJobs = options.since
        ? jobs.filter((job) => new Date(job.createdAt) >= new Date(options.since!))
        : jobs;

      // Apply limit if provided
      const limitedJobs = options.limit ? filteredJobs.slice(0, options.limit) : filteredJobs;

      return {
        jobs: limitedJobs,
        metadata: {
          totalCount: limitedJobs.length,
          softwareCount: limitedJobs.filter((j) => j.classification.isSoftwareAdjacent).length,
          fetchedAt: new Date().toISOString(),
        },
      };
    } catch (error) {
      console.error('[Ashby Client] Error:', error);
      if (error instanceof APIError) {
        throw error;
      }
      throw new APIError(
        `Failed to fetch Ashby jobs: ${(error as Error).message}`,
        undefined,
        'ashby',
        true
      );
    }
  },
};
