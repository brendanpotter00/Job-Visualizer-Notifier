import { describe, it, expect } from 'vitest';
import { CHANGELOG, CHANGELOG_TAGS, type ChangelogTag } from '../../config/changelog';
import { ROUTES } from '../../config/routes';

describe('CHANGELOG config', () => {
  it('every entry has at least one tag', () => {
    for (const entry of CHANGELOG) {
      expect(entry.tags.length).toBeGreaterThan(0);
    }
  });

  it('every tag is in the frozen CHANGELOG_TAGS enum', () => {
    const allowed = new Set<ChangelogTag>(CHANGELOG_TAGS);
    for (const entry of CHANGELOG) {
      for (const tag of entry.tags) {
        expect(allowed.has(tag)).toBe(true);
      }
    }
  });

  it('entry ids are unique', () => {
    const ids = CHANGELOG.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('keeps the reveal announcement as its OWN entry', () => {
    // Pinned deliberately. The "Job title" -> "Job category" RENAME is visible
    // the day its code merges; the subcategory TREE is invisible until an admin
    // flips the reveal flag, so one fused entry would have to announce a
    // feature nobody can see yet.
    //
    // The full two-entry pin also asserts `job-category-rename-2026-08`, which
    // is FE-CL-1's entry and ships in the rename PR — a SIBLING branch, not an
    // ancestor of this one. Add that half to this assertion when the two merge,
    // so a future tidy-up cannot fuse them back together and re-introduce the
    // lie.
    const ids = CHANGELOG.map((e) => e.id);
    expect(ids).toContain('swe-subcategories-2026-08');
    expect(ids.filter((id) => id === 'swe-subcategories-2026-08')).toHaveLength(1);
  });

  it('entry dates parse as valid dates', () => {
    for (const entry of CHANGELOG) {
      const parsed = Date.parse(entry.date);
      expect(Number.isNaN(parsed)).toBe(false);
    }
  });

  it('entries can be sorted newest-first by date', () => {
    const sorted = [...CHANGELOG].sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
    for (let i = 1; i < sorted.length; i++) {
      expect(Date.parse(sorted[i - 1].date)).toBeGreaterThanOrEqual(Date.parse(sorted[i].date));
    }
  });

  it('ships with at least the two real seed entries', () => {
    const ids = new Set(CHANGELOG.map((e) => e.id));
    expect(ids.has('accounts')).toBe(true);
    expect(ids.has('saved-company-preferences')).toBe(true);
  });

  it('CHANGELOG_TAGS is exactly ["feature", "improvement", "new-companies"]', () => {
    expect([...CHANGELOG_TAGS]).toEqual(['feature', 'improvement', 'new-companies']);
  });

  it('every changelog link points at a real route', () => {
    const routeValues = new Set<string>(Object.values(ROUTES));
    for (const entry of CHANGELOG) {
      if (entry.link) {
        expect(routeValues.has(entry.link.to)).toBe(true);
      }
    }
  });

  it('the location-normalization entry links to the Location Pipeline page', () => {
    const entry = CHANGELOG.find((e) => e.id === 'location-normalization');
    expect(entry?.link?.to).toBe(ROUTES.LOCATION_PIPELINE);
    expect(entry?.link?.label).toBeTruthy();
  });
});
