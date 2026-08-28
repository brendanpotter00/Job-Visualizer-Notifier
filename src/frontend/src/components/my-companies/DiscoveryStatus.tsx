import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import { buildMyCompanyDetailPath } from '../../config/routes';
import { extractErrorMessage } from '../../lib/errors';
import { SUPPORTED_BOARDS } from '../../features/userCompanies/resolveErrors';
import {
  isAlreadyPublic,
  isDiscoveryPending,
  isMonthlyLimitError,
  isNameGuessMatch,
  type AddUserCompanyResult,
} from '../../features/userCompanies/userCompaniesApi';
import { AlreadyPublicNotice } from './AlreadyPublicNotice';
import { TrackAnywayAction } from './TrackAnywayAction';

interface DiscoveryStatusProps {
  /** The add mutation's body, once it has one: a `202` pending or a `200`/`201` company. */
  result: AddUserCompanyResult | undefined;
  /** The add mutation's rejection, if it failed. Typed `unknown` — see `extractErrorMessage`. */
  error: unknown;
  /**
   * Re-send this URL with `trackAnyway`, creating the board as its own company after
   * all. Used ONLY on a `matchKind: 'name'` result — the guessed match. Optional so a
   * caller with no mutation to lend can still render the notice; when it is absent (or
   * the match was exact) the already-published branch shows the link alone.
   */
  onTrackAnyway?: (url: string) => void;
  /** The parent's add mutation in flight — disables the correction while it runs. */
  isTracking?: boolean;
}

/**
 * What happened to the one-time discovery a non-ATS URL was routed into.
 *
 * PURELY PRESENTATIONAL — it owns no mutation. Discovery is kicked off by
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
export function DiscoveryStatus({
  result,
  error,
  onTrackAnyway,
  isTracking = false,
}: DiscoveryStatusProps) {
  if (result !== undefined && isDiscoveryPending(result)) {
    // One line after the server's own `detail`, and it says where to look — the row
    // below is already narrating the setup, so anything more here is a second copy of
    // it. Flag-free on purpose: "watch it in your list below" is true whether that row
    // shows the four-step checklist or just a "Setting up…" chip, and the two branches
    // this used to have were two ways of saying the same sentence.
    return (
      <Alert severity="info" data-testid="discovery-pending">
        <AlertTitle>Setting this board up</AlertTitle>
        {result.detail} Watch it in your list below.
      </Alert>
    );
  }

  if (result !== undefined && isAlreadyPublic(result)) {
    // NOT a rare branch any more, and that is the change. This component only ever
    // sees a result when the first resolve said `no_ats_detected`, which is where BOTH
    // of the backend's URL-shaped dedupe answers now land:
    //
    //  - the careers-host match, for the five `ats='script'` boards (Amazon, Apple,
    //    Google, Microsoft, TikTok) that no URL can spell as an ATS pair, and
    //  - the company-name match, for a vanity careers domain like `lifeatspotify.com`.
    //
    // ONLY THE SECOND GETS A WAY OUT, and the whole justification is in the difference.
    // A careers-host hit is an exact match against a declared table: the user pasted a
    // board we publish, and a private duplicate of it re-scrapes the same feed for a
    // chart whose history starts today instead of the full one behind the link above.
    // Offering that was a trap dressed as a choice, so that branch is terminal.
    //
    // A name hit is a guess from a string inside a domain. Its failure mode is a false
    // positive — somebody whose company merely shares a substring with one of ours — and
    // a guess with no way out would HARD-BLOCK them from adding a legitimately different
    // company with no way to tell us we were wrong. That is the worse anti-pattern, so
    // this one keeps the correction.
    //
    // The mutation is still the parent's; this only renders the button.
    const guessed = isNameGuessMatch(result);
    return (
      <AlreadyPublicNotice
        result={result}
        action={
          guessed && onTrackAnyway ? (
            <TrackAnywayAction
              onClick={() => onTrackAnyway(result.finalUrl)}
              isLoading={isTracking}
            />
          ) : undefined
        }
      />
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
    // The monthly cap is not a verdict about the BOARD, so it does not get the board
    // advice. "We read Greenhouse, Ashby, … with no setup at all — paste one of those
    // instead" would send someone off to find a different URL when no URL was ever the
    // problem. Same alert, no new UI: only the headline changes and the advice is
    // dropped. The counter at the top of the page carries the rest.
    //
    // Rare by construction — the submit is disabled at zero — but reachable whenever
    // the cached counter is a step behind the server (a second tab, an add from
    // another device), which is exactly when wrong advice would be most confusing.
    const outOfAdds = isMonthlyLimitError(error);
    return (
      <Alert severity="warning" data-testid="discovery-error">
        <AlertTitle>
          {outOfAdds
            ? "You've used this month's company adds"
            : "We couldn't set that board up"}
        </AlertTitle>
        <Typography variant="body2">
          {extractErrorMessage(error, "The one-time setup couldn't be started. Please try again.")}
        </Typography>
        {!outOfAdds && (
          <Typography variant="body2" sx={{ mt: 1 }}>
            We read {SUPPORTED_BOARDS} boards with no setup at all — if this company uses
            one, paste a link to its job listings instead.
          </Typography>
        )}
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
