import { Link as RouterLink } from 'react-router-dom';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Link from '@mui/material/Link';
import Typography from '@mui/material/Typography';
import { buildMyCompanyDetailPath } from '../../config/routes';
import { CUSTOM_COMPANIES_CONFIG } from '../../config/customCompanies';
import { extractErrorMessage } from '../../lib/errors';
import {
  useAddUserCompanyMutation,
  isDiscoveryPending,
} from '../../features/userCompanies/userCompaniesApi';

interface DiscoveryCTAProps {
  /** The URL to hand to one-time discovery (the resolver's final URL). */
  url: string;
}

/**
 * "Try one-time discovery" — offered when a pasted URL resolves to no supported
 * ATS board (E7 Phase 3b). Posting the same `add` endpoint routes the URL to an
 * async discovery agent; the backend answers `202` (discovery_pending). Nothing is
 * tracked yet — the company surfaces in the list below after the first scan, or as
 * a "Not trackable" (`refused`) badge if it can't be read reliably.
 *
 * An idempotent re-add of a board discovered earlier resolves to the existing
 * tracked company (`200`), so a second click lands in the success branch.
 */
export function DiscoveryCTA({ url }: DiscoveryCTAProps) {
  const [addUserCompany, { isLoading, data, error }] = useAddUserCompanyMutation();

  const handleDiscover = () => {
    void addUserCompany({ url });
  };

  if (data !== undefined && isDiscoveryPending(data)) {
    // With the checklist on, the row below is now narrating the setup step by step, so
    // point at it instead of repeating "Setting up…" — rendering a second copy of the
    // same checklist here would say the same thing twice on a very short page. Flag OFF
    // keeps the original copy verbatim: there is no checklist to look at.
    return (
      <Alert severity="info" sx={{ mt: 2 }} data-testid="discovery-pending">
        <AlertTitle>One-time setup</AlertTitle>
        {data.detail}{' '}
        {CUSTOM_COMPANIES_CONFIG.isDiscoveryProgressEnabled
          ? 'Follow it step by step on its row in your companies list below — it starts tracking automatically once we can read the board.'
          : 'It now shows as “Setting up…” in your companies list below and starts tracking automatically once the first scan finishes.'}
      </Alert>
    );
  }

  if (data !== undefined) {
    // A board we discovered on an earlier attempt — resolved idempotently.
    return (
      <Alert severity="success" sx={{ mt: 2 }} data-testid="discovery-already-tracked">
        <AlertTitle>Now tracking {data.displayName}</AlertTitle>
        We&apos;ll build its hiring history from here.{' '}
        <Link component={RouterLink} to={buildMyCompanyDetailPath(data.id)}>
          View its trend page
        </Link>
      </Alert>
    );
  }

  return (
    <Box sx={{ mt: 2 }} data-testid="discovery-cta">
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        This isn&apos;t a job board we recognize yet. We can try a one-time setup to
        teach ourselves how to read it — it runs in the background and jobs appear
        after the first scan.
      </Typography>
      <Button
        variant="outlined"
        onClick={handleDiscover}
        disabled={isLoading}
        data-testid="discovery-button"
      >
        {isLoading ? 'Setting up…' : 'Try one-time discovery'}
      </Button>

      {error !== undefined && (
        <Alert severity="warning" sx={{ mt: 2 }} data-testid="discovery-error">
          {extractErrorMessage(error, "We couldn't start discovery. Please try again.")}
        </Alert>
      )}
    </Box>
  );
}
