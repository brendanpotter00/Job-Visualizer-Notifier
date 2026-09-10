import { useEffect } from 'react';
import type { LandingContent } from '../content';
import { buildLandingJsonLd, serializeJsonLd } from './landingJsonLd';

interface LandingSeoProps {
  content: LandingContent;
}

/**
 * Everything the document head says about the landing page. Rendered from the
 * page shell (outside the lazy scene chunk) so it applies the moment the route
 * mounts, before three/rapier ever download.
 *
 * Title and description are set IMPERATIVELY, not rendered as `<title>` /
 * `<meta>`: React 19 hoists those into `<head>`, but it appends them after
 * the static ones `index.html` already carries, and the browser (and Google)
 * resolve `document.title` and the description from the FIRST match — so a
 * rendered `<title>` would never win. The effect edits the static elements in
 * place and restores them on unmount, which is what lets `/landing` carry a
 * keyword-first title while every other route keeps the app default.
 *
 * The canonical link and the JSON-LD have no static counterpart, so they are
 * rendered: React hoists the `<link>`; the inline script is NOT hoisted (React
 * only hoists `async` scripts with a `src`) and stays in the body, which every
 * structured-data parser accepts.
 *
 * Known limit, not a bug here: none of this reaches a crawler that does not
 * run JavaScript (brief §10 P0). For those, `index.html`'s static head is the
 * whole page; prerendering `/landing` is the 11.2 lever.
 */
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
