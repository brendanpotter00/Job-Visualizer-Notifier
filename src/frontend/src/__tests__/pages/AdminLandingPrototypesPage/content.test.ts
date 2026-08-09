import { describe, it, expect } from 'vitest';
import { LANDING_CONTENT, TOP_COMPANY_IDS } from '../../../pages/AdminLandingPrototypesPage/content';
import { ROUTES } from '../../../config/routes';
import { COMPANIES } from '../../../config/companies';

const ROUTE_VALUES = new Set<string>(Object.values(ROUTES));

describe('landing prototype content config', () => {
  it('claim record keys match each claim id and copy is non-empty', () => {
    for (const [key, claim] of Object.entries(LANDING_CONTENT.claims)) {
      expect(claim.id).toBe(key);
      expect(claim.heading.trim().length).toBeGreaterThan(0);
      expect(claim.body.trim().length).toBeGreaterThan(0);
      expect(claim.evidence.trim().length, `claim ${key} needs a brief breadcrumb`).toBeGreaterThan(0);
    }
  });

  it('hero variants carry headline + subheadline', () => {
    for (const variant of Object.values(LANDING_CONTENT.heroVariants)) {
      expect(variant.headline.trim().length).toBeGreaterThan(0);
      expect(variant.subheadline.trim().length).toBeGreaterThan(0);
    }
  });

  it('every internal link target is a real ROUTES value', () => {
    const links = [
      LANDING_CONTENT.ctas.primary,
      LANDING_CONTENT.ctas.secondary,
      ...LANDING_CONTENT.popularSearches,
      ...LANDING_CONTENT.footer.links,
    ];
    for (const link of links) {
      expect(ROUTE_VALUES, `bad link target: ${link.label} -> ${link.to}`).toContain(link.to);
    }
  });

  it('quotable claims and FAQ entries are present and answer-first', () => {
    expect(LANDING_CONTENT.quotableClaims.length).toBeGreaterThanOrEqual(3);
    expect(LANDING_CONTENT.faq.length).toBeGreaterThanOrEqual(5);
    for (const entry of LANDING_CONTENT.faq) {
      expect(entry.question.trim().endsWith('?')).toBe(true);
      expect(entry.answer.trim().length).toBeGreaterThan(0);
    }
  });

  it('TOP_COMPANY_IDS are unique, real registry ids', () => {
    const registry = new Set(COMPANIES.map((c) => c.id));
    expect(new Set(TOP_COMPANY_IDS).size).toBe(TOP_COMPANY_IDS.length);
    for (const id of TOP_COMPANY_IDS) {
      expect(registry, `unknown TOP_COMPANY_IDS entry: ${id}`).toContain(id);
    }
  });
});
