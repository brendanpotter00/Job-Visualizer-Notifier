import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import { buildMyCompanyDetailPath } from '../../config/routes';
import { extractErrorMessage } from '../../lib/errors';
import {
  useAddUserCompanyMutation,
  isAlreadyPublic,
  isDiscoveryPending,
  type AddUserCompanyFailure,
} from '../../features/userCompanies/userCompaniesApi';
import { AlreadyPublicNotice } from './AlreadyPublicNotice';

interface AddCompanyCTAProps {
  /** The resolver's final URL — what we actually probed and now persist. */
  finalUrl: string;
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
 * "Track this company" call-to-action, rendered inside the successful-resolve
 * block. Persists the resolved board to the caller's account via
 * `POST /api/users/companies` and links onward to its private trend page.
 *
 * Idempotent by design: re-adding an already-owned board returns `200` with the
 * same `UserCompany`, so a second click lands in the success branch rather than
 * crashing — nothing here special-cases "already added".
 */
export function AddCompanyCTA({ finalUrl }: AddCompanyCTAProps) {
  const [addUserCompany, { isLoading, data, error }] = useAddUserCompanyMutation();

  const handleAdd = () => {
    // Fire-and-forget: the rendered state below reads from the mutation result,
    // and the rejection is already surfaced as `error`.
    void addUserCompany({ url: finalUrl });
  };

  if (data !== undefined && isDiscoveryPending(data)) {
    // A non-ATS URL was routed to one-time discovery (async). Nothing is tracked
    // yet — it will surface in the list below after the first scan.
    return (
      <Alert severity="info" sx={{ mt: 2 }} data-testid="add-company-discovery-pending">
        <AlertTitle>One-time setup</AlertTitle>
        {data.detail}
      </Alert>
    );
  }

  if (data !== undefined && isAlreadyPublic(data)) {
    // TERMINAL, and no escape hatch — that is deliberate, and it is a change.
    //
    // This component only renders after a SUCCESSFUL resolve, which means the resolver
    // named an `(ats, boardToken)` pair. So the only `already_public` that can land here
    // is the exact board-token match: the user pasted a board we already publish, by its
    // own identifier. There is no plausible reading where they meant a different company.
    //
    // We used to offer "Track it separately anyway" here. It was a trap dressed as a
    // choice: a private duplicate re-scrapes the same feed, costs the user a setup, and
    // gives them a chart whose history starts TODAY instead of the full history sitting
    // one click away behind the link in this notice. The notice's own copy said so.
    // Offering a strictly worse option is not user agency.
    //
    // The GUESSED match keeps its way out, because there the risk is a false positive
    // rather than a duplicate — see `DiscoveryStatus`, which is the only place that
    // branch can land (a name guess only happens when no ATS board resolved at all, and
    // this component never renders in that case).
    return <AlreadyPublicNotice result={data} />;
  }

  if (data !== undefined) {
    return (
      <Alert severity="success" sx={{ mt: 2 }} data-testid="add-company-success">
        <AlertTitle>Now tracking {data.displayName}</AlertTitle>
        We&apos;ll build its hiring history from here.{' '}
        <Link
          component={RouterLink}
          to={buildMyCompanyDetailPath(data.id)}
          data-testid="view-company-link"
        >
          View its trend page
        </Link>
      </Alert>
    );
  }

  const failure = asAddFailure(error);
  const knownReason = failure ? asKnownAddReason(failure.reason) : null;

  return (
    <Box sx={{ mt: 2 }}>
      <Button
        variant="contained"
        onClick={handleAdd}
        disabled={isLoading}
        data-testid="add-company-button"
      >
        {isLoading ? 'Adding…' : 'Track this company'}
      </Button>

      {error !== undefined && (
        <Alert severity="warning" sx={{ mt: 2 }} data-testid="add-company-error">
          {failure ? (
            <>
              <AlertTitle>
                {knownReason ? ADD_REASON_TITLES[knownReason] : "We couldn't add that company"}
              </AlertTitle>
              {/* The trailing "(code: probe_failed)" is gone for every reason we have
                  copy for — the headline above already says it in English, and the raw
                  token was machine noise in the middle of a sentence. An UNMAPPED reason
                  still prints it: there the headline is generic, so the code is the only
                  thing that makes a screenshot diagnosable. */}
              {failure.detail || 'The board was rejected.'}
              {knownReason ? '' : ` (code: ${failure.reason})`}
            </>
          ) : (
            extractErrorMessage(error, "We couldn't add that company. Please try again.")
          )}
        </Alert>
      )}
    </Box>
  );
}
