import { Box, Container, Typography } from '@mui/material';
import { useGetAllJobsQuery } from '../../features/jobs/jobsApi';

/**
 * Recent Job Postings page component
 *
 * Displays recently posted jobs across all companies using RTK Query
 * with 10-minute cache and automatic request deduplication.
 *
 * @returns Recent job postings page with loading, error, or data display
 */
export function RecentJobPostingsPage() {
  const { data, isLoading, error } = useGetAllJobsQuery();

  console.log('All jobs data:', data);

  if (isLoading) {
    return (
      <Container maxWidth="xl">
        <Box sx={{ my: 4 }}>
          <Typography variant="h3" component="h1" gutterBottom>
            Recent Job Postings
          </Typography>
          <Typography variant="body1">Loading jobs from all companies...</Typography>
        </Box>
      </Container>
    );
  }

  if (error) {
    return (
      <Container maxWidth="xl">
        <Box sx={{ my: 4 }}>
          <Typography variant="h3" component="h1" gutterBottom>
            Recent Job Postings
          </Typography>
          <Typography variant="body1" color="error">
            Error loading jobs. Please try again later.
          </Typography>
        </Box>
      </Container>
    );
  }

  return (
    <Container maxWidth="xl">
      <Box sx={{ my: 4 }}>
        <Typography variant="h3" component="h1" gutterBottom>
          Recent Job Postings
        </Typography>
        <Typography variant="body1" color="text.secondary">
          Loaded jobs from {Object.keys(data?.byCompanyId || {}).length} companies.
        </Typography>
        {/* TODO: Add job list visualization here */}
      </Box>
    </Container>
  );
}
