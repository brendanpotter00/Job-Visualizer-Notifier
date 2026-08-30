import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import {
  isDiscoveryPending,
  isNameGuessMatch,
  type AlreadyPublicResponse,
  type DiscoveryPendingResponse,
} from '../../features/userCompanies/userCompaniesApi';
import { AlreadyPublicNotice } from './AlreadyPublicNotice';
import { TrackAnywayAction } from './TrackAnywayAction';

interface DiscoveryStatusProps {
  /** The `202` pending body, or the `200` "we already publish this" body. */
  result: DiscoveryPendingResponse | AlreadyPublicResponse;
  /**
   * Re-send this URL with `trackAnyway`, creating the board as its own company after
   * all. Used ONLY on a `matchKind: 'name'` result — the guessed match. Optional so a
   * caller with no mutation to lend can still render the notice; when it is absent (or
   * the match was exact) the already-published branch shows the link alone.
   */
  onTrackAnyway?: (url: string) => void;
}

/**
 * The two add outcomes that are neither a plain success nor a failure.
 *
 * PURELY PRESENTATIONAL — it owns no mutation. `AddCompanyOutcome` decides which
 * outcome a response is and hands the body here; the add mutation itself lives on
 * `MyCompaniesPage`, which needs its in-flight flag to keep the form disabled.
 *
 * It used to render four branches, because it used to be the whole outcome surface for
 * the discovery half of a two-call flow. Two of them are gone with that flow:
 *
 *  - a `UserCompany` body — `AddCompanyOutcome` renders every tracked-company success
 *    the same way now, whether the board is an ATS one or a re-add of a discovered one.
 *    Two success cards worded identically was one card too many.
 *  - an error, and a "starting a one-time setup…" placeholder for the window between
 *    the resolve rejecting and the discovery POST going out. There is no such window
 *    any more — there is one call — and errors are one alert in `AddCompanyOutcome`,
 *    which is also the only place that knows the add endpoint's own reason codes.
 */
export function DiscoveryStatus({ result, onTrackAnyway }: DiscoveryStatusProps) {
  if (isDiscoveryPending(result)) {
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

  // A company we ALREADY PUBLISH. Three server-side checks produce this body, and
  // ONLY THE WEAKEST GETS A WAY OUT — the whole justification is in the difference.
  //
  // A board match is exact: the `(ats, boardToken)` pair the resolver named, or a
  // careers host in our own declared table (Amazon, Apple, Google, Microsoft,
  // TikTok). The user pasted a board we publish, and a private duplicate of it
  // re-scrapes the same feed for a chart whose history starts today instead of the
  // full one behind the link above. Offering that was a trap dressed as a choice, so
  // those branches are terminal.
  //
  // A name match is a guess from a string inside a domain (`lifeatspotify.com` →
  // Spotify). Its failure mode is a false positive — somebody whose company merely
  // shares a substring with one of ours — and a guess with no way out would
  // HARD-BLOCK them from adding a legitimately different company with no way to tell
  // us we were wrong. That is the worse anti-pattern, so this one keeps the
  // correction.
  //
  // The mutation is still the parent's; this only renders the button.
  const guessed = isNameGuessMatch(result);
  return (
    <AlreadyPublicNotice
      result={result}
      action={
        guessed && onTrackAnyway ? (
          <TrackAnywayAction onClick={() => onTrackAnyway(result.finalUrl)} />
        ) : undefined
      }
    />
  );
}
