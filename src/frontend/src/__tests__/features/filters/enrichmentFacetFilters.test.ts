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

describe('matchesCategory (multi-select)', () => {
  it('matches everything when no category filter is set', () => {
    expect(matchesCategory(makeJob(), undefined)).toBe(true);
    expect(matchesCategory(makeJob(), [])).toBe(true);
    expect(matchesCategory(makeJob({ category: null }), undefined)).toBe(true);
  });

  it('matches only jobs whose category is in the selection (OR logic)', () => {
    expect(matchesCategory(makeJob({ category: 'growth' }), ['growth'])).toBe(true);
    expect(matchesCategory(makeJob({ category: 'software_engineering' }), ['growth'])).toBe(false);
    // OR across multiple selected categories
    expect(
      matchesCategory(makeJob({ category: 'software_engineering' }), [
        'growth',
        'software_engineering',
      ])
    ).toBe(true);
    expect(
      matchesCategory(makeJob({ category: 'hardware_engineer' }), ['growth', 'software_engineering'])
    ).toBe(false);
  });

  it('ALWAYS includes unenriched jobs while a category filter is active', () => {
    // The enrichment pipeline lags days behind; not-yet-tagged jobs must not
    // disappear from a filtered view.
    expect(matchesCategory(makeJob({ category: null }), ['growth'])).toBe(true);
    expect(matchesCategory(makeJob(), ['growth'])).toBe(true);
  });
});

describe('matchesLevel (multi-select) — the new_grad ⊂ entry contract', () => {
  it("selecting 'entry' also surfaces new_grad jobs (expansion)", () => {
    expect(matchesLevel(makeJob({ level: 'entry' }), ['entry'])).toBe(true);
    expect(matchesLevel(makeJob({ level: 'new_grad' }), ['entry'])).toBe(true);
  });

  it("selecting 'new_grad' stays exact — no upward expansion", () => {
    expect(matchesLevel(makeJob({ level: 'new_grad' }), ['new_grad'])).toBe(true);
    expect(matchesLevel(makeJob({ level: 'entry' }), ['new_grad'])).toBe(false);
  });

  it('matches across multiple selected levels (OR + per-level expansion)', () => {
    expect(matchesLevel(makeJob({ level: 'senior' }), ['entry', 'senior'])).toBe(true);
    expect(matchesLevel(makeJob({ level: 'new_grad' }), ['entry', 'senior'])).toBe(true);
    expect(matchesLevel(makeJob({ level: 'mid' }), ['entry', 'senior'])).toBe(false);
  });

  it("'intern' is standalone — its own filter, never surfaced by entry/new_grad", () => {
    expect(matchesLevel(makeJob({ level: 'intern' }), 'intern')).toBe(true);
    // interns must NOT leak into the early-career filters, and vice versa
    expect(matchesLevel(makeJob({ level: 'intern' }), 'entry')).toBe(false);
    expect(matchesLevel(makeJob({ level: 'intern' }), 'new_grad')).toBe(false);
    expect(matchesLevel(makeJob({ level: 'new_grad' }), 'intern')).toBe(false);
    expect(matchesLevel(makeJob({ level: 'entry' }), 'intern')).toBe(false);
  });

  it('other levels match exactly', () => {
    expect(matchesLevel(makeJob({ level: 'senior' }), ['senior'])).toBe(true);
    expect(matchesLevel(makeJob({ level: 'mid' }), ['senior'])).toBe(false);
  });

  it('ALWAYS includes unenriched jobs while a level filter is active', () => {
    expect(matchesLevel(makeJob({ level: null }), ['entry'])).toBe(true);
    expect(matchesLevel(makeJob(), ['entry'])).toBe(true);
  });
});

describe('filterJobsByFilters with facet filters', () => {
  const jobs = [
    makeJob({ id: 'a', category: 'software_engineering', level: 'new_grad' }),
    makeJob({ id: 'b', category: 'software_engineering', level: 'senior' }),
    makeJob({ id: 'c', category: 'growth', level: 'entry' }),
    makeJob({ id: 'd' }), // unenriched
  ];

  it('level=[entry] returns entry AND new_grad jobs, PLUS unenriched jobs', () => {
    const out = filterJobsByFilters(jobs, { ...baseFilters, level: ['entry'] });
    // a (new_grad) + c (entry) match; d (unenriched) is always kept; b (senior) is excluded
    expect(out.map((j) => j.id).sort()).toEqual(['a', 'c', 'd']);
  });

  it('multi-select category returns the union, PLUS unenriched jobs', () => {
    const out = filterJobsByFilters(jobs, {
      ...baseFilters,
      category: ['software_engineering', 'growth'],
    });
    // a, b (SWE) + c (growth) match; d (unenriched) always kept
    expect(out.map((j) => j.id).sort()).toEqual(['a', 'b', 'c', 'd']);
  });

  it('category + level compose with AND (still keeping unenriched jobs)', () => {
    const out = filterJobsByFilters(jobs, {
      ...baseFilters,
      category: ['software_engineering'],
      level: ['entry'],
    });
    // a matches both facets; d is unenriched so it passes both; b/c fail one facet
    expect(out.map((j) => j.id).sort()).toEqual(['a', 'd']);
  });

  it('no facet filters -> unenriched jobs still flow through', () => {
    const out = filterJobsByFilters(jobs, baseFilters);
    expect(out).toHaveLength(4);
  });
});

describe('graphFilters slice facet actions (multi-select)', () => {
  it('sets category/level to slug arrays', () => {
    let state = graphFiltersReducer(undefined, setGraphCategory(['growth']));
    expect(state.filters.category).toEqual(['growth']);
    state = graphFiltersReducer(state, setGraphLevel(['entry', 'senior']));
    expect(state.filters.level).toEqual(['entry', 'senior']);
  });

  it('normalizes an empty selection (and undefined) back to undefined = All', () => {
    let state = graphFiltersReducer(undefined, setGraphCategory(['growth']));
    state = graphFiltersReducer(state, setGraphCategory([]));
    expect(state.filters.category).toBeUndefined();
    state = graphFiltersReducer(state, setGraphLevel(undefined));
    expect(state.filters.level).toBeUndefined();
  });

  it('facet edits mark the slice user-modified (hydration guard)', () => {
    const state = graphFiltersReducer(undefined, setGraphLevel(['mid']));
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

  it('a standalone intern (parentSlug null) adds no expansion edge', () => {
    const levels: FacetOption[] = [
      { slug: 'intern', label: 'Intern', sortOrder: 0, parentSlug: null },
      { slug: 'new_grad', label: 'New Grad', sortOrder: 1, parentSlug: 'entry' },
      { slug: 'entry', label: 'Entry', sortOrder: 2, parentSlug: null },
    ];
    expect(buildLevelExpansion(levels)).toEqual({ entry: ['entry', 'new_grad'] });
  });
});
