import { Paper, Stack, Box, Typography } from '@mui/material';

interface RecentJobsMetricsProps {
  metadata: {
    totalJobs: number;
    filteredCount: number;
    companiesRepresented: number;
  };
  timeWindow: string;
}

/**
 * Displays metrics for Recent Job Postings page
 * Shows filtered job count, companies represented, and time window
 */
export function RecentJobsMetrics({ metadata, timeWindow }: RecentJobsMetricsProps) {
  return (
    <Paper sx={{ p: 2, mb: 3, bgcolor: 'background.default' }}>
      <Stack direction="row" spacing={4} justifyContent="center">
        <Box textAlign="center">
          <Typography variant="h4" component="div">
            {metadata.filteredCount}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Job Postings
          </Typography>
        </Box>
        <Box textAlign="center">
          <Typography variant="h4" component="div">
            {metadata.companiesRepresented}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Companies
          </Typography>
        </Box>
        <Box textAlign="center">
          <Typography variant="h4" component="div">
            {timeWindow}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Time Window
          </Typography>
        </Box>
      </Stack>
    </Paper>
  );
}
