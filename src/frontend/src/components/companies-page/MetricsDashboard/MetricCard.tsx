import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';

interface MetricCardProps {
  /**
   * The number to show, or a short placeholder string for "not a number yet"
   * (the Recent page passes an em-dash when a count is genuinely unknown — see
   * `RecentJobsMetrics`). Anything longer than a couple of characters will not
   * fit the `h3` tile.
   */
  value: number | string;
  label: string;
  /**
   * Compact mode for narrow viewports (e.g. the Recent Jobs page on mobile):
   * shrinks the number and label at the `xs` breakpoint. Defaults to false so
   * the companies-page metrics dashboard is unchanged.
   */
  dense?: boolean;
}

/**
 * Pure presentational component for displaying a single metric
 */
export function MetricCard({ value, label, dense = false }: MetricCardProps) {
  return (
    <Box sx={{ flex: 1, textAlign: 'center', minWidth: 0 }}>
      <Typography
        variant="h3"
        component="div"
        gutterBottom
        sx={{ fontWeight: 'bold', ...(dense && { fontSize: RESPONSIVE.fontSize.metricValue }) }}
      >
        {value}
      </Typography>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={dense ? { fontSize: RESPONSIVE.fontSize.metricLabel } : undefined}
      >
        {label}
      </Typography>
    </Box>
  );
}
