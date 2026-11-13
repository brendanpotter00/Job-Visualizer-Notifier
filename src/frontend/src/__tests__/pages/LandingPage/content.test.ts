import { describe, it, expect } from 'vitest';
import { LANDING_CONTENT, TOP_COMPANY_IDS } from '../../../pages/LandingPage/content';
import type { SectionIntro } from '../../../pages/LandingPage/content';
import { COMPANY_CATEGORIES } from '../../../pages/LandingPage/companyCategories';
import { ROUTES } from '../../../config/routes';
import { COMPANIES } from '../../../config/companies';

const ROUTE_VALUES = new Set<string>(Object.values(ROUTES));

const wordCount = (text: string) => text.trim().split(/\s+/).length;

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

/** Every section that opens with the shared eyebrow + heading. */
const SECTION_INTROS: Record<string, SectionIntro> = {
  freshJobs: LANDING_CONTENT.freshJobs,
  comparison: LANDING_CONTENT.comparison,
  companies: LANDING_CONTENT.companies,
  featureMatrix: LANDING_CONTENT.featureMatrix,
  faq: LANDING_CONTENT.faq,
};

describe('landing content config', () => {
  // One h1, one tone (owner-directed 2026-11-12): the brief §4 B1 hook plus
  // "Just jobs." The gray continuation that carried the query phrase is gone,
  // so the phrase must survive in the title and description instead.
  it('hero: one short line, and the query phrase still in the head', () => {
    const { headline, evidence } = LANDING_CONTENT.hero;
    expect(headline).toBe('No reposts. No stale listings. No noise. Just jobs.');
    expect(wordCount(headline)).toBeLessThanOrEqual(9);
    expect(LANDING_CONTENT.hero).not.toHaveProperty('continuation');
    expect(LANDING_CONTENT.seo.title).toMatch(/software engineer jobs/i);
    expect(LANDING_CONTENT.seo.description).toMatch(/software engineers/i);
    expect(evidence.trim().length, 'hero needs a brief breadcrumb').toBeGreaterThan(0);
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
    ];
    for (const link of links) {
      expect(ROUTE_VALUES, `bad link target: ${link.label} -> ${link.to}`).toContain(link.to);
    }
  });

  // The header is chrome, not a site map: the link cap is the whole point of
  // the section, so it is asserted rather than left to reviewer discipline. It
  // went from two to three on 2026-11-12 (owner-directed): "Jobs" leads, now
  // that the board lives at /jobs rather than at the root.
  it('header carries a wordmark, exactly three nav links, and both auth labels', () => {
    const { wordmark, nav, logIn, signUp, sourceCode, evidence } = LANDING_CONTENT.header;
    expect(wordmark.label).toBe(LANDING_CONTENT.productName);
    expect(nav).toHaveLength(3);
    for (const link of [wordmark, ...nav, logIn, signUp]) {
      expect(link.label.trim().length, `header link ${link.to} needs a label`).toBeGreaterThan(0);
    }
    expect(new Set(nav.map((item) => item.label)).size).toBe(nav.length);
    // Owner-directed 2026-09-03: "Why" gave up the second slot to "Changelog",
    // pointed at the vote-features page (which IS the public changelog — its
    // shipped section).
    expect(nav.map((item) => item.label)).toEqual(['Jobs', 'Companies', 'Changelog']);
    expect(nav[0].to).toBe(ROUTES.RECENT_JOBS);
    expect(nav[2].to).toBe(ROUTES.VOTE_FEATURES);
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

  // The page's rhythm is one opening shape repeated: a ≤8-word heading (the
  // eyebrow that used to sit over it was cut on 2026-11-12). A section that
  // needs more words in its heading has started selling in the wrong place.
  it('every section opens with a one-line heading, and no two share one', () => {
    for (const [name, intro] of Object.entries(SECTION_INTROS)) {
      expect(wordCount(intro.heading), `${name} heading too long`).toBeLessThanOrEqual(8);
      expect(intro.heading.trim().length, `${name} heading empty`).toBeGreaterThan(0);
      expect(intro, `${name} must not carry an eyebrow`).not.toHaveProperty('eyebrow');
    }
    const headings = Object.values(SECTION_INTROS).map((intro) => intro.heading);
    expect(new Set(headings).size).toBe(headings.length);
  });

  // Naming LinkedIn was on the brief's do-not-say list until the owner asked
  // for this section (2026-09-10). The override must stay visibly recorded on
  // the section, and every cell stays a short, checkable fact — the only
  // comparison framing that survives being quoted (brief §10 P4).
  it('LinkedIn comparison: a few short factual rows, owner-traced', () => {
    const { columns, rows, evidence } = LANDING_CONTENT.comparison;
    expect(columns.linkedin).toBe('LinkedIn');
    expect(columns.onesecondswe).toBe(LANDING_CONTENT.productName);
    expect(evidence).toMatch(/owner-directed 2026-09-10/);
    expect(rows.length).toBeGreaterThanOrEqual(3);
    expect(rows.length).toBeLessThanOrEqual(5);
    expect(new Set(rows.map((row) => row.id)).size).toBe(rows.length);
    for (const row of rows) {
      expect(wordCount(row.label), `row ${row.id} label too long`).toBeLessThanOrEqual(3);
      expect(wordCount(row.linkedin), `row ${row.id} LinkedIn cell too long`).toBeLessThanOrEqual(
        8
      );
      expect(
        wordCount(row.onesecondswe),
        `row ${row.id} onesecondswe cell too long`
      ).toBeLessThanOrEqual(8);
      expect(row.evidence.trim().length, `row ${row.id} needs a breadcrumb`).toBeGreaterThan(0);
    }
    // The two claims the owner named are the two the section must make.
    expect(rows.map((row) => row.id)).toEqual(expect.arrayContaining(['reposts', 'companies']));
  });

  // The floor is on COVERAGE, not a quota: five distinct questions, one of which
  // is the LinkedIn comparison asked the way people ask answer engines.
  it('FAQ entries are present, answer-first, and include the LinkedIn question', () => {
    const { entries } = LANDING_CONTENT.faq;
    expect(entries.length).toBeGreaterThanOrEqual(5);
    for (const entry of entries) {
      expect(entry.question.trim().endsWith('?')).toBe(true);
      expect(entry.answer.trim().length).toBeGreaterThan(0);
    }
    expect(entries.some((entry) => /linkedin/i.test(entry.question))).toBe(true);
  });

  it('asks each FAQ question only once', () => {
    const questions = LANDING_CONTENT.faq.entries.map((entry) => entry.question);
    expect(new Set(questions).size).toBe(questions.length);
    const answers = LANDING_CONTENT.faq.entries.map((entry) => entry.answer);
    expect(new Set(answers).size).toBe(answers.length);
  });

  it('feature matrix cells are uniquely keyed, short, and traceable', () => {
    const { features } = LANDING_CONTENT.featureMatrix;
    expect(features.length).toBeGreaterThanOrEqual(6);
    expect(new Set(features.map((f) => f.id)).size).toBe(features.length);
    for (const feature of features) {
      expect(wordCount(feature.name), `feature ${feature.id} name too long`).toBeLessThanOrEqual(4);
      expect(
        wordCount(feature.detail),
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
  // cells' terseness because it renders in the same grid, and to a small CAP so
  // the exception cannot quietly grow into a roadmap page.
  it('coming-soon tier is a small set of terse, traceable cells, disjoint from the live set', () => {
    const { comingSoonLabel, comingSoon, features } = LANDING_CONTENT.featureMatrix;
    expect(comingSoonLabel.trim().length).toBeGreaterThan(0);
    expect(comingSoon.length).toBeGreaterThanOrEqual(1);
    expect(comingSoon.length).toBeLessThanOrEqual(3);
    const liveIds = new Set(features.map((f) => f.id));
    for (const feature of comingSoon) {
      expect(liveIds, `coming-soon id ${feature.id} collides with a live cell`).not.toContain(
        feature.id
      );
      expect(wordCount(feature.name), `coming-soon ${feature.id} name too long`).toBeLessThanOrEqual(
        4
      );
      expect(
        wordCount(feature.detail),
        `coming-soon ${feature.id} detail too long`
      ).toBeLessThanOrEqual(8);
      expect(
        feature.evidence.trim().length,
        `coming-soon ${feature.id} needs an epic breadcrumb`
      ).toBeGreaterThan(0);
    }
    expect(new Set(comingSoon.map((f) => f.id)).size).toBe(comingSoon.length);
  });

  it('closing line is one short, traceable sentence', () => {
    const { heading, evidence } = LANDING_CONTENT.closing;
    expect(wordCount(heading)).toBeLessThanOrEqual(6);
    expect(evidence.trim().length).toBeGreaterThan(0);
  });

  // Brief §9 title shape and §10 P3: the query phrase, the brand, and a
  // description short enough to survive a results page uncut.
  it('seo: keyword-first title with brand suffix, short description, root canonical', () => {
    const { title, description, siteUrl, canonicalPath, ogImagePath } = LANDING_CONTENT.seo;
    expect(title).toMatch(/^software engineer jobs/i);
    expect(title).toMatch(/\| onesecondswe$/);
    expect(title.length).toBeLessThanOrEqual(70);
    expect(description.length).toBeLessThanOrEqual(160);
    expect(description).toMatch(/software engineers/i);
    expect(siteUrl).toBe('https://onesecondswe.dev');
    expect(canonicalPath).toBe(ROUTES.HOME);
    expect(ogImagePath.startsWith('/')).toBe(true);
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
    // that the newest copy branches are among them.
    for (const prefix of [
      'LANDING_CONTENT.featureMatrix.comingSoon[',
      'LANDING_CONTENT.header.',
      'LANDING_CONTENT.comparison.rows[',
      'LANDING_CONTENT.seo.',
      'LANDING_CONTENT.closing.',
    ]) {
      expect(
        paths.some(([path]) => path.startsWith(prefix)),
        `em-dash walker never reached ${prefix}`
      ).toBe(true);
    }
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
