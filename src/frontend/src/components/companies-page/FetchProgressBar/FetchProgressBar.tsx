import { useState, useEffect, useRef } from 'react';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  LinearProgress,
  Typography,
  Chip,
  Stack,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import { useAllJobsProgress } from '../../../features/jobs/hooks/useAllJobsProgress';

/**
 * Progress bar component for displaying incremental loading status
 * as companies are fetched in parallel.
 *
 * Shows:
 * - Linear progress bar with percentage during loading
 * - Count of loaded companies
 * - Chips for each company showing status (pending/success/error)
 * - Job counts for successfully loaded companies
 *
 * Collapses to a summary accordion when loading is complete.
 * Users can expand to see per-company details.
 */
export function FetchProgressBar() {
  const { progress, isLoading } = useAllJobsProgress();

  const [expanded, setExpanded] = useState(isLoading);
  const wasLoadingRef = useRef(false);

  useEffect(() => {
    if (isLoading) {
      wasLoadingRef.current = true;
      setExpanded(true);
    } else if (wasLoadingRef.current) {
      setExpanded(false);
      wasLoadingRef.current = false;
    }
  }, [isLoading]);

  if (progress.total === 0) {
    return null;
  }

  const successCount = progress.companies.filter((c) => c.status === 'success').length;
  const errorCount = progress.companies.filter((c) => c.status === 'error').length;
  const totalJobs = progress.companies
    .filter((c) => c.status === 'success')
    .reduce((sum, c) => sum + (c.jobCount ?? 0), 0);

  return (
    <Accordion
      expanded={expanded}
      onChange={(_, isExpanded) => setExpanded(isExpanded)}
      disableGutters
      slotProps={{ transition: { unmountOnExit: true } }}
      sx={{
        bgcolor: 'background.paper',
        borderBottom: '1px solid',
        borderColor: 'divider',
        boxShadow: 'none',
        mb: 2,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        {isLoading ? (
          <Box sx={{ width: '100%', pr: 2 }}>
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
              sx={{ height: 8, borderRadius: 4, mt: 1 }}
            />
          </Box>
        ) : (
          <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
            <Typography variant="subtitle2">
              Loaded {progress.completed}/{progress.total} companies
            </Typography>
            {successCount > 0 && (
              <Chip
                icon={<CheckCircleIcon />}
                label={`${successCount} loaded (${totalJobs} jobs)`}
                size="small"
                color="success"
                variant="outlined"
              />
            )}
            {errorCount > 0 && (
              <Chip
                icon={<ErrorIcon />}
                label={`${errorCount} failed`}
                size="small"
                color="error"
                variant="outlined"
              />
            )}
          </Box>
        )}
      </AccordionSummary>
      <AccordionDetails>
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
      </AccordionDetails>
    </Accordion>
  );
}
