import { describe, it, expect } from 'vitest';
import type { RootState } from '../../../app/store';
import reducer, {
  upsertLocationDescriptors,
  selectLocationCatalog,
} from '../../../features/locations/locationCatalogSlice';
import type { LocationSearchResult } from '../../../features/locations/locationsApi';

const row = (over: Partial<LocationSearchResult>): LocationSearchResult => ({
  id: 1,
  canonicalName: 'X',
  kind: 'city',
  city: null,
  region: null,
  country: null,
  remoteScope: null,
  ...over,
});

describe('locationCatalogSlice', () => {
  it('starts empty', () => {
    expect(reducer(undefined, { type: '@@INIT' })).toEqual({ byName: {} });
  });

  it('upserts descriptors keyed by canonicalName, mapping the structured fields', () => {
    const state = reducer(
      undefined,
      upsertLocationDescriptors([
        row({ id: 59, canonicalName: 'Texas, US', kind: 'region', region: 'TX', country: 'US' }),
        row({ id: 7, canonicalName: 'Japan', kind: 'country', country: 'JP' }),
      ])
    );
    expect(state.byName).toEqual({
      'Texas, US': { kind: 'region', city: null, region: 'TX', country: 'US', remoteScope: null },
      Japan: { kind: 'country', city: null, region: null, country: 'JP', remoteScope: null },
    });
  });

  it('overwrites an existing entry for the same canonicalName (last write wins)', () => {
    let state = reducer(
      undefined,
      upsertLocationDescriptors([row({ canonicalName: 'A', kind: 'city' })])
    );
    state = reducer(
      state,
      upsertLocationDescriptors([row({ canonicalName: 'A', kind: 'region', region: 'CA' })])
    );
    expect(state.byName['A']).toEqual({
      kind: 'region',
      city: null,
      region: 'CA',
      country: null,
      remoteScope: null,
    });
  });

  describe('selectLocationCatalog', () => {
    it('returns the byName map', () => {
      const state = reducer(undefined, upsertLocationDescriptors([row({ canonicalName: 'A' })]));
      const catalog = selectLocationCatalog({ locationCatalog: state } as RootState);
      expect(catalog).toBe(state.byName);
    });

    it('returns a stable empty object when the slice is absent (minimal test stores)', () => {
      // Some selector tests build partial stores without this slice registered.
      const a = selectLocationCatalog({} as RootState);
      const b = selectLocationCatalog({} as RootState);
      expect(a).toEqual({});
      expect(a).toBe(b); // reference-stable so downstream memoization holds
    });
  });
});
