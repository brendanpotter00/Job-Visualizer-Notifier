import { describe, it, expect } from 'vitest';
import { COMPANIES } from '../../../config/companies';
import { COMPANY_CATEGORIES } from '../../../pages/AdminLandingPrototypesPage/companyCategories';

/**
 * Authoritative roster for the "no typos" check.
 *
 * `COMPANIES` — not the `COMPANY_IDS` enum — is the source of truth here: the
 * enum is hand-maintained and currently lags the array by ten live companies
 * (the eight quant/prop-trading firms plus Retool and Gem), so validating
 * against it would reject companies that really are tracked. `COMPANIES` is what
 * the app renders from, so it is what a category id must exist in.
 */
const ROSTER_IDS = new Set(COMPANIES.map((company) => company.id));

/** Floor for "this card looks substantial" — see the taxonomy header comment. */
const MIN_MEMBERS = 5;

describe('COMPANY_CATEGORIES', () => {
  it('is a non-empty taxonomy', () => {
    expect(COMPANY_CATEGORIES.length).toBeGreaterThan(0);
  });

  it('references only companies that exist in the real roster', () => {
    const unknown = COMPANY_CATEGORIES.flatMap((category) =>
      category.companyIds
        .filter((companyId) => !ROSTER_IDS.has(companyId))
        .map((companyId) => `${category.id} -> ${companyId}`)
    );
    expect(unknown).toEqual([]);
  });

  it('has unique category ids', () => {
    const ids = COMPANY_CATEGORIES.map((category) => category.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('has unique category labels', () => {
    const labels = COMPANY_CATEGORIES.map((category) => category.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it('gives every category a non-empty blurb', () => {
    for (const category of COMPANY_CATEGORIES) {
      expect(category.blurb.trim().length).toBeGreaterThan(0);
    }
  });

  it('gives every category a non-empty label and id', () => {
    for (const category of COMPANY_CATEGORIES) {
      expect(category.id.trim().length).toBeGreaterThan(0);
      expect(category.label.trim().length).toBeGreaterThan(0);
    }
  });

  it('holds at least the minimum number of members in every category', () => {
    const thin = COMPANY_CATEGORIES.filter(
      (category) => category.companyIds.length < MIN_MEMBERS
    ).map((category) => `${category.id} (${category.companyIds.length})`);
    expect(thin).toEqual([]);
  });

  it('never repeats a company inside a single category', () => {
    for (const category of COMPANY_CATEGORIES) {
      expect(new Set(category.companyIds).size).toBe(category.companyIds.length);
    }
  });

  /**
   * Categories are deliberately NOT mutually exclusive — Stripe is a YC alum, a
   * unicorn, AND fintech. This pins that overlap as intended behavior so nobody
   * "fixes" it into an exclusivity rule later.
   */
  it('allows a company to appear in several categories at once', () => {
    const yc = COMPANY_CATEGORIES.find((category) => category.id === 'yc_alumni');
    const bigTech = COMPANY_CATEGORIES.find((category) => category.id === 'big_tech');
    expect(yc).toBeDefined();
    expect(bigTech).toBeDefined();
    const shared = yc!.companyIds.filter((companyId) => bigTech!.companyIds.includes(companyId));
    expect(shared.length).toBeGreaterThan(0);
  });

  it('keeps the seed categories Brendan asked for', () => {
    const ids = COMPANY_CATEGORIES.map((category) => category.id);
    expect(ids).toEqual(
      expect.arrayContaining([
        'big_tech',
        'ai_labs',
        'yc_alumni',
        'unicorns',
        'breakout_startups',
        'household_names',
      ])
    );
  });
});
