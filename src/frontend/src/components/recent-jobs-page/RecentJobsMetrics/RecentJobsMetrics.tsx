import { Paper, Stack, Divider } from '@mui/material';
import { MetricCard } from '../../companies-page/MetricsDashboard/MetricCard.tsx';

interface RecentJobsMetricsProps {
  totalJobs: number;
  jobsLast24Hours: number;
  jobsLast3Hours: number;
}

/**
 * Displays metrics for Recent Job Postings page
 * Matches styling of MetricsDashboard component
 * Shows total jobs and time-based counts (24h, 3h)
 */
export function RecentJobsMetrics({
  totalJobs,
  jobsLast24Hours,
  jobsLast3Hours,
}: RecentJobsMetricsProps) {
  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3} sx={{ mb: 3 }}>
        <MetricCard value={totalJobs} label="Displayed Jobs" />
        <Divider orientation="vertical" flexItem />
        <MetricCard value={jobsLast24Hours} label="Past 24 Hours" />
        <Divider orientation="vertical" flexItem />
        <MetricCard value={jobsLast3Hours} label="Past 3 Hours" />
      </Stack>
    </Paper>
  );
}
