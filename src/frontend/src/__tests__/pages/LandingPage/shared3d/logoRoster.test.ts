import { describe, it, expect } from 'vitest';
import { COMPANIES, getCompanyLogoUrl } from '../../../../config/companies';
import { TOP_COMPANY_IDS } from '../../../../pages/LandingPage/content';
import { selectLogoRoster } from '../../../../pages/LandingPage/prototypes/shared3d/logoRoster';

const SEED = 42;

describe('selectLogoRoster', () => {
  it('is deterministic for a given seed', () => {
    expect(selectLogoRoster(COMPANIES, 72, SEED)).toEqual(selectLogoRoster(COMPANIES, 72, SEED));
  });

  it('different seeds produce a different ordering', () => {
    const a = selectLogoRoster(COMPANIES, 72, 1).map((entry) => entry.companyId);
    const b = selectLogoRoster(COMPANIES, 72, 2).map((entry) => entry.companyId);
    expect(a.join(',')).not.toBe(b.join(','));
  });

  it('respects the requested count', () => {
    expect(selectLogoRoster(COMPANIES, 40, SEED)).toHaveLength(40);
    expect(selectLogoRoster(COMPANIES, 0, SEED)).toHaveLength(0);
  });

  it('clamps to the unique company pool when count exceeds it', () => {
    expect(selectLogoRoster(COMPANIES, 10_000, SEED)).toHaveLength(COMPANIES.length);
  });

  it('never emits a duplicate company', () => {
    const roster = selectLogoRoster(COMPANIES, COMPANIES.length, SEED);
    expect(new Set(roster.map((entry) => entry.companyId)).size).toBe(roster.length);
  });

  it('dedupes duplicated ids in the input', () => {
    const roster = selectLogoRoster([{ id: 'dupe' }, { id: 'dupe' }, { id: 'other' }], 10, SEED);
    expect(roster.map((entry) => entry.companyId).sort()).toEqual(['dupe', 'other']);
  });

  it('prefers TOP_COMPANY_IDS: household names fill the leading slots', () => {
    const presentTop = TOP_COMPANY_IDS.filter((id) =>
      COMPANIES.some((company) => company.id === id)
    );
    expect(presentTop.length).toBeGreaterThan(0);
    const roster = selectLogoRoster(COMPANIES, 72, SEED);
    const leading = roster.slice(0, presentTop.length).map((entry) => entry.companyId);
    expect(new Set(leading)).toEqual(new Set(presentTop));
  });

  it('builds logo urls through getCompanyLogoUrl (committed icon assets)', () => {
    for (const entry of selectLogoRoster(COMPANIES, 40, SEED)) {
      expect(entry.logoUrl).toBe(getCompanyLogoUrl(entry.companyId));
      expect(entry.logoUrl).toMatch(/^\/logos\/icons\/[^/]+\.png$/);
    }
  });
});
