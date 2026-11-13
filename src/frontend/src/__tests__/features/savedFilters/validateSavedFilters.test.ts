import { describe, it, expect } from 'vitest';
import { validateSavedFilters } from '../../../features/savedFilters/savedFiltersApi';

/**
 * The whole risk in the subcategory widening is WIDENING ONE CHECK AND
 * ACCIDENTALLY LOOSENING ITS NEIGHBOURS, so the strict checks on category,
 * level and locations are re-asserted here as a regression guard.
 *
 * Called directly rather than through the endpoint: `fetchBaseQuery` builds a
 * `Request` from a relative URL, which throws in jsdom before the mock is ever
 * consulted, and every rejection case would then pass on the wrong error.
 */

/** A stored row exactly as it exists today: no `subcategory` key at all. */
const LEGACY_PAYLOAD = {
  recentTimeWindow: '90d',
  trendTimeWindow: '30d',
  locations: ['Austin, TX, US'],
  category: ['software_engineering'],
  level: ['senior'],
  recentActiveKeywordListId: 'builtin-swe',
  trendActiveKeywordListId: null,
};

describe('validateSavedFilters — the subcategory widening', () => {
  it('accepts a LEGACY payload with no subcategory key and yields []', () => {
    // Every row stored before this feature looks like this. A strict check here
    // would take down all saved filters for every existing user — time windows,
    // locations, keyword lists — and a merely lenient one would leave the field
    // undefined and throw later in `draftFromServer`'s `[...p.subcategory]`.
    const out = validateSavedFilters(LEGACY_PAYLOAD);

    expect(out.subcategory).toEqual([]);
    // The rest of the payload is untouched.
    expect(out.category).toEqual(['software_engineering']);
    expect(out.level).toEqual(['senior']);
    expect(out.locations).toEqual(['Austin, TX, US']);
    expect(out.recentTimeWindow).toBe('90d');
  });

  it('passes a real subcategory array through unchanged', () => {
    const out = validateSavedFilters({ ...LEGACY_PAYLOAD, subcategory: ['backend'] });
    expect(out.subcategory).toEqual(['backend']);
  });

  it('rejects an EXPLICIT null — only an ABSENT key is tolerated', () => {
    // The tolerance is scoped to "this row predates the feature", which on the
    // wire means the key is missing. An explicit null is a backend that has the
    // column and got it wrong, and the response model (`list[str]`, NOT NULL
    // with a '[]' default) says that cannot happen — so it stays loud.
    expect(() => validateSavedFilters({ ...LEGACY_PAYLOAD, subcategory: null })).toThrow(
      /subcategory must be a string array/
    );
  });

  it('rejects a subcategory that is a bare string', () => {
    expect(() =>
      validateSavedFilters({ ...LEGACY_PAYLOAD, subcategory: 'backend' })
    ).toThrow(/subcategory must be a string array/);
  });

  it('rejects a subcategory array holding a non-string', () => {
    expect(() => validateSavedFilters({ ...LEGACY_PAYLOAD, subcategory: [1] })).toThrow(
      /subcategory must be a string array/
    );
  });

  it.each([
    ['category', { category: 'software_engineering' }, /category must be a string array/],
    ['category (non-string member)', { category: [7] }, /category must be a string array/],
    ['level', { level: 'senior' }, /level must be a string array/],
    ['level (non-string member)', { level: [7] }, /level must be a string array/],
    ['locations', { locations: 'Austin' }, /locations must be a string array/],
    ['locations (non-string member)', { locations: [7] }, /locations must be a string array/],
    ['recentTimeWindow', { recentTimeWindow: 7 }, /recentTimeWindow must be a string/],
  ])('STILL rejects a malformed %s — the neighbours did not loosen', (_l, override, re) => {
    expect(() => validateSavedFilters({ ...LEGACY_PAYLOAD, ...override })).toThrow(re);
  });

  it('still rejects a body that is not an object at all', () => {
    expect(() => validateSavedFilters('nope')).toThrow(/body is not an object/);
  });
});
