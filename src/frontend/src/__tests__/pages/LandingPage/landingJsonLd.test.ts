import { describe, it, expect } from 'vitest';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import {
  buildLandingJsonLd,
  serializeJsonLd,
} from '../../../pages/LandingPage/seo/landingJsonLd';

type Node = Record<string, unknown>;

function nodeOfType(type: string): Node {
  const node = buildLandingJsonLd(LANDING_CONTENT)['@graph'].find((n) => n['@type'] === type);
  expect(node, `no ${type} node in the graph`).toBeDefined();
  return node as Node;
}

describe('buildLandingJsonLd', () => {
  // Brief §9: landing schema is Organization + WebSite (+ the page itself and
  // its FAQ). JobPosting belongs on a per-job page and must never appear here.
  it('emits exactly Organization, WebSite, WebPage and FAQPage, and no JobPosting', () => {
    const graph = buildLandingJsonLd(LANDING_CONTENT);
    expect(graph['@context']).toBe('https://schema.org');
    expect(graph['@graph'].map((n) => n['@type'])).toEqual([
      'Organization',
      'WebSite',
      'WebPage',
      'FAQPage',
    ]);
  });

  it('links the page to the site and the site to the organization by @id', () => {
    const { seo } = LANDING_CONTENT;
    const organization = nodeOfType('Organization');
    const website = nodeOfType('WebSite');
    const page = nodeOfType('WebPage');
    expect(organization['@id']).toBe(`${seo.siteUrl}/#organization`);
    expect(organization.url).toBe(seo.siteUrl);
    expect(organization.sameAs).toEqual([LANDING_CONTENT.header.sourceCode.href]);
    expect(website.publisher).toEqual({ '@id': organization['@id'] });
    expect(website.description).toBe(LANDING_CONTENT.categoryLine);
    expect(page.url).toBe(`${seo.siteUrl}${seo.canonicalPath}`);
    expect(page.name).toBe(seo.title);
    expect(page.description).toBe(seo.description);
    expect(page.isPartOf).toEqual({ '@id': website['@id'] });
  });

  // The FAQ schema is built from the SAME entries the FAQ section renders, so
  // the two can never drift: one question per entry, answer text verbatim.
  it('mirrors every FAQ entry as a Question with its verbatim Answer', () => {
    const faq = nodeOfType('FAQPage');
    const questions = faq.mainEntity as Node[];
    expect(questions).toHaveLength(LANDING_CONTENT.faq.entries.length);
    LANDING_CONTENT.faq.entries.forEach((entry, i) => {
      expect(questions[i]['@type']).toBe('Question');
      expect(questions[i].name).toBe(entry.question);
      expect(questions[i].acceptedAnswer).toEqual({ '@type': 'Answer', text: entry.answer });
    });
  });
});

describe('serializeJsonLd', () => {
  it('escapes "<" so no copy string can close the inline script early', () => {
    const graph = buildLandingJsonLd({
      ...LANDING_CONTENT,
      seo: { ...LANDING_CONTENT.seo, title: 'x</script><script>alert(1)' },
    });
    const json = serializeJsonLd(graph);
    expect(json).not.toContain('</script>');
    expect(json).toContain('\\u003c/script>');
    // Still valid JSON that round-trips to the original string.
    const page = (JSON.parse(json)['@graph'] as Node[]).find((n) => n['@type'] === 'WebPage');
    expect(page?.name).toBe('x</script><script>alert(1)');
  });
});
