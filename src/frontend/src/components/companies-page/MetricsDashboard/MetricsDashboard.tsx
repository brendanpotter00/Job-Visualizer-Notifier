import { Paper, Divider } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';
import { useAppSelector } from '../../../app/hooks';
import { selectCurrentCompanyJobsRtk } from '../../../features/jobs/jobsSelectors';
import { selectEffectiveCompanyById } from '../../../features/userCompanies/effectiveCompanies';
import { useTimeBasedJobCounts } from './hooks/useTimeBasedJobCounts';
import { MetricsRow } from './MetricsRow';
import { LinksRow } from './LinksRow';

/**
 * Dashboard displaying key metrics and links above the graph
 */
export function MetricsDashboard() {
  const allJobs = useAppSelector(selectCurrentCompanyJobsRtk);
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);

  // Curated companies AND the viewer's own boards. For a custom board `jobsUrl`
  // is the board we actually read (`sourceBoardUrl`) and there is deliberately
  // no recruiter link. Already referentially stable — the option object comes
  // out of a memoized array — so no `useMemo` is needed around the lookup.
  const company = useAppSelector((state) => selectEffectiveCompanyById(state, selectedCompanyId));

  // Get time-based job counts using custom hook
  // Calculations are deterministic based on job.firstSeenAt timestamps
  const { jobsLast3Days, jobsLast24Hours, jobsLast12Hours } = useTimeBasedJobCounts(allJobs);

  return (
    <Paper sx={{ p: RESPONSIVE.spacing.paperPadding, mb: RESPONSIVE.spacing.sectionMarginB }}>
      <MetricsRow
        jobsLast3Days={jobsLast3Days}
        jobsLast24Hours={jobsLast24Hours}
        jobsLast12Hours={jobsLast12Hours}
      />

      <Divider sx={{ mb: 2 }} />

      <LinksRow jobsUrl={company?.jobsUrl} recruiterLinkedInUrl={company?.recruiterLinkedInUrl} />
    </Paper>
  );
}
