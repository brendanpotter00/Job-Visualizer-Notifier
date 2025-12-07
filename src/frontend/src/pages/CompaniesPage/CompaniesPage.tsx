import { Box, Container, Alert, Button } from '@mui/material';
import { Refresh } from '@mui/icons-material';
import { useAppSelector, useCompanyLoader } from '../../app/hooks';
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
  const { isLoading, error, handleRetry } = useCompanyLoader();

  const showLoading = globalLoading || isLoading;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100%' }}>
      <Container maxWidth="xl" sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <Box sx={{ my: 4, flex: 1 }}>
          <CompaniesPageHeader />

          {error && (
            <Alert
              severity="error"
              sx={{ mb: 3 }}
              action={
                <Button
                  color="inherit"
                  size="small"
                  onClick={handleRetry}
                  startIcon={<Refresh />}
                  disabled={isLoading}
                >
                  Retry
                </Button>
              }
            >
              Failed to load job data: {error}
            </Alert>
          )}

          <CompaniesPageContent isLoading={showLoading} />

          <BucketJobsModal />
        </Box>
      </Container>
    </Box>
  );
}
