import { useState } from 'react';
import {
  Box,
  LinearProgress,
  Typography,
  Chip,
  Stack,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { useAllJobsProgress } from '../../../features/jobs/hooks/useAllJobsProgress';

/**
 * Progress bar component for displaying incremental loading status
 * as companies are fetched in parallel.
 *
 * Shows an accordion that:
 * - Expands automatically while loading with progress bar and company chips
 * - Collapses to a summary when loading completes
 * - Can be manually expanded/collapsed by the user at any time
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
  const [manualToggle, setManualToggle] = useState<boolean | null>(null);

  // Don't render if we have no companies to show progress for
  if (progress.total === 0) {
    return null;
  }

  // Expand while loading, collapse when done, but respect manual toggle
  const expanded = manualToggle !== null ? manualToggle : isLoading;

  const successCount = progress.companies.filter((c) => c.status === 'success').length;
  const errorCount = progress.companies.filter((c) => c.status === 'error').length;
  const totalJobs = progress.companies.reduce((sum, c) => sum + (c.jobCount ?? 0), 0);

  const summaryText = isLoading
    ? `Loading jobs from ${progress.completed}/${progress.total} companies (${progress.percentComplete.toFixed(0)}%)`
    : `Loaded ${successCount} companies (${totalJobs.toLocaleString()} jobs)${errorCount > 0 ? `, ${errorCount} failed` : ''}`;

  return (
    <Accordion
      expanded={expanded}
      onChange={(_event, isExpanded) => setManualToggle(isExpanded)}
      sx={{
        mb: 2,
        '&:before': { display: 'none' },
        bgcolor: 'background.paper',
      }}
      disableGutters
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        aria-controls="fetch-progress-content"
        id="fetch-progress-header"
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%', mr: 1 }}>
          <Typography variant="subtitle2" sx={{ flexShrink: 0 }}>
            {summaryText}
          </Typography>
          {isLoading && (
            <LinearProgress
              variant="determinate"
              value={progress.percentComplete}
              sx={{ height: 6, borderRadius: 3, flexGrow: 1 }}
            />
          )}
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={1}>
          {isLoading && (
            <>
              <Box display="flex" justifyContent="space-between" alignItems="center">
                <Typography variant="subtitle2">
                  Loading jobs from {progress.completed}/{progress.total} companies
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {progress.percentComplete.toFixed(0)}%
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={progress.percentComplete}
                sx={{ height: 8, borderRadius: 4 }}
              />
            </>
          )}

          {/* Company status chips */}
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
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
      </AccordionDetails>
    </Accordion>
  );
}
