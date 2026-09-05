import { Paper, Stack, Divider } from '@mui/material';
import { MetricCard } from '../../companies-page/MetricsDashboard/MetricCard.tsx';
import { RESPONSIVE } from '../../../config/responsive';

interface RecentJobsMetricsProps {
  /**
   * `null` means the number is NOT KNOWN — page 1 has not landed, or it failed
   * and the hook deliberately dropped the previous filter set's figures. It is
   * never "zero": rendering an unknown count as 0 puts a confident number over an
   * error banner, which reads as "your filters matched nothing" and sends the
   * reader off to widen filters that were never the problem.
   *
   * Both are scoped to the companies the reader follows and to NOTHING else — not
   * category, level, keywords, locations or the time window. That is deliberate:
   * these two tiles answer "how busy is the market I follow", so a narrowed list
   * still sits under an unchanged market reading.
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

/** What an unknown count renders as. An em-dash, never a zero. */
const UNKNOWN = '—';

const show = (value: number | null): number | string => (value === null ? UNKNOWN : value);

/**
 * The Recent page's header metrics: how busy the market is, and nothing else.
 *
 * A "Displayed Jobs" tile led this row until it was removed at the owner's
 * request (2026-09-05). Worth writing down, because the obvious instinct is to
 * put a count back: since #277 the server does not compute the filtered total on
 * page 1 (fast searches beat exact counts), so the only figure this tile could
 * honestly show was a LOWER BOUND over the rows walked so far — "50+" above
 * exactly fifty cards. That is self-referential rather than informative: it
 * restates the list under it and climbs as the reader scrolls. The owner's
 * verdict was "it's useless if it says 50 plus jobs", and an uninformative number
 * costs more attention than it returns.
 *
 * So do not re-add it as a bare `jobs.length`, and do not re-add it by making the
 * server count again — that trade was already made deliberately. The list still
 * derives the same figure for `aria-setsize` (`features/jobs/resultTotal.ts`),
 * where ARIA needs a set size and honestly reports "unknown" mid-walk.
 */
export function RecentJobsMetrics({
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
      {/* Always a horizontal row (was column on xs, which stacked the numbers
          vertically and filled the whole phone screen). */}
      <Stack
        direction="row"
        spacing={RESPONSIVE.spacing.rowSpacing}
        divider={<Divider orientation="vertical" flexItem />}
        sx={{ mb: { xs: 0, sm: 3 } }}
      >
        <MetricCard value={show(jobsLast24Hours)} label="Past 24 Hours" dense />
        <MetricCard value={show(jobsLast3Hours)} label="Past 3 Hours" dense />
      </Stack>
    </Paper>
  );
}
