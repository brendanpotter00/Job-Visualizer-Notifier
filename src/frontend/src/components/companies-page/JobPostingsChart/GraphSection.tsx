import { Typography } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../../app/hooks';
import { JobPostingsChart } from './JobPostingsChart';
import { GraphFilters } from '../GraphFilters.tsx';
import { selectGraphBucketData } from '../../../features/filters/selectors/graphFiltersSelectors.ts';
import {
  selectCurrentCompanyLoadingRtk,
  selectCurrentCompanyError,
} from '../../../features/jobs/jobsSelectors';
import { openGraphModal } from '../../../features/ui/uiSlice';
import { ErrorDisplay } from '../../shared/ErrorDisplay.tsx';
import type { TimeBucket } from '../../../types';

/**
 * Graph section: the shared filter controls and the postings chart.
 *
 * Rendered inside the page's shared `<Paper>` card (alongside the job list), so
 * it no longer supplies its own card wrapper.
 */
export function GraphSection() {
  const dispatch = useAppDispatch();
  const bucketData = useAppSelector(selectGraphBucketData);
  const isLoading = useAppSelector(selectCurrentCompanyLoadingRtk);
  const error = useAppSelector(selectCurrentCompanyError);
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

  return (
    <>
      <Typography variant="h5" component="h2" gutterBottom>
        Job Posting Timeline
      </Typography>

      <GraphFilters />

      {error ? (
        <ErrorDisplay title="Failed to Load Chart Data" message={error} />
      ) : (
        <JobPostingsChart
          data={bucketData}
          onPointClick={handlePointClick}
          timeWindow={graphFilters.timeWindow}
          isLoading={isLoading}
          height={400}
        />
      )}
    </>
  );
}
