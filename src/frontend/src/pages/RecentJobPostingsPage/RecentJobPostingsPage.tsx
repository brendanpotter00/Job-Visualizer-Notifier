import { useMemo } from 'react';
import { Container, Typography, Box, Alert } from '@mui/material';
import { useGetAllJobsQuery } from '../../features/jobs/jobsApi';
import { useAppSelector } from '../../app/hooks';
import {
  selectRecentJobsMetadata,
  selectRecentJobsTimeBasedCounts,
} from '../../features/filters/selectors/recentJobsSelectors';
import { selectEnabledCompanyIds } from '../../features/preferences/enabledCompaniesSlice';
import { useAuth } from '../../features/auth/useAuth';
import { RecentJobsMetrics } from '../../components/recent-jobs-page/RecentJobsMetrics/RecentJobsMetrics';
import { RecentJobsFilters } from '../../components/recent-jobs-page/RecentJobsFilters';
import { RecentJobsList } from '../../components/recent-jobs-page/RecentJobsList/RecentJobsList';
import { EditCompanyPreferencesRow } from '../../components/recent-jobs-page/EditCompanyPreferencesRow';
import { FetchProgressBar } from '../../components/companies-page/FetchProgressBar/FetchProgressBar';
import { FetchProgressBarSkeleton } from '../../components/companies-page/FetchProgressBar/FetchProgressBarSkeleton';
import { ERROR_MESSAGES } from '../../constants/messages';

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
  const enabledIds = useAppSelector(selectEnabledCompanyIds);
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  // Constrain the progress bar's chips/totals to the user's enabled set.
  // null/[] = "all enabled" (matches the recent-jobs selector semantics).
  const progressFilter = useMemo(
    () => (enabledIds && enabledIds.length > 0 ? new Set(enabledIds) : null),
    [enabledIds]
  );
  // Avoid flashing the full company list before the signed-in user's enabled
  // preferences arrive. Render once either: auth has resolved to signed-out,
  // or we have the user's ids in hand.
  const preferencesReady = !authLoading && (!isAuthenticated || enabledIds !== null);

  return (
    <Container maxWidth="xl">
      <Box sx={{ my: 4 }}>
        <Typography variant="h3" component="h1" gutterBottom>
          Recent Job Postings
        </Typography>
        <EditCompanyPreferencesRow />
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
            {data &&
              (preferencesReady ? (
                <FetchProgressBar companyIdFilter={progressFilter} />
              ) : (
                <FetchProgressBarSkeleton />
              ))}
            <RecentJobsFilters />
            <RecentJobsList />
          </>
        )}
      </Box>
    </Container>
  );
}
