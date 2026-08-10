import { useState, useEffect, useMemo, useCallback } from 'react';
import { Stack, Typography, Box, Button } from '@mui/material';
import { useAppSelector } from '../../../app/hooks';
import { selectRecentJobsSorted } from '../../../features/filters/selectors/recentJobsSelectors.ts';
import { selectRecentJobsFilterSignature } from '../../../features/filters/selectors/recentJobsFilterSignature.ts';
import { JobListingCard } from '../../shared/JobCard/JobListingCard.tsx';
import { VirtualJobRows } from './VirtualJobRows.tsx';
import { useRecentJobsPaging } from './useRecentJobsPaging.ts';
import { LoadingSkeletons } from './LoadingSkeletons';
import { BackToTopButton } from './BackToTopButton';
import { EmptyJobListState } from '../../shared/EmptyJobListState.tsx';
import { SignInOverlay } from '../../shared/SignInOverlay.tsx';
import { useInfiniteScroll } from '../../../hooks/useInfiniteScroll.ts';
import {
  INFINITE_SCROLL_CONFIG,
  SIGN_IN_OVERLAY_CONFIG,
  VIRTUAL_LIST_CONFIG,
} from '../../../constants/ui.ts';
import { EMPTY_STATE_MESSAGES } from '../../../constants/messages.ts';
import { RESPONSIVE } from '../../../config/responsive.ts';
import { useAuth } from '../../../features/auth/useAuth.ts';

/**
 * List of jobs from all companies sorted chronologically.
 *
 * Three layers cooperate, innermost first:
 *
 * 1. **Virtualization** (`VirtualJobRows`) — bounds the number of mounted
 *    `JobListingCard`s to roughly a screenful regardless of how many rows the
 *    list holds. This is what makes a 29k-row corpus survivable; the list used
 *    to mount one card per revealed row and grow without limit as the user
 *    scrolled.
 * 2. **The client window** (`displayedCount`) — how many of the loaded rows the
 *    list is willing to show, grown in batches by infinite scroll. Still worth
 *    keeping under virtualization: it is what "All N jobs loaded" means, it
 *    caps the virtualizer's per-row measurement bookkeeping, and it is the unit
 *    the signed-out limit is expressed in.
 * 3. **The server walk** (`useRecentJobsPaging`) — when the client window has
 *    shown everything loaded, the next scroll pulls another keyset page; when
 *    the user picks a time window wider than the fetch bound, the walk restarts
 *    under the wider bound.
 *
 * **Auto-fetching is bounded on purpose.** A filter that matches nothing in the
 * older pages leaves the visible list unchanged after every fetch, so the
 * sentinel never leaves the viewport and the observer — which re-arms on the
 * loading flip and fires immediately on `observe()` — would walk the entire
 * corpus from one scroll to the bottom. After
 * `VIRTUAL_LIST_CONFIG.MAX_EMPTY_AUTO_FETCHES` consecutive pages that add no
 * visible row, the list stops and offers an explicit "search older jobs"
 * button. A failed fetch stops it the same way, with the error shown, because
 * a rejection leaves the cursors intact and would otherwise retry forever.
 *
 * **Zero matches must NOT unmount the machinery.** The terminal empty state
 * renders only when the walk is exhausted (`!hasMoreServer`). When the filter
 * matches nothing on page 1 but cursors are still outstanding, the list stays
 * mounted with the sentinel so the walk auto-deepens (bounded by the same
 * empty-fetch budget above). Early-returning the empty state here is the
 * 2026-08-10 incident: the sentinel — the only thing that can advance the walk
 * — unmounts, the budget never spends, and the page reports "No jobs found"
 * forever while matching rows sit one page deeper. See
 * `docs/incidents/2026-08-10-recent-jobs-empty-filter-deadlock.md`.
 *
 * When the user is signed out the list is capped at
 * SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT and both infinite scroll and
 * server paging are disabled; a SignInOverlay is shown below to prompt sign-up.
 * That path renders its dozen cards directly rather than through the
 * virtualizer — a hard-capped dozen is already bounded, and keeping them in
 * normal flow keeps the overlay's gradient anchored to the real bottom of the
 * list instead of to a spacer.
 */
