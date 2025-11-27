import { Box, Typography } from '@mui/material';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { format } from 'date-fns';
import { useMemo } from 'react';
import { ChartSkeleton } from '../LoadingIndicator';
import { formatBucketLabel } from '../../utils/dateUtils';
import type { TimeBucket, TimeWindow } from '../../types';
import { ChartTooltip } from './ChartTooltip';
import { CustomDot } from './CustomDot';

interface JobPostingsChartProps {
  /** Bucketed data for the chart */
  data: TimeBucket[];

  /** Click handler for data points */
  onPointClick: (bucket: TimeBucket) => void;

  /** Time window for adaptive axis formatting */
  timeWindow: TimeWindow;

  /** Loading state */
  isLoading?: boolean;

  /** Optional height override */
  height?: number;
}

/**
 * Line chart component for job posting timeline visualization
 */
export function JobPostingsChart({
  data,
  onPointClick,
  timeWindow,
  isLoading = false,
  height = 400,
}: JobPostingsChartProps) {
  if (isLoading) {
    return (
      <Box sx={{ height }}>
        <ChartSkeleton />
      </Box>
    );
  }

  if (data.length === 0) {
    return (
      <Box
        sx={{
          height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Typography color="text.secondary">No data to display</Typography>
      </Box>
    );
  }

  // Transform TimeBucket[] to Recharts format (memoized to prevent unnecessary recalculations)
  const chartData = useMemo(
    () =>
      data.map((bucket) => ({
        time: new Date(bucket.bucketStart).getTime(),
        count: bucket.count,
        label: format(new Date(bucket.bucketStart), 'MMM d HH:mm'),
        bucket, // Store original for click handler
      })),
    [data]
  );

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
        <XAxis
          dataKey="time"
          type="number"
          domain={['dataMin', 'dataMax']}
          tickFormatter={(tick) => {
            const bucket: TimeBucket = {
              bucketStart: new Date(tick).toISOString(),
              bucketEnd: '',
              count: 0,
              jobIds: [],
            };
            return formatBucketLabel(bucket, timeWindow);
          }}
          stroke="#666"
        />
        <YAxis stroke="#666" />
        <Tooltip content={<ChartTooltip />} />
        <Line
          type="monotone"
          dataKey="count"
          stroke="#000"
          strokeWidth={2}
          dot={<CustomDot fill="#000" r={4} onPointClick={onPointClick} />}
          activeDot={<CustomDot fill="#000" r={6} onPointClick={onPointClick} />}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
