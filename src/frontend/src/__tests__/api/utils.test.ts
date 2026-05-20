import { describe, it, expect } from 'vitest';
import { getClientForATS } from '../../api/utils';
import { workdayClient } from '../../api/clients/workdayClient';

describe('getClientForATS', () => {
  it('returns workdayClient for workday ATS type', () => {
    const client = getClientForATS('workday');
    expect(client).toBe(workdayClient);
  });

  it('throws error for unknown ATS type', () => {
    expect(() => getClientForATS('unknown')).toThrow('Unknown ATS type: unknown');
  });

  it('throws error for empty string', () => {
    expect(() => getClientForATS('')).toThrow('Unknown ATS type: ');
  });

  it('throws error for legacy "eightfold" ATS type (now backend-scraper)', () => {
    // Eightfold moved to backend cron+queue; Netflix is now backend-scraper
    // with sourceAts='eightfold'. Any caller still passing 'eightfold' is a
    // stale code path and should fail loudly.
    expect(() => getClientForATS('eightfold')).toThrow('Unknown ATS type: eightfold');
  });
});
