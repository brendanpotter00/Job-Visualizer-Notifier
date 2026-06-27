import { Box, Container } from '@mui/material';
import { RESPONSIVE } from '../../config/responsive';
import { ErrorState } from '../../components/shared/ErrorDisplay';
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
        <Box sx={{ my: RESPONSIVE.spacing.pageMarginY, flex: 1 }}>
          <CompaniesPageHeader />

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

          <BucketJobsModal />
        </Box>
      </Container>
    </Box>
  );
}
