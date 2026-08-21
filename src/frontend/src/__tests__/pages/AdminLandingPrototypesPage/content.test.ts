import { describe, it, expect } from 'vitest';
import { LANDING_CONTENT, TOP_COMPANY_IDS } from '../../../pages/AdminLandingPrototypesPage/content';
import { COMPANY_CATEGORIES } from '../../../pages/AdminLandingPrototypesPage/companyCategories';
import { ROUTES } from '../../../config/routes';
import { COMPANIES } from '../../../config/companies';

const ROUTE_VALUES = new Set<string>(Object.values(ROUTES));

/** Walk any nested content object and yield every string leaf with its path. */
function* walkStrings(value: unknown, path = ''): Generator<[string, string]> {
  if (typeof value === 'string') {
    yield [path, value];
  } else if (Array.isArray(value)) {
    for (const [i, item] of value.entries()) yield* walkStrings(item, `${path}[${i}]`);
  } else if (value !== null && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      yield* walkStrings(item, path ? `${path}.${key}` : key);
    }
  }
}

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
      LANDING_CONTENT.header.wordmark,
      ...LANDING_CONTENT.header.nav,
      LANDING_CONTENT.header.logIn,
      LANDING_CONTENT.header.signUp,
      LANDING_CONTENT.ctas.primary,
      LANDING_CONTENT.ctas.secondary,
      LANDING_CONTENT.featureMatrix.nextUp,
      ...LANDING_CONTENT.popularSearches,
      ...LANDING_CONTENT.footer.links,
    ];
    for (const link of links) {
      expect(ROUTE_VALUES, `bad link target: ${link.label} -> ${link.to}`).toContain(link.to);
    }
  });

  // The header is chrome, not a site map: the two-link cap is the whole point
  // of the section, so it is asserted rather than left to reviewer discipline.
  it('header carries a wordmark, exactly two nav links, and both auth labels', () => {
    const { wordmark, nav, logIn, signUp, sourceCode, evidence } = LANDING_CONTENT.header;
    expect(wordmark.label).toBe(LANDING_CONTENT.productName);
    expect(nav).toHaveLength(2);
    for (const link of [wordmark, ...nav, logIn, signUp]) {
      expect(link.label.trim().length, `header link ${link.to} needs a label`).toBeGreaterThan(0);
    }
    expect(new Set(nav.map((item) => item.label)).size).toBe(nav.length);
    expect(evidence.trim().length, 'header needs an owner breadcrumb').toBeGreaterThan(0);
    // External by definition, so it must NOT masquerade as an internal route.
    expect(sourceCode.href.startsWith('https://')).toBe(true);
    expect(ROUTE_VALUES).not.toContain(sourceCode.href);
    expect(sourceCode.label.trim().length).toBeGreaterThan(0);
    expect(
      sourceCode.evidence.trim().length,
      'source-code link needs an owner breadcrumb'
    ).toBeGreaterThan(0);
  });

  it('quotable claims and FAQ entries are present and answer-first', () => {
    expect(LANDING_CONTENT.quotableClaims.length).toBeGreaterThanOrEqual(3);
    expect(LANDING_CONTENT.faq.length).toBeGreaterThanOrEqual(5);
    for (const entry of LANDING_CONTENT.faq) {
      expect(entry.question.trim().endsWith('?')).toBe(true);
      expect(entry.answer.trim().length).toBeGreaterThan(0);
    }
  });

  // The two text sections exist to be skimmable; these invariants are the
  // guard rail against copy quietly growing into paragraphs.
  it('how-it-works ships exactly three terse, uniquely-keyed steps', () => {
    const { heading, steps } = LANDING_CONTENT.howItWorks;
    expect(heading.trim().length).toBeGreaterThan(0);
    expect(steps).toHaveLength(3);
    expect(new Set(steps.map((s) => s.id)).size).toBe(steps.length);
    for (const step of steps) {
      expect(
        step.label.trim().split(/\s+/).length,
        `step ${step.id} label too long`
      ).toBeLessThanOrEqual(4);
      expect(
        step.line.trim().split(/\s+/).length,
        `step ${step.id} line too long`
      ).toBeLessThanOrEqual(14);
      expect(step.evidence.trim().length, `step ${step.id} needs a breadcrumb`).toBeGreaterThan(0);
    }
  });

  it('feature matrix cells are uniquely keyed, short, and traceable', () => {
    const { heading, features } = LANDING_CONTENT.featureMatrix;
    expect(heading.trim().length).toBeGreaterThan(0);
    // 6 cells fills both the 2-column (mobile) and 3-column (desktop) grid
    // exactly — no orphan cell in either layout.
    expect(features.length % 6).toBe(0);
    expect(new Set(features.map((f) => f.id)).size).toBe(features.length);
    for (const feature of features) {
      expect(
        feature.name.trim().split(/\s+/).length,
        `feature ${feature.id} name too long`
      ).toBeLessThanOrEqual(4);
      expect(
        feature.detail.trim().split(/\s+/).length,
        `feature ${feature.id} detail too long`
      ).toBeLessThanOrEqual(8);
      expect(
        feature.evidence.trim().length,
        `feature ${feature.id} needs a breadcrumb`
      ).toBeGreaterThan(0);
    }
  });

  // The grayed tier is the ONE place unshipped work may appear (owner decision
  // 2026-08-20, docs/marketing/business-context.md). It is held to the live
  // cells' terseness because it renders in the same grid, and to a hard count
  // of three so the exception cannot quietly grow into a roadmap page.
  it('coming-soon tier is exactly three terse, traceable cells, disjoint from the live set', () => {
    const { comingSoonLabel, comingSoon, features } = LANDING_CONTENT.featureMatrix;
    expect(comingSoonLabel.trim().length).toBeGreaterThan(0);
    expect(comingSoon).toHaveLength(3);
    const liveIds = new Set(features.map((f) => f.id));
    for (const feature of comingSoon) {
      expect(liveIds, `coming-soon id ${feature.id} collides with a live cell`).not.toContain(
        feature.id
      );
      expect(
        feature.name.trim().split(/\s+/).length,
        `coming-soon ${feature.id} name too long`
      ).toBeLessThanOrEqual(4);
      expect(
        feature.detail.trim().split(/\s+/).length,
        `coming-soon ${feature.id} detail too long`
      ).toBeLessThanOrEqual(8);
      expect(
        feature.evidence.trim().length,
        `coming-soon ${feature.id} needs an epic breadcrumb`
      ).toBeGreaterThan(0);
    }
    expect(new Set(comingSoon.map((f) => f.id)).size).toBe(comingSoon.length);
  });

  // Owner-directed house style (2026-08-09): the landing voice uses periods and
  // commas, never em-dashes. This walks EVERY string in the content config (and
  // the category taxonomy it renders beside), so a new claim, FAQ answer, or
  // blurb cannot smuggle one back in. Comments are prose about the code, not
  // page copy, and are deliberately out of scope.
  it('contains no em-dashes in any user-facing string', () => {
    const paths = [
      ...walkStrings(LANDING_CONTENT, 'LANDING_CONTENT'),
      ...walkStrings(COMPANY_CATEGORIES, 'COMPANY_CATEGORIES'),
    ];
    // The walk is only a guarantee over the keys it actually reaches, so pin
    // that the newest copy branch is one of them.
    expect(
      paths.some(([path]) => path.startsWith('LANDING_CONTENT.featureMatrix.comingSoon[')),
      'em-dash walker never reached featureMatrix.comingSoon'
    ).toBe(true);
    expect(
      paths.some(([path]) => path.startsWith('LANDING_CONTENT.header.')),
      'em-dash walker never reached the header copy'
    ).toBe(true);
    const offenders = paths.filter(([, text]) => text.includes('—'));
    expect(offenders.map(([path]) => path)).toEqual([]);
  });

  it('TOP_COMPANY_IDS are unique, real registry ids', () => {
    const registry = new Set(COMPANIES.map((c) => c.id));
    expect(new Set(TOP_COMPANY_IDS).size).toBe(TOP_COMPANY_IDS.length);
    for (const id of TOP_COMPANY_IDS) {
      expect(registry, `unknown TOP_COMPANY_IDS entry: ${id}`).toContain(id);
    }
  });
});
