import { useMemo } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { useTheme } from '@mui/material/styles';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { format } from 'date-fns';
import { bucketPerDay, type DayPoint } from '../lib/bucketSignups';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { RESPONSIVE } from '../../../config/responsive';

interface SignupsPerDayChartProps {
  /** ISO timestamps of every user's `createdAt`. */
  createdAts: string[];
  /** Chart height in pixels. Defaults to 280 to match the sibling cumulative chart. */
  height?: number;
}

export function SignupsPerDayChart({ createdAts, height = 280 }: SignupsPerDayChartProps) {
  const theme = useTheme();
  const isMobile = useIsMobile();
  // Shorter on mobile (desktop keeps the passed/default 280).
  const h = isMobile ? RESPONSIVE.adminChart.height.compact : height;
  const data = useMemo(() => bucketPerDay(createdAts), [createdAts]);

  if (data.length === 0) {
    return (
      <Box
        sx={{
          height: h,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Typography color="text.secondary">No signups yet</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ width: '100%', height: h }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={theme.palette.divider} />
          <XAxis
            dataKey="label"
            tick={{ fill: theme.palette.text.secondary, fontSize: 12 }}
            stroke={theme.palette.divider}
            minTickGap={24}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: theme.palette.text.secondary, fontSize: 12 }}
            stroke={theme.palette.divider}
            width={32}
          />
          <Tooltip
            cursor={{ fill: theme.palette.action.hover }}
            contentStyle={{
              backgroundColor: theme.palette.background.paper,
              border: `1px solid ${theme.palette.divider}`,
              fontSize: 13,
            }}
            labelStyle={{ color: theme.palette.text.primary }}
            formatter={(value: number) => [value.toLocaleString(), 'Signups']}
            labelFormatter={(label: string, payload) => {
              const point = payload?.[0]?.payload as DayPoint | undefined;
              if (!point) return label;
              return format(new Date(point.time), 'MMM d, yyyy');
            }}
          />
          <Bar
            dataKey="count"
            fill={theme.palette.primary.main}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </Box>
  );
}
