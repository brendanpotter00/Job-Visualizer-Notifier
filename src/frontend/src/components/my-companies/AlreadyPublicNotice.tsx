import type { ReactNode } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Link from '@mui/material/Link';
import { getCompanyById } from '../../config/companies';
import { ROUTES } from '../../config/routes';
import { COMPANY_PARAM } from '../../lib/url';
import type { AlreadyPublicResponse } from '../../features/userCompanies/userCompaniesApi';

interface AlreadyPublicNoticeProps {
  result: AlreadyPublicResponse;
  /** Optional secondary action, rendered under the link. Never the default choice. */
  action?: ReactNode;
}

/**
 * "We already track this" — the terminal answer when a pasted URL turns out to be a
 * job board we already publish to everyone.
 *
 * The case that prompted it: one company ends up with TWO scrapers and two job sets —
 * a public one with months of history and a private copy that starts at zero. Adding
 * the duplicate helps nobody, so the add stops and this points at the page that
 * already has the answer.
 *
 * `severity="info"`, not `warning`. Nothing failed and there is nothing for the user to
 * fix; the company they asked for exists and is one click away. Colouring that as a
 * problem would be the same mistake as an alarm badge for something the user cannot act
 * on.
 *
 * Terminal, not dismissible. It is the response to a submit the user just made, it
 * carries the only two things they can do next, and the next submit replaces it — a
 * dismiss would be a third state that persists nothing.
 *
 * THE LINK IS GUARDED. `companyId` is a backend id, and this build's `companies.ts` is
 * a compile-time list, so a company seeded on the server but not yet in the frontend
 * bundle would deep-link to `?company=<unknown>` — which `getCompanyFromURL` silently
 * falls back on, landing the user on SpaceX's chart after being told "here's Spotify".
 * When we do not recognise the id we link to the trends page itself and say so.
 *
 * The copy says "the same job board", never "the same company". All we checked is that
 * the URL resolved to a board we already read. We did not compare job sets, and a
 * company's own careers site never reaches this branch at all.
 */
export function AlreadyPublicNotice({ result, action }: AlreadyPublicNoticeProps) {
  const known = getCompanyById(result.companyId) !== undefined;
  const to = known
    ? `${ROUTES.COMPANIES}?${COMPANY_PARAM}=${encodeURIComponent(result.companyId)}`
    : ROUTES.COMPANIES;

  return (
    <Alert severity="info" sx={{ mt: 2 }} data-testid="already-public">
      <AlertTitle>We already track {result.displayName}</AlertTitle>
      {result.detail}{' '}
      <Link component={RouterLink} to={to} data-testid="already-public-link">
        {known ? `Open ${result.displayName}'s hiring trend` : 'Open Company Hiring Trends'}
      </Link>
      {action}
    </Alert>
  );
}
