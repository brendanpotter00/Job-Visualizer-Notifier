import { Container, Typography, Box, Alert } from '@mui/material';
import { useGetAllJobsQuery } from '../../features/jobs/jobsApi';
import { useAppSelector } from '../../app/hooks';
import {
  selectRecentJobsMetadata,
  selectRecentJobsTimeBasedCounts,
} from '../../features/filters/recentJobsSelectors';
import { RecentJobsMetrics } from '../../components/RecentJobsMetrics';
import { RecentJobsFilters } from '../../components/RecentJobsFilters';
import { RecentJobsList } from '../../components/RecentJobsList';
import { FetchProgressBar } from '../../components/FetchProgressBar';
import { ERROR_MESSAGES } from '../../constants/messageConstants';

/**
 * Recent Job Postings page component
 *
 * Displays recently posted jobs across all companies using RTK Query
 * with 10-minute cache and automatic request deduplication.
 * Features independent filters and chronological job list.
 *
 * Uses memoized selectors for optimal performance:
 * - selectRecentJobsMetadata: Filtered job counts and company representation
 * - selectRecentJobsTimeBasedCounts: Time-based counts (24h and 3h windows)
 *
 * @returns Recent job postings page with loading, error, or data display
 */
export function RecentJobPostingsPage() {
  const { data, error } = useGetAllJobsQuery();
  const metadata = useAppSelector(selectRecentJobsMetadata);
  const timeBasedCounts = useAppSelector(selectRecentJobsTimeBasedCounts);

  return (
    <Container maxWidth="xl">
      <Box sx={{ my: 4 }}>
        <Typography variant="h3" component="h1" gutterBottom>
          Recent Job Postings
        </Typography>
        <Typography variant="body1" color="text.secondary" gutterBottom>
          View the latest job postings across all companies
        </Typography>

        {error ? (
          <Alert severity="error" sx={{ mb: 2 }}>
            {ERROR_MESSAGES.LOAD_JOBS_FAILED}
          </Alert>
        ) : null}

        {!error && data && (
          <>
            <RecentJobsMetrics
              totalJobs={metadata.filteredCount}
              companiesRepresented={metadata.companiesRepresented}
              jobsLast24Hours={timeBasedCounts.jobsLast24Hours}
              jobsLast3Hours={timeBasedCounts.jobsLast3Hours}
            />
              {data?.isStreaming && <FetchProgressBar />}
            <RecentJobsFilters />
            <RecentJobsList />
          </>
        )}
      </Box>
    </Container>
  );
}
