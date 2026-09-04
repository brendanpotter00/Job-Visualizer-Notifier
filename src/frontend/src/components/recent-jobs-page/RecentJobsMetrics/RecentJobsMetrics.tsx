import { Paper, Stack, Divider } from '@mui/material';
import { MetricCard } from '../../companies-page/MetricsDashboard/MetricCard.tsx';
import { RESPONSIVE } from '../../../config/responsive';

interface RecentJobsMetricsProps {
  /**
   * `null` means the number is NOT KNOWN — page 1 has not landed, or it failed
   * and the hook deliberately dropped the previous filter set's figures. It is
   * never "zero": rendering an unknown count as 0 puts "0 Displayed Jobs" over an
   * error banner, which reads as "your filters matched nothing" and sends the
   * reader off to widen filters that were never the problem.
   */
  totalJobs: number | null;
  jobsLast24Hours: number | null;
  jobsLast3Hours: number | null;
  /**
   * The numbers on screen describe the PREVIOUS filter set and a new page 1 is in
   * flight (`isRefreshing`). They are kept rather than blanked — the tiles
   * vanishing on every filter edit is its own kind of wrong — but they are dimmed
   * and marked `aria-busy` so "not current yet" is visible rather than implied.
   */
  pending?: boolean;
}

/** What an unknown count renders as. An em-dash, never a zero. */
const UNKNOWN = '—';

const show = (value: number | null): number | string => (value === null ? UNKNOWN : value);

/**
 * Displays metrics for Recent Job Postings page
 * Matches styling of MetricsDashboard component
 * Shows total jobs and time-based counts (24h, 3h)
 */
export function RecentJobsMetrics({
  totalJobs,
  jobsLast24Hours,
  jobsLast3Hours,
  pending = false,
}: RecentJobsMetricsProps) {
  return (
    <Paper
      aria-busy={pending || undefined}
      sx={{
        p: RESPONSIVE.spacing.paperPadding,
        mb: RESPONSIVE.spacing.sectionMarginB,
        opacity: pending ? 0.5 : 1,
        transition: 'opacity 150ms ease-out',
      }}
    >
      {/* Always a horizontal 3-up row (was column on xs, which stacked the three
          numbers vertically and filled the whole phone screen). */}
      <Stack
        direction="row"
        spacing={RESPONSIVE.spacing.rowSpacing}
        divider={<Divider orientation="vertical" flexItem />}
        sx={{ mb: { xs: 0, sm: 3 } }}
      >
        <MetricCard value={show(totalJobs)} label="Displayed Jobs" dense />
        <MetricCard value={show(jobsLast24Hours)} label="Past 24 Hours" dense />
        <MetricCard value={show(jobsLast3Hours)} label="Past 3 Hours" dense />
      </Stack>
    </Paper>
  );
}
