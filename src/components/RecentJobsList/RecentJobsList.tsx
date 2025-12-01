import { Stack, Typography, Box } from '@mui/material';
import { useAppSelector } from '../../app/hooks';
import { selectRecentJobsSorted } from '../../features/filters/recentJobsSelectors';
import { getCompanyById } from '../../config/companies';
import { RecentJobCard } from '../RecentJobCard';

/**
 * List of jobs from all companies sorted chronologically
 * Shows empty state when no jobs match filters
 */
export function RecentJobsList() {
  const jobs = useAppSelector(selectRecentJobsSorted);

  if (jobs.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', py: 8 }}>
        <Typography variant="h6" gutterBottom>
          No jobs found matching your filters
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Try adjusting your filters or extending the time window
        </Typography>
      </Box>
    );
  }

  return (
    <Stack spacing={0}>
      {jobs.map((job) => {
        const company = getCompanyById(job.company);
        return (
          <RecentJobCard
            key={job.id}
            job={job}
            companyName={company?.name || job.company}
            recruiterLinkedInUrl={company?.recruiterLinkedInUrl}
          />
        );
      })}
    </Stack>
  );
}
