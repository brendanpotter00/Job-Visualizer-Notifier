/**
 * ⚠ THE FIFTH BOUNDARY — the frontend fallback constants vs `taxonomy.json`.
 *
 * SCHEMA-15's `test_taxonomy_artifact.py` asserts a FOUR-way equality:
 * `taxonomy.json` == the code constants == the migration seeds ==
 * `get_facets()`. All four live in the backend. `FALLBACK_CATEGORIES` /
 * `FALLBACK_LEVELS` are a fifth copy of the same taxonomy, in another language,
 * in another deploy unit — and nothing compared them to anything.
 *
 * That gap is not hypothetical. It is the SAME cross-boundary blind spot that
 * let the original 7-vs-6 category drift live for months: `job_categories` had
 * seven seeded rows, `CATEGORY_SLUGS` had seven, the enricher's taxonomy had
 * six, and every guard in the repo was intra-repo. SCHEMA-11 retires
 * `project_manager` from the DB and from `CATEGORY_SLUGS`; without this test the
 * frontend would keep offering it in every dropdown whose `/api/jobs/facets`
 * fetch failed, and selecting it would return nothing — the dimension row and
 * the FK target are gone.
 *
 * `taxonomy.json` is GENERATED from the migrations (`tools/generate_taxonomy_artifact.py`),
 * so this test is anchored to the database's own truth, not to a second hand-typed list.
 *
 * FE-CT-2 (PR-F) adds `FALLBACK_SUBCATEGORIES`, so the artifact's
 * `subcategories` arm IS asserted here now. That arm is the one that catches a
 * partial taxonomy widening: the backend grew the list from fifteen slugs to
 * seventeen, and a frontend fallback left at fifteen would render a dropdown
 * that silently omits two real specialties on every facets-fetch failure. The
 * in-file `toHaveLength(17)` in `enrichment.test.ts` is deliberately a
 * hand-typed literal; THIS test is the one anchored to the database's own
 * truth.
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect } from 'vitest';
import {
  FALLBACK_CATEGORIES,
  FALLBACK_LEVELS,
  FALLBACK_SUBCATEGORIES,
} from '../../constants/enrichment';
import type { FacetOption } from '../../types';

interface ArtifactFacet {
  slug: string;
  label: string;
  sort_order: number;
  parent_slug: string | null;
}

const ARTIFACT_PATH = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../../../backend/taxonomy.json'
);

const artifact = JSON.parse(readFileSync(ARTIFACT_PATH, 'utf-8')) as {
  categories: ArtifactFacet[];
  levels: ArtifactFacet[];
  subcategories: ArtifactFacet[];
};

/** Compare on slug + label + sortOrder; parentSlug only where the FE models it. */
const fromArtifact = (rows: ArtifactFacet[], withParent: boolean) =>
  rows.map((row) => ({
    slug: row.slug,
    label: row.label,
    sortOrder: row.sort_order,
    ...(withParent ? { parentSlug: row.parent_slug } : {}),
  }));

const fromFrontend = (options: FacetOption[], withParent: boolean) =>
  options.map((option) => ({
    slug: option.slug,
    label: option.label,
    sortOrder: option.sortOrder,
    ...(withParent ? { parentSlug: option.parentSlug ?? null } : {}),
  }));

describe('frontend fallback constants ↔ backend taxonomy.json', () => {
  it('FALLBACK_CATEGORIES matches the artifact exactly (slug, label, sortOrder)', () => {
    expect(fromFrontend(FALLBACK_CATEGORIES, false)).toEqual(
      fromArtifact(artifact.categories, false)
    );
  });

  it('FALLBACK_LEVELS matches the artifact exactly, parentSlug included', () => {
    // `parentSlug` is load-bearing here and not decoration: LEVEL_FILTER_EXPANSION
    // and buildLevelExpansion read those edges, so a drifted parent silently
    // changes which jobs an `entry` filter surfaces.
    expect(fromFrontend(FALLBACK_LEVELS, true)).toEqual(fromArtifact(artifact.levels, true));
  });

  it('⚠ does not offer a RETIRED category — project_manager is gone from the DB', () => {
    // Named explicitly, not just implied by the deep-equal above: this is the
    // one slug whose reappearance is a data bug rather than a cosmetic diff.
    // Its FK target and dimension row were deleted by
    // `retire_project_manager_category`, so a user who picks it gets an empty
    // result set with no error to explain it.
    expect(FALLBACK_CATEGORIES.map((c) => c.slug)).not.toContain('project_manager');
    expect(artifact.categories.map((c) => c.slug)).not.toContain('project_manager');
  });

  it('FALLBACK_SUBCATEGORIES matches the artifact exactly, parentSlug included', () => {
    // `parentSlug` is asserted because FacetTreeMultiSelect renders the tree off
    // it: a subcategory whose parent drifted away from `software_engineering`
    // would vanish from under the only parent that expands.
    expect(fromFrontend(FALLBACK_SUBCATEGORIES, true)).toEqual(
      fromArtifact(artifact.subcategories, true)
    );
  });

  it('⚠ the fallback is not stuck at the PRE-WIDENING fifteen slugs', () => {
    // Named explicitly rather than left to the deep-equal above, because this is
    // the drift the epic actually shipped into: the backend widened the
    // taxonomy to seventeen in a separate PR from the frontend fallback. A
    // count typed out on BOTH sides is what makes a half-applied widening fail
    // loudly instead of quietly dropping two options.
    expect(FALLBACK_SUBCATEGORIES).toHaveLength(17);
    expect(artifact.subcategories).toHaveLength(17);
    expect(FALLBACK_SUBCATEGORIES.map((s) => s.slug)).toEqual(
      expect.arrayContaining(['growth_engineering', 'product_engineering'])
    );
  });

  it('the sort_order GAP at 3 survives — the seed is not renumbered', () => {
    // conftest's `_CATEGORY_SEED` and the migration both leave 3 empty on
    // purpose. If the frontend renumbers to close the gap, the dropdown order
    // still looks right and the parity test above is the only thing that says
    // the two lists have stopped being the same list.
    expect(FALLBACK_CATEGORIES.map((c) => c.sortOrder)).toEqual([0, 1, 2, 4, 5, 6]);
  });
});
