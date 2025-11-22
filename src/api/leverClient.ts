import type { JobAPIClient, LeverJobResponse } from './types';
import { APIError } from './types';
import { transformLeverJob } from './transformers/leverTransformer';

/**
 * Lever postings API client
 */
export const leverClient: JobAPIClient = {
  async fetchJobs(config, options = {}) {
    if (config.type !== 'lever') {
      throw new Error('Invalid config type for Lever client');
    }

    // Lever API endpoint: /api/lever/v0/postings/{company} (proxied)
    const url = `/api/lever/v0/postings/${config.companyId}`;
    console.log('[Lever Client] Fetching from URL:', url);

    try {
      const response = await fetch(url, {
        signal: options.signal,
        headers: {
          Accept: 'application/json',
        },
      });

      console.log('[Lever Client] Response status:', response.status);

      if (!response.ok) {
        console.error('[Lever Client] Response not OK:', response.statusText);
        throw new APIError(
          `Lever API error: ${response.statusText}`,
          response.status,
          'lever',
          response.status >= 500 || response.status === 429
        );
      }

      const data: LeverJobResponse[] = await response.json();
      console.log('[Lever Client] Received jobs:', data.length, 'jobs');

      // Transform to internal model
      const jobs = data.map((job) => transformLeverJob(job, config.companyId));

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
      console.error('[Lever Client] Error:', error);
      if (error instanceof APIError) {
        throw error;
      }
      throw new APIError(
        `Failed to fetch Lever jobs: ${(error as Error).message}`,
        undefined,
        'lever',
        true
      );
    }
  },
};
