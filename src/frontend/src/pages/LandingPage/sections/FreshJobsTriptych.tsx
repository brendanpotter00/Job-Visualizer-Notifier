import { useMemo } from 'react';
import { Box, Grid, Link, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { Job } from '../../../types';
import { RESPONSIVE } from '../../../config/responsive';
import { ROUTES } from '../../../config/routes';
import { FlippingCard, SlotCaption } from './FlippingCard';
import { selectTriptychSlots, type TriptychSlot } from './triptychJobs';

/**
 * Phase step between adjacent slots (ms). Three slots at 0 / 1.5s / 3s against
 * a 4.5s interval spread the flips evenly across the cycle, so the row always
 * reads as "something just changed" rather than a synchronized blink.
 */
const PHASE_STEP_MS = 1500;

interface FreshJobsTriptychProps {
  jobs: Job[];
  /** The fixtures' MOCK_NOW — see LandingPrototypeProps.now. */
  now: number;
}

/**
 * Three real `JobListingCard`s side by side, each answering a different
 * question a visitor actually arrives with — "is there anything for someone
 * with no experience?", "is this thing actually live?", "do you have the
 * companies I care about?" — and each flipping independently through its own
 * small pool.
 *
 * The pools come from `selectTriptychSlots`, which guarantees the three slots
 * never show the same job at the same time (priority: early-career > last 24h >
 * big tech). Slots are staggered by `PHASE_STEP_MS` so they never flip in
 * unison, and each pauses on its own hover/focus without touching its
 * neighbours. A slot with an empty pool says so plainly and points at the live
 * board; the section only disappears entirely when all three come back empty.
 *
 * Stacks to a single column below `sm` via the standard Grid idiom.
 */
export function FreshJobsTriptych({ jobs, now }: FreshJobsTriptychProps) {
  const slots = useMemo(() => selectTriptychSlots(jobs, now), [jobs, now]);

  if (slots.every((slot) => slot.jobs.length === 0)) return null;

  return (
    <Grid container spacing={{ xs: 2, sm: 3 }} data-testid="fresh-jobs-triptych">
      {slots.map((slot, i) => (
        <Grid key={slot.id} size={{ xs: 12, sm: 4 }}>
          {slot.jobs.length > 0 ? (
            <FlippingCard
              jobs={slot.jobs}
              caption={slot.label}
              phaseMs={i * PHASE_STEP_MS}
              testId={slotTestId(slot.id)}
            />
          ) : (
            <QuietSlot slot={slot} />
          )}
        </Grid>
      ))}
    </Grid>
  );
}

/**
 * Stable per-slot test hook, shared by the card and the empty state so a test
 * can find a slot without caring which of the two it got.
 */
function slotTestId(id: TriptychSlot['id']): string {
  return `triptych-slot-${id}`;
}

/**
 * An honestly empty slot: same caption, same reserved height, no invented
 * content. On a quiet weekend this is the truthful answer, and the one useful
 * next step is the live board.
 */
function QuietSlot({ slot }: { slot: TriptychSlot }) {
  return (
    <>
      <SlotCaption>{slot.label}</SlotCaption>
      <Box
        data-testid={slotTestId(slot.id)}
        data-empty="true"
        sx={{
          display: 'grid',
          alignContent: 'center',
          justifyItems: 'center',
          gap: 1,
          textAlign: 'center',
          minHeight: RESPONSIVE.landingProto.rotatingCardMinHeight,
        }}
      >
        <Typography variant="body2" sx={{ color: 'text.secondary' }}>
          {slot.emptyText}
        </Typography>
        <Link component={RouterLink} to={ROUTES.RECENT_JOBS} variant="body2">
          Check the board
        </Link>
      </Box>
    </>
  );
}
