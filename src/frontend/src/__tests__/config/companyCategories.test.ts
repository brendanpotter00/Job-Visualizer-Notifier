import { describe, it, expect } from 'vitest';
import { COMPANIES } from '../../config/companies';
import {
  COMPANY_CATEGORIES,
  COMPANY_CATEGORY_SLUGS,
  FALLBACK_COMPANY_CATEGORY_OPTIONS,
  companyCategoryOptions,
  companyIdsInCategories,
  companyIdsInCategory,
} from '../../config/companyCategories';
import type { JobFacets } from '../../types';

/**
 * The company categories come from ONE file the backend also seeds from
 * (`src/backend/api/data/company_categories.json`). The backend checks the
 * same rules against `company_profiles.json`
 * (`api/tests/test_company_categories_data.py`); this side checks them against
 * the roster the SPA renders, `COMPANIES` (not the hand-kept `COMPANY_IDS`
 * enum, which lags it).
 */
const ROSTER_IDS = new Set(COMPANIES.map((company) => company.id));

/** The approved set, in display order. Adding or removing one is a decision, not an edit. */
const APPROVED_SLUGS = [
  'big_tech',
  'ai_labs',
  'ai_startups',
  'yc_alumni',
  'unicorns',
  'breakout_startups',
  'hard_tech',
  'fintech',
  'dev_tools',
  'household_names',
];

const MIN_MEMBERS = 5;

describe('COMPANY_CATEGORIES', () => {
  it('is exactly the approved categories, in display order', () => {
    expect(COMPANY_CATEGORY_SLUGS).toEqual(APPROVED_SLUGS);
  });

  it('has unique, non-empty labels and non-empty definitions', () => {
    const labels = COMPANY_CATEGORIES.map((c) => c.label);
    expect(new Set(labels).size).toBe(labels.length);
    for (const category of COMPANY_CATEGORIES) {
      expect(category.label.trim()).not.toBe('');
      expect(category.definition.trim()).not.toBe('');
    }
  });

  it('puts every tracked company in at least one category', () => {
    const categorized = new Set(COMPANY_CATEGORIES.flatMap((c) => c.companyIds));
    const missing = [...ROSTER_IDS].filter((id) => !categorized.has(id));
    expect(missing).toEqual([]);
  });

  it('references only companies that exist in the roster', () => {
    const unknown = COMPANY_CATEGORIES.flatMap((category) =>
      category.companyIds
        .filter((id) => !ROSTER_IDS.has(id))
        .map((id) => `${category.slug} -> ${id}`)
    );
    expect(unknown).toEqual([]);
  });

  it('never repeats a company inside one category', () => {
    for (const category of COMPANY_CATEGORIES) {
      expect(new Set(category.companyIds).size).toBe(category.companyIds.length);
    }
  });

  it(`holds at least ${MIN_MEMBERS} companies in every category`, () => {
    const thin = COMPANY_CATEGORIES.filter((c) => c.companyIds.length < MIN_MEMBERS).map(
      (c) => `${c.slug} (${c.companyIds.length})`
    );
    expect(thin).toEqual([]);
  });

  it('allows a company in several categories (Google is Big Tech and AI Labs)', () => {
    expect(companyIdsInCategory('big_tech')).toContain('google');
    expect(companyIdsInCategory('ai_labs')).toContain('google');
  });

  it('keeps Big Tech to the giants: 25 or fewer, no subsidiaries', () => {
    const bigTech = companyIdsInCategory('big_tech');
    expect(bigTech.length).toBeLessThanOrEqual(25);
    for (const subsidiary of ['github', 'slack', 'twitch', 'waymo', 'zoox', 'xai']) {
      expect(bigTech).not.toContain(subsidiary);
    }
  });
});

describe('FALLBACK_COMPANY_CATEGORY_OPTIONS', () => {
  it('mirrors the data as facet options', () => {
    expect(FALLBACK_COMPANY_CATEGORY_OPTIONS).toEqual(
      COMPANY_CATEGORIES.map((c, index) => ({
        slug: c.slug,
        label: c.label,
        sortOrder: index,
        parentSlug: null,
      }))
    );
  });
});

describe('companyCategoryOptions', () => {
  const base: JobFacets = { categories: [], levels: [] };
  const served = [{ slug: 'fintech', label: 'Fintech & Trading', sortOrder: 0, parentSlug: null }];

  it('uses the facets list when it is non-empty', () => {
    expect(companyCategoryOptions({ ...base, companyCategories: served })).toEqual(served);
  });

  it('falls back to the bundled list when facets are missing, keyless or empty', () => {
    const fallback = [...FALLBACK_COMPANY_CATEGORY_OPTIONS];
    expect(companyCategoryOptions(undefined)).toEqual(fallback);
    expect(companyCategoryOptions(base)).toEqual(fallback);
    expect(companyCategoryOptions({ ...base, companyCategories: [] })).toEqual(fallback);
  });
});

describe('companyIdsInCategories', () => {
  it('is the union of the selected categories', () => {
    const union = companyIdsInCategories(['big_tech', 'fintech']);
    for (const id of companyIdsInCategory('big_tech')) expect(union.has(id)).toBe(true);
    for (const id of companyIdsInCategory('fintech')) expect(union.has(id)).toBe(true);
    const expected = new Set([
      ...companyIdsInCategory('big_tech'),
      ...companyIdsInCategory('fintech'),
    ]);
    expect(union.size).toBe(expected.size);
  });

  it('is empty for no slugs and for unknown slugs', () => {
    expect(companyIdsInCategories([]).size).toBe(0);
    expect(companyIdsInCategories(['not_a_type']).size).toBe(0);
    expect(companyIdsInCategory('not_a_type')).toEqual([]);
  });
});
