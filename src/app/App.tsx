import { Box, Container, Alert, Button, capitalize } from '@mui/material';
import { Refresh } from '@mui/icons-material';
import { useAppSelector, useURLSync, useCompanyLoader, useBrowserNavigation } from './hooks';
import { AppHeader } from '../components/AppLayout/AppHeader';
import { AppContent } from '../components/AppLayout/AppContent';
import { BucketJobsModal } from '../components/BucketJobsModal/BucketJobsModal';
import { getCompanyById } from '../config/companies';

/**
 * Root application component
 *
 * Coordinates routing, data loading, and layout composition.
 * Uses custom hooks for complex logic and presentational components for UI.
 */
function App() {
  const globalLoading = useAppSelector((state) => state.ui.globalLoading);

  // Custom hooks handle complex side effects and business logic
  const { isLoading, error, handleRetry } = useCompanyLoader();
  useURLSync();
  useBrowserNavigation();

  const showLoading = globalLoading || isLoading;

  return (
    <Container maxWidth="xl">
      <Box sx={{ my: 4 }}>
        <AppHeader />

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

        <AppContent isLoading={showLoading} />

        <BucketJobsModal />
      </Box>
    </Container>
  );
}

export default App;
