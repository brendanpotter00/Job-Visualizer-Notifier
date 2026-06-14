import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Grid from '@mui/material/Grid';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { StatTile } from '../../AdminUsersPage/components/StatTile';
import type { LocationHealth } from '../../../features/admin/adminApi';
import {
  HEARTBEAT_CRIT_MINUTES,
  HEARTBEAT_WARN_MINUTES,
  severityToMuiColor,
  type MetricSeverity,
} from '../verdict';

interface HealthOverviewProps {
  health: LocationHealth;
}

function heartbeatSeverity(ageMinutes: number | null): MetricSeverity {
  if (ageMinutes === null) return 'crit';
  if (ageMinutes > HEARTBEAT_CRIT_MINUTES) return 'crit';
  if (ageMinutes > HEARTBEAT_WARN_MINUTES) return 'warn';
  return 'ok';
}

function formatHeartbeat(ageMinutes: number | null): string {
  if (ageMinutes === null) return 'Heartbeat: none';
  if (ageMinutes < 1) return 'Heartbeat: <1m ago';
  return `Heartbeat: ${Math.round(ageMinutes)}m ago`;
}

export function HealthOverview({ health }: HealthOverviewProps) {
  const queue = health.normalizeQueue;
  const queueFailed = queue.failed ?? 0;

  return (
    <Box>
      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid size={{ xs: 6, sm: 3 }}>
          <StatTile
            label="NULL aged"
            value={health.nullAged.toLocaleString()}
            meta={`${health.nullBacklog.toLocaleString()} total backlog`}
          />
        </Grid>
        <Grid size={{ xs: 6, sm: 3 }}>
          <StatTile
            label="Done"
            value={health.done.toLocaleString()}
            meta="normalized (all time)"
          />
        </Grid>
        <Grid size={{ xs: 6, sm: 3 }}>
          <StatTile
            label="Failed"
            value={health.failed.toLocaleString()}
            meta={`${health.failedNonblankRatio.toFixed(1)}% nonblank`}
          />
        </Grid>
        <Grid size={{ xs: 6, sm: 3 }}>
          <StatTile label="Total" value={health.total.toLocaleString()} meta="rows tracked" />
        </Grid>
      </Grid>

      <Stack
        direction="row"
        spacing={1}
        sx={{ mb: 2, flexWrap: 'wrap', gap: 1, alignItems: 'center' }}
      >
        <Chip
          size="small"
          label={formatHeartbeat(health.heartbeatAgeMinutes)}
          color={severityToMuiColor(heartbeatSeverity(health.heartbeatAgeMinutes))}
          variant={
            heartbeatSeverity(health.heartbeatAgeMinutes) === 'ok' ? 'outlined' : 'filled'
          }
        />
        <Chip
          size="small"
          label={health.keyConfigured ? 'LLM key: configured' : 'LLM key: missing'}
          color={health.keyConfigured ? 'success' : 'warning'}
          variant={health.keyConfigured ? 'outlined' : 'filled'}
        />
        <Chip
          size="small"
          variant="outlined"
          label={
            health.throughputInWindow !== null
              ? `Throughput: ${health.throughputInWindow.toLocaleString()} / ${health.windowHours}h`
              : `Throughput: — / ${health.windowHours}h`
          }
        />
      </Stack>

      <Box>
        <Typography variant="overline" color="text.secondary">
          Worker queue
        </Typography>
        <Stack direction="row" spacing={1} sx={{ mt: 0.5, flexWrap: 'wrap', gap: 1 }}>
          <Chip size="small" variant="outlined" label={`todo ${(queue.todo ?? 0).toLocaleString()}`} />
          <Chip
            size="small"
            variant="outlined"
            label={`doing ${(queue.doing ?? 0).toLocaleString()}`}
          />
          <Chip
            size="small"
            variant="outlined"
            label={`succeeded ${(queue.succeeded ?? 0).toLocaleString()}`}
          />
          <Chip
            size="small"
            variant={queueFailed > 0 ? 'filled' : 'outlined'}
            color={queueFailed > 0 ? 'error' : 'default'}
            label={`failed ${queueFailed.toLocaleString()}`}
          />
        </Stack>
      </Box>
    </Box>
  );
}
