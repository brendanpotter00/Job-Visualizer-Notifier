import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import { buildMyCompanyDetailPath } from '../../config/routes';
import { CUSTOM_COMPANIES_CONFIG } from '../../config/customCompanies';
import { extractErrorMessage } from '../../lib/errors';
import { SUPPORTED_BOARDS } from '../../features/userCompanies/resolveErrors';
import {
  isDiscoveryPending,
  type AddUserCompanyResult,
} from '../../features/userCompanies/userCompaniesApi';

interface DiscoveryStatusProps {
  /** The add mutation's body, once it has one: a `202` pending or a `200`/`201` company. */
  result: AddUserCompanyResult | undefined;
  /** The add mutation's rejection, if it failed. Typed `unknown` — see `extractErrorMessage`. */
  error: unknown;
}

/**
 * What happened to the one-time discovery a non-ATS URL was routed into.
 *
 * PURELY PRESENTATIONAL — it owns no mutation and no button. Discovery is kicked off by
 * the page's single submit action the moment the resolver reports no supported ATS, so
 * the "Try one-time discovery" button this component used to render was a second click
 * standing between the user and the only thing left to do. The mutation therefore lives
 * in `MyCompaniesPage`, which needs its in-flight flag to keep the form disabled across
 * both network calls; this component only renders the outcome it is handed.
 *
 * Three terminal outcomes, all of which predate the auto-start and none of which changed:
 *  - `202 discovery_pending` — a background agent is teaching itself to read the board.
 *  - `200` — an idempotent re-add of a board discovered on an earlier attempt; it is
 *    already tracked, so link straight to it.
 *  - an error — most often the `422` the backend returns when
 *    `custom_company_discovery_enabled` is OFF, which reads as "no supported ATS board
 *    was found behind this URL". That is a truthful dead end, not a spinner, and it is
 *    the reason this branch also names the boards we can read without discovery.
 */
export function DiscoveryStatus({ result, error }: DiscoveryStatusProps) {
  if (result !== undefined && isDiscoveryPending(result)) {
    // With the checklist on, the row below is now narrating the setup step by step, so
    // point at it instead of repeating "Setting up…" — rendering a second copy of the
    // same checklist here would say the same thing twice on a very short page. Flag OFF
    // keeps the original copy verbatim: there is no checklist to look at.
    return (
      <Alert severity="info" data-testid="discovery-pending">
        <AlertTitle>One-time setup</AlertTitle>
        {result.detail}{' '}
        {CUSTOM_COMPANIES_CONFIG.isDiscoveryProgressEnabled
          ? 'Follow it step by step on its row in your companies list below — it starts tracking automatically once we can read the board.'
          : 'It now shows as “Setting up…” in your companies list below and starts tracking automatically once the first scan finishes.'}
      </Alert>
    );
  }

  if (result !== undefined) {
    // A board we discovered on an earlier attempt — resolved idempotently.
    return (
      <Alert severity="success" data-testid="discovery-already-tracked">
        <AlertTitle>Now tracking {result.displayName}</AlertTitle>
        We&apos;ll build its hiring history from here.{' '}
        <Link component={RouterLink} to={buildMyCompanyDetailPath(result.id)}>
          View its trend page
        </Link>
      </Alert>
    );
  }

  if (error !== undefined) {
    return (
      <Alert severity="warning" data-testid="discovery-error">
        <AlertTitle>We couldn&apos;t set that board up</AlertTitle>
        <Typography variant="body2">
          {extractErrorMessage(error, "The one-time setup couldn't be started. Please try again.")}
        </Typography>
        <Typography variant="body2" sx={{ mt: 1 }}>
          We can always read {SUPPORTED_BOARDS} boards without any setup — if this company
          uses one, pasting a link to its actual job listings will track it right away.
        </Typography>
      </Alert>
    );
  }

  // Reachable only in the handoff between the resolve call rejecting and the discovery
  // POST being dispatched. The page hides this block behind its own busy flag for exactly
  // that window, but rendering a truthful line beats rendering `null` if that flag is ever
  // wired wrong — a blank page after a submit is the failure this branch exists to prevent.
  return (
    <Alert severity="info" data-testid="discovery-starting">
      Starting a one-time setup for this board…
    </Alert>
  );
}
