import { useCallback, useEffect, useRef, useState } from 'react';
import { Box } from '@mui/material';
import { useWindowVirtualizer } from '@tanstack/react-virtual';
import type { Job } from '../../../types';
import { JobListingCard } from '../../shared/JobCard/JobListingCard.tsx';
import { VIRTUAL_LIST_CONFIG } from '../../../constants/ui.ts';
import { useIsMobile } from '../../../hooks/useIsMobile.ts';

interface VirtualJobRowsProps {
  /** Rows to render. Already filtered and ordered by the server. */
  jobs: Job[];
  /**
   * Length of the list the reader is navigating, for `aria-setsize` — NOT the
   * rows loaded so far, which is a paging detail assistive tech must never hear.
   * The two are different numbers and the difference is the whole point: the
   * caller pages server-side, so `jobs` is "what has arrived", while this is the
   * filtered result set the endpoint measured. Passing `jobs.length` makes a
   * screen reader announce "item 20 of 20" in the middle of a 4,000-row walk.
   *
   * `null` means the total is genuinely UNKNOWN — page 1 (which carries the
   * counts) has not landed, or its failure nulled them. That renders
   * `aria-setsize="-1"`, which is ARIA's own spelling of "the total number of
   * items is unknown", rather than a number nothing has measured.
   */
  totalCount: number | null;
}

/**
 * Window-scrolled virtual list of `JobListingCard`s.
 *
 * Only the rows near the viewport are mounted (about a screenful plus
 * `VIRTUAL_LIST_CONFIG.OVERSCAN` above and below), so the mounted card count
 * stays flat no matter how deep the user scrolls or how long `jobs` is. A
 * spacer of the full computed height stands in for the rest, so the page's
 * scrollbar still reflects the whole list.
 *
 * **Window scrolling, not an inner scroll box.** The page itself scrolls: the
 * sibling `BackToTopButton` reads `window.scrollY`, browser scroll restoration
 * on back-navigation restores the window offset, and an inner `overflow: auto`
 * box would break both (the FAB would never appear and the restored offset
 * would land on an unscrolled container). `useWindowVirtualizer` + `scrollMargin`
 * therefore drives everything off the document scroll, and the list keeps its
 * place in normal page flow.
 *
 * **Heights are measured, not assumed.** `JobListingCard` is variable-height
 * (chips wrap, the recruiter link is conditional, mobile shrinks every chip),
 * so each mounted row reports its real box through `measureElement` and the
 * estimate is only a seed for rows that have never been on screen.
 *
 * **A11y.** The rows carry `role="listitem"` inside a `role="list"` container
 * with `aria-setsize`/`aria-posinset`, so assistive tech announces "item N of
 * total" against the FULL list rather than against the handful of mounted
 * nodes — the count a bare virtualized `div` would otherwise report. The total
 * is the caller's to supply (`totalCount`) because this component only ever
 * sees the rows that have arrived, which on a server-paged list is not the
 * list.
 */
