import { Stack, Divider } from '@mui/material';
import { MetricCard } from './MetricCard';
import { RESPONSIVE } from '../../../config/responsive';

interface MetricsRowProps {
  jobsLast3Days: number;
  jobsLast24Hours: number;
  jobsLast12Hours: number;
}

/**
 * Pure presentational component for displaying all job metrics in a row.
 *
 * Deliberately RECENCY ONLY. A "Total Jobs" tile led this row until it was
 * removed at the owner's request (2026-09-05) alongside the Recent page's
 * "Displayed Jobs": a standing headcount answers "how big is this board", which
 * is not what either page is for — the question here is how much hiring is
 * happening lately, and every remaining tile answers it. Recorded so the next
 * reader does not re-add it as an obvious omission.
 */
export function MetricsRow({ jobsLast3Days, jobsLast24Hours, jobsLast12Hours }: MetricsRowProps) {
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
      <MetricCard value={jobsLast3Days} label="Past 3 Days" dense />
      <MetricCard value={jobsLast24Hours} label="Past 24 Hours" dense />
      <MetricCard value={jobsLast12Hours} label="Past 12 Hours" dense />
    </Stack>
  );
}
