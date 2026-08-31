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
 * TWO CONFIDENCE LEVELS, AND THEY MUST NOT READ THE SAME. `matchKind` says which
 * evidence produced this notice, and the headline is the one place a user actually reads
 * it:
 *
 *  - `'board'` — we matched a BOARD, by its ATS `(ats, boardToken)` pair or, for the five
 *    script-scraped boards, by its declared careers host. Exact. "We already track X",
 *    stated flat, and the server's own `detail` says "the same job board". Terminal: the
 *    caller passes no `action`, because a private duplicate of a board we already publish
 *    is strictly worse for the user than the link above it.
 *  - `'name'` — we matched the company NAME inside the domain. That is a string in a web
 *    address, not a board and not a job set, so the headline hedges to "This looks like
 *    X" and the caller passes the `action` that lets them say we guessed wrong.
 *
 * Neither says "the same company" outright: even the exact rung only checked that the URL
 * names a board we already read. We never compared job sets.
 *
 * THE LINK IS THE PRIMARY ACTION on both. `action` is optional and always secondary.
 *
 * THE EXACT (`'board'`) CASE IS ONE LINE. It is terminal — no correction, no `action` in
 * practice — so the server's `detail` sentence explaining *why* would just be restating
 * "we matched your URL" to someone who cannot do anything with that. The guessed
 * (`'name'`) case keeps the full `AlertTitle` + `detail` + link layout: a hedge needs the
 * room to say what kind of evidence it is, because the `action` next to it is the user's
 * one chance to say we got it wrong.
 */
export function AlreadyPublicNotice({ result, action }: AlreadyPublicNoticeProps) {
  const known = getCompanyById(result.companyId) !== undefined;
  const to = known
    ? `${ROUTES.COMPANIES}?${COMPANY_PARAM}=${encodeURIComponent(result.companyId)}`
    : ROUTES.COMPANIES;
  // Absent `matchKind` means the stricter, older reading — a server that predates the
  // field only ever sent board matches.
  const guessed = result.matchKind === 'name';

  if (guessed) {
    return (
      <Alert severity="info" sx={{ mt: 2 }} data-testid="already-public">
        <AlertTitle>{`This looks like ${result.displayName}, which we already track`}</AlertTitle>
        {result.detail}{' '}
        <Link component={RouterLink} to={to} data-testid="already-public-link">
          {known ? `Open ${result.displayName}'s hiring trend` : 'Open Company Hiring Trends'}
        </Link>
        {action}
      </Alert>
    );
  }

  return (
    <Alert severity="info" sx={{ mt: 2 }} data-testid="already-public">
      {`We already track ${result.displayName} — `}
      <Link component={RouterLink} to={to} data-testid="already-public-link">
        {known ? 'See all jobs' : 'See Company Hiring Trends'}
      </Link>
      {action}
    </Alert>
  );
}
