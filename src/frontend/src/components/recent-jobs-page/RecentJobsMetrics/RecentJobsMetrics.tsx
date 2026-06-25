import { Paper, Stack, Divider } from '@mui/material';
import { MetricCard } from '../../companies-page/MetricsDashboard/MetricCard.tsx';
import { RESPONSIVE } from '../../../config/responsive';

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
    <Paper sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}>
      {/* Always a horizontal 3-up row (was column on xs, which stacked the three
          numbers vertically and filled the whole phone screen). */}
      <Stack
        direction="row"
        spacing={RESPONSIVE.spacing.rowSpacing}
        divider={<Divider orientation="vertical" flexItem />}
        sx={{ mb: { xs: 0, sm: 3 } }}
      >
        <MetricCard value={totalJobs} label="Total Job Postings Displayed" dense />
        <MetricCard value={jobsLast24Hours} label="Past 24 Hours" dense />
        <MetricCard value={jobsLast3Hours} label="Past 3 Hours" dense />
      </Stack>
    </Paper>
  );
}
