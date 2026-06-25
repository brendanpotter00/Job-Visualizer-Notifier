import { Stack, Divider } from '@mui/material';
import { MetricCard } from './MetricCard';
import { RESPONSIVE } from '../../../config/responsive';

interface MetricsRowProps {
  totalJobs: number;
  jobsLast3Days: number;
  jobsLast24Hours: number;
  jobsLast12Hours: number;
}

/**
 * Pure presentational component for displaying all job metrics in a row
 */
export function MetricsRow({
  totalJobs,
  jobsLast3Days,
  jobsLast24Hours,
  jobsLast12Hours,
}: MetricsRowProps) {
  return (
    // Always a horizontal row (was column on xs, which stacked the four numbers
    // vertically and filled the whole phone screen). `dense` shrinks the numbers
    // on mobile only; `rowSpacing`'s sm slot restates the current 3 == 24px, so
    // desktop is unchanged.
    <Stack
      direction="row"
      spacing={RESPONSIVE.spacing.rowSpacing}
      divider={<Divider orientation="vertical" flexItem />}
      sx={{ mb: { xs: 2, sm: 3 } }}
    >
      <MetricCard value={totalJobs} label="Total Jobs" dense />
      <MetricCard value={jobsLast3Days} label="Past 3 Days" dense />
      <MetricCard value={jobsLast24Hours} label="Past 24 Hours" dense />
      <MetricCard value={jobsLast12Hours} label="Past 12 Hours" dense />
    </Stack>
  );
}
