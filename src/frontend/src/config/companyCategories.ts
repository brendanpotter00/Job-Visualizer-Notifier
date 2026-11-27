/**
 * Company categories ("company types"): which kinds of companies we track.
 *
 * ONE SOURCE. The data lives in the backend's
 * `src/backend/api/data/company_categories.json`, and this module imports that
 * same file. The backend seeds its `company_categories` tables from it on boot
 * (facets + the `/api/jobs/search?company_category=` filter); the SPA reads it
 * for the landing cards, the "Just Posted" Big Tech slot, the fallback dropdown
 * options and the demo-mode filter. Moving the file breaks the build, loudly.
 *
 * - Array order is display order (the landing grid, the dropdown).
 * - `companyIds` order is landing logo order, most recognizable first.
 * - A company can be in several categories (Google is Big Tech, AI Labs and
 *   Household Names).
 *
 * The add-company skill (`.claude/skills/add-company/`) owns the rules for
 * putting a new company into categories.
 */
import data from '../../../backend/api/data/company_categories.json';
import type { FacetOption, JobFacets } from '../types';

export interface CompanyCategory {
  /** Stable slug: the URL `company_type` value and the API `company_category` value. */
  slug: string;
  /** Card heading and dropdown label. */
  label: string;
  /** The rule for membership. Read by people adding companies, not shown in the UI. */
  definition: string;
  /** Member company ids, most recognizable first. */
  companyIds: readonly string[];
}

export const COMPANY_CATEGORIES: readonly CompanyCategory[] = data.categories;

export const COMPANY_CATEGORY_SLUGS: readonly string[] = COMPANY_CATEGORIES.map((c) => c.slug);

/**
 * The dropdown options when the backend has none to give: an older backend
 * (Vercel ships ~6 min before Railway), a facets edge cache from before the
 * deploy, or an empty seed. Same data the backend seeds, so nothing differs.
 */
export const FALLBACK_COMPANY_CATEGORY_OPTIONS: readonly FacetOption[] = COMPANY_CATEGORIES.map(
  (category, index) => ({
    slug: category.slug,
    label: category.label,
    sortOrder: index,
    parentSlug: null,
  })
);

/**
 * Options for a Company type control: the backend's list when it sent a
 * non-empty one, else the bundled list. Never empty, so the control never
 * hides and a selected value always has a label.
 */
export function companyCategoryOptions(facets: JobFacets | undefined): FacetOption[] {
  const fromServer = facets?.companyCategories;
  if (fromServer && fromServer.length > 0) return fromServer;
  return [...FALLBACK_COMPANY_CATEGORY_OPTIONS];
}

/** Every company in any of these categories (OR across categories). */
export function companyIdsInCategories(slugs: readonly string[]): Set<string> {
  const wanted = new Set(slugs);
  const ids = new Set<string>();
  for (const category of COMPANY_CATEGORIES) {
    if (!wanted.has(category.slug)) continue;
    for (const id of category.companyIds) ids.add(id);
  }
  return ids;
}

/** One category's members, or `[]` for an unknown slug. */
export function companyIdsInCategory(slug: string): readonly string[] {
  return COMPANY_CATEGORIES.find((category) => category.slug === slug)?.companyIds ?? [];
}
