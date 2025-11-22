import { Paper, Typography } from '@mui/material';
import { useAppSelector } from '../../app/hooks';
import { JobList } from './JobList';
import { ListFilters } from '../filters/ListFilters';
import { selectListFilteredJobs } from '../../features/filters/filtersSelectors';
import { selectCurrentCompanyLoading } from '../../features/jobs/jobsSelectors';

/**
 * Job list section with filters
 */
export function ListSection() {
  const jobs = useAppSelector(selectListFilteredJobs);
  const isLoading = useAppSelector(selectCurrentCompanyLoading);

  console.log("list section", jobs)

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
