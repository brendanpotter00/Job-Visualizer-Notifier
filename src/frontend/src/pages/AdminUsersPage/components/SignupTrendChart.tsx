import { useMemo } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { useTheme } from '@mui/material/styles';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { format } from 'date-fns';
import { bucketCumulative, type DayPoint } from '../lib/bucketSignups';

interface SignupTrendChartProps {
  /** ISO timestamps of every user's `createdAt`. */
  createdAts: string[];
  /** Chart height in pixels. Defaults to 280 to match the provider-breakdown card. */
  height?: number;
}

export function SignupTrendChart({ createdAts, height = 280 }: SignupTrendChartProps) {
  const theme = useTheme();
  const data = useMemo(() => bucketCumulative(createdAts), [createdAts]);

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
        <Typography color="text.secondary">No signups yet</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ width: '100%', height }}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
          <defs>
            <linearGradient id="signupTrendFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={theme.palette.primary.main} stopOpacity={0.35} />
              <stop offset="95%" stopColor={theme.palette.primary.main} stopOpacity={0} />
            </linearGradient>
          </defs>
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
            contentStyle={{
              backgroundColor: theme.palette.background.paper,
              border: `1px solid ${theme.palette.divider}`,
              fontSize: 13,
            }}
            labelStyle={{ color: theme.palette.text.primary }}
            formatter={(value: number) => [value.toLocaleString(), 'Total users']}
            labelFormatter={(label: string, payload) => {
              const point = payload?.[0]?.payload as DayPoint | undefined;
              if (!point) return label;
              return format(new Date(point.time), 'MMM d, yyyy');
            }}
          />
          <Area
            type="monotone"
            dataKey="count"
            stroke={theme.palette.primary.main}
            strokeWidth={2}
            fill="url(#signupTrendFill)"
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </Box>
  );
}
