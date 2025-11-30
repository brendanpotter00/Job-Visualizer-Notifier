import { Box, Container, Alert, Button } from '@mui/material';
import { Refresh } from '@mui/icons-material';
import { useAppSelector, useURLSync, useCompanyLoader, useBrowserNavigation } from './hooks';
import { AppHeader } from '../components/AppLayout/AppHeader';
import { AppContent } from '../components/AppLayout/AppContent';
import { BucketJobsModal } from '../components/BucketJobsModal/BucketJobsModal';
import { AppFooter } from '../components/AppLayout/AppFooter.tsx';

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
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <Container maxWidth="xl" sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <Box sx={{ my: 4, flex: 1 }}>
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
      <AppFooter />
    </Box>
  );
}

export default App;
