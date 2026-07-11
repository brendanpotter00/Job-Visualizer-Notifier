/**
 * Enrichment facet constants.
 *
 * The dropdown OPTIONS are data-driven (GET /api/jobs/facets, seeded from the
 * backend's job_categories / job_levels dimensions) — these constants carry
 * only what must work before/without that fetch: the client-side level-filter
 * expansion and a fallback option set mirroring the migration seed.
 */
import type { FacetOption } from '../types';

/**
 * Client-side mirror of the backend's `_LEVEL_FILTER_EXPANSION`
 * (src/backend/api/services/database.py): selecting 'entry' must also surface
 * new_grad jobs (new_grad ⊂ entry). Selecting 'new_grad' stays exact. If the
 * hierarchy ever grows, prefer deriving this from the facets endpoint's
 * `parentSlug` (see buildLevelExpansion) — this constant is the cold-start
 * fallback.
 */
export const LEVEL_FILTER_EXPANSION: Record<string, string[]> = {
  entry: ['entry', 'new_grad'],
};

/**
 * Derive the expansion map from the live facets (parentSlug edges), so a
 * taxonomy migration that adds a hierarchy level doesn't need a frontend
 * change. Falls back to LEVEL_FILTER_EXPANSION semantics: parent -> itself +
 * all children.
 */
export function buildLevelExpansion(levels: FacetOption[]): Record<string, string[]> {
  const expansion: Record<string, string[]> = {};
  for (const level of levels) {
    if (level.parentSlug) {
      (expansion[level.parentSlug] ??= [level.parentSlug]).push(level.slug);
    }
  }
  return Object.keys(expansion).length > 0 ? expansion : LEVEL_FILTER_EXPANSION;
}

/** Fallback category options (mirrors the migration seed) until facets load. */
export const FALLBACK_CATEGORIES: FacetOption[] = [
  { slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0 },
  { slug: 'hardware_engineer', label: 'Hardware Engineer', sortOrder: 1 },
  { slug: 'product_manager', label: 'Product Manager', sortOrder: 2 },
  { slug: 'project_manager', label: 'Project Manager', sortOrder: 3 },
  { slug: 'data_scientist', label: 'Data Scientist', sortOrder: 4 },
  { slug: 'growth', label: 'Growth', sortOrder: 5 },
  { slug: 'business_ops', label: 'Business Ops', sortOrder: 6 },
];

/**
 * Fallback level options (mirrors the migration seed) until facets load.
 * `intern` is standalone (parentSlug null) — it sorts first and does NOT expand
 * into any other filter, so LEVEL_FILTER_EXPANSION above is unchanged.
 */
export const FALLBACK_LEVELS: FacetOption[] = [
  { slug: 'intern', label: 'Intern', sortOrder: 0, parentSlug: null },
  { slug: 'new_grad', label: 'New Grad', sortOrder: 1, parentSlug: 'entry' },
  { slug: 'entry', label: 'Entry', sortOrder: 2, parentSlug: null },
  { slug: 'mid', label: 'Mid', sortOrder: 3, parentSlug: null },
  { slug: 'senior', label: 'Senior', sortOrder: 4, parentSlug: null },
  { slug: 'senior_plus', label: 'Staff / Principal', sortOrder: 5, parentSlug: null },
  { slug: 'manager', label: 'Manager', sortOrder: 6, parentSlug: null },
];

/** Quick slug -> label lookup across both fallback sets (chip rendering). */
export const FACET_LABELS: Record<string, string> = Object.fromEntries(
  [...FALLBACK_CATEGORIES, ...FALLBACK_LEVELS].map((f) => [f.slug, f.label])
);
