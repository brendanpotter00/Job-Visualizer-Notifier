import { describe, it, expect } from 'vitest';
import {
  buildSearchFromFilters,
  parseFiltersFromSearch,
} from '../../../features/filters/urlFilters';
import type { RecentJobsFilters } from '../../../types';

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

  it('round-trips a keyword that itself starts with a dash', () => {
    // Silently flipping "-suite" to an exclusion would give the reader fewer
    // results with no indication why.
    const filters = { ...base, searchTags: [{ text: '-suite', mode: 'include' as const }] };
    const parsed = parseFiltersFromSearch(buildSearchFromFilters(filters));
    expect(parsed?.searchTags).toEqual([{ text: '-suite', mode: 'include' }]);
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
