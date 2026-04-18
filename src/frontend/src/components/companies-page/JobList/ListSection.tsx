import { Box, Paper, Typography } from '@mui/material';
import { useAppSelector } from '../../../app/hooks';
import { JobList } from './JobList';
import { ListFilters } from '../ListFilters.tsx';
import { SignInOverlay } from '../../shared/SignInOverlay.tsx';
import { selectListFilteredJobs } from '../../../features/filters/selectors/listFiltersSelectors.ts';
import { selectCurrentCompanyLoadingRtk } from '../../../features/jobs/jobsSelectors';
import { useAuth } from '../../../features/auth/useAuth.ts';
import { SIGN_IN_OVERLAY_CONFIG } from '../../../constants/ui.ts';

/**
 * Job list section with filters.
 *
 * When the user is signed out, the list is capped at
 * SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT and a SignInOverlay is shown to
 * prompt sign-up. Because this section lives inside a `<Paper>`, the overlay
 * uses the `'paper'` background variant so its gradient fades to the same
 * color as the surrounding container.
 */
export function ListSection() {
  const jobs = useAppSelector(selectListFilteredJobs);
  const isLoading = useAppSelector(selectCurrentCompanyLoadingRtk);
  const { isAuthenticated, isEnabled } = useAuth();

  const isSignedOut = isEnabled && !isAuthenticated;
  const visibleJobs = isSignedOut
    ? jobs.slice(0, SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT)
    : jobs;
  const showSignInOverlay =
    isSignedOut && jobs.length > SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT;

  return (
    <Paper sx={{ p: { xs: 2, sm: 3 } }}>
      <Typography variant="h5" component="h2" gutterBottom>
        Job Listings
      </Typography>

      <ListFilters />

      <Box
        sx={{
          position: 'relative',
          ...(showSignInOverlay && { overflow: 'hidden' }),
        }}
      >
        <JobList jobs={visibleJobs} isLoading={isLoading} />
        {showSignInOverlay && <SignInOverlay background="paper" />}
      </Box>
    </Paper>
  );
}
