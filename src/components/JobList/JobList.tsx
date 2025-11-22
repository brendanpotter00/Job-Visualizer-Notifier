import { Box, Typography, Stack } from '@mui/material';
import { JobCard } from './JobCard';
import { JobListSkeleton } from '../LoadingIndicator';
import type { Job } from '../../types';

interface JobListProps {
  /** Jobs to display */
  jobs: Job[];

  /** Loading state */
  isLoading?: boolean;
}

/**
 * List component for displaying job postings
 */
export function JobList({ jobs, isLoading = false }: JobListProps) {
  if (isLoading) {
    return <JobListSkeleton count={5} />;
  }

  if (jobs.length === 0) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          py: 8,
        }}
      >
        <Typography color="text.secondary">No jobs found matching your filters</Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        {jobs.length} {jobs.length === 1 ? 'job' : 'jobs'} found
      </Typography>
      {jobs.map((job) => (
        <JobCard key={job.id} job={job} />
      ))}
    </Stack>
  );
}
