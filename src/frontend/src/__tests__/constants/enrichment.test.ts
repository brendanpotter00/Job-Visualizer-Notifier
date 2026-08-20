import { describe, it, expect } from 'vitest';
import { loadSubcategoryOracle } from '../subcategoryOracle';
import {
  FACET_LABELS,
  FALLBACK_CATEGORIES,
  FALLBACK_LEVELS,
  FALLBACK_SUBCATEGORIES,
  SUBCATEGORY_FILTER_EXPANSION,
} from '../../constants/enrichment';

/**
 * The subcategory taxonomy exists byte-identically in six places across two
 * repos. These assertions are this repo's half of holding that line, plus one
 * cross-language pin against the committed oracle fixture the backend authors.
 */

/** Label-alphabetical, which for this set is also slug-alphabetical. */
const CANONICAL_SLUGS = [
  'ai_engineering',
  'backend',
  'data_engineering',
  'devops_sre',
  'embedded_systems',
  'forward_deployed',
  'frontend',
  'full_stack',
  'infrastructure_platform',
  'ml_engineering',
  'mobile',
  'qa_testing',
  'quantitative',
  'robotics_autonomy',
  'security',
];

describe('FALLBACK_SUBCATEGORIES', () => {
  it('has exactly fifteen entries', () => {
    expect(FALLBACK_SUBCATEGORIES).toHaveLength(15);
  });

  it('matches the canonical slug list IN ORDER', () => {
    // Ordered equality, not set equality: it freezes the enum against a typo,
    // a re-order, and a silent drop all at once.
    expect(FALLBACK_SUBCATEGORIES.map((o) => o.slug)).toEqual(CANONICAL_SLUGS);
  });

  it('hangs every entry off software_engineering', () => {
    expect(FALLBACK_SUBCATEGORIES.every((o) => o.parentSlug === 'software_engineering')).toBe(
      true
    );
  });

  it('carries sortOrder 0..14 with no gaps', () => {
    expect(FALLBACK_SUBCATEGORIES.map((o) => o.sortOrder)).toEqual(
      Array.from({ length: 15 }, (_, i) => i)
    );
  });

  it('is in ascending label order', () => {
    // Verified true for this set: Fo < Fr < Fu, Da < De, Ma < Mo, qa < qu.
    const labels = FALLBACK_SUBCATEGORIES.map((o) => o.label);
    const sorted = [...labels].sort((a, b) => a.localeCompare(b));
    expect(labels).toEqual(sorted);
  });

  it('labels quantitative "Quantitative & Trading Systems"', () => {
    // The design mock says "Quantitative & Trading". The MOCK is the odd one
    // out; the decision table is authoritative.
    const quant = FALLBACK_SUBCATEGORIES.find((o) => o.slug === 'quantitative');
    expect(quant?.label).toBe('Quantitative & Trading Systems');
  });

  it('COLLIDES WITH NOTHING in the category or level namespaces', () => {
    // THE INVARIANT FacetTreeMultiSelect's partition depends on. It splits the
    // merged selection by membership in the child slug set, so a subcategory
    // slug equal to a category slug would route selections to the WRONG field,
    // silently, with no error anywhere. This has to stay a test, not a comment.
    const categorySlugs = new Set(FALLBACK_CATEGORIES.map((o) => o.slug));
    const levelSlugs = new Set(FALLBACK_LEVELS.map((o) => o.slug));

    const collisions = FALLBACK_SUBCATEGORIES.map((o) => o.slug).filter(
      (slug) => categorySlugs.has(slug) || levelSlugs.has(slug)
    );
    expect(collisions).toEqual([]);
  });
});

describe('FALLBACK_CATEGORIES', () => {
  it('has exactly six entries with contiguous sortOrder', () => {
    // SIX, not seven: `project_manager` was retired by SCHEMA-11 as live drift
    // used by zero listings.
    expect(FALLBACK_CATEGORIES).toHaveLength(6);
    expect(FALLBACK_CATEGORIES.map((o) => o.sortOrder)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it('no longer offers project_manager', () => {
    expect(FALLBACK_CATEGORIES.map((o) => o.slug)).not.toContain('project_manager');
  });
});

describe('FACET_LABELS', () => {
  it('resolves every subcategory slug to its label', () => {
    for (const option of FALLBACK_SUBCATEGORIES) {
      expect(FACET_LABELS[option.slug]).toBe(option.label);
    }
  });

  it('resolves the two slugs whose label is not a de-underscored slug', () => {
    // These are exactly the cases where `slug.split('_').join(' ')` — the chip
    // fallback — would produce the wrong string, so they are what proves the
    // fold is being consulted at all.
    expect(FACET_LABELS['ai_engineering']).toBe('AI Engineering');
    expect(FACET_LABELS['ml_engineering']).toBe('Machine Learning');
  });

  it('still resolves category and level slugs', () => {
    expect(FACET_LABELS['software_engineering']).toBe('Software Engineering');
    expect(FACET_LABELS['senior_plus']).toBe('Staff / Principal');
  });
});

describe('SUBCATEGORY_FILTER_EXPANSION', () => {
  it('widens frontend and backend into full_stack, one-way', () => {
    expect(SUBCATEGORY_FILTER_EXPANSION).toEqual({
      frontend: ['frontend', 'full_stack'],
      backend: ['backend', 'full_stack'],
    });
    expect(SUBCATEGORY_FILTER_EXPANSION['full_stack']).toBeUndefined();
  });

  it('deep-equals the expansion map declared in the BACKEND oracle fixture', () => {
    // THE CROSS-LANGUAGE PIN. One committed file, read by the pytest half of the
    // oracle and by this test, so "the two languages agree" is a mechanical
    // fact rather than two lists someone kept in sync by hand.
    //
    // Resolved by walking UP from the runner's cwd to the first directory that
    // contains `src/backend`, rather than off `import.meta.url`: vitest runs in
    // the jsdom environment, where `import.meta.url` is an http: URL and
    // `fileURLToPath` throws. Walking up is cwd-independent in the way that
    // actually matters — it works from the repo root and from `src/frontend`.
    const oracle = loadSubcategoryOracle();

    expect(SUBCATEGORY_FILTER_EXPANSION).toEqual(oracle.expansion);
  });
});
