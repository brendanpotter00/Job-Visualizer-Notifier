/**
 * Structured data for the landing page, as one `@graph` (brief §9/§10):
 * Organization + WebSite for the entity, a WebPage for this URL, and a
 * FAQPage over the same entries the FAQ section renders. JobPosting is
 * deliberately absent — per Google it belongs on a per-job page, never on a
 * landing or list page.
 *
 * Pure: takes the content config, returns a plain object. `LandingSeo` is the
 * only caller and serializes it; keeping the shape here means a test can pin
 * the graph without rendering anything.
 */
import type { LandingContent } from '../content';

export interface LandingJsonLd {
  '@context': 'https://schema.org';
  '@graph': readonly Record<string, unknown>[];
}

export function buildLandingJsonLd(content: LandingContent): LandingJsonLd {
  const { seo, productName, categoryLine, header, faq } = content;
  const organizationId = `${seo.siteUrl}/#organization`;
  const websiteId = `${seo.siteUrl}/#website`;
  const pageUrl = `${seo.siteUrl}${seo.canonicalPath}`;

  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'Organization',
        '@id': organizationId,
        name: productName,
        url: seo.siteUrl,
        logo: `${seo.siteUrl}${seo.ogImagePath}`,
        sameAs: [header.sourceCode.href],
      },
      {
        '@type': 'WebSite',
        '@id': websiteId,
        url: seo.siteUrl,
        name: productName,
        description: categoryLine,
        publisher: { '@id': organizationId },
      },
      {
        '@type': 'WebPage',
        '@id': pageUrl,
        url: pageUrl,
        name: seo.title,
        description: seo.description,
        isPartOf: { '@id': websiteId },
        about: { '@id': organizationId },
      },
      {
        '@type': 'FAQPage',
        '@id': `${pageUrl}#faq`,
        mainEntity: faq.entries.map((entry) => ({
          '@type': 'Question',
          name: entry.question,
          acceptedAnswer: { '@type': 'Answer', text: entry.answer },
        })),
      },
    ],
  };
}

/**
 * JSON for an inline `<script type="application/ld+json">`. `<` is escaped so
 * no string in the config (an answer, a title) can ever close the script tag
 * early, which is the one injection an inline JSON block is exposed to.
 */
export function serializeJsonLd(jsonLd: LandingJsonLd): string {
  return JSON.stringify(jsonLd).replace(/</g, '\\u003c');
}
