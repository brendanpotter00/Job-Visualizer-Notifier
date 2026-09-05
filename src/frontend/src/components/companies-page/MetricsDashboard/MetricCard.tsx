import { Box, Typography } from '@mui/material';
import { RESPONSIVE } from '../../../config/responsive';

interface MetricCardProps {
  /**
   * The number to show, or a short string where a bare number will not do — the
   * Recent page passes an em-dash for a genuinely unknown count and a bounded
   * form like "1250+" while a walk can still turn up more (see
   * `RecentJobsMetrics` and `features/jobs/resultTotal.ts`). Keep it to a handful
   * of characters; a long string will not fit the `h3` tile at the dense size.
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
