import { Stack, Typography, Box, Button } from '@mui/material';
import { JobListingCard } from '../../shared/JobCard/JobListingCard.tsx';
import { VirtualJobRows } from './VirtualJobRows.tsx';
import { LoadingSkeletons } from './LoadingSkeletons';
import { BackToTopButton } from './BackToTopButton';
import { EmptyJobListState } from '../../shared/EmptyJobListState.tsx';
import { SignInOverlay } from '../../shared/SignInOverlay.tsx';
import { useInfiniteScroll } from '../../../hooks/useInfiniteScroll.ts';
import { INFINITE_SCROLL_CONFIG, SIGN_IN_OVERLAY_CONFIG } from '../../../constants/ui.ts';
import { EMPTY_STATE_MESSAGES } from '../../../constants/messages.ts';
import { RESPONSIVE } from '../../../config/responsive.ts';
import { useAuth } from '../../../features/auth/useAuth.ts';
import type { RecentJobsSearch } from '../../../features/jobs/hooks/useRecentJobsSearch.ts';

export interface RecentJobsListProps {
  search: RecentJobsSearch;
}

/**
 * The Recent page's job list.
 *
 * Two layers now, where there used to be three:
 *
 * 1. **Virtualization** (`VirtualJobRows`) — bounds mounted `JobListingCard`s to
 *    roughly a screenful however many rows have accumulated.
 * 2. **Server pages** — the sentinel asks `useRecentJobsSearch` for the next
 *    keyset page when the reader reaches the bottom.
 *
 * The middle layer — a client-side reveal window that metered out rows the page
 * had already fetched — is gone with the client-side filtering that needed it.
 * The server now returns only matching rows, so a fetched row is a shown row and
 * the two counts can never diverge.
 *
 * **Everything that made auto-fetching dangerous is gone with it.** The old list
 * had to bound its own fetching (`MAX_EMPTY_AUTO_FETCHES`, a "search older jobs"
 * button) because a filter matching nothing in the loaded pages left the visible
 * list unchanged after every fetch, so the sentinel stayed in view and would walk
 * the whole corpus from one scroll. A filtered endpoint cannot produce that
 * situation: a page with no rows in it means there are none left.
 *
 * **The terminal empty state must stay provably terminal.** It renders only when
 * the walk is exhausted AND nothing is in flight AND there is no error. Showing
 * it while more could still arrive is the 2026-08-10 incident in general form:
 * the early return unmounts the sentinel, which is the only thing that could have
 * disproved it. See `docs/incidents/2026-08-10-recent-jobs-empty-filter-deadlock.md`.
 *
 * Signed out, the list caps at `SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT`,
 * paging is off, and a `SignInOverlay` prompts sign-up. That path renders its
 * dozen cards directly rather than through the virtualizer — a hard-capped dozen
 * is already bounded, and normal flow keeps the overlay's gradient anchored to
 * the real bottom of the list instead of to a spacer.
 */
export function RecentJobsList({ search }: RecentJobsListProps) {
  const {
    jobs,
    isInitialLoading,
    isRefreshing,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage,
    error,
    errorScope,
    retry,
    isSkippedEmpty,
    isAwaitingDeploy,
  } = search;
  const { isAuthenticated, isEnabled } = useAuth();
  const isSignedOut = isEnabled && !isAuthenticated;

  // One loading flag for every kind of "more on the way": the first page of a new
  // filter, and the next page of the current one. The sentinel and the skeletons
  // key off it identically.
  // `isAwaitingDeploy` counts as loading HERE, not only in the page shell above.
  // The page currently renders a spinner instead of this list during the grace
  // window, so the list is never mounted in that state — but relying on a
  // caller's `if` to keep a terminal state honest is exactly the pattern the
  // 2026-08-10 incident's first lesson warns about. The list must be unable to
  // claim "no jobs found" while a retry is still pending, whoever renders it.
  const isLoadingMore =
    isInitialLoading || isRefreshing || isFetchingNextPage || isAwaitingDeploy;
  // A failed next-page fetch stops automatic loading: the sentinel would sit in
  // the viewport and retry the same failing request forever, silently, for as
  // long as the reader stayed at the bottom.
  const hasMore = !isSignedOut && hasNextPage && errorScope !== 'nextPage';
  const showSignInOverlay =
    isSignedOut && jobs.length > SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT;
  const displayedJobs = isSignedOut
    ? jobs.slice(0, SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT)
    : jobs;
  // Signed-out readers are capped, not finished: `hasNextPage` is forced false
  // for them, so without this guard the list would announce "All 13 jobs loaded"
  // (the fetch limit) while showing 12 cards out of thousands.
  const atTrueEnd = !isSignedOut && !hasNextPage && !isLoadingMore;

  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    isLoadingMore,
    onLoadMore: fetchNextPage,
    rootMargin: INFINITE_SCROLL_CONFIG.SENTINEL_ROOT_MARGIN,
    threshold: INFINITE_SCROLL_CONFIG.SENTINEL_THRESHOLD,
  });

  // TERMINAL empty state. Every clause is load-bearing: `!hasNextPage` because
  // pages may still hold matches, the two in-flight flags because a filter change
  // must not flash "no jobs found" over rows that are about to arrive, and
  // `!error` because a failure is not an empty result — the page renders a real
  // error for that. `isSkippedEmpty` is the one case that is terminal without any
  // request at all: the company filter and the user's enabled companies are
  // disjoint, so nothing could match.
  if (isSkippedEmpty || (jobs.length === 0 && !hasNextPage && !isLoadingMore && !error)) {
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
            <VirtualJobRows jobs={displayedJobs} totalCount={displayedJobs.length} />
          )}

          {isLoadingMore && <LoadingSkeletons count={INFINITE_SCROLL_CONFIG.SKELETON_COUNT} />}

          {hasMore && !isLoadingMore && (
            <div ref={sentinelRef} aria-hidden="true" style={{ height: '1px', width: '100%' }} />
          )}

          {/* A next-page failure keeps the rows already loaded on screen — losing
              them would punish the reader for a transient network error — and
              offers an explicit retry in place of the silent auto-retry loop. */}
          {errorScope === 'nextPage' && (
            <Box sx={{ textAlign: 'center', py: 4 }} role="status">
              <Typography variant="body2" color="error" sx={{ mb: 1 }}>
                {error}
              </Typography>
              <Button
                variant="outlined"
                size="small"
                onClick={retry}
                sx={{
                  minHeight: RESPONSIVE.control.minHeight,
                  fontSize: RESPONSIVE.control.buttonFontSize,
                }}
              >
                {EMPTY_STATE_MESSAGES.RETRY_OLDER_JOBS}
              </Button>
            </Box>
          )}

          {atTrueEnd && !error && displayedJobs.length > 0 && (
            <Box sx={{ textAlign: 'center', py: 4 }} role="status">
              <Typography variant="body2" color="text.secondary">
                {EMPTY_STATE_MESSAGES.ALL_LOADED(displayedJobs.length)}
              </Typography>
            </Box>
          )}
        </Stack>

        {showSignInOverlay && <SignInOverlay page="recent" />}
      </Box>

      <BackToTopButton />
    </>
  );
}
