import { describe, it, expect } from 'vitest';
import {
  matchesCategory,
  matchesLevel,
  filterJobsByFilters,
} from '../../../features/filters/utils/jobFilteringUtils';
import { buildLevelExpansion, LEVEL_FILTER_EXPANSION } from '../../../constants/enrichment';
import graphFiltersReducer, {
  setGraphCategory,
  setGraphLevel,
} from '../../../features/filters/slices/graphFiltersSlice';
import type { GraphFilters, Job, FacetOption } from '../../../types';

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 'j1',
    source: 'backend-scraper',
    company: 'google',
    title: 'Software Engineer',
    createdAt: new Date().toISOString(),
    url: 'https://example.com',
    raw: {},
    ...overrides,
  };
}

const baseFilters: GraphFilters = {
  timeWindow: 'all',
  searchTags: undefined,
  location: undefined,
  department: undefined,
  employmentType: undefined,
  softwareOnly: false,
};

describe('matchesCategory', () => {
  it('matches everything when no category filter is set', () => {
    expect(matchesCategory(makeJob(), undefined)).toBe(true);
    expect(matchesCategory(makeJob({ category: null }), undefined)).toBe(true);
  });

  it('matches only jobs with the selected category', () => {
    expect(matchesCategory(makeJob({ category: 'growth' }), 'growth')).toBe(true);
    expect(matchesCategory(makeJob({ category: 'software_engineering' }), 'growth')).toBe(false);
  });

  it('excludes unenriched jobs while a category filter is active', () => {
    expect(matchesCategory(makeJob({ category: null }), 'growth')).toBe(false);
    expect(matchesCategory(makeJob(), 'growth')).toBe(false);
  });
});

describe('matchesLevel — the new_grad ⊂ entry contract', () => {
  it("selecting 'entry' also surfaces new_grad jobs (expansion)", () => {
    expect(matchesLevel(makeJob({ level: 'entry' }), 'entry')).toBe(true);
    expect(matchesLevel(makeJob({ level: 'new_grad' }), 'entry')).toBe(true);
  });

  it("selecting 'new_grad' stays exact — no upward expansion", () => {
    expect(matchesLevel(makeJob({ level: 'new_grad' }), 'new_grad')).toBe(true);
    expect(matchesLevel(makeJob({ level: 'entry' }), 'new_grad')).toBe(false);
  });

  it('other levels match exactly', () => {
    expect(matchesLevel(makeJob({ level: 'senior' }), 'senior')).toBe(true);
    expect(matchesLevel(makeJob({ level: 'mid' }), 'senior')).toBe(false);
  });

  it('excludes unenriched jobs while a level filter is active', () => {
    expect(matchesLevel(makeJob({ level: null }), 'entry')).toBe(false);
    expect(matchesLevel(makeJob(), 'entry')).toBe(false);
  });
});

describe('filterJobsByFilters with facet filters', () => {
  const jobs = [
    makeJob({ id: 'a', category: 'software_engineering', level: 'new_grad' }),
    makeJob({ id: 'b', category: 'software_engineering', level: 'senior' }),
    makeJob({ id: 'c', category: 'growth', level: 'entry' }),
    makeJob({ id: 'd' }), // unenriched
  ];

  it('level=entry returns entry AND new_grad jobs across categories', () => {
    const out = filterJobsByFilters(jobs, { ...baseFilters, level: 'entry' });
    expect(out.map((j) => j.id).sort()).toEqual(['a', 'c']);
  });

  it('category + level compose with AND', () => {
    const out = filterJobsByFilters(jobs, {
      ...baseFilters,
      category: 'software_engineering',
      level: 'entry',
    });
    expect(out.map((j) => j.id)).toEqual(['a']);
  });

  it('no facet filters -> unenriched jobs still flow through', () => {
    const out = filterJobsByFilters(jobs, baseFilters);
    expect(out).toHaveLength(4);
  });
});

describe('graphFilters slice facet actions', () => {
  it('sets and clears category/level (undefined = All)', () => {
    let state = graphFiltersReducer(undefined, setGraphCategory('growth'));
    expect(state.filters.category).toBe('growth');
    state = graphFiltersReducer(state, setGraphLevel('entry'));
    expect(state.filters.level).toBe('entry');
    state = graphFiltersReducer(state, setGraphCategory(undefined));
    expect(state.filters.category).toBeUndefined();
  });

  it('facet edits mark the slice user-modified (hydration guard)', () => {
    const state = graphFiltersReducer(undefined, setGraphLevel('mid'));
    expect(state.userModified).toBe(true);
  });
});

describe('buildLevelExpansion', () => {
  it('derives parent -> children expansion from facets parentSlug edges', () => {
    const levels: FacetOption[] = [
      { slug: 'new_grad', label: 'New Grad', sortOrder: 0, parentSlug: 'entry' },
      { slug: 'entry', label: 'Entry', sortOrder: 1, parentSlug: null },
      { slug: 'mid', label: 'Mid', sortOrder: 2, parentSlug: null },
    ];
    expect(buildLevelExpansion(levels)).toEqual({ entry: ['entry', 'new_grad'] });
  });

  it('falls back to the static expansion when no edges exist', () => {
    expect(buildLevelExpansion([])).toEqual(LEVEL_FILTER_EXPANSION);
  });
});
