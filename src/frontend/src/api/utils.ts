import type { JobAPIClient } from './types';
import { backendScraperClient } from './clients/backendScraperClient';

/**
 * Get the appropriate API client for a given ATS type.
 *
 * @param atsType - The ATS provider type. After the Eightfold (#124) and
 *   Workday (#123) backend migrations the only supported value is
 *   `'backend-scraper'`. Greenhouse, Ashby, Lever, Gem, Eightfold, and
 *   Workday companies all flow through the backend `/api/jobs` endpoint
 *   and carry `sourceAts` to resolve their true source (see config/atsSource.ts).
 * @returns The corresponding API client.
 * @throws Error if ATS type is unknown.
 *
 * @example
 * ```typescript
 * const client = getClientForATS('backend-scraper');
 * const result = await client.fetchJobs(config, {});
 * ```
 */
export function getClientForATS(atsType: string): JobAPIClient {
  switch (atsType) {
    case 'backend-scraper':
      return backendScraperClient;
    default:
      throw new Error(`Unknown ATS type: ${atsType}`);
  }
}
