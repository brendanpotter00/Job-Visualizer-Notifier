import { Container, Typography, Box, CircularProgress, Alert } from '@mui/material';
import { useGetAllJobsQuery } from '../../features/jobs/jobsApi';
import { useAppSelector } from '../../app/hooks';
import {
  selectRecentJobsMetadata,
  selectAllJobsFromQuery,
} from '../../features/filters/recentJobsSelectors';
import { RecentJobsMetrics } from '../../components/RecentJobsMetrics';
import { RecentJobsFilters } from '../../components/RecentJobsFilters';
import { RecentJobsList } from '../../components/RecentJobsList';
import { useRecentJobsTimeBasedCounts } from '../../components/RecentJobsMetrics/hooks/useRecentJobsTimeBasedCounts';

/**
 * Recent Job Postings page component
 *
 * Displays recently posted jobs across all companies using RTK Query
 * with 10-minute cache and automatic request deduplication.
 * Features independent filters and chronological job list.
 *
 * @returns Recent job postings page with loading, error, or data display
 */
export function RecentJobPostingsPage() {
  const { data, isLoading, error } = useGetAllJobsQuery();
  const metadata = useAppSelector(selectRecentJobsMetadata);
  const allJobs = useAppSelector(selectAllJobsFromQuery);

  // Calculate time-based job counts (24h and 3h)
  const timeBasedCounts = useRecentJobsTimeBasedCounts(allJobs);

  return (
    <Container maxWidth="xl">
      <Box sx={{ my: 4 }}>
        <Typography variant="h3" component="h1" gutterBottom>
          Recent Job Postings
        </Typography>
        <Typography variant="body1" color="text.secondary" gutterBottom>
          View the latest job postings across all companies
        </Typography>

        {isLoading && (
          <Box display="flex" flexDirection="column" alignItems="center" py={8}>
            <CircularProgress />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              Loading job postings from all companies...
            </Typography>
          </Box>
        )}

        {error ? (
          <Alert severity="error" sx={{ mb: 2 }}>
            Failed to load job postings. Please try again later.
          </Alert>
        ) : null}

        {!isLoading && !error && data && (
          <>
            <RecentJobsMetrics
              totalJobs={metadata.filteredCount}
              companiesRepresented={metadata.companiesRepresented}
              jobsLast24Hours={timeBasedCounts.jobsLast24Hours}
              jobsLast3Hours={timeBasedCounts.jobsLast3Hours}
            />
            <RecentJobsFilters />
            <RecentJobsList />
          </>
        )}
      </Box>
    </Container>
  );
}
