import { describe, it, expect } from 'vitest';
import { validateLocationSearchResults } from '../../../features/locations/locationsApi';

describe('validateLocationSearchResults', () => {
  it('accepts a well-formed response including structured fields', () => {
    const res = [
      {
        id: 59,
        canonicalName: 'Texas, US',
        kind: 'region',
        city: null,
        region: 'TX',
        country: 'US',
        remoteScope: null,
      },
      {
        id: 1,
        canonicalName: 'Remote (US)',
        kind: 'remote',
        city: null,
        region: null,
        country: 'US',
        remoteScope: 'us',
      },
    ];
    expect(validateLocationSearchResults(res)).toBe(res);
  });

  it('throws when the body is not an array', () => {
    expect(() => validateLocationSearchResults({ oops: true })).toThrow(/not an array/);
  });

  it('throws on a bad row shape (id not a number)', () => {
    expect(() =>
      validateLocationSearchResults([
        {
          id: 'x',
          canonicalName: 'A',
          kind: 'city',
          city: null,
          region: null,
          country: null,
          remoteScope: null,
        },
      ])
    ).toThrow(/bad row shape/);
  });

  it('throws when a structured field is the wrong type (region is a number)', () => {
    expect(() =>
      validateLocationSearchResults([
        {
          id: 1,
          canonicalName: 'A',
          kind: 'city',
          city: null,
          region: 5,
          country: null,
          remoteScope: null,
        },
      ])
    ).toThrow(/bad row shape/);
  });
});
