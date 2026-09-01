import { Box, Button, Container, Paper, Typography } from '@mui/material';
import { RESPONSIVE } from '../../config/responsive';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { useAppSelector, useCompanyLoader } from '../../app/hooks';
import { useAuth } from '../../features/auth/useAuth';
import { CompaniesPageHeader } from './CompaniesPageHeader';
import { CompaniesPageContent } from './CompaniesPageContent';
import { BucketJobsModal } from '../../components/modals/BucketJobsModal/BucketJobsModal';

/**
 * Companies page component
 *
 * Main page showing job posting analytics for selected company.
 * Includes:
 * - Page header with company selector
 * - Error banner with retry button (if error)
 * - Graph and list sections (when loaded)
 * - Bucket jobs modal
 *
 * @returns Companies page with job analytics
 */
export function CompaniesPage() {
  const globalLoading = useAppSelector((state) => state.ui.globalLoading);
  const { isLoading, error, errorStatus, handleRetry } = useCompanyLoader();
  const { login } = useAuth();

  const showLoading = globalLoading || isLoading;

  // Only a user-added board can answer either of these, and both mean something
  // specific enough that the generic "Failed to load job data" banner would be
  // actively misleading — nothing failed, the viewer just cannot see this board.
  // Same two states the private trend page renders, worded the same way.
  const isSignedOutFromPrivateBoard = errorStatus === 401;
  const isNotOwner = errorStatus === 403;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100%' }}>
      <Container maxWidth="xl" sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <Box sx={{ my: RESPONSIVE.spacing.pageMarginY, flex: 1 }}>
          <CompaniesPageHeader />

          {isSignedOutFromPrivateBoard ? (
            <Paper sx={{ p: RESPONSIVE.spacing.paperPaddingLg, textAlign: 'center' }}>
              <Typography variant="h5" gutterBottom>
                Sign in to view this company
              </Typography>
              <Typography variant="body1" color="text.secondary" sx={{ mb: 3 }}>
                Companies you track are private to your account.
              </Typography>
              <Button variant="contained" onClick={login}>
                Sign In
              </Button>
            </Paper>
          ) : isNotOwner ? (
            <ErrorState
              title="Not your company"
              message="This isn't one of your tracked companies, so its jobs aren't visible to you."
            />
          ) : (
            <>
              {error && (
                <Box sx={{ mb: 3 }}>
                  <ErrorState
                    inline
                    message={`Failed to load job data: ${error}`}
                    onRetry={handleRetry}
                  />
                </Box>
              )}

              <CompaniesPageContent isLoading={showLoading} />
            </>
          )}

          <BucketJobsModal />
        </Box>
      </Container>
    </Box>
  );
}
