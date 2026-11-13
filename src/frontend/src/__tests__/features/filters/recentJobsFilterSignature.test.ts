import { describe, it, expect } from 'vitest';
import { selectRecentJobsFilterSignature } from '../../../features/filters/selectors/recentJobsFilterSignature';
import type { RecentJobsFilters } from '../../../types';
import type { RootState } from '../../../app/store';

const BASE_FILTERS: RecentJobsFilters = {
  timeWindow: '90d',
  searchTags: undefined,
  location: undefined,
  employmentType: undefined,
  softwareOnly: false,
  company: undefined,
  category: undefined,
  level: undefined,
  subcategory: undefined,
};

function makeState(
  filters: Partial<RecentJobsFilters> = {},
  enabledCompanyIds: string[] | null = null,
  demoModeEnabled = false
): RootState {
  return {
    recentJobsFilters: { filters: { ...BASE_FILTERS, ...filters } },
    enabledCompanies: { ids: enabledCompanyIds },
    ui: { demoModeEnabled },
  } as unknown as RootState;
}

/** Fresh state objects each call, so memoization can never mask a difference. */
function signatureOf(
  filters: Partial<RecentJobsFilters> = {},
  enabledCompanyIds: string[] | null = null,
  demoModeEnabled = false
) {
  return selectRecentJobsFilterSignature(
    makeState(filters, enabledCompanyIds, demoModeEnabled)
  );
}

describe('selectRecentJobsFilterSignature', () => {
  it('is stable for identical filters', () => {
    expect(signatureOf({ location: ['Seattle'] })).toBe(signatureOf({ location: ['Seattle'] }));
  });

  it.each([
    ['time window', { timeWindow: '180d' as const }],
    ['location', { location: ['Austin'] }],
    ['employment type', { employmentType: 'Contract' }],
    ['software-only toggle', { softwareOnly: true }],
    ['company', { company: ['netflix'] }],
    ['category', { category: ['backend'] }],
    ['level', { level: ['senior'] }],
    ['subcategory', { subcategory: ['backend'] }],
    ['search tags', { searchTags: [{ text: 'rust', mode: 'include' as const }] }],
  ])('changes when the %s filter changes', (_label, override) => {
    expect(signatureOf(override)).not.toBe(signatureOf());
  });

  it('changes when admin demo mode is toggled', () => {
    // Demo mode swaps the entire dataset for the curated DEMO_JOBS, which is as
    // total a result-set change as any filter.
    expect(signatureOf({}, null, true)).not.toBe(signatureOf({}, null, false));
  });

  it('changes when the enabled-companies set changes', () => {
    expect(signatureOf({}, ['a', 'b'])).not.toBe(signatureOf({}, ['a']));
  });

  it('distinguishes "no enabled-companies preference" from an empty set', () => {
    expect(signatureOf({}, null)).not.toBe(signatureOf({}, []));
  });

  it('ignores the ORDER of a subcategory selection', () => {
    expect(signatureOf({ subcategory: ['backend', 'frontend'] })).toBe(
      signatureOf({ subcategory: ['frontend', 'backend'] })
    );
  });

  it('distinguishes a category-only selection from category + subcategory', () => {
    // The narrowing case, and the one that actually breaks in production: the
    // user already has Software Engineering ticked and then ticks Backend under
    // it. If the signature ignores `subcategory`, that second tick changes
    // nothing, no request goes out, and the list silently stays as it was.
    expect(signatureOf({ category: ['software_engineering'] })).not.toBe(
      signatureOf({ category: ['software_engineering'], subcategory: ['backend'] })
    );
  });

  it('ignores the ORDER of multi-select values', () => {
    expect(signatureOf({ location: ['Austin', 'Seattle'] })).toBe(
      signatureOf({ location: ['Seattle', 'Austin'] })
    );
    expect(signatureOf({}, ['b', 'a'])).toBe(signatureOf({}, ['a', 'b']));
  });

  it('ignores the ORDER of search tags but not their mode', () => {
    const include = { text: 'rust', mode: 'include' as const };
    const exclude = { text: 'sales', mode: 'exclude' as const };

    expect(signatureOf({ searchTags: [include, exclude] })).toBe(
      signatureOf({ searchTags: [exclude, include] })
    );
    expect(signatureOf({ searchTags: [include] })).not.toBe(
      signatureOf({ searchTags: [{ text: 'rust', mode: 'exclude' }] })
    );
  });

  it('treats an undefined multi-select the same as an empty one', () => {
    // Both mean "no constraint", so neither should reset the client window.
    expect(signatureOf({ location: undefined })).toBe(signatureOf({ location: [] }));
  });
});
