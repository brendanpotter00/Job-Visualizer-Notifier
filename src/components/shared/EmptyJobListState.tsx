import { Box, Typography } from '@mui/material';
import { EMPTY_STATE_MESSAGES } from '../../constants/messageConstants';

interface EmptyJobListStateProps {
  /**
   * Optional custom title to display
   * Defaults to standard "No jobs found" message
   */
  title?: string;
  /**
   * Optional custom hint/message to display
   * Defaults to standard filter adjustment hint
   */
  message?: string;
  /**
   * Whether to center the content
   * @default true
   */
  centered?: boolean;
}

/**
 * Shared empty state component for job lists
 * Displays a consistent message when no jobs are found
 *
 * Used by:
 * - JobList (company-specific job list)
 * - RecentJobsList (all companies combined)
 *
 * @example
 * ```tsx
 * {jobs.length === 0 && <EmptyJobListState />}
 * ```
 */
export function EmptyJobListState({
  title = EMPTY_STATE_MESSAGES.NO_JOBS_TITLE,
  message = EMPTY_STATE_MESSAGES.NO_JOBS_HINT,
  centered = true,
}: EmptyJobListStateProps) {
  return (
    <Box sx={{ textAlign: centered ? 'center' : 'left', py: 8 }}>
      <Typography variant="h6" gutterBottom>
        {title}
      </Typography>
      {message && (
        <Typography variant="body2" color="text.secondary">
          {message}
        </Typography>
      )}
    </Box>
  );
}
