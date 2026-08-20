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

  /**
   * The changelog is a dated public record and is append-only: a published
   * entry is never rewritten, even when a later entry contradicts it. The
   * 2026-07 entry announced the "Category" -> "Job title" rename that the
   * 2026-08 entry reverses; both stay, and the newer one reads as the
   * correction. Editing the older one to match would erase what users were
   * actually told at the time.
   */
  it('keeps the superseded "Job title" entry alongside the entry that corrects it', () => {
    const ids = new Set(CHANGELOG.map((e) => e.id));
    expect(ids.has('default-90d-and-job-title')).toBe(true);
    expect(ids.has('job-category-rename-2026-08')).toBe(true);

    const superseded = CHANGELOG.find((e) => e.id === 'default-90d-and-job-title');
    const correction = CHANGELOG.find((e) => e.id === 'job-category-rename-2026-08');
    expect(Date.parse(correction!.date)).toBeGreaterThan(Date.parse(superseded!.date));
  });
});
