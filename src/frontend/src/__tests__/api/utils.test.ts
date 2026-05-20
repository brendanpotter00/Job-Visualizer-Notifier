import { describe, it, expect } from 'vitest';
import { getClientForATS } from '../../api/utils';
import { backendScraperClient } from '../../api/clients/backendScraperClient';

describe('getClientForATS', () => {
  it('returns backendScraperClient for backend-scraper ATS type', () => {
    const client = getClientForATS('backend-scraper');
    expect(client).toBe(backendScraperClient);
  });

  it('throws error for unknown ATS type', () => {
    expect(() => getClientForATS('unknown')).toThrow('Unknown ATS type: unknown');
  });

  it.each(['greenhouse', 'ashby', 'lever', 'gem', 'eightfold', 'workday'])(
    'throws error for the now-removed %s ATS type',
    (ats) => {
      // All six legacy ATSes migrated to backend-scraper in their respective
      // backend migrations; the legacy strings should be hard errors
      // rather than silently falling through to a stale client.
      expect(() => getClientForATS(ats)).toThrow(`Unknown ATS type: ${ats}`);
    }
  );

  it('throws error for empty string', () => {
    expect(() => getClientForATS('')).toThrow('Unknown ATS type: ');
  });
});