export function RecentJobsList() {
  const jobs = useAppSelector(selectRecentJobsSorted);
  const filterSignature = useAppSelector(selectRecentJobsFilterSignature);
  const { isAuthenticated, isEnabled } = useAuth();
  const isSignedOut = isEnabled && !isAuthenticated;
  const [displayedCount, setDisplayedCount] = useState<number>(
    INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE
  );
  const [isRevealingMore, setIsRevealingMore] = useState(false);
  // Consecutive server pages that produced no new VISIBLE row. Reset by any
  // reveal (proof the last fetch helped), by a filter change, and by a manual
  // continue.
  const [emptyFetchStreak, setEmptyFetchStreak] = useState(0);

  const {
    hasMoreServer,
    isFetchingNextPage,
    error: pagingError,
    loadNextServerPage,
    retryServerPage,
  } = useRecentJobsPaging({ enabled: !isSignedOut });

  // When signed out, cap visible jobs at SIGNED_OUT_JOB_LIMIT regardless of
  // displayedCount; hasMore is forced false so the IntersectionObserver
  // sentinel never renders and loadMore is never triggered.
  const effectiveCount = isSignedOut
    ? SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT
    : displayedCount;
  // Two independent reasons the list is not finished, and the scroll trigger
  // has to honour both: rows already loaded but not yet revealed, and rows the
  // server still holds behind an outstanding cursor.
  const hasMoreInWindow = displayedCount < jobs.length;
  const autoFetchBlocked =
    emptyFetchStreak >= VIRTUAL_LIST_CONFIG.MAX_EMPTY_AUTO_FETCHES || pagingError !== null;
  // What the sentinel is allowed to pursue. Note this is NOT "is the list
  // finished" — a blocked auto-fetch still has more to give, just not without
  // the user asking.
  const hasMore = !isSignedOut && (hasMoreInWindow || (hasMoreServer && !autoFetchBlocked));
  // One loading flag for both kinds of "more": revealing an already-loaded
  // batch, and fetching the next page (or restarting the walk under a wider
  // window). The sentinel and the skeletons key off it identically.
  const isLoadingMore = isRevealingMore || isFetchingNextPage;
  const showSignInOverlay =
    isSignedOut && jobs.length > SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT;
  // Stopped short: the walk still holds pages, but auto-fetching has been
  // switched off (empty streak or a failure) and only the user can resume.
  const showContinueAffordance =
    !isSignedOut && !hasMoreInWindow && hasMoreServer && autoFetchBlocked && !isLoadingMore;
  // Genuinely finished: nothing left to reveal and nothing left to fetch.
  const atTrueEnd = !hasMoreInWindow && !hasMoreServer;

  // Load more jobs callback
  const loadMore = useCallback(() => {
    if (!hasMore || isLoadingMore) return;

    // Prefer what is already in memory: reveal the next batch of loaded rows
    // and don't touch the network until they run out. Reaching this branch also
    // proves the previous fetch produced visible rows, so the streak resets.
    if (hasMoreInWindow) {
      setEmptyFetchStreak(0);
      setIsRevealingMore(true);
      // Simulate async loading with microtask delay
      // This gives the browser time to update UI before processing next batch
      setTimeout(() => {
        setDisplayedCount((prev) =>
          Math.min(prev + INFINITE_SCROLL_CONFIG.SUBSEQUENT_BATCH_SIZE, jobs.length)
        );
        setIsRevealingMore(false);
      }, 0);
      return;
    }

    // Everything loaded is on screen — advance the keyset walk, counting this
    // as an empty fetch until a reveal proves otherwise. Double-fire is guarded
    // here (isLoadingMore), by the observer disconnecting while loading, and
    // once more inside the hook.
    setEmptyFetchStreak((streak) => streak + 1);
    loadNextServerPage();
  }, [hasMore, isLoadingMore, hasMoreInWindow, jobs.length, loadNextServerPage]);

  // Manual continue: clears the stop (streak and/or error) and fetches once.
  const continueLoading = useCallback(() => {
    setEmptyFetchStreak(0);
    retryServerPage();
  }, [retryServerPage]);

  // Initialize infinite scroll hook.
  //
  // The sentinel stays the trigger rather than the virtualizer's range end. It
  // sits in normal flow *after* the virtual container, whose height is the full
  // client window, so it becomes visible at exactly the same scroll position it
  // did before virtualization — the semantics, the rootMargin prefetch, and the
  // hook's own test suite all carry over untouched. Driving loads from the
  // virtualizer's last rendered index instead would mean reacting to a value
  // computed during render, which is how "load more" turns into a render loop.
  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    isLoadingMore,
    onLoadMore: loadMore,
    rootMargin: INFINITE_SCROLL_CONFIG.SENTINEL_ROOT_MARGIN,
    threshold: INFINITE_SCROLL_CONFIG.SENTINEL_THRESHOLD,
  });

  // Reset the reveal window when the FILTERS change — never when the data
  // ticks. See `selectRecentJobsFilterSignature` for why `jobs.length` was
  // wrong in both directions. The streak resets with it: a new filter deserves
  // its own budget of automatic pages.
  useEffect(() => {
    setDisplayedCount(INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE);
    setEmptyFetchStreak(0);
  }, [filterSignature]);

  // Memoize displayed jobs slice
  const displayedJobs = useMemo(() => jobs.slice(0, effectiveCount), [jobs, effectiveCount]);

  // TERMINAL empty state: only honest once the walk holds nothing more
  // (`!hasMoreServer`). Suppressed while a page is in flight (a widening
  // restart shows skeletons, not a flash of "no jobs found"), suppressed when
  // auto-fetching stopped short (the continue affordance below offers the
  // rest), and — load-bearing — suppressed while cursors are outstanding:
  // this return unmounts the sentinel, so taking it with pages left would
  // deadlock the walk at "No jobs found" with matches one page deeper.
  if (jobs.length === 0 && !isLoadingMore && !showContinueAffordance && !hasMoreServer) {
    return <EmptyJobListState />;
  }

  return (
    <>
      <Box
        sx={{
          position: 'relative',
          ...(showSignInOverlay && { overflow: 'hidden' }),
        }}
      >
        <Stack spacing={0}>
          {isSignedOut ? (
            <Box role="list">
              {displayedJobs.map((job) => (
                <Box key={job.id} role="listitem">
                  <JobListingCard job={job} />
                </Box>
              ))}
            </Box>
          ) : (
            <VirtualJobRows jobs={displayedJobs} totalCount={jobs.length} />
          )}

          {/* Zero matches so far, walk still deepening: say so, instead of
              bare skeletons (or a blank frame between fetches) where the list
              should be. The stopped-short case has its own message below.
              Deliberately NOT role="status": the skeletons below are already a
              live region ("Loading more jobs"), and doubling the announcement
              per auto-deepened page is screen-reader noise. Signed-out users
              never deepen the walk, so the line would be a lie for them. */}
          {!isSignedOut && jobs.length === 0 && !showContinueAffordance && (
            <Box sx={{ textAlign: 'center', pt: 4 }}>
              <Typography variant="body2" color="text.secondary">
                {EMPTY_STATE_MESSAGES.SEARCHING_OLDER_JOBS_IN_PROGRESS}
              </Typography>
            </Box>
          )}

          {/* Loading skeletons */}
          {isLoadingMore && <LoadingSkeletons count={INFINITE_SCROLL_CONFIG.SKELETON_COUNT} />}

          {/* Sentinel element for infinite scroll trigger */}
          {hasMore && !isLoadingMore && (
            <div ref={sentinelRef} aria-hidden="true" style={{ height: '1px', width: '100%' }} />
          )}

          {/* Auto-fetching stopped: say why, and let the user carry on. */}
          {showContinueAffordance && (
            <Box sx={{ textAlign: 'center', py: 4 }} role="status">
              <Typography
                variant="body2"
                color={pagingError ? 'error' : 'text.secondary'}
                sx={{ mb: 1 }}
              >
                {pagingError ?? EMPTY_STATE_MESSAGES.NO_MATCHES_IN_RECENT_PAGES}
              </Typography>
              <Button
                variant="outlined"
                size="small"
                onClick={continueLoading}
                sx={{
                  minHeight: RESPONSIVE.control.minHeight,
                  fontSize: RESPONSIVE.control.buttonFontSize,
                }}
              >
                {pagingError
                  ? EMPTY_STATE_MESSAGES.RETRY_OLDER_JOBS
                  : EMPTY_STATE_MESSAGES.SEARCH_OLDER_JOBS}
              </Button>
            </Box>
          )}

          {/* All jobs loaded message */}
          {atTrueEnd && !isLoadingMore && jobs.length > INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE && (
            <Box sx={{ textAlign: 'center', py: 4 }} role="status">
              <Typography variant="body2" color="text.secondary">
                {EMPTY_STATE_MESSAGES.ALL_LOADED(jobs.length)}
              </Typography>
            </Box>
          )}
        </Stack>

        {/* Sign-in prompt for signed-out users with more jobs available */}
        {showSignInOverlay && <SignInOverlay page="recent" />}
      </Box>

      {/* Back to top button */}
      <BackToTopButton />
    </>
  );
}
