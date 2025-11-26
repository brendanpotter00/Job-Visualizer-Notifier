import type { Job, GreenhouseConfig, LeverConfig, AshbyConfig } from '../types';
import type { JobAPIClient, FetchJobsOptions, FetchJobsResult } from './types';
import { APIError } from './types';
import { logger } from '../utils/logger';

/** Union of all ATS company configuration types */
export type ATSCompanyConfig = GreenhouseConfig | LeverConfig | AshbyConfig;

/**
 * Configuration for creating an API client
 * @template TResponse - The raw API response type
 * @template TConfig - The company configuration type
 */
export interface ClientConfig<TResponse, TConfig extends ATSCompanyConfig> {
  /** Client name for logging (e.g., "Greenhouse") */
  name: string;

  /** Function to build the API URL from config */
  buildUrl: (config: TConfig) => string;

  /** Function to extract job array from raw API response */
  extractJobs: (response: TResponse) => any[];

  /** Function to transform raw job to internal Job model */
  transformer: (job: any, identifier: string) => Job;

  /** Function to get identifier string from config (e.g., boardToken, companyId) */
  getIdentifier: (config: TConfig) => string;

  /** Type guard to validate config type */
  validateConfig: (config: ATSCompanyConfig) => config is TConfig;
}

/**
 * Factory function to create an API client with shared logic.
 *
 * This eliminates 90%+ code duplication across ATS clients by extracting
 * common patterns: fetch, error handling, filtering, metadata calculation.
 *
 * @example
 * ```typescript
 * export const greenhouseClient = createAPIClient({
 *   name: 'Greenhouse',
 *   buildUrl: (config) => `${config.apiBaseUrl}/v1/boards/${config.boardToken}/jobs?content=true`,
 *   extractJobs: (response) => response.jobs,
 *   transformer: transformGreenhouseJob,
 *   getIdentifier: (config) => config.boardToken,
 *   validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
 * });
 * ```
 *
 * @param clientConfig - Configuration for the specific ATS client
 * @returns JobAPIClient implementation
 */
export function createAPIClient<TResponse, TConfig extends ATSCompanyConfig>(
  clientConfig: ClientConfig<TResponse, TConfig>
): JobAPIClient {
  return {
    async fetchJobs(
      config: ATSCompanyConfig,
      options: FetchJobsOptions = {}
    ): Promise<FetchJobsResult> {
      // 1. Validate config type
      if (!clientConfig.validateConfig(config)) {
        throw new Error(`Invalid config type for ${clientConfig.name} client`);
      }

      // 2. Build URL
      const url = clientConfig.buildUrl(config);
      logger.debug(`[${clientConfig.name} Client] Fetching from URL:`, url);

      try {
        // 3. Fetch with signal and headers
        const response = await fetch(url, {
          signal: options.signal,
          headers: {
            Accept: 'application/json',
          },
        });

        logger.debug(`[${clientConfig.name} Client] Response status:`, response.status);

        // 4. Check response status
        if (!response.ok) {
          logger.error(`[${clientConfig.name} Client] Response not OK:`, response.statusText);
          throw new APIError(
            `${clientConfig.name} API error: ${response.statusText}`,
            response.status,
            config.type as 'greenhouse' | 'lever' | 'ashby',
            response.status >= 500 || response.status === 429
          );
        }

        // 5. Parse JSON response
        const data: TResponse = await response.json();

        // 6. Extract jobs array from response
        const rawJobs = clientConfig.extractJobs(data);
        logger.debug(`[${clientConfig.name} Client] Received jobs:`, rawJobs.length, 'jobs');

        // 7. Transform to internal model
        const identifier = clientConfig.getIdentifier(config);
        const jobs = rawJobs.map((job) => clientConfig.transformer(job, identifier));

        // 8. Apply 'since' filter if provided
        const filteredJobs = options.since
          ? jobs.filter((job) => new Date(job.createdAt) >= new Date(options.since!))
          : jobs;

        // 9. Apply limit if provided
        const limitedJobs = options.limit ? filteredJobs.slice(0, options.limit) : filteredJobs;

        // 10. Calculate metadata
        return {
          jobs: limitedJobs,
          metadata: {
            totalCount: limitedJobs.length,
            softwareCount: limitedJobs.filter((j) => j.classification.isSoftwareAdjacent).length,
            fetchedAt: new Date().toISOString(),
          },
        };
      } catch (error) {
        logger.error(`[${clientConfig.name} Client] Error:`, error);

        // Re-throw APIError as-is
        if (error instanceof APIError) {
          throw error;
        }

        // Wrap other errors in APIError
        throw new APIError(
          `Failed to fetch ${clientConfig.name} jobs: ${(error as Error).message}`,
          undefined,
          config.type as 'greenhouse' | 'lever' | 'ashby',
          true // Assume retryable for network/unknown errors
        );
      }
    },
  };
}
