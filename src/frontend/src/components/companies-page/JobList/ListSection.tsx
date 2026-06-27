import { Box, Typography } from '@mui/material';
import { useAppSelector } from '../../../app/hooks';
import { JobList } from './JobList';
import { SignInOverlay } from '../../shared/SignInOverlay.tsx';
import { selectGraphFilteredJobsSorted } from '../../../features/filters/selectors/graphFiltersSelectors.ts';
import { selectCurrentCompanyLoadingRtk } from '../../../features/jobs/jobsSelectors';
import { useAuth } from '../../../features/auth/useAuth.ts';
import { SIGN_IN_OVERLAY_CONFIG } from '../../../constants/ui.ts';

/**
 * Job list section.
 *
 * Shares the graph's filters as the single source of truth — the list reflects
 * whatever the graph is filtered to, sorted most-recent-first.
 *
 * When the user is signed out, the list is capped at
 * SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT and a SignInOverlay is shown to
 * prompt sign-up. Because this section renders inside the page's shared
 * `<Paper>` card, the overlay uses the `'paper'` background variant so its
 * gradient fades to the same color as the surrounding container.
 */
export function ListSection() {
  const jobs = useAppSelector(selectGraphFilteredJobsSorted);
  const isLoading = useAppSelector(selectCurrentCompanyLoadingRtk);
  const { isAuthenticated, isEnabled } = useAuth();

  const isSignedOut = isEnabled && !isAuthenticated;
  const visibleJobs = isSignedOut
    ? jobs.slice(0, SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT)
    : jobs;
  const showSignInOverlay =
    isSignedOut && jobs.length > SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT;

  return (
    <>
      <Typography variant="h5" component="h2" gutterBottom>
        Job Listings
      </Typography>

      <Box
        sx={{
          position: 'relative',
          ...(showSignInOverlay && { overflow: 'hidden' }),
        }}
      >
        <JobList jobs={visibleJobs} isLoading={isLoading} />
        {showSignInOverlay && <SignInOverlay background="paper" page="companies" />}
      </Box>
    </>
  );
}
