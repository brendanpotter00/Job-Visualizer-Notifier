import { Paper, Divider } from '@mui/material';
import { useMemo } from 'react';
import { useAppSelector } from '../../app/hooks';
import {
  selectCurrentCompanyMetadataRtk,
  selectCurrentCompanyJobsRtk,
} from '../../features/jobs/jobsSelectors';
import { getCompanyById } from '../../config/companies';
import { useTimeBasedJobCounts } from './hooks/useTimeBasedJobCounts';
import { MetricsRow } from './MetricsRow';
import { LinksRow } from './LinksRow';

/**
 * Dashboard displaying key metrics and links above the graph
 */
export function MetricsDashboard() {
  const metadata = useAppSelector(selectCurrentCompanyMetadataRtk);
  const allJobs = useAppSelector(selectCurrentCompanyJobsRtk);
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);

  // Memoize company lookup
  const company = useMemo(() => getCompanyById(selectedCompanyId), [selectedCompanyId]);

  // Get time-based job counts using custom hook
  // Calculations are deterministic based on job.createdAt timestamps
  const { jobsLast3Days, jobsLast24Hours, jobsLast12Hours } = useTimeBasedJobCounts(allJobs);

  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <MetricsRow
        totalJobs={metadata?.totalCount ?? 0}
        jobsLast3Days={jobsLast3Days}
        jobsLast24Hours={jobsLast24Hours}
        jobsLast12Hours={jobsLast12Hours}
      />

      <Divider sx={{ mb: 2 }} />

      <LinksRow jobsUrl={company?.jobsUrl} recruiterLinkedInUrl={company?.recruiterLinkedInUrl} />
    </Paper>
  );
}
