import { describe, it, expect } from 'vitest';
import { getClientForATS } from '../../api/utils';
import { greenhouseClient } from '../../api/greenhouseClient';
import { leverClient } from '../../api/leverClient';
import { ashbyClient } from '../../api/ashbyClient';
import { workdayClient } from '../../api/workdayClient';

describe('getClientForATS', () => {
  it('returns greenhouseClient for greenhouse ATS type', () => {
    const client = getClientForATS('greenhouse');
    expect(client).toBe(greenhouseClient);
  });

  it('returns leverClient for lever ATS type', () => {
    const client = getClientForATS('lever');
    expect(client).toBe(leverClient);
  });

  it('returns ashbyClient for ashby ATS type', () => {
    const client = getClientForATS('ashby');
    expect(client).toBe(ashbyClient);
  });

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
});
