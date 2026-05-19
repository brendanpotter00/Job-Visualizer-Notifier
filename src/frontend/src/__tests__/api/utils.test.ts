import { describe, it, expect } from 'vitest';
import { getClientForATS } from '../../api/utils';
import { leverClient } from '../../api/clients/leverClient';
import { workdayClient } from '../../api/clients/workdayClient';
import { eightfoldClient } from '../../api/clients/eightfoldClient';

describe('getClientForATS', () => {
  it('returns leverClient for lever ATS type', () => {
    const client = getClientForATS('lever');
    expect(client).toBe(leverClient);
  });

  it('returns workdayClient for workday ATS type', () => {
    const client = getClientForATS('workday');
    expect(client).toBe(workdayClient);
  });

  it('returns eightfoldClient for eightfold ATS type', () => {
    const client = getClientForATS('eightfold');
    expect(client).toBe(eightfoldClient);
  });

  it('throws error for unknown ATS type', () => {
    expect(() => getClientForATS('unknown')).toThrow('Unknown ATS type: unknown');
  });

  it('throws error for empty string', () => {
    expect(() => getClientForATS('')).toThrow('Unknown ATS type: ');
  });
});
