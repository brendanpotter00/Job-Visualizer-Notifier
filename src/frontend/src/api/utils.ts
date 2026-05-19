import type { JobAPIClient } from './types';
import { leverClient } from './clients/leverClient';
import { gemClient } from './clients/gemClient';
import { eightfoldClient } from './clients/eightfoldClient';
import { backendScraperClient } from './clients/backendScraperClient';

/**
 * Get the appropriate API client for a given ATS type
 *
 * @param atsType - The ATS provider type ('lever', 'gem', 'eightfold',
 *   'backend-scraper'). Workday rows are 'backend-scraper' since the
 *   Workday backend migration; they carry `sourceAts: 'workday'` for
 *   the Why-page grouping (see atsGrouping.ts).
 * @returns The corresponding API client
 * @throws Error if ATS type is unknown
 *
 * @example
 * ```typescript
 * const client = getClientForATS('lever');
 * const result = await client.fetchJobs(config, {});
 * ```
 */
export function getClientForATS(atsType: string): JobAPIClient {
  switch (atsType) {
    case 'lever':
      return leverClient;
    case 'gem':
      return gemClient;
    case 'eightfold':
      return eightfoldClient;
    case 'backend-scraper':
      return backendScraperClient;
    default:
      throw new Error(`Unknown ATS type: ${atsType}`);
  }
}
