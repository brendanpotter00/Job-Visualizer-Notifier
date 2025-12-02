import type { SxProps, Theme } from '@mui/material';

/**
 * Shared styling constants for job card components
 * Ensures consistent hover behavior and appearance across JobCard and RecentJobCard
 */

/**
 * Hover effect styling for job cards
 * Changes background color when user hovers over the card
 */
export const CARD_HOVER_SX: SxProps<Theme> = {
  '&:hover': { bgcolor: 'action.hover' },
};

/**
 * Standard card variant for all job cards
 * Uses MUI's outlined variant for consistency
 */
export const CARD_VARIANT = 'outlined' as const;
