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
import { TrackAnywayAction } from './TrackAnywayAction';

interface AddCompanyCTAProps {
  /** The resolver's final URL — what we actually probed and now persist. */
  finalUrl: string;
}

/** Friendly headline per add-failure `reason`. Backend `detail` fills the body. */
const ADD_REASON_TITLES: Record<string, string> = {
  unsupported: "That board isn't supported yet",
  probe_failed: "We couldn't read that board",
  empty: 'That board has no open jobs right now',
  deadline_exceeded: 'That board took too long to answer',
  no_ats_detected: "We couldn't find a job board there",
};

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

  // Re-submits the SAME url with the override, so the already-published branch is
  // skipped and a private copy is created. Same mutation, so its result replaces the
  // notice below with the ordinary success alert — no second piece of state.
  const handleTrackAnyway = () => {
    void addUserCompany({ url: finalUrl, trackAnyway: true });
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
    // Nothing was created. The primary action is the link inside the notice; the
    // secondary one lives in `TrackAnywayAction`, shared with `DiscoveryStatus` so the
    // two places this notice appears cannot drift apart.
    return (
      <AlreadyPublicNotice
        result={data}
        action={<TrackAnywayAction onClick={handleTrackAnyway} isLoading={isLoading} />}
      />
    );
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
                {ADD_REASON_TITLES[failure.reason] ?? "We couldn't add that company"}
              </AlertTitle>
              {/* The trailing "(code: probe_failed)" is gone for every reason we have
                  copy for — the headline above already says it in English, and the raw
                  token was machine noise in the middle of a sentence. An UNMAPPED reason
                  still prints it: there the headline is generic, so the code is the only
                  thing that makes a screenshot diagnosable. */}
              {failure.detail || 'The board was rejected.'}
              {ADD_REASON_TITLES[failure.reason] ? '' : ` (code: ${failure.reason})`}
            </>
          ) : (
            extractErrorMessage(error, "We couldn't add that company. Please try again.")
          )}
        </Alert>
      )}
    </Box>
  );
}
