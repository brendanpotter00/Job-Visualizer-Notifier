import { useMemo } from 'react';
import Box from '@mui/material/Box';
import { OPS } from '../adminUsersTheme';

interface SignupSparklineProps {
  createdAts: string[];
  /** Width / height of the rendered SVG */
  width?: number;
  height?: number;
}

/**
 * Tiny SVG bar chart of signups bucketed by week.
 *
 * Buckets are derived from the min/max ``createdAt`` in the input. Six to ten
 * buckets is the sweet spot — enough to show the growth shape, few enough to
 * render at 28-32px height without losing legibility. The component intentionally
 * has no axes or labels: it lives in a corner of a stat tile.
 */
export function SignupSparkline({ createdAts, width = 110, height = 28 }: SignupSparklineProps) {
  const buckets = useMemo(() => {
    if (createdAts.length === 0) return [];
    const times = createdAts
      .map((s) => new Date(s).getTime())
      .filter((t) => !Number.isNaN(t));
    if (times.length === 0) return [];

    // Reducer instead of `Math.min(...times)`: the spread operator hits the
    // JS argument-count limit (~65k on V8) past a certain user count, and the
    // admin dashboard is the one place that will see that. Frontend CLAUDE.md
    // gotcha #10 calls out memory issues for unbounded lists.
    let min = Infinity;
    let max = -Infinity;
    for (const t of times) {
      if (t < min) min = t;
      if (t > max) max = t;
    }
    const span = Math.max(max - min, 1);
    const bucketCount = Math.min(10, Math.max(4, Math.ceil(Math.sqrt(times.length))));
    const counts = new Array(bucketCount).fill(0) as number[];

    for (const t of times) {
      let idx = Math.floor(((t - min) / span) * bucketCount);
      if (idx >= bucketCount) idx = bucketCount - 1;
      counts[idx] += 1;
    }
    return counts;
  }, [createdAts]);

  if (buckets.length === 0) return null;

  const maxCount = buckets.reduce((m, c) => Math.max(m, c), 0);
  const barWidth = width / buckets.length;
  const gap = 1;

  return (
    <Box component="svg" viewBox={`0 0 ${width} ${height}`} sx={{ width, height, display: 'block' }}>
      {buckets.map((count, i) => {
        const barHeight = maxCount === 0 ? 0 : (count / maxCount) * (height - 2);
        return (
          <rect
            key={i}
            x={i * barWidth + gap / 2}
            y={height - barHeight}
            width={barWidth - gap}
            height={barHeight}
            fill={OPS.accent}
            opacity={0.85}
          />
        );
      })}
    </Box>
  );
}
