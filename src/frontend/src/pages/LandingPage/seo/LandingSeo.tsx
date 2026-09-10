import type { LandingContent } from '../content';
import { buildLandingJsonLd, serializeJsonLd } from './landingJsonLd';

interface LandingSeoProps {
  content: LandingContent;
}

/**
 * Everything the document head says about the landing page. Rendered from the
 * page shell (outside the lazy scene chunk) so the tags exist the moment the
 * route mounts, before three/rapier ever download.
 *
 * React 19 hoists `<title>`, `<meta>` and `<link>` rendered anywhere in the
 * tree into `<head>` — no helmet library, no effect. The inline JSON-LD script
 * is NOT hoisted (React only hoists `async` scripts with a `src`) and stays in
 * the body, which every structured-data parser accepts.
 *
 * Known limit, not a bug here: none of this reaches a crawler that does not
 * run JavaScript (brief §10 P0). For those, `index.html` carries the same
 * title and description statically; prerendering `/landing` is the 11.2 lever.
 */
export function LandingSeo({ content }: LandingSeoProps) {
  const { seo } = content;
  const canonicalUrl = `${seo.siteUrl}${seo.canonicalPath}`;
  const ogImageUrl = `${seo.siteUrl}${seo.ogImagePath}`;

  return (
    <>
      <title>{seo.title}</title>
      <meta name="description" content={seo.description} />
      <link rel="canonical" href={canonicalUrl} />
      <meta property="og:title" content={seo.title} />
      <meta property="og:description" content={seo.description} />
      <meta property="og:type" content="website" />
      <meta property="og:url" content={canonicalUrl} />
      <meta property="og:image" content={ogImageUrl} />
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={seo.title} />
      <meta name="twitter:description" content={seo.description} />
      <meta name="twitter:image" content={ogImageUrl} />
      <script
        type="application/ld+json"
        data-testid="landing-json-ld"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(buildLandingJsonLd(content)) }}
      />
    </>
  );
}
