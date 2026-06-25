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
import { ChartSkeleton } from '../../shared/LoadingIndicator.tsx';
import { formatBucketLabel } from '../../../lib/date.ts';
import type { TimeBucket, TimeWindow } from '../../../types';
import { ChartTooltip } from './ChartTooltip';
import { CustomDot } from './CustomDot';
import { RESPONSIVE } from '../../../config/responsive';
import { useIsMobile } from '../../../hooks/useIsMobile';

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
  const isMobile = useIsMobile();
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

  // Mobile-only Recharts overrides via tokens. Desktop passes `undefined` for
  // tick font / YAxis width so Recharts keeps its current defaults byte-for-byte.
  const tickStyle = isMobile ? { fontSize: RESPONSIVE.chart.axisFontSizeCompact } : undefined;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart
        data={chartData}
        margin={isMobile ? RESPONSIVE.chart.marginCompact : RESPONSIVE.chart.marginDefault}
      >
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
          tick={tickStyle}
          // Keep date labels from colliding on the narrow phone plot.
          minTickGap={isMobile ? 28 : 5}
        />
        <YAxis stroke="#666" tick={tickStyle} width={isMobile ? 28 : undefined} />
        <Tooltip content={<ChartTooltip />} />
        <Line
          type="monotone"
          dataKey="count"
          stroke="#000"
          strokeWidth={2}
          dot={
            <CustomDot
              fill="#000"
              r={isMobile ? RESPONSIVE.chart.dotR.compact : RESPONSIVE.chart.dotR.default}
              onPointClick={onPointClick}
            />
          }
          activeDot={
            <CustomDot
              fill="#000"
              r={isMobile ? RESPONSIVE.chart.activeDotR.compact : RESPONSIVE.chart.activeDotR.default}
              onPointClick={onPointClick}
            />
          }
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
