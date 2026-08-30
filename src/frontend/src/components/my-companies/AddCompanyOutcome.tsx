import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import { buildMyCompanyDetailPath } from '../../config/routes';
import {
  SUPPORTED_BOARDS,
  describeResolveError,
} from '../../features/userCompanies/resolveErrors';
import {
  isAlreadyPublic,
  isDiscoveryPending,
  type AddUserCompanyFailure,
  type AddUserCompanyResult,
} from '../../features/userCompanies/userCompaniesApi';
import { DiscoveryStatus } from './DiscoveryStatus';

interface AddCompanyOutcomeProps {
  /** The add mutation's body, once it has one. `undefined` until it resolves. */
  result: AddUserCompanyResult | undefined;
  /** The add mutation's rejection, if it failed. Typed `unknown` — see `describeResolveError`. */
  error: unknown;
  /**
   * Re-send this URL with `trackAnyway`. Handed straight to `DiscoveryStatus`, which
   * offers it ONLY under a guessed (`matchKind: 'name'`) already-published notice.
   */
  onTrackAnyway?: (url: string) => void;
}

/**
 * The add endpoint's stable, machine-readable failure codes (backend-owned).
 *
 * A CLOSED union, mirroring `RESOLVE_FAILURE_REASONS` in `resolveErrors.ts`, and it
 * was not always one. `ADD_REASON_TITLES` used to be a plain `Record<string, string>`
 * with a `??` fallback, so adding a code to the backend without writing copy for it
 * compiled fine and silently rendered the generic headline — a missing case that only
 * a user could discover. With the map keyed by this union, a new code is a compile
 * error at build time instead. The WIRE type stays `string` (see
 * `AddUserCompanyFailure`): the server owns the list and may add to it, so an unknown
 * code from a newer server must still render, and `asKnownAddReason` is what narrows.
 */
const ADD_FAILURE_REASONS = [
  'unsupported',
  'probe_failed',
  'empty',
  'deadline_exceeded',
  'no_ats_detected',
  'monthly_limit_reached',
] as const;

type AddFailureReason = (typeof ADD_FAILURE_REASONS)[number];

/** Friendly headline per add-failure `reason`. Backend `detail` fills the body. */
const ADD_REASON_TITLES: Record<AddFailureReason, string> = {
  unsupported: "That board isn't supported yet",
  probe_failed: "We couldn't read that board",
  empty: 'That board has no open jobs right now',
  deadline_exceeded: 'That board took too long to answer',
  no_ats_detected: "We couldn't find a job board there",
  // The monthly cap. The counter at the top of the page already says how many are
  // left and when they come back, so this headline only has to name what happened —
  // the server's `detail` carries the numbers.
  monthly_limit_reached: "You've used this month's company adds",
};

const KNOWN_ADD_REASONS = new Set<string>(ADD_FAILURE_REASONS);

/** Narrows a wire `reason` to the closed union, or `null` for anything new. */
function asKnownAddReason(reason: string): AddFailureReason | null {
  return KNOWN_ADD_REASONS.has(reason) ? (reason as AddFailureReason) : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** Narrows an RTK Query error to the flat add-failure body (422 with a reason). */
function asAddFailure(error: unknown): AddUserCompanyFailure | null {
  if (!isRecord(error) || error.status !== 422) return null;
  const data = (error as { data?: unknown }).data;
  if (isRecord(data) && typeof data.reason === 'string') {
    return {
      reason: data.reason,
      detail: typeof data.detail === 'string' ? data.detail : '',
      finalUrl: typeof data.finalUrl === 'string' ? data.finalUrl : '',
    };
  }
  return null;
}

/**
 * Everything one press of **Add company** can land on.
 *
 * ONE COMPONENT because there is now one call. This file used to be `AddCompanyCTA` —
 * a "Track this company" button rendered inside a preview card, owning its own
 * mutation, reachable only after a separate `POST /api/companies/resolve` had already
 * succeeded. The preview and the second press are gone: the page fires the add
 * straight from the submit and hands the result here.
 *
 * Four terminal outcomes, and the endpoint decides which:
 *
 *  - **201 / 200 `UserCompany`** — created, or an idempotent re-add of a board this
 *    user already owns. The success card below, linking to its private trend page.
 *    Deliberately does NOT quote a job count: on a fresh add the row's
 *    `openJobCount` is 0 because the first harvest was only just enqueued, and the
 *    list right below carries the real number the moment it lands.
 *  - **200 `already_public`** — a board we already publish. `DiscoveryStatus` renders
 *    it, including the `trackAnyway` correction on the guessed match only.
 *  - **202 `discovery_pending`** — a one-time setup started. Also `DiscoveryStatus`.
 *  - **an error** — the alert at the bottom.
 *
 * THE FAILURE ALERT NOW SPEAKS TWO VOCABULARIES, and it has to. When the page still
 * called `/resolve` first, a URL-shaped refusal (`scheme_not_https`,
 * `dns_resolution_failed`, a 429, a 503) was answered by the RESOLVE call and rendered
 * by `ResolveErrorDisplay`. Those failures now arrive from the ADD call instead, so
 * this alert falls back to `describeResolveError` for anything outside the add
 * endpoint's own six codes. Without that fallback a mistyped scheme would render the
 * generic "we couldn't add that company" plus a raw `(code: scheme_not_https)`.
 */
export function AddCompanyOutcome({ result, error, onTrackAnyway }: AddCompanyOutcomeProps) {
  if (error !== undefined) {
    const failure = asAddFailure(error);
    const knownReason = failure ? asKnownAddReason(failure.reason) : null;
    // `describeResolveError` handles EVERY other shape this call can fail with: the
    // resolver's own flat 422 reasons, FastAPI's `{detail: [...]}` validation body,
    // 401 / 429 / 502 / 503, and RTK Query's non-HTTP statuses. It never returns an
    // empty title or detail, which is the property that keeps `[object Object]` off
    // the screen.
    const fallback = describeResolveError(error);
    const title = knownReason ? ADD_REASON_TITLES[knownReason] : fallback.title;
    const detail = knownReason ? failure!.detail || 'The board was rejected.' : fallback.detail;

    return (
      <Alert severity="warning" data-testid="add-company-error">
        <AlertTitle>{title}</AlertTitle>
        <Typography variant="body2">{detail}</Typography>
        {/* The one piece of advice worth adding, and only where it is true: we could
            not find a board behind this URL and discovery is not going to be tried.
            Deliberately NOT shown for the monthly cap — "paste a supported board
            instead" would send someone off to find a different URL when no URL was
            ever the problem. */}
        {knownReason === 'no_ats_detected' && (
          <Typography variant="body2" sx={{ mt: 1 }}>
            We read {SUPPORTED_BOARDS} boards with no setup at all — if this company
            uses one, paste a link to its job listings instead.
          </Typography>
        )}
      </Alert>
    );
  }

  if (result === undefined) return null;

  if (isDiscoveryPending(result) || isAlreadyPublic(result)) {
    // Both bodies already have a component that renders them exactly right, including
    // the certainty rule that decides whether the already-published notice has a way
    // past it. Re-implementing either here would be a second place for that rule to
    // live.
    return <DiscoveryStatus result={result} onTrackAnyway={onTrackAnyway} />;
  }

  return (
    <Alert severity="success" data-testid="add-company-success">
      <AlertTitle>Now tracking {result.displayName}</AlertTitle>
      We&apos;ll build its hiring history from here.{' '}
      <Link
        component={RouterLink}
        to={buildMyCompanyDetailPath(result.id)}
        data-testid="view-company-link"
      >
        View its trend page
      </Link>
    </Alert>
  );
}
