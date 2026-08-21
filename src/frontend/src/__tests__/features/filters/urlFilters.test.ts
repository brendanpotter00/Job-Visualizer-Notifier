import { describe, it, expect } from 'vitest';
import {
  MAX_URL_FACET_VALUES,
  MAX_URL_LOCATIONS,
  buildSearchFromFilters,
  parseFiltersFromSearch,
} from '../../../features/filters/urlFilters';
import { MAX_SEARCH_TAGS } from '../../../constants/tags';
import type { RecentJobsFilters, SearchTag } from '../../../types';

const base: RecentJobsFilters = { timeWindow: 'all', softwareOnly: false };

describe('parseFiltersFromSearch', () => {
  it('returns null when the URL carries none of our params', () => {
    // Not an empty object: "ordinary visit" and "shared link with everything
    // cleared" must behave differently, because only the first should let saved
    // filters hydrate.
    expect(parseFiltersFromSearch('')).toBeNull();
    expect(parseFiltersFromSearch('?utm_source=slack')).toBeNull();
  });

  it('returns an object once any owned param is present, even if it is the only one', () => {
    expect(parseFiltersFromSearch('?time=24h')).toEqual({ timeWindow: '24h' });
  });

  it('reads repeated params as lists', () => {
    expect(parseFiltersFromSearch('?category=software_engineering&category=data_scientist')).toEqual({
      category: ['software_engineering', 'data_scientist'],
    });
  });

  it('drops an unknown time window rather than erroring', () => {
    // A link is often hand-edited or truncated by a chat client. Showing a wider
    // result set beats an error page; a dropped value cannot silently NARROW
    // what the reader sees, which is the direction that would mislead.
    expect(parseFiltersFromSearch('?time=not-a-window&level=entry')).toEqual({ level: ['entry'] });
  });

  it('reads a leading dash as an excluded keyword', () => {
    expect(parseFiltersFromSearch('?tag=backend&tag=-senior')).toEqual({
      searchTags: [
        { text: 'backend', mode: 'include' },
        { text: 'senior', mode: 'exclude' },
      ],
    });
  });

  it.each(['include', 'exclude'] as const)(
    'round-trips a keyword that itself starts with a dash (%s)',
    (mode) => {
      // Silently flipping "-suite" to an exclusion would give the reader fewer
      // results with no indication why — and the EXCLUDE half is the half that
      // was broken: `encodeTag` escapes first and prefixes second, so `-\-suite`
      // came back as the literal text `\-suite`, a keyword that matches nothing.
      // Every job the sender excluded silently reappeared for the recipient and
      // the chip on screen read `\-suite`.
      const searchTags: SearchTag[] = [{ text: '-suite', mode }];
      const parsed = parseFiltersFromSearch(buildSearchFromFilters({ ...base, searchTags }));
      expect(parsed?.searchTags).toEqual(searchTags);
    }
  );

  it('round-trips a lone dash as a keyword in both modes', () => {
    // The degenerate case of the same escape: the text IS the prefix character.
    for (const mode of ['include', 'exclude'] as const) {
      const searchTags: SearchTag[] = [{ text: '-', mode }];
      const parsed = parseFiltersFromSearch(buildSearchFromFilters({ ...base, searchTags }));
      expect(parsed?.searchTags).toEqual(searchTags);
    }
  });

  it('truncates a hand-edited link at the shared keyword budget', () => {
    // The one add-site with no UI control in front of it. Over the cap the
    // endpoint answers a hard 400 to EVERY subsequent search and the reader's
    // only way back is deleting chips one at a time.
    const search = '?' + Array.from({ length: 30 }, (_, i) => `tag=kw${i}`).join('&');
    const parsed = parseFiltersFromSearch(search);
    expect(parsed?.searchTags).toHaveLength(MAX_SEARCH_TAGS);
    expect(parsed?.searchTags?.[0]).toEqual({ text: 'kw0', mode: 'include' });
  });

  it('does not let a malformed tag eat one of the budgeted slots', () => {
    // A dropped value costs no room, so a link mangled by a chat client still
    // arrives with a full set of REAL chips rather than a short one.
    const raws = ['', '-', ...Array.from({ length: MAX_SEARCH_TAGS }, (_, i) => `kw${i}`)];
    const search = '?' + raws.map((t) => `tag=${encodeURIComponent(t)}`).join('&');
    expect(parseFiltersFromSearch(search)?.searchTags).toHaveLength(MAX_SEARCH_TAGS);
  });

  it('truncates category, level and location at the endpoint caps', () => {
    const many = (name: string, n: number) =>
      Array.from({ length: n }, (_, i) => `${name}=v${i}`).join('&');
    const parsed = parseFiltersFromSearch(
      `?${many('category', 30)}&${many('level', 30)}&${many('location', 120)}`
    );
    expect(parsed?.category).toHaveLength(MAX_URL_FACET_VALUES);
    expect(parsed?.level).toHaveLength(MAX_URL_FACET_VALUES);
    expect(parsed?.location).toHaveLength(MAX_URL_LOCATIONS);
  });

  it('treats a link whose owned params ALL fail validation as an ordinary visit', () => {
    // Returning `{}` here was destructive rather than merely useless.
    // `hydrate{Name}Filters` marks the slice hydrated UNCONDITIONALLY, so
    // `?time=garbage` made the real saved-filters hydration a permanent no-op and
    // a signed-in reader silently got site defaults instead of their own set.
    expect(parseFiltersFromSearch('?time=garbage')).toBeNull();
    expect(parseFiltersFromSearch('?tag=&tag=-')).toBeNull();
    expect(parseFiltersFromSearch('?category=&level=')).toBeNull();
  });

  it('still lets a DELIBERATELY cleared link win', () => {
    // "Clear everything" is spellable — `?time=all` survives validation, so the
    // object is non-empty and the URL still beats the reader's saved filters.
    // (A link that clears the window too is `/`, which is what
    // `buildSearchFromFilters` emits for a default set anyway.)
    expect(parseFiltersFromSearch('?time=all')).toEqual({ timeWindow: 'all' });
  });

  it('ignores an empty tag value', () => {
    expect(parseFiltersFromSearch('?tag=&tag=backend')?.searchTags).toEqual([
      { text: 'backend', mode: 'include' },
    ]);
  });
});

