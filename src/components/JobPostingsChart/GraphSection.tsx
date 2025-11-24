import { Paper, Typography } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import { JobPostingsChart } from './JobPostingsChart';
import { GraphFilters } from '../filters/GraphFilters';
import { MetricsDashboard } from '../MetricsDashboard/MetricsDashboard';
import { selectGraphBucketData } from '../../features/filters/graphFiltersSelectors';
import {
  selectCurrentCompanyLoading,
  selectCurrentCompanyError,
} from '../../features/jobs/jobsSelectors';
import { openGraphModal } from '../../features/ui/uiSlice';
import { loadJobsForCompany } from '../../features/jobs/jobsThunks';
import { ErrorDisplay } from '../ErrorDisplay';
import type { TimeBucket } from '../../types';

/**
 * Graph section with filters and chart
 */
export function GraphSection() {
  const dispatch = useAppDispatch();
  const bucketData = useAppSelector(selectGraphBucketData);
  const isLoading = useAppSelector(selectCurrentCompanyLoading);
  const error = useAppSelector(selectCurrentCompanyError);
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const graphFilters = useAppSelector((state) => state.graphFilters.filters);

  const handlePointClick = (bucket: TimeBucket) => {
    if (bucket.count > 0) {
      dispatch(
        openGraphModal({
          bucketStart: bucket.bucketStart,
          bucketEnd: bucket.bucketEnd,
          filteredJobIds: bucket.jobIds,
        })
      );
    }
  };

  const handleRetry = () => {
    dispatch(
      loadJobsForCompany({
        companyId: selectedCompanyId,
      })
    );
  };

  return (
    <>
      <MetricsDashboard />

      <Paper sx={{ p: { xs: 2, sm: 3 }, mb: 3 }}>
        <Typography variant="h5" component="h2" gutterBottom>
          Job Posting Timeline
        </Typography>

        <GraphFilters />

        {error ? (
          <ErrorDisplay title="Failed to Load Chart Data" message={error} onRetry={handleRetry} />
        ) : (
          <JobPostingsChart
            data={bucketData}
            onPointClick={handlePointClick}
            timeWindow={graphFilters.timeWindow}
            isLoading={isLoading}
            height={400}
          />
        )}
      </Paper>
    </>
  );
}
