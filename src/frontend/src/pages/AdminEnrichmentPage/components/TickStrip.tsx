import Box from '@mui/material/Box';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { useTheme } from '@mui/material/styles';
import type { EnrichmentTickRow } from '../../../features/admin/adminApi';
import { formatAge } from '../verdict';

/** Strip cell sizing (px). Small and dense on purpose — it's an EKG, not a chart. */
const CELL = 14;
const CELL_GAP = 3;

interface TickStripProps {
  ticks: EnrichmentTickRow[];
  windowHours: number;
}

/**
 * The pipeline's EKG: one small cell per enricher tick in the window, oldest →
 * newest. Fill encodes outcome — solid (ok, wrote results), hollow (ok but an
 * empty poll), warning (drift suspected), error tone (tick failed), pulsing
 * outline (still running). Hover a cell for the tick's full vitals. A glance
 * answers "has the laptop been showing up, and has it been healthy?" without
 * reading a single number.
 */
export function TickStrip({ ticks, windowHours }: TickStripProps) {
  const theme = useTheme();

  if (ticks.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        No ticks pushed in the last {windowHours}h. The enricher reports each cycle via{' '}
        <code>cli metrics-push</code> — silence here with claimable backlog means the laptop is
        dark.
      </Typography>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: `${CELL_GAP}px`, alignItems: 'flex-end' }}>
        {ticks.map((tick) => {
          const wrote = tick.sent > 0 || tick.classified > 0;
          const isError = tick.status === 'error';
          const isRunning = tick.status === 'running';
          const bg = isError
            ? theme.palette.error.main
            : tick.driftSuspected
              ? theme.palette.warning.main
              : wrote
                ? theme.palette.grey[800]
                : 'transparent';
          const border = isError
            ? theme.palette.error.main
            : tick.driftSuspected
              ? theme.palette.warning.main
              : theme.palette.grey[500];
          return (
            <Tooltip
              key={tick.tickUuid}
              title={
                <Box sx={{ fontSize: 12, lineHeight: 1.6 }}>
                  <div>
                    {new Date(tick.startedAt).toLocaleString()} · {tick.status}
                    {tick.durationS != null && ` · ${formatAge(tick.durationS)}`}
                  </div>
                  <div>
                    claimed {tick.claimed} · classified {tick.classified} · judged {tick.judged} ·
                    sent {tick.sent}
                  </div>
                  {(tick.errors > 0 || tick.nulledFacets > 0) && (
                    <div>
                      errors {tick.errors} · nulled facets {tick.nulledFacets}
                    </div>
                  )}
                  {tick.notes && <div>{tick.notes}</div>}
                </Box>
              }
            >
              <Box
                sx={{
                  width: CELL,
                  height: CELL,
                  borderRadius: 0.5,
                  bgcolor: bg,
                  border: `1.5px solid ${border}`,
                  cursor: 'default',
                  ...(isRunning && {
                    animation: 'tickPulse 1.6s ease-in-out infinite',
                    '@keyframes tickPulse': {
                      '0%, 100%': { opacity: 1 },
                      '50%': { opacity: 0.35 },
                    },
                    '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
                  }),
                }}
              />
            </Tooltip>
          );
        })}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.75 }}>
        {ticks.length} tick(s) / {windowHours}h · filled = wrote results · hollow = empty poll ·
        amber = drift suspected · red = error
      </Typography>
    </Box>
  );
}
