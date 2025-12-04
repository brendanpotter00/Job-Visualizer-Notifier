import { Stack, Divider } from '@mui/material';
import { MetricCard } from './MetricCard';

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
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={3}
      divider={<Divider orientation="vertical" flexItem />}
      sx={{ mb: 3 }}
    >
      <MetricCard value={totalJobs} label="Total Jobs" />
      <MetricCard value={jobsLast3Days} label="Past 3 Days" />
      <MetricCard value={jobsLast24Hours} label="Past 24 Hours" />
      <MetricCard value={jobsLast12Hours} label="Past 12 Hours" />
    </Stack>
  );
}
