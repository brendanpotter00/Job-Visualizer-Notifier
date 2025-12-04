import { Chip, Stack } from '@mui/material';

interface JobChipsSectionProps {
  /**
   * Department name to display
   */
  department?: string;
  /**
   * Whether the job is remote
   */
  isRemote?: boolean;
}

/**
 * Shared component for rendering job metadata chips
 * Used by both JobCard and RecentJobCard components
 *
 * Displays:
 * - Department chip (if present)
 * - Remote chip (if job is remote)
 */
export function JobChipsSection({ department, isRemote }: JobChipsSectionProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {department && <Chip label={department} size="small" variant="outlined" />}
      {isRemote && <Chip label="Remote" size="small" color="primary" variant="outlined" />}
    </Stack>
  );
}