export function VirtualJobRows({ jobs, totalCount }: VirtualJobRowsProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const isMobile = useIsMobile();

  // Distance from the top of the DOCUMENT to the top of the list. The
  // virtualizer needs it to translate a window scroll offset into a row index,
  // because everything above the list (title, metrics, progress bar, filters)
  // scrolls past first.
  //
  // `getBoundingClientRect().top + window.scrollY` — NOT `offsetTop`, which is
  // measured from the nearest positioned ancestor. The list's parent is
  // `position: relative` (it anchors the signed-out overlay), so `offsetTop`
  // reports ~0 and the virtual range comes out shifted by the entire page
  // header: a persistent blank band at the top of the list, worst on narrow
  // screens where the header is tallest and the shift exceeds the overscan.
  const [scrollMargin, setScrollMargin] = useState(0);

  const measureScrollMargin = useCallback(() => {
    const node = containerRef.current;
    if (!node) return;
    const offset = Math.round(node.getBoundingClientRect().top + window.scrollY);
    setScrollMargin((previous) => (previous === offset ? previous : offset));
  }, []);

  const attachContainer = useCallback(
    (node: HTMLDivElement | null) => {
      containerRef.current = node;
      measureScrollMargin();
    },
    [measureScrollMargin]
  );

  // The header above the list changes height on its own — the filter chips
  // rewrap onto another line as the reader adds or removes companies, locations
  // and keywords, and a filter input grows a helperText row when its options
  // query fails. (It used to change for a third reason, FetchProgressBarSkeleton
  // swapping for the real FetchProgressBar; both components were deleted with the
  // client-side walk, so only the header's own reflow is left.) None of that is a
  // window resize, so watching `resize` alone leaves the margin stale and the
  // range shifted. Observing the body catches every such reflow; the identity
  // guard above means the common case (the list's own height changing as rows
  // measure) costs one rect read and no re-render.
  useEffect(() => {
    window.addEventListener('resize', measureScrollMargin);
    const observer =
      typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measureScrollMargin);
    observer?.observe(document.body);
    return () => {
      window.removeEventListener('resize', measureScrollMargin);
      observer?.disconnect();
    };
  }, [measureScrollMargin]);

  // Memoized so the identity is stable across scroll-driven renders: the
  // virtualizer memoizes its whole measurement pass on this function, and a
  // fresh arrow every render rebuilds every row's measurement on every frame.
  //
  // The breakpoint is part of the key on purpose. Measured heights are cached
  // per key, and a card is materially shorter on mobile (smaller chips, smaller
  // Apply button), so reusing desktop heights after a rotation would leave
  // `getTotalSize()` — and every row offset below the viewport — drifted until
  // the list happened to remount. Changing the key retires the stale cache and
  // the rows re-measure.
  const getItemKey = useCallback(
    (index: number) => `${isMobile ? 'm' : 'd'}:${jobs[index]?.id ?? index}`,
    [isMobile, jobs]
  );

  const virtualizer = useWindowVirtualizer({
    count: jobs.length,
    estimateSize: () => VIRTUAL_LIST_CONFIG.ESTIMATED_CARD_HEIGHT,
    overscan: VIRTUAL_LIST_CONFIG.OVERSCAN,
    scrollMargin,
    getItemKey,
  });

  return (
    <Box
      ref={attachContainer}
      role="list"
      // How many rows have been loaded so far, published for tests and for
      // debugging a list whose mounted rows deliberately tell you nothing about
      // it. Named for the client-side reveal window it used to measure; it now
      // measures the pages the keyset walk has fetched.
      data-client-window={jobs.length}
      sx={{
        position: 'relative',
        width: '100%',
        // The spacer: total measured/estimated height of every row, so the
        // document scrollbar matches the full list even though a few rows exist.
        height: virtualizer.getTotalSize(),
      }}
    >
      {virtualizer.getVirtualItems().map((virtualRow) => {
        // The row set can SHRINK under the virtualizer: on a filter change RTK
        // Query swaps `data` to the new filter set's pages, which is routinely
        // SHORTER than what was on screen (page 1 of a narrower search replacing
        // five loaded pages of a wider one). The virtual items computed from the
        // previous render still carry the old, larger indices. Load-bearing, not
        // defensive habit — deleting it renders `undefined.id` and throws.
        const job = jobs[virtualRow.index];
        if (!job) return null;

        return (
          <div
            key={virtualRow.key}
            data-index={virtualRow.index}
            ref={virtualizer.measureElement}
            role="listitem"
            // -1 is ARIA's "total unknown", not a sentinel of our own.
            aria-setsize={totalCount ?? -1}
            aria-posinset={virtualRow.index + 1}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              // `flow-root` establishes a block formatting context so the card's
              // own bottom margin (RESPONSIVE.spacing.cardMarginB) is contained by
              // this wrapper and included in its measured height. Without it the
              // margin collapses through and consecutive cards overlap by exactly
              // the gap they are supposed to leave.
              display: 'flow-root',
              transform: `translateY(${virtualRow.start - virtualizer.options.scrollMargin}px)`,
            }}
          >
            <JobListingCard job={job} />
          </div>
        );
      })}
    </Box>
  );
}
