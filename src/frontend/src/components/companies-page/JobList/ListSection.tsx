import { Paper, Typography } from '@mui/material';
import { useAppSelector } from '../../../app/hooks';
import { JobList } from './JobList';
import { ListFilters } from '../ListFilters.tsx';
import { selectListFilteredJobs } from '../../../features/filters/selectors/listFiltersSelectors.ts';
import { selectCurrentCompanyLoadingRtk } from '../../../features/jobs/jobsSelectors';

/**
 * Job list section with filters
 */
export function ListSection() {
  const jobs = useAppSelector(selectListFilteredJobs);
  const isLoading = useAppSelector(selectCurrentCompanyLoadingRtk);

  return (
    <Paper sx={{ p: { xs: 2, sm: 3 } }}>
      <Typography variant="h5" component="h2" gutterBottom>
        Job Listings
      </Typography>

      <ListFilters />

      <JobList jobs={jobs} isLoading={isLoading} />
    </Paper>
  );
}