describe('buildSearchFromFilters', () => {
  it('emits nothing for an untouched page', () => {
    expect(buildSearchFromFilters(base)).toBe('');
  });

  it('omits the default time window but keeps a chosen one', () => {
    expect(buildSearchFromFilters({ ...base, timeWindow: 'all' })).toBe('');
    expect(buildSearchFromFilters({ ...base, timeWindow: '24h' })).toBe('?time=24h');
  });

  it('never emits company', () => {
    // The enabled-companies roster is the reader's own preference, not a filter
    // set on this page. Putting it in a shared link would change which companies
    // the RECIPIENT follows.
    const search = buildSearchFromFilters({ ...base, company: ['tiktok', 'spacex'] });
    expect(search).toBe('');
    expect(search).not.toContain('tiktok');
  });

  it('preserves query params it does not own', () => {
    const search = buildSearchFromFilters({ ...base, level: ['entry'] }, '?utm_source=slack');
    expect(search).toContain('utm_source=slack');
    expect(search).toContain('level=entry');
  });

  it('replaces its own params rather than appending to them', () => {
    const search = buildSearchFromFilters({ ...base, level: ['mid'] }, '?level=entry&level=senior');
    expect(search).toBe('?level=mid');
  });

  it('round-trips a full filter set', () => {
    const filters: RecentJobsFilters = {
      timeWindow: '7d',
      softwareOnly: false,
      category: ['software_engineering'],
      level: ['entry', 'new_grad'],
      location: ['Austin, TX, US'],
      searchTags: [
        { text: 'backend', mode: 'include' },
        { text: 'senior', mode: 'exclude' },
      ],
    };
    const parsed = parseFiltersFromSearch(buildSearchFromFilters(filters));
    expect(parsed).toEqual({
      timeWindow: '7d',
      category: ['software_engineering'],
      level: ['entry', 'new_grad'],
      location: ['Austin, TX, US'],
      searchTags: filters.searchTags,
    });
  });

  it('round-trips a location containing commas', () => {
    // Repeated params, never a comma join — "Austin, TX, US" is one value.
    const filters = { ...base, location: ['Austin, TX, US', 'Remote (US)'] };
    expect(parseFiltersFromSearch(buildSearchFromFilters(filters))?.location).toEqual([
      'Austin, TX, US',
      'Remote (US)',
    ]);
  });
});
