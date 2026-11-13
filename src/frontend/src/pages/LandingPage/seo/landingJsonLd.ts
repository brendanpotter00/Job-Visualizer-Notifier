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

export function serializeJsonLd(jsonLd: LandingJsonLd): string {
  return JSON.stringify(jsonLd).replace(/</g, '\\u003c');
}
