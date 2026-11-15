import { useEffect } from 'react';
import { LANDING_CONTENT } from '../LandingPage/content';
import { ROUTES } from '../../config/routes';
import { PRICING_CONTENT } from './content';

/**
 * Title + description set imperatively, for the same reason as `LandingSeo`: a
 * React 19 hoisted `<title>` lands AFTER index.html's static one and the first
 * wins. Restored on unmount so the next page does not inherit them.
 */
export function PricingSeo() {
  const { title, description } = PRICING_CONTENT.seo;

  useEffect(() => {
    const previousTitle = document.title;
    document.title = title;

    const existing = document.head.querySelector<HTMLMetaElement>('meta[name="description"]');
    const previousDescription = existing?.getAttribute('content') ?? null;
    let created: HTMLMetaElement | null = null;
    if (existing) {
      existing.setAttribute('content', description);
    } else {
      created = document.createElement('meta');
      created.name = 'description';
      created.content = description;
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
  }, [title, description]);

  return <link rel="canonical" href={`${LANDING_CONTENT.seo.siteUrl}${ROUTES.PRICING}`} />;
}
