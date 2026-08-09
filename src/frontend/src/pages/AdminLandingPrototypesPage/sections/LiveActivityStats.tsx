import { useMemo } from 'react';
import { Box, Stack, Typography } from '@mui/material';
import type { Job } from '../../../types';
import { RESPONSIVE } from '../../../config/responsive';
import type { LandingStats } from '../types';
import { computeActivityStats } from './activityStats';

interface LiveActivityStatsProps {
  jobs: Job[];
  stats: LandingStats;
  /** The fixtures' MOCK_NOW — see LandingPrototypeProps.now. */
  now: number;
}

/**
 * Event-shaped proof strip (brief §7): numbers derived from the jobs actually
 * rendered nearby, phrased as recent activity — never vanity metrics.
 */
export function LiveActivityStats({ jobs, stats, now }: LiveActivityStatsProps) {
  const items = useMemo(() => computeActivityStats(jobs, stats, now), [jobs, stats, now]);
  return (
    <Stack
      direction="row"
      sx={{
        justifyContent: 'center',
        gap: { xs: 2, sm: 6 },
        flexWrap: 'wrap',
      }}
    >
      {items.map((item) => (
        <Box key={item.label} sx={{ textAlign: 'center', maxWidth: 220 }}>
          <Typography
            sx={{
              fontSize: RESPONSIVE.landingProto.statValueFontSize,
              fontWeight: 600,
              lineHeight: 1.2,
            }}
          >
            {item.value}
          </Typography>
          <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.5 }}>
            {item.label}
          </Typography>
        </Box>
      ))}
    </Stack>
  );
}
