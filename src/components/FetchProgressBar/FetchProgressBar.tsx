import { Box, LinearProgress, Typography, Chip, Stack } from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import { useAllJobsProgress } from '../../features/jobs/useAllJobsProgress';

/**
 * Progress bar component for displaying incremental loading status
 * as companies are fetched in parallel.
 *
 * Shows:
 * - Linear progress bar with percentage
 * - Count of loaded companies
 * - Chips for each company showing status (pending/success/error)
 * - Job counts for successfully loaded companies
 *
 * Auto-hides when loading is complete.
 *
 * @example
 * ```tsx
 * function MyPage() {
 *   return (
 *     <div>
 *       <FetchProgressBar />
 *       <JobList />
 *     </div>
 *   );
 * }
 * ```
 */
export function FetchProgressBar() {
  const { progress, isLoading } = useAllJobsProgress();

  // Auto-hide when loading is complete (isLoading now includes isFetching)
  if (!isLoading) {
    return null;
  }

  return (
    <Box
      sx={{
        p: 2,
        bgcolor: 'background.paper',
        borderBottom: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Stack spacing={1}>
        {/* Header with count and percentage */}
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography variant="subtitle2">
            Loading jobs from {progress.completed}/{progress.total} companies
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {progress.percentComplete.toFixed(0)}%
          </Typography>
        </Box>

        {/* Linear progress bar */}
        <LinearProgress
          variant="determinate"
          value={progress.percentComplete}
          sx={{ height: 8, borderRadius: 4 }}
        />

        {/* Company status chips */}
        <Stack direction="row" spacing={0.5} flexWrap="wrap" sx={{ mt: 1 }}>
          {progress.companies.map((company) => {
            if (company.status === 'success') {
              return (
                <Chip
                  key={company.companyId}
                  icon={<CheckCircleIcon />}
                  label={`${company.companyId}${company.jobCount !== undefined ? ` (${company.jobCount})` : ''}`}
                  size="small"
                  color="success"
                  variant="outlined"
                />
              );
            }

            if (company.status === 'error') {
              return (
                <Chip
                  key={company.companyId}
                  icon={<ErrorIcon />}
                  label={company.companyId}
                  size="small"
                  color="error"
                  variant="outlined"
                  title={company.error || 'Failed to load'}
                />
              );
            }

            // Pending or loading
            return (
              <Chip
                key={company.companyId}
                label={company.companyId}
                size="small"
                variant="outlined"
              />
            );
          })}
        </Stack>
      </Stack>
    </Box>
  );
}
