import { useMemo } from 'react';
import Box from '@mui/material/Box';
import { useTheme } from '@mui/material/styles';

interface SignupSparklineProps {
  createdAts: string[];
  width?: number;
  height?: number;
}

/**
 * Tiny SVG bar chart of signups bucketed across the full date range. The
 * component intentionally has no axes or labels — it lives in a corner of a
 * stat tile and is read like a sparkline.
 */
export function SignupSparkline({
  createdAts,
  width = 110,
  height = 28,
}: SignupSparklineProps) {
  const theme = useTheme();

  const buckets = useMemo(() => {
    if (createdAts.length === 0) return [];
    const times = createdAts
      .map((s) => new Date(s).getTime())
      .filter((t) => !Number.isNaN(t));
    if (times.length === 0) return [];

    // Reducer instead of `Math.min(...times)`: spread hits the JS argument
    // limit (~65k on V8) past a certain user count.
    let min = Infinity;
    let max = -Infinity;
    for (const t of times) {
      if (t < min) min = t;
      if (t > max) max = t;
    }
    const span = Math.max(max - min, 1);
    const bucketCount = Math.min(
      10,
      Math.max(4, Math.ceil(Math.sqrt(times.length)))
    );
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
  const fill = theme.palette.primary.main;

  return (
    <Box
      component="svg"
      viewBox={`0 0 ${width} ${height}`}
      sx={{ width, height, display: 'block' }}
      aria-hidden
    >
      {buckets.map((count, i) => {
        const barHeight = maxCount === 0 ? 0 : (count / maxCount) * (height - 2);
        return (
          <rect
            key={i}
            x={i * barWidth + gap / 2}
            y={height - barHeight}
            width={barWidth - gap}
            height={barHeight}
            fill={fill}
            opacity={0.7}
          />
        );
      })}
    </Box>
  );
}
