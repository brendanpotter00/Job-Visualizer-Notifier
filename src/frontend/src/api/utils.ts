import type { JobAPIClient } from './types';
import { greenhouseClient } from './clients/greenhouseClient';
import { leverClient } from './clients/leverClient';
import { ashbyClient } from './clients/ashbyClient';
import { workdayClient } from './clients/workdayClient';

/**
 * Get the appropriate API client for a given ATS type
 *
 * @param atsType - The ATS provider type ('greenhouse', 'lever', 'ashby', 'workday')
 * @returns The corresponding API client
 * @throws Error if ATS type is unknown
 *
 * @example
 * ```typescript
 * const client = getClientForATS('greenhouse');
 * const result = await client.fetchJobs(config, {});
 * ```
 */
export function getClientForATS(atsType: string): JobAPIClient {
  switch (atsType) {
    case 'greenhouse':
      return greenhouseClient;
    case 'lever':
      return leverClient;
    case 'ashby':
      return ashbyClient;
    case 'workday':
      return workdayClient;
    default:
      throw new Error(`Unknown ATS type: ${atsType}`);
  }
}
