import { useMemo } from 'react';
import { Box } from '@mui/material';
import type { Job } from '../../../types';
import { TOP_COMPANY_IDS } from '../content';
import { FlippingCard } from './FlippingCard';
import { selectTickerJobs } from './tickerJobs';

/** Rotation pool size; past ~6 the loop stops reading as "a few fresh jobs". */
const DEFAULT_MAX_ITEMS = 6;
/** Breakpoint-independent: one card should never span the full 1200px container. */
const CARD_MAX_WIDTH = 720;

interface RotatingJobCardProps {
  jobs: Job[];
  /** The fixtures' MOCK_NOW — see LandingPrototypeProps.now. */
  now: number;
  maxItems?: number;
}

/**
 * ONE real `JobListingCard` flipping through the freshest jobs — the
 * single-card successor to the pill rail. The card IS the proof: identical to
 * what a visitor gets after they click through, with the honest window caption
 * from `selectTickerJobs` above it ("Posted in the last 48 hours" / "Fresh this
 * week").
 *
 * This component owns only the POOL and the CAPTION; the flip itself (timing,
 * crossfade, hover/focus pause, reduced motion, height floor) lives in the
 * shared `FlippingCard`, which the triptych slots reuse. Time comes from the
 * `now` prop only (repo law: no Date.now() in a render path) — it drives both
 * the <48h/7d selection and the caption.
 */
export function RotatingJobCard({ jobs, now, maxItems = DEFAULT_MAX_ITEMS }: RotatingJobCardProps) {
  const { items, mode } = useMemo(
    () => selectTickerJobs(jobs, TOP_COMPANY_IDS, now, maxItems),
    [jobs, now, maxItems]
  );

  if (items.length === 0) return null;

  return (
    <Box sx={{ maxWidth: CARD_MAX_WIDTH, mx: 'auto' }}>
      <FlippingCard
        jobs={items}
        caption={mode === 'fresh' ? 'Posted in the last 48 hours' : 'Fresh this week'}
        testId="rotating-job-card"
      />
    </Box>
  );
}
