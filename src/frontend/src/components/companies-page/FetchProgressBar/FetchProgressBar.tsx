import { useState, useEffect, useRef, useMemo } from 'react';
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
import { getCompanyById } from '../../../config/companies';

interface FetchProgressBarProps {
  /**
   * Optional set of company IDs to constrain the displayed progress to.
   * When provided, the bar's chips, totals, and percentage reflect only
   * the intersection of fetched companies with this set — even though
   * the underlying fetch still hits every company (cache shared with
   * the Companies page). `null` or `undefined` means "show all".
   */
  companyIdFilter?: Set<string> | null;
}

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
export function FetchProgressBar({ companyIdFilter }: FetchProgressBarProps = {}) {
  const { progress, isLoading } = useAllJobsProgress();

  const visibleCompanies = useMemo(() => {
    const filtered =
      !companyIdFilter || companyIdFilter.size === 0
        ? progress.companies
        : progress.companies.filter((c) => companyIdFilter.has(c.companyId));
    return [...filtered].sort((a, b) => {
      const nameA = getCompanyById(a.companyId)?.name ?? a.companyId;
      const nameB = getCompanyById(b.companyId)?.name ?? b.companyId;
      return nameA.localeCompare(nameB);
    });
  }, [progress.companies, companyIdFilter]);

  const visibleTotal = visibleCompanies.length;
  const visibleCompleted = visibleCompanies.filter(
    (c) => c.status === 'success' || c.status === 'error'
  ).length;
  const visiblePercentComplete =
    visibleTotal > 0 ? (visibleCompleted / visibleTotal) * 100 : 0;

  const [expanded, setExpanded] = useState(isLoading);
  const wasLoadingRef = useRef(false);

  useEffect(() => {
    if (isLoading) {
      wasLoadingRef.current = true;
      setExpanded(true); // eslint-disable-line react-hooks/set-state-in-effect -- syncing derived state from isLoading prop
    } else if (wasLoadingRef.current) {
      setExpanded(false);
      wasLoadingRef.current = false;
    }
  }, [isLoading]);

  if (progress.total === 0 || visibleTotal === 0) {
    return null;
  }

  const successCount = visibleCompanies.filter((c) => c.status === 'success').length;
  const errorCount = visibleCompanies.filter((c) => c.status === 'error').length;
  const totalJobs = visibleCompanies
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
        borderRadius: 1,
        overflow: 'hidden',
        mb: 2,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        {isLoading ? (
          <Box sx={{ width: '100%', pr: 2 }}>
            <Box display="flex" justifyContent="space-between" alignItems="center">
              <Typography variant="subtitle2">
                Loading jobs from {visibleCompleted}/{visibleTotal} companies
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {visiblePercentComplete.toFixed(0)}%
              </Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={visiblePercentComplete}
              sx={{ height: 8, borderRadius: 4, mt: 1 }}
            />
          </Box>
        ) : (
          <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
            <Typography variant="subtitle2">
              Loaded {visibleCompleted}/{visibleTotal} companies
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
          {visibleCompanies.map((company) => {
            const displayName = getCompanyById(company.companyId)?.name ?? company.companyId;

            if (company.status === 'success') {
              return (
                <Chip
                  key={company.companyId}
                  icon={<CheckCircleIcon />}
                  label={`${displayName}${company.jobCount !== undefined ? ` (${company.jobCount})` : ''}`}
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
                  label={displayName}
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
                label={displayName}
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
