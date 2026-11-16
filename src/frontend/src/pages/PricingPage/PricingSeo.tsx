import { useDocumentHead } from '../../hooks/useDocumentHead';
import { LANDING_CONTENT } from '../LandingPage/content';
import { ROUTES } from '../../config/routes';
import { PRICING_CONTENT } from './content';

export function PricingSeo() {
  useDocumentHead(PRICING_CONTENT.seo.title, PRICING_CONTENT.seo.description);
  return <link rel="canonical" href={`${LANDING_CONTENT.seo.siteUrl}${ROUTES.PRICING}`} />;
}
