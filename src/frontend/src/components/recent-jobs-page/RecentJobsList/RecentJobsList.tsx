import { useState, useEffect, useMemo, useCallback } from 'react';
import { Stack, Typography, Box } from '@mui/material';
import { useAppSelector } from '../../../app/hooks';
import { selectRecentJobsSorted } from '../../../features/filters/selectors/recentJobsSelectors.ts';
import { getCompanyById } from '../../../config/companies';
import { RecentJobCard } from '../RecentJobCard/RecentJobCard';
import { LoadingSkeletons } from './LoadingSkeletons';
import { BackToTopButton } from './BackToTopButton';
import { EmptyJobListState } from '../../shared/EmptyJobListState.tsx';
import { useInfiniteScroll } from '../../../hooks/useInfiniteScroll.ts';
import { INFINITE_SCROLL_CONFIG } from '../../../constants/ui.ts';
import { EMPTY_STATE_MESSAGES } from '../../../constants/messages.ts';

/**
 * List of jobs from all companies sorted chronologically
 * Features infinite scrolling to improve performance with large job lists
 * Shows empty state when no jobs match filters
 */
export function RecentJobsList() {
  const jobs = useAppSelector(selectRecentJobsSorted);
  const [displayedCount, setDisplayedCount] = useState<number>(
    INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE
  );
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  // Calculate if there are more jobs to load
  const hasMore = displayedCount < jobs.length;

  // Load more jobs callback
  const loadMore = useCallback(() => {
    if (!hasMore || isLoadingMore) return;

    setIsLoadingMore(true);
    // Simulate async loading with microtask delay
    // This gives the browser time to update UI before processing next batch
    setTimeout(() => {
      setDisplayedCount((prev) =>
        Math.min(prev + INFINITE_SCROLL_CONFIG.SUBSEQUENT_BATCH_SIZE, jobs.length)
      );
      setIsLoadingMore(false);
    }, 0);
  }, [hasMore, isLoadingMore, jobs.length]);

  // Initialize infinite scroll hook
  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    isLoadingMore,
    onLoadMore: loadMore,
    rootMargin: INFINITE_SCROLL_CONFIG.SENTINEL_ROOT_MARGIN,
    threshold: INFINITE_SCROLL_CONFIG.SENTINEL_THRESHOLD,
  });

  // Reset displayed count when filters change (detected by jobs.length change)
  useEffect(() => {
    setDisplayedCount(INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE);
  }, [jobs.length]);

  // Memoize displayed jobs slice
  const displayedJobs = useMemo(() => jobs.slice(0, displayedCount), [jobs, displayedCount]);

  // Empty state
  if (jobs.length === 0) {
    return <EmptyJobListState />;
  }

  return (
    <>
      <Stack spacing={0}>
        {displayedJobs.map((job) => {
          const company = getCompanyById(job.company);
          return (
            <RecentJobCard
              key={job.id}
              job={job}
              companyName={company?.name || job.company}
              recruiterLinkedInUrl={company?.recruiterLinkedInUrl}
            />
          );
        })}

        {/* Loading skeletons */}
        {isLoadingMore && <LoadingSkeletons count={INFINITE_SCROLL_CONFIG.SKELETON_COUNT} />}

        {/* Sentinel element for infinite scroll trigger */}
        {hasMore && !isLoadingMore && (
          <div ref={sentinelRef} aria-hidden="true" style={{ height: '1px', width: '100%' }} />
        )}

        {/* All jobs loaded message */}
        {!hasMore && jobs.length > INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE && (
          <Box sx={{ textAlign: 'center', py: 4 }} role="status">
            <Typography variant="body2" color="text.secondary">
              {EMPTY_STATE_MESSAGES.ALL_LOADED(jobs.length)}
            </Typography>
          </Box>
        )}
      </Stack>

      {/* Back to top button */}
      <BackToTopButton />
    </>
  );
}
