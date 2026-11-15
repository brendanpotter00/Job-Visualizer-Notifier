import { useMemo } from 'react';
import { Box, Grid, Link, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { Job } from '../../../types';
import type { JobCardLink } from '../../../components/shared/JobCard/JobListingCard';
import { RESPONSIVE } from '../../../config/responsive';
import { ROUTES } from '../../../config/routes';
import type { SectionIntro as SectionIntroContent } from '../content';
import { FlippingCard, SizerStack, SlotCaption } from './FlippingCard';
import { SectionIntro } from './SectionIntro';
import type { TriptychSlot, TriptychSlots } from './triptychJobs';

export const FRESH_JOBS_HEADING_ID = 'landing-fresh-jobs-heading';

/**
 * Phase step between adjacent slots (ms). Three slots at 0 / 1.5s / 3s against
 * a 4.5s interval spread the flips evenly across the cycle, so the row always
 * reads as "something just changed" rather than a synchronized blink.
 */
const PHASE_STEP_MS = 1500;

interface FreshJobsTriptychProps {
  slots: TriptychSlots;
  intro?: SectionIntroContent;
  cardLink: JobCardLink;
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
 * board.
 *
 * Stacks to a single column below `md` via the standard Grid idiom.
 */
export function FreshJobsTriptych({ slots, intro, cardLink }: FreshJobsTriptychProps) {
  const allSlotJobs = useMemo(
    () => [...new Map(slots.flatMap((slot) => slot.jobs).map((job) => [job.id, job])).values()],
    [slots]
  );

  return (
    <Box
      component="section"
      aria-labelledby={intro ? FRESH_JOBS_HEADING_ID : undefined}
      data-testid="fresh-jobs-triptych"
    >
      {intro && <SectionIntro heading={intro.heading} headingId={FRESH_JOBS_HEADING_ID} />}
      <Grid container spacing={{ xs: 2, sm: 3 }}>
        {slots.map((slot, i) => (
          <Grid key={slot.id} size={{ xs: 12, md: 4 }}>
            {slot.jobs.length > 0 ? (
              <FlippingCard
                jobs={slot.jobs}
                caption={slot.label}
                phaseMs={i * PHASE_STEP_MS}
                testId={slotTestId(slot.id)}
                sizerJobs={allSlotJobs}
                cardLink={cardLink}
              />
            ) : (
              <QuietSlot slot={slot} sizerJobs={allSlotJobs} />
            )}
          </Grid>
        ))}
      </Grid>
    </Box>
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
function QuietSlot({ slot, sizerJobs }: { slot: TriptychSlot; sizerJobs: Job[] }) {
  return (
    <>
      <SlotCaption>{slot.label}</SlotCaption>
      <Box
        data-testid={slotTestId(slot.id)}
        data-empty="true"
        sx={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr)',
          minHeight: RESPONSIVE.landingProto.rotatingCardMinHeight,
        }}
      >
        <SizerStack jobs={sizerJobs} />
        <Box
          sx={{
            gridArea: '1 / 1',
            display: 'grid',
            alignContent: 'center',
            justifyItems: 'center',
            gap: 1,
            textAlign: 'center',
          }}
        >
          <Typography variant="body2" sx={{ color: 'text.secondary' }}>
            {slot.emptyText}
          </Typography>
          <Link component={RouterLink} to={ROUTES.RECENT_JOBS} variant="body2">
            Browse jobs
          </Link>
        </Box>
      </Box>
    </>
  );
}
