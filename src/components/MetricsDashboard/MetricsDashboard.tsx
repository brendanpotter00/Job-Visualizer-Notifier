import { Paper, Divider } from '@mui/material';
import { useMemo, useState, useEffect } from 'react';
import { useAppSelector } from '../../app/hooks';
import {
  selectCurrentCompanyMetadata,
  selectCurrentCompanyJobs,
} from '../../features/jobs/jobsSelectors';
import { getCompanyById } from '../../config/companies';
import { useTimeBasedJobCounts } from './hooks/useTimeBasedJobCounts';
import { MetricsRow } from './MetricsRow';
import { LinksRow } from './LinksRow';

/**
 * Dashboard displaying key metrics and links above the graph
 */
export function MetricsDashboard() {
  const metadata = useAppSelector(selectCurrentCompanyMetadata);
  const allJobs = useAppSelector(selectCurrentCompanyJobs);
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);

  // Track current time and update it periodically
  const [currentTime, setCurrentTime] = useState(() => Date.now());

  useEffect(() => {
    // Update time every minute to keep counts fresh
    const interval = setInterval(() => {
      setCurrentTime(Date.now());
    }, 60000); // Update every 60 seconds

    return () => clearInterval(interval);
  }, []);

  // Memoize company lookup
  const company = useMemo(() => getCompanyById(selectedCompanyId), [selectedCompanyId]);

  // Get time-based job counts using custom hook
  const { jobsLast3Days, jobsLast24Hours, jobsLast12Hours } = useTimeBasedJobCounts(
    allJobs,
    currentTime
  );

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
