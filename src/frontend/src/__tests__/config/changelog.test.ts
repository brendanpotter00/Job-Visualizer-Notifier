import { describe, it, expect } from 'vitest';
import {
  CHANGELOG,
  CHANGELOG_TAGS,
  type ChangelogTag,
} from '../../config/changelog';

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
    const sorted = [...CHANGELOG].sort(
      (a, b) => Date.parse(b.date) - Date.parse(a.date)
    );
    for (let i = 1; i < sorted.length; i++) {
      expect(Date.parse(sorted[i - 1].date)).toBeGreaterThanOrEqual(
        Date.parse(sorted[i].date)
      );
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
});
