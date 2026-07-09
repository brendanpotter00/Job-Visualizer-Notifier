import { useMemo } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { useTheme } from '@mui/material/styles';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { format } from 'date-fns';
import type { EnrichmentTickRow } from '../../../features/admin/adminApi';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { RESPONSIVE } from '../../../config/responsive';

interface TickChartsProps {
  ticks: EnrichmentTickRow[];
}

/** Stage keys charted in the latency panel, pipeline order. */
const STAGES = ['pull', 'clean', 'classify', 'judge', 'write_back'] as const;

/**
 * Two Recharts panels over the pushed tick series:
 *  - Throughput: jobs sent (published) vs errors per tick.
 *  - Stage latency: stacked per-stage milliseconds per tick — where a slow
 *    tick actually spent its time (classify/judge fan-outs dominate healthy
 *    ticks; a fat write_back bar means JVN was slow or retrying).
 * Theme-driven colors, mirroring SignupsPerDayChart's conventions.
 */
export function TickCharts({ ticks }: TickChartsProps) {
  const theme = useTheme();
  const isMobile = useIsMobile();
  const h = isMobile ? RESPONSIVE.adminChart.height.compact : 240;

  const throughputData = useMemo(
    () =>
      ticks.map((t) => ({
        at: format(new Date(t.startedAt), 'MMM d HH:mm'),
        sent: t.sent,
        errors: t.errors,
        needsHuman: t.needsHuman,
      })),
    [ticks]
  );

  const latencyData = useMemo(
    () =>
      ticks.map((t) => {
        const row: Record<string, number | string> = {
          at: format(new Date(t.startedAt), 'MMM d HH:mm'),
        };
        for (const stage of STAGES) {
          const timing = t.stageTimings?.find((s) => s.stage === stage);
          row[stage] = timing ? Math.round(timing.ms / 1000) : 0;
        }
        return row;
      }),
    [ticks]
  );

  if (ticks.length === 0) {
    return null;
  }

  const axisColor = theme.palette.text.secondary;
  const gridColor = theme.palette.divider;
  // Monochrome ramp for the stacked stages (pipeline order, light -> dark).
  const stageFills = [
    theme.palette.grey[300],
    theme.palette.grey[400],
    theme.palette.grey[600],
    theme.palette.grey[800],
    theme.palette.grey[900],
  ];

  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
        gap: 3,
      }}
    >
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Throughput per tick
        </Typography>
        <Box sx={{ width: '100%', height: h }}>
          <ResponsiveContainer>
            <BarChart data={throughputData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
              <XAxis dataKey="at" tick={{ fontSize: 11, fill: axisColor }} minTickGap={24} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: axisColor }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: theme.palette.background.paper,
                  border: `1px solid ${gridColor}`,
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="sent" name="Sent" stackId="a" fill={theme.palette.grey[800]} />
              <Bar
                dataKey="needsHuman"
                name="Needs human"
                stackId="a"
                fill={theme.palette.warning.main}
              />
              <Bar dataKey="errors" name="Errors" stackId="a" fill={theme.palette.error.main} />
            </BarChart>
          </ResponsiveContainer>
        </Box>
      </Box>
      <Box>
        <Typography variant="subtitle2" gutterBottom>
          Stage latency per tick (seconds)
        </Typography>
        <Box sx={{ width: '100%', height: h }}>
          <ResponsiveContainer>
            <BarChart data={latencyData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridColor} />
              <XAxis dataKey="at" tick={{ fontSize: 11, fill: axisColor }} minTickGap={24} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: axisColor }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: theme.palette.background.paper,
                  border: `1px solid ${gridColor}`,
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {STAGES.map((stage, i) => (
                <Bar key={stage} dataKey={stage} name={stage} stackId="lat" fill={stageFills[i]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </Box>
      </Box>
    </Box>
  );
}
