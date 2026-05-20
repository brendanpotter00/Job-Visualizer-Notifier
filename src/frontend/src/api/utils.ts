import type { JobAPIClient } from './types';
import { eightfoldClient } from './clients/eightfoldClient';
import { backendScraperClient } from './clients/backendScraperClient';

/**
 * Get the appropriate API client for a given ATS type
 *
 * @param atsType - The ATS provider type ('eightfold' or 'backend-scraper').
 *   Greenhouse, Ashby, Lever, Gem, and Workday rows are 'backend-scraper'
 *   since their respective backend migrations; they carry
 *   `sourceAts: 'greenhouse' | 'ashby' | 'lever' | 'gem' | 'workday'` for the
 *   Why-page grouping (see atsGrouping.ts).
 * @returns The corresponding API client
 * @throws Error if ATS type is unknown
 *
 * @example
 * ```typescript
 * const client = getClientForATS('eightfold');
 * const result = await client.fetchJobs(config, {});
 * ```
 */
export function getClientForATS(atsType: string): JobAPIClient {
  switch (atsType) {
    case 'eightfold':
      return eightfoldClient;
    case 'backend-scraper':
      return backendScraperClient;
    default:
      throw new Error(`Unknown ATS type: ${atsType}`);
  }
}
