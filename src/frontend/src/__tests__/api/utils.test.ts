import { describe, it, expect } from 'vitest';
import { getClientForATS } from '../../api/utils';
import { gemClient } from '../../api/clients/gemClient';
import { workdayClient } from '../../api/clients/workdayClient';
import { eightfoldClient } from '../../api/clients/eightfoldClient';

describe('getClientForATS', () => {
  it('returns gemClient for gem ATS type', () => {
    const client = getClientForATS('gem');
    expect(client).toBe(gemClient);
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
