/**
 * Enrichment facet constants.
 *
 * The dropdown OPTIONS are data-driven (GET /api/jobs/facets, seeded from the
 * backend's job_categories / job_subcategories / job_levels dimensions) — these
 * constants carry
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

declare const EXPANSION_EDGE: unique symbol;

/**
 * A facet whose `parentSlug` is an **EXPANSION** edge, branded so it is
 * NOMINALLY distinct from a plain `FacetOption`.
 *
 * ⚠ THE PROJECT HAS TWO INCOMPATIBLE MEANINGS FOR `parentSlug`, AND THEY ARE
 * STRUCTURALLY IDENTICAL:
 *
 * | dimension     | `parentSlug` means | selecting the parent...                |
 * |---------------|--------------------|----------------------------------------|
 * | levels        | EXPANSION          | must ALSO match every child (new_grad ⊂ entry) |
 * | subcategories | GROUPING           | must match NOTHING extra — the parent is a category, the children are specialties within it |
 *
 * `facets.subcategories` is a `FacetOption[]` whose every entry carries
 * `parentSlug: 'software_engineering'`. Handed to the expansion builder it
 * type-checks perfectly and turns one Software Engineering selection into a
 * fifteen-slug OR — silently widening every user's filter. The brand is what
 * stops that from being a plain assignment; reaching for
 * {@link asExpansionFacets} makes it a NAMED, greppable claim instead.
 */
export type ExpansionFacetOption = FacetOption & {
  readonly [EXPANSION_EDGE]: 'expansion';
};

/**
 * Assert that these facets carry EXPANSION edges (see
 * {@link ExpansionFacetOption}). Type-only — nothing to strip at runtime.
 *
 * ⚠ Legitimate for `facets.levels` and `FALLBACK_LEVELS`. NEVER for
 * `facets.subcategories`: those edges group, they do not expand.
 */
export function asExpansionFacets(options: FacetOption[]): ExpansionFacetOption[] {
  return options as ExpansionFacetOption[];
}

/**
 * Derive the expansion map from the live facets (parentSlug edges), so a
 * taxonomy migration that adds a hierarchy level doesn't need a frontend
 * change. Falls back to LEVEL_FILTER_EXPANSION semantics: parent -> itself +
 * all children.
 */
export function buildLevelExpansion(
  levels: ExpansionFacetOption[],
): Record<string, string[]> {
  const expansion: Record<string, string[]> = {};
  for (const level of levels) {
    if (level.parentSlug) {
      (expansion[level.parentSlug] ??= [level.parentSlug]).push(level.slug);
    }
  }
  return Object.keys(expansion).length > 0 ? expansion : LEVEL_FILTER_EXPANSION;
}

/**
 * Fallback category options (mirrors the migration seed) until facets load.
 *
 * ⚠ SIX, NOT SEVEN, AND `sort_order` 3 IS A DELIBERATE GAP. `project_manager`
 * was retired by the `retire_project_manager_category` migration (SCHEMA-11):
 * the dimension row and the `enrichment_category` FK target are both gone, so
 * offering it here would put a dead option in every dropdown that falls back —
 * any `/api/jobs/facets` FETCH FAILURE, which `getFacets`'s additive
 * normalization does not cover (that only handles a MISSING `subcategories`
 * key). Selecting it returns nothing, with no error to explain why.
 *
 * This list is the FIFTH copy of the taxonomy and the only one outside
 * SCHEMA-15's four-way backend check. `enrichmentFallbackParity.test.ts` pins
 * it to `src/backend/taxonomy.json` — do not edit either one alone.
 */
export const FALLBACK_CATEGORIES: FacetOption[] = [
  { slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0 },
  { slug: 'hardware_engineer', label: 'Hardware Engineer', sortOrder: 1 },
  { slug: 'product_manager', label: 'Product Manager', sortOrder: 2 },
  { slug: 'data_scientist', label: 'Data Scientist', sortOrder: 4 },
  { slug: 'growth', label: 'Growth', sortOrder: 5 },
  { slug: 'business_ops', label: 'Business Ops', sortOrder: 6 },
];

