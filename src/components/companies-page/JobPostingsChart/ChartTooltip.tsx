import { Paper, Typography } from '@mui/material';
import type { TimeBucket } from '../../../types';

/**
 * Props for ChartTooltip component
 */
export interface ChartTooltipProps {
  active?: boolean;
  payload?: Array<{
    payload: {
      time: number;
      count: number;
      label: string;
      bucket: TimeBucket;
    };
  }>;
}

/**
 * Custom tooltip for the chart
 * Displays time and job count when hovering over data points
 */
export function ChartTooltip({ active, payload }: ChartTooltipProps) {
  if (!active || !payload || !payload.length) {
    return null;
  }

  const data = payload[0].payload;
  if (!data) return null;

  return (
    <Paper sx={{ p: 1.5, border: '1px solid', borderColor: 'divider' }}>
      <Typography variant="body2" fontWeight="bold">
        {data.label}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {data.count} {data.count === 1 ? 'job' : 'jobs'} posted
      </Typography>
    </Paper>
  );
}
