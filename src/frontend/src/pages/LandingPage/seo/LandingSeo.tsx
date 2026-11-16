import { useDocumentHead } from '../../../hooks/useDocumentHead';
import type { LandingContent } from '../content';
import { buildLandingJsonLd, serializeJsonLd } from './landingJsonLd';

interface LandingSeoProps {
  content: LandingContent;
}

export function LandingSeo({ content }: LandingSeoProps) {
  const { seo } = content;
  const canonicalUrl = `${seo.siteUrl}${seo.canonicalPath}`;

  useDocumentHead(seo.title, seo.description);

  return (
    <>
      <link rel="canonical" href={canonicalUrl} />
      <script
        type="application/ld+json"
        data-testid="landing-json-ld"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(buildLandingJsonLd(content)) }}
      />
    </>
  );
}
