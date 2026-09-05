import { useEffect, useState, type ReactNode } from 'react';
import { Box, Typography } from '@mui/material';
import { AnimatePresence, motion } from 'framer-motion';
import type { Job } from '../../../types';
import { JobListingCard } from '../../../components/shared/JobCard/JobListingCard';
import { RESPONSIVE } from '../../../config/responsive';
import { usePrefersReducedMotion } from '../usePrefersReducedMotion';

/** How long each job holds the card before the next one fades in. */
const ROTATE_INTERVAL_MS = 4500;
/** Crossfade duration (seconds, framer's unit) — restraint over flash. */
const CROSSFADE_SECONDS = 0.3;

/**
 * The overline above a card. Exported as a component (not a style object) so an
 * empty triptych slot renders a byte-identical caption without importing loose
 * styles across module boundaries.
 */
export function SlotCaption({ children }: { children: ReactNode }) {
  return (
    <Typography
      variant="overline"
      component="h2"
      sx={{ display: 'block', textAlign: 'center', color: 'text.secondary', mb: 1 }}
    >
      {children}
    </Typography>
  );
}

interface FlippingCardProps {
  /** The pool to flip through, newest-first. Already selected and capped. */
  jobs: Job[];
  /** Overline above the card — must be honest about what the pool holds. */
  caption: string;
  /**
   * Dead time added before this card's FIRST flip, so a row of cards does not
   * flip in unison. Zero (the default) reproduces the original single-card
   * timing exactly: first flip at `ROTATE_INTERVAL_MS`, then every interval.
   */
  phaseMs?: number;
  /** Test hook on the swapping region; also carries `data-active-job-id`. */
  testId: string;
}

/**
 * ONE real `JobListingCard` (the same component the live board renders),
 * flipping through a pool of jobs. This is the shared mechanic behind both the
 * single hero card (`RotatingJobCard`) and each slot of `FreshJobsTriptych`;
 * pool selection and layout belong to those callers, never here.
 *
 * Behavior:
 *  - auto-advances every 4.5s (after an optional `phaseMs` offset); pauses
 *    while hovered or while focus is inside (so a keyboard user can reach the
 *    Apply link without it sliding away),
 *  - 300ms opacity crossfade via `AnimatePresence`; both cards briefly share
 *    one CSS-grid cell, so the row height is always max(outgoing, incoming) —
 *    no absolute positioning, no clipping,
 *  - the cell ALSO holds a hidden "sizer" copy of every job in the pool, so its
 *    height is the tallest card in the pool no matter which one is showing —
 *    see `SizerStack`,
 *  - a `minHeight` floor keeps the card from collapsing below the reserved
 *    strip when every job in a pool is short,
 *  - reduced motion: no timers at all — the freshest job, rendered once and
 *    left alone,
 *  - `aria-live="off"`: the swap is decorative, never an announcement.
 *
 * Nothing here samples the clock: the card's "posted X ago" label comes from
 * `JobListingCard` itself, and the pool was selected against the caller's
 * `now`, keeping react-hooks/purity honestly clean.
 */
export function FlippingCard({ jobs, caption, phaseMs = 0, testId }: FlippingCardProps) {
  const reducedMotion = usePrefersReducedMotion();
  const [index, setIndex] = useState(0);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);

  const count = jobs.length;
  const rotating = !reducedMotion && count > 1 && !hovered && !focused;

  useEffect(() => {
    if (!rotating) return;
    // The stagger is a one-shot timeout in FRONT of the interval, not a shifted
    // interval: the first flip lands at `phaseMs + ROTATE_INTERVAL_MS`, so a
    // phase of 0 is byte-for-byte the old single-card cadence. Pausing and
    // resuming re-applies the offset, which is what keeps a hovered row from
    // collapsing back into lockstep.
    let interval: ReturnType<typeof setInterval> | undefined;
    const firstFlip = setTimeout(() => {
      setIndex((prev) => prev + 1);
      interval = setInterval(() => setIndex((prev) => prev + 1), ROTATE_INTERVAL_MS);
    }, phaseMs + ROTATE_INTERVAL_MS);
    return () => {
      clearTimeout(firstFlip);
      if (interval !== undefined) clearInterval(interval);
    };
  }, [rotating, phaseMs]);

  if (count === 0) return null;

  // Modulo at read time (never in state) so a shrinking pool can't strand the
  // index out of range, and reduced motion always shows the freshest job.
  const job = jobs[reducedMotion ? 0 : index % count];

  return (
    <>
      <SlotCaption>{caption}</SlotCaption>
      <Box
        data-testid={testId}
        data-active-job-id={job.id}
        aria-live="off"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        sx={{
          display: 'grid',
          // One column pinned to the container width, so the cell can never be
          // widened by a sizer whose min-content is unusually wide. Every card
          // — visible or hidden — therefore wraps at exactly the same width,
          // which is what makes a sizer's measured height truthful.
          gridTemplateColumns: 'minmax(0, 1fr)',
          minHeight: RESPONSIVE.landingProto.rotatingCardMinHeight,
        }}
      >
        {reducedMotion ? (
          <JobListingCard job={job} />
        ) : (
          <>
            <SizerStack jobs={jobs} />
            <AnimatePresence initial={false}>
              <motion.div
                key={job.id}
                data-flip-role="active"
                // Every card lands in the same grid cell, so the outgoing and
                // incoming cards overlap for the crossfade instead of stacking.
                style={{ gridArea: '1 / 1' }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: CROSSFADE_SECONDS, ease: 'easeOut' }}
              >
                <JobListingCard job={job} />
              </motion.div>
            </AnimatePresence>
          </>
        )}
      </Box>
    </>
  );
}

/**
 * The height guarantee: one hidden copy of EVERY job in the pool, all sharing
 * the single grid cell with the visible card. The cell is as tall as its
 * tallest occupant, so the section's height is `max(pool)` from first paint and
 * stays there for the whole rotation — a three-line title with wrapping chips
 * flipping in changes nothing, because its own sizer was already reserving that
 * height while a shorter card was showing. A `minHeight` floor alone could not
 * do this: it is a floor, and the bug was a card poking through the ceiling.
 *
 * `visibility: hidden` (not `display: none`, not `opacity: 0`) is the whole
 * trick — the boxes keep their layout, so they still size the row, while being
 * unpaintable, unhittable and untabbable. `aria-hidden` + `inert` say the same
 * thing to assistive tech and to the focus order explicitly, so a screen-reader
 * user hears one job per slot, not seven.
 *
 * Skipped entirely when the pool holds a single job (nothing ever flips, so the
 * visible card already IS the tallest) and in the reduced-motion path (a static
 * card whose height never changes has nothing to reserve against).
 */
function SizerStack({ jobs }: { jobs: Job[] }) {
  if (jobs.length < 2) return null;

  return (
    <>
      {jobs.map((sizerJob) => (
        <div
          key={sizerJob.id}
          data-flip-role="sizer"
          aria-hidden
          inert
          style={{ gridArea: '1 / 1', visibility: 'hidden' }}
        >
          <JobListingCard job={sizerJob} />
        </div>
      ))}
    </>
  );
}
