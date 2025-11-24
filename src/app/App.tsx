import { useEffect } from 'react';
import { Box, Typography, Container, CircularProgress, Stack, Alert, Button } from '@mui/material';
import { Refresh } from '@mui/icons-material';
import { useAppDispatch, useAppSelector } from './hooks';
import { loadJobsForCompany } from '../features/jobs/jobsThunks';
import {
  selectCurrentCompanyError,
  selectCurrentCompanyLoading,
} from '../features/jobs/jobsSelectors';
import { CompanySelector } from '../components/CompanySelector/CompanySelector';
import { GraphSection } from '../components/JobPostingsChart/GraphSection';
import { ListSection } from '../components/JobList/ListSection';
import { BucketJobsModal } from '../components/BucketJobsModal/BucketJobsModal';
import { getCompanyById } from '../config/companies';

/**
 * Root application component
 */
function App() {
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const globalLoading = useAppSelector((state) => state.ui.globalLoading);
  const isLoading = useAppSelector(selectCurrentCompanyLoading);
  const error = useAppSelector(selectCurrentCompanyError);

  // Get selected company name
  const companyName = getCompanyById(selectedCompanyId)?.name || 'Job Posting Analytics';

  // Load jobs on mount and when company changes
  useEffect(() => {
    dispatch(
      loadJobsForCompany({
        companyId: selectedCompanyId,
      })
    );
  }, [dispatch, selectedCompanyId]);

  const handleRetry = () => {
    dispatch(
      loadJobsForCompany({
        companyId: selectedCompanyId,
      })
    );
  };

  return (
    <Container maxWidth="xl">
      <Box sx={{ my: 4 }}>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={2}
          alignItems={{ xs: 'flex-start', sm: 'center' }}
          justifyContent="space-between"
          sx={{ mb: 4 }}
        >
          <Typography variant="h3" component="h1">
            {companyName} - Job Posting Analytics
          </Typography>
          <CompanySelector />
        </Stack>

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

        {globalLoading || isLoading ? (
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '400px',
            }}
          >
            <CircularProgress size={60} />
          </Box>
        ) : (
          <Stack spacing={3}>
            <GraphSection />
            <ListSection />
          </Stack>
        )}

        <BucketJobsModal />
      </Box>
    </Container>
  );
}

export default App;
