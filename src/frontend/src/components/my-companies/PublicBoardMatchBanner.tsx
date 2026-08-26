import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { getCompanyById } from '../../config/companies';
import { ROUTES } from '../../config/routes';
import { COMPANY_PARAM } from '../../lib/url';
import type { UserCompany } from '../../features/userCompanies/userCompaniesApi';
import { isPublicMatchDismissed, markPublicMatchDismissed } from './publicMatchDismissal';

interface PublicBoardMatchBannerProps {
  company: UserCompany;
  /** Hands the company to the list's existing remove-confirmation dialog. */
  onRemove: (company: UserCompany) => void;
}

/**
 * "This looks like **Spotify**, which we already track — 70 of 81 roles match."
 *
 * THE CASE THAT PROMPTED IT. Somebody pastes `lifeatspotify.com`, we discover it, and they
 * end up with a private second copy of a board we have published for months: the public row
 * has the history, the private one starts at zero, and nobody wanted two. The URL check
 * cannot catch it — that URL resolves to no ATS at all, and the endpoint capture picks up is
 * a different feed from the Lever board. The only signal is the job set, which is what the
 * backend compared to produce this.
 *
 * IT IS A SUGGESTION AND THE UI HAS TO READ LIKE ONE. Nothing was merged, moved or changed;
 * there is no un-merge path in this codebase, so the backend never merges and this banner is
 * the whole of the consequence. Hence `severity="info"` rather than `warning` — nothing
 * failed and nothing is broken. The board is tracking fine and will keep tracking fine if
 * the user ignores this forever.
 *
 * The numbers are IN the sentence, not behind a tooltip. "This looks like Spotify" is an
 * assertion the user has no way to check; "70 of 81 roles match" is the evidence, and it is
 * the difference between a claim they can act on and one they have to trust.
 *
 * Two actions, and the ORDER is the argument. The link is first because it is the thing
 * that helps (the public page already has the history the private copy is missing). Delete
 * is second and routes through the list's ordinary confirmation dialog — the destructive
 * action here must be exactly as guarded as it is everywhere else, never a one-click
 * shortcut just because a banner suggested it. Dismiss is last and PERSISTS: a suggestion
 * that comes back after being dismissed is a suggestion people learn to ignore.
 *
 * THE MIDDLE BUTTON SAYS "DELETE" BECAUSE IT DELETES. It reaches
 * `custom_companies_service.remove_owned_company`, which does not stop collection going
 * forward — it issues `DELETE FROM job_listings WHERE source_id = 'custom:<id>'` and the
 * same for this board's tags, enrichment, location links, harvests and scrape runs. The
 * word "Remove", paired with a dialog that said the history "will no longer be collected",
 * read as a pause. It never was one, and the one place a user can be told that is the
 * button they are about to press and the dialog behind it. The caption under the row says
 * the other half — the PUBLIC company we are pointing them at is a different row entirely
 * and keeps every job it has, so taking the suggestion costs them nothing they can see.
 *
 * THE LINK IS GUARDED, for the reason `AlreadyPublicNotice` documents: `companyId` is a
 * backend id and this build's `companies.ts` is a compile-time list, so a company seeded on
 * the server but not yet in the frontend bundle would deep-link to `?company=<unknown>` —
 * which `getCompanyFromURL` silently falls back on, landing the user on somebody else's
 * chart right after being told "here's Spotify".
 */
export function PublicBoardMatchBanner({ company, onRemove }: PublicBoardMatchBannerProps) {
  const match = company.publicMatch ?? null;
  // The dismissal check lives in the initializer so the render body stays pure — the same
  // reason `NewFeatureCallout` does it, and the same lint rule (`react-hooks/purity`).
  // Once per mount is the right granularity: nothing can dismiss this from elsewhere.
  const [dismissed, setDismissed] = useState<boolean>(() =>
    match ? isPublicMatchDismissed(company.id, match.companyId) : false,
  );

  if (!match || dismissed) {
    return null;
  }

  const known = getCompanyById(match.companyId) !== undefined;
  const to = known
    ? `${ROUTES.COMPANIES}?${COMPANY_PARAM}=${encodeURIComponent(match.companyId)}`
    : ROUTES.COMPANIES;

  const handleDismiss = () => {
    markPublicMatchDismissed(company.id, match.companyId);
    setDismissed(true);
  };

  return (
    <Alert severity="info" sx={{ mt: 1.5 }} data-testid="public-board-match">
      <AlertTitle>This looks like {match.displayName}, which we already track</AlertTitle>
      <Typography variant="body2" component="p">
        {match.shared.toLocaleString()} of {match.candidateTitles.toLocaleString()}{' '}
        {match.candidateTitles === 1 ? 'role' : 'roles'} on this board match{' '}
        {match.displayName}&apos;s. Use the public page instead? It already has the hiring
        history this board is building from scratch.
      </Typography>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
        <Link component={RouterLink} to={to} data-testid="public-board-match-link">
          {known
            ? `Open ${match.displayName}'s hiring trend`
            : 'Open Company Hiring Trends'}
        </Link>
        <Button
          color="error"
          size="small"
          onClick={() => onRemove(company)}
          data-testid="public-board-match-remove"
        >
          Delete this board
        </Button>
        <Button size="small" onClick={handleDismiss} data-testid="public-board-match-dismiss">
          Dismiss
        </Button>
      </Stack>
      <Typography
        variant="caption"
        component="p"
        sx={{ mt: 0.5 }}
        data-testid="public-board-match-delete-note"
      >
        Deleting is permanent — it erases the jobs already collected for this board, not just
        future ones. {match.displayName}&apos;s public page is a separate record and keeps its
        history either way.
      </Typography>
    </Alert>
  );
}
