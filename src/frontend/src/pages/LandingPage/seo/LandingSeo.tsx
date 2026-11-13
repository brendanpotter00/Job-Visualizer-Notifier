import { useEffect } from 'react';
import type { LandingContent } from '../content';
import { buildLandingJsonLd, serializeJsonLd } from './landingJsonLd';

interface LandingSeoProps {
  content: LandingContent;
}

export function LandingSeo({ content }: LandingSeoProps) {
  const { seo } = content;
  const canonicalUrl = `${seo.siteUrl}${seo.canonicalPath}`;

  useEffect(() => {
    const previousTitle = document.title;
    document.title = seo.title;

    const existing = document.head.querySelector<HTMLMetaElement>('meta[name="description"]');
    const previousDescription = existing?.getAttribute('content') ?? null;
    let created: HTMLMetaElement | null = null;
    if (existing) {
      existing.setAttribute('content', seo.description);
    } else {
      created = document.createElement('meta');
      created.name = 'description';
      created.content = seo.description;
      document.head.appendChild(created);
    }

    return () => {
      document.title = previousTitle;
      if (created) {
        created.remove();
      } else if (existing && previousDescription !== null) {
        existing.setAttribute('content', previousDescription);
      }
    };
  }, [seo.title, seo.description]);

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