/**
 * Fallback level options (mirrors the migration seed) until facets load. Also
 * pinned to `taxonomy.json` by `enrichmentFallbackParity.test.ts`, `parentSlug`
 * included — those edges drive the level-filter expansion below.
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

/**
 * Fallback SWE subcategory options (mirrors SCHEMA-7's migration seed).
 *
 * LABEL-ALPHABETICAL, which for this set is also slug-alphabetical, with
 * `sortOrder` 0..14 and `parentSlug: 'software_engineering'` on every row.
 *
 * BYTE-BOUND. This list must match, exactly, in six places:
 *   1. the backend seed migration's `ADDED_SUBCATEGORIES`
 *   2. `enrichment_writer.SUBCATEGORY_SLUGS`
 *   3. THIS constant
 *   4. the enricher's `taxonomy.SUBCATEGORIES`
 *   5. the enricher's `ollama._SUBCATEGORY_SCHEMA` enum
 *   6. the taxonomy skill's SKILL.md §1b
 * Parity tests on both sides of both repos are what hold that line.
 *
 * NOTE ON ONE LABEL: an early design mock rendered `quantitative` as
 * "Quantitative & Trading". The MOCK is the odd one out and gets corrected; the
 * decision table's "Quantitative & Trading Systems" is authoritative.
 *
 * Used only where the live facets are unavailable. The filter bars deliberately
 * do NOT fall back to this list for the subcategory dimension — they use
 * `facets?.subcategories ?? []`, so an empty catalog renders no chevron rather
 * than a tree that expands into options the server has never heard of.
 */
export const FALLBACK_SUBCATEGORIES: FacetOption[] = [
  { slug: 'ai_engineering', label: 'AI Engineering', sortOrder: 0, parentSlug: 'software_engineering' },
  { slug: 'backend', label: 'Backend', sortOrder: 1, parentSlug: 'software_engineering' },
  { slug: 'data_engineering', label: 'Data Engineering', sortOrder: 2, parentSlug: 'software_engineering' },
  { slug: 'devops_sre', label: 'DevOps & Site Reliability', sortOrder: 3, parentSlug: 'software_engineering' },
  { slug: 'embedded_systems', label: 'Embedded & Low-Level Systems', sortOrder: 4, parentSlug: 'software_engineering' },
  { slug: 'forward_deployed', label: 'Forward Deployed', sortOrder: 5, parentSlug: 'software_engineering' },
  { slug: 'frontend', label: 'Frontend', sortOrder: 6, parentSlug: 'software_engineering' },
  { slug: 'full_stack', label: 'Full Stack', sortOrder: 7, parentSlug: 'software_engineering' },
  { slug: 'infrastructure_platform', label: 'Infrastructure & Platform', sortOrder: 8, parentSlug: 'software_engineering' },
  { slug: 'ml_engineering', label: 'Machine Learning', sortOrder: 9, parentSlug: 'software_engineering' },
  { slug: 'mobile', label: 'Mobile', sortOrder: 10, parentSlug: 'software_engineering' },
  { slug: 'qa_testing', label: 'QA & Testing', sortOrder: 11, parentSlug: 'software_engineering' },
  { slug: 'quantitative', label: 'Quantitative & Trading Systems', sortOrder: 12, parentSlug: 'software_engineering' },
  { slug: 'robotics_autonomy', label: 'Robotics & Autonomy', sortOrder: 13, parentSlug: 'software_engineering' },
  { slug: 'security', label: 'Security', sortOrder: 14, parentSlug: 'software_engineering' },
];

/**
 * Client-side mirror of the backend's `SUBCATEGORY_FILTER_EXPANSION`
 * (src/backend/api/services/enrichment_writer.py): selecting Frontend or Backend
 * also surfaces Full Stack roles. ONE-WAY — selecting Full Stack stays exact.
 *
 * STATIC, unlike `buildLevelExpansion`'s derived map, and deliberately so:
 * `parentSlug` on a SUBCATEGORY is a GROUPING edge (every row's parent is
 * `software_engineering`), not a filter-expansion edge, and `full_stack` has TWO
 * expansion parents which one self-FK column cannot express. Deriving this from
 * `parentSlug` would expand a category selection into fifteen subcategories.
 *
 * SOLE EXPANDER FOR THE CLIENT PATH ONLY. The Recent page filters server-side
 * and sends its selection UNEXPANDED; `services/job_search.py` expands it there.
 * Expanding on both sides would persist `['backend','full_stack']` into the
 * user's saved filters and chips.
 */
export const SUBCATEGORY_FILTER_EXPANSION: Record<string, string[]> = {
  frontend: ['frontend', 'full_stack'],
  backend: ['backend', 'full_stack'],
};

/** Quick slug -> label lookup across every fallback set (chip rendering). */
export const FACET_LABELS: Record<string, string> = Object.fromEntries(
  [...FALLBACK_CATEGORIES, ...FALLBACK_SUBCATEGORIES, ...FALLBACK_LEVELS].map((f) => [
    f.slug,
    f.label,
  ])
);
