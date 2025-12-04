import { Chip, Stack } from '@mui/material';
import type { Job } from '../../../types';

interface JobChipsSectionProps {
  /**
   * Department name to display
   */
  department?: string;
  /**
   * Whether the job is remote
   */
  isRemote?: boolean;
  /**
   * Job classification data
   */
  classification: Job['classification'];
}

/**
 * Shared component for rendering job metadata chips
 * Used by both JobCard and RecentJobCard components
 *
 * Displays:
 * - Department chip (if present)
 * - Remote chip (if job is remote)
 * - Software category chip (if software-adjacent)
 */
export function JobChipsSection({ department, isRemote, classification }: JobChipsSectionProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
      {department && <Chip label={department} size="small" variant="outlined" />}
      {isRemote && <Chip label="Remote" size="small" color="primary" variant="outlined" />}
      {classification.isSoftwareAdjacent && (
        <Chip label={classification.category} size="small" color="primary" />
      )}
    </Stack>
  );
}
