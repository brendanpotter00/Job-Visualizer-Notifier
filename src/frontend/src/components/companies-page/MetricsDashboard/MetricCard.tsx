import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';

interface MetricCardProps {
  /**
   * The number to show, or a short string where a bare number will not do (an
   * em-dash for a count nothing has measured, say). Keep it to a handful of
   * characters; a long string will not fit the `h3` tile at the dense size.
   *
   * `string` is currently unused — the Recent page was the only caller that
   * needed it and its metric row is gone (2026-09-05). Kept because "unknown"
   * has to be expressible in a tile whose value is genuinely not a number, and
   * narrowing to `number` would make the next such caller re-widen it.
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
