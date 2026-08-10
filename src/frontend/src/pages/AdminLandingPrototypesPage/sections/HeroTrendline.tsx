import { Box } from '@mui/material';
import { buildSmoothPath } from './trendlinePath';

/**
 * MOCK cadence line — a hardcoded week of job-posting rhythm (weekday peaks,
 * weekend dip). Purely decorative for the prototype: at promotion this would
 * be fed by real posting-cadence data, but Brendan explicitly wants "just a
 * line" for now to judge the visual. Coordinates live in a 700×100 viewBox;
 * lower y = more postings.
 */
const TREND_POINTS: ReadonlyArray<readonly [number, number]> = [
  [0, 74],
  [50, 58],
  [100, 36],
  [150, 50],
  [200, 28],
  [250, 44],
  [300, 24],
  [350, 40],
  [400, 32],
  [450, 56],
  [500, 74],
  [550, 82],
  [600, 60],
  [650, 34],
  [700, 46],
];

/**
 * Barely-there posting-cadence line for hero backgrounds. Fills its
 * (position: relative) parent, sits behind the copy, and never intercepts the
 * pointer — the Gravity hero's physics canvas keeps receiving every event.
 */
export function HeroTrendline() {
  return (
    <Box
      aria-hidden
      data-testid="hero-trendline"
      sx={{
        position: 'absolute',
        inset: 0,
        display: 'flex',
        alignItems: 'flex-start',
        pointerEvents: 'none',
        color: 'text.primary',
      }}
    >
      <Box
        component="svg"
        viewBox="0 0 700 100"
        preserveAspectRatio="none"
        sx={{ width: '100%', height: '55%', mt: '6%' }}
      >
        <path
          d={buildSmoothPath(TREND_POINTS)}
          fill="none"
          stroke="currentColor"
          strokeOpacity={0.07}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      </Box>
    </Box>
  );
}

export default HeroTrendline;
