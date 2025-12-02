import { Paper, Stack, Divider } from '@mui/material';
import { MetricCard } from '../MetricsDashboard/MetricCard';

interface RecentJobsMetricsProps {
  totalJobs: number;
  companiesRepresented: number;
  jobsLast24Hours: number;
  jobsLast3Hours: number;
}

/**
 * Displays metrics for Recent Job Postings page
 * Matches styling of MetricsDashboard component
 * Shows total jobs, companies, and time-based counts (24h, 3h)
 */
export function RecentJobsMetrics({
  totalJobs,
  companiesRepresented,
  jobsLast24Hours,
  jobsLast3Hours,
}: RecentJobsMetricsProps) {
  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={3} sx={{ mb: 3 }}>
        <MetricCard value={totalJobs} label="Total Job Postings" />
        <Divider orientation="vertical" flexItem />
        <MetricCard value={companiesRepresented} label="Companies Represented" />
        <Divider orientation="vertical" flexItem />
        <MetricCard value={jobsLast24Hours} label="Past 24 Hours" />
        <Divider orientation="vertical" flexItem />
        <MetricCard value={jobsLast3Hours} label="Past 3 Hours" />
      </Stack>
    </Paper>
  );
}
