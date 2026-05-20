import type { JobAPIClient } from './types';
import { workdayClient } from './clients/workdayClient';
import { eightfoldClient } from './clients/eightfoldClient';
import { backendScraperClient } from './clients/backendScraperClient';

/**
 * Get the appropriate API client for a given ATS type
 *
 * @param atsType - The ATS provider type ('workday', 'eightfold', 'backend-scraper')
 * @returns The corresponding API client
 * @throws Error if ATS type is unknown
 *
 * @example
 * ```typescript
 * const client = getClientForATS('workday');
 * const result = await client.fetchJobs(config, {});
 * ```
 */
export function getClientForATS(atsType: string): JobAPIClient {
  switch (atsType) {
    case 'workday':
      return workdayClient;
    case 'eightfold':
      return eightfoldClient;
    case 'backend-scraper':
      return backendScraperClient;
    default:
      throw new Error(`Unknown ATS type: ${atsType}`);
  }
}
