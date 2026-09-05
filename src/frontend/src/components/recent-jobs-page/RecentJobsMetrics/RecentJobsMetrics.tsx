import { Paper, Stack, Divider } from '@mui/material';
import { MetricCard } from '../../companies-page/MetricsDashboard/MetricCard.tsx';
import { RESPONSIVE } from '../../../config/responsive';
import {
  formatResultTotal,
  UNKNOWN_TOTAL,
  type ResultTotal,
} from '../../../features/jobs/resultTotal.ts';

interface RecentJobsMetricsProps {
  /**
   * How many jobs the filter set holds, to whatever precision is honest.
   *
   * NOT a plain number, because since #277 the exact total usually does not
   * exist: the server defers it and the rows walked so far are a lower bound, so
   * this tile shows "50+". It rendered a bare em-dash for every real search until
   * that bound was plumbed through — the count was there the whole time, in the
   * rows on screen, and the header simply had no way to say "at least".
   *
   * `unknown` still renders the em-dash, and still must: it means page 1 has not
   * landed or it failed and the previous filter set's figures were deliberately
   * dropped. Never "zero" — "0 Displayed Jobs" over an error banner reads as
   * "your filters matched nothing" and sends the reader off to widen filters that
   * were never the problem.
   */
  totalJobs: ResultTotal;
  /**
   * `null` means NOT KNOWN, for the same reasons and with the same em-dash. These
   * two stay exact numbers — the server still counts them on every page 1; only
   * the filtered total was deferred.
   */
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

const show = (value: number | null): number | string => (value === null ? UNKNOWN_TOTAL : value);

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
        <MetricCard value={formatResultTotal(totalJobs)} label="Displayed Jobs" dense />
        <MetricCard value={show(jobsLast24Hours)} label="Past 24 Hours" dense />
        <MetricCard value={show(jobsLast3Hours)} label="Past 3 Hours" dense />
      </Stack>
    </Paper>
  );
}
