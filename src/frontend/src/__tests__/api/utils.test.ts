import { describe, it, expect } from 'vitest';
import { getClientForATS } from '../../api/utils';
import { leverClient } from '../../api/clients/leverClient';
import { gemClient } from '../../api/clients/gemClient';
import { eightfoldClient } from '../../api/clients/eightfoldClient';

describe('getClientForATS', () => {
  it('returns leverClient for lever ATS type', () => {
    const client = getClientForATS('lever');
    expect(client).toBe(leverClient);
  });

  it('returns gemClient for gem ATS type', () => {
    const client = getClientForATS('gem');
    expect(client).toBe(gemClient);
  });

  it('returns eightfoldClient for eightfold ATS type', () => {
    const client = getClientForATS('eightfold');
    expect(client).toBe(eightfoldClient);
  });

  it('throws error for unknown ATS type', () => {
    expect(() => getClientForATS('unknown')).toThrow('Unknown ATS type: unknown');
  });

  it('throws error for the now-removed workday ATS type', () => {
    // Workday rows migrated to backend-scraper in the workday backend
    // migration; the legacy 'workday' string should be a hard error
    // rather than silently falling through to a stale client.
    expect(() => getClientForATS('workday')).toThrow('Unknown ATS type: workday');
  });

  it('throws error for empty string', () => {
    expect(() => getClientForATS('')).toThrow('Unknown ATS type: ');
  });
});
