import { Paper, Stack } from '@mui/material';
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
   * Scoped to the companies the reader follows and to NOTHING else — not
   * category, level, keywords, locations or the time window. That is deliberate:
   * this tile answers "how busy is the market I follow", so a narrowed list still
   * sits under an unchanged market reading.
   */
  jobsLast24Hours: number | null;
  /**
   * The number on screen describes the PREVIOUS filter set and a new page 1 is in
   * flight (`isRefreshing`). It is kept rather than blanked — the tile vanishing
   * on every filter edit is its own kind of wrong — but it is dimmed and marked
   * `aria-busy` so "not current yet" is visible rather than implied.
   */
  pending?: boolean;
}

/** What an unknown count renders as. An em-dash, never a zero. */
const UNKNOWN = '—';

const show = (value: number | null): number | string => (value === null ? UNKNOWN : value);

/**
 * The Recent page's header metric: how busy the market is, and nothing else.
 *
 * Down to ONE tile, by two separate owner calls, and both are worth writing down
 * because the instinct on seeing a single number is to put companions back:
 *
 *  * **"Displayed Jobs" (removed 2026-09-05.)** Since #277 the server does not
 *    compute the filtered total on page 1 — fast searches beat exact counts — so
 *    the only figure it could honestly show was a LOWER BOUND over the rows walked
 *    so far: "50+" above exactly fifty cards. That restates the list under it and
 *    climbs as the reader scrolls. Verdict: "it's useless if it says 50 plus
 *    jobs". Do not re-add it as a bare `jobs.length`, and do not re-add it by
 *    making the server count again. The list still derives that figure for
 *    `aria-setsize` (`features/jobs/resultTotal.ts`), where ARIA needs a set size
 *    and honestly reports "unknown" mid-walk.
 *  * **"Past 3 Hours" (removed 2026-09-05.)** Two windows over the same question
 *    is one more than the question needs, and the shorter one is mostly noise —
 *    on a normal day it is a single-digit number that says little on its own.
 *    `counts.last3h` is still on the wire and still served by the WebMCP
 *    `search_jobs` tool; only the tile is gone. Keep it that way: the backend
 *    computes both windows as two FILTER clauses over ONE scan, so dropping the
 *    3h count server-side would save nothing, and the 2026-08-10 incident is
 *    diagnosed by 24h and 3h being suspiciously EQUAL (see
 *    `docs/incidents/2026-08-10-recent-jobs-empty-filter-deadlock.md`) — a
 *    comparison that needs both numbers to exist.
 */
export function RecentJobsMetrics({ jobsLast24Hours, pending = false }: RecentJobsMetricsProps) {
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
      {/* Still a Stack rather than a bare MetricCard: the row is one tile TODAY,
          and this keeps the layout (and the vertical dividers) ready if another
          window is ever added back. No `divider` prop — a single child would
          render none anyway, and MUI would still walk the list to find that out. */}
      <Stack direction="row" spacing={RESPONSIVE.spacing.rowSpacing} sx={{ mb: { xs: 0, sm: 3 } }}>
        <MetricCard value={show(jobsLast24Hours)} label="Past 24 Hours" dense />
      </Stack>
    </Paper>
  );
}
