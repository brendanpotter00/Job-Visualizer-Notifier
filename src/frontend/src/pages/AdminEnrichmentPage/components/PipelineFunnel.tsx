import Box from '@mui/material/Box';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { useTheme } from '@mui/material/styles';
import type { EnrichmentHealth } from '../../../features/admin/adminApi';

/** Display order + labels for the enrichment buckets of OPEN jobs. */
const SEGMENTS = [
  { key: 'unenriched', label: 'Unenriched' },
  { key: 'claimed', label: 'Claimed' },
  { key: 'done', label: 'Done' },
  { key: 'needs_human', label: 'Needs human' },
] as const;

interface PipelineFunnelProps {
  health: EnrichmentHealth;
}

/**
 * One horizontal segmented bar: every OPEN job's enrichment bucket, in
 * pipeline order. Monochrome fills (theme greys, darker = further along) with
 * the needs-human segment in the warning tone — the single colored element,
 * because it is the single segment asking for a person. Below the bar, the
 * claimable/ineligible split of the unenriched mass (the backlog the laptop
 * can actually see vs the rows with no description under any known key).
 */
export function PipelineFunnel({ health }: PipelineFunnelProps) {
  const theme = useTheme();
  const counts = SEGMENTS.map((s) => health.openByStatus[s.key] ?? 0);
  const total = counts.reduce((a, b) => a + b, 0);

  const fills = [
    theme.palette.grey[200],
    theme.palette.grey[400],
    theme.palette.grey[800],
    theme.palette.warning.main,
  ];

  if (total === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        No OPEN jobs.
      </Typography>
    );
  }

  const ineligible = Math.max(0, (health.openByStatus.unenriched ?? 0) - health.eligibleUnenriched);

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          width: '100%',
          height: 28,
          borderRadius: 1,
          overflow: 'hidden',
          border: `1px solid ${theme.palette.divider}`,
        }}
      >
        {SEGMENTS.map((seg, i) => {
          const n = counts[i];
          if (n === 0) return null;
          const pct = (100 * n) / total;
          return (
            <Tooltip key={seg.key} title={`${seg.label}: ${n.toLocaleString()} (${pct.toFixed(1)}%)`}>
              <Box
                sx={{
                  width: `${pct}%`,
                  minWidth: 6,
                  bgcolor: fills[i],
                  transition: 'width 300ms ease',
                }}
              />
            </Tooltip>
          );
        })}
      </Box>
      <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mt: 1 }}>
        {SEGMENTS.map((seg, i) => (
          <Box key={seg.key} sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
            <Box sx={{ width: 10, height: 10, borderRadius: 0.5, bgcolor: fills[i] }} />
            <Typography variant="caption" color="text.secondary">
              {seg.label} {counts[i].toLocaleString()}
            </Typography>
          </Box>
        ))}
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
        Of the unenriched: {health.eligibleUnenriched.toLocaleString()} claimable
        {ineligible > 0 &&
          ` · ${ineligible.toLocaleString()} not claimable (no description scraped yet)`}
      </Typography>
    </Box>
  );
}
