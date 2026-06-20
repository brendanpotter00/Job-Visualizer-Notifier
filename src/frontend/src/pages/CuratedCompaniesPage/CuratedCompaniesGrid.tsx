import { useCallback, useEffect, useMemo, useState } from 'react';
import { Box, Grid, Typography } from '@mui/material';
import { EmptyState } from '../../components/shared/ErrorDisplay';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { useInfiniteScroll } from '../../hooks/useInfiniteScroll';
import { CHANGELOG_INFINITE_SCROLL_CONFIG } from '../../constants/ui';
import type { CuratedCompany } from '../../features/companies/companiesApi';
import { CompanyCard } from './CompanyCard';
import { CompanyCardSkeleton } from './CompanyCardSkeleton';
import { SearchBar } from './SearchBar';

interface CuratedCompaniesGridProps {
  companies: CuratedCompany[];
}

const GRID_ITEM_SIZE = { xs: 12, sm: 6, md: 4 } as const;

export function CuratedCompaniesGrid({ companies }: CuratedCompaniesGridProps) {
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search, 200);

  // Alphabetical by display name (case-insensitive). The backend already
  // returns this order, but re-asserting it keeps the sort contract on the
  // client regardless of payload order.
  const sorted = useMemo(
    () =>
      [...companies].sort((a, b) =>
        a.displayName.localeCompare(b.displayName, undefined, { sensitivity: 'base' })
      ),
    [companies]
  );

  const filtered = useMemo(() => {
    const query = debouncedSearch.trim().toLowerCase();
    if (!query) return sorted;
    return sorted.filter(
      (c) =>
        c.displayName.toLowerCase().includes(query) ||
        (c.blurb?.toLowerCase().includes(query) ?? false)
    );
  }, [sorted, debouncedSearch]);

  // Incremental client-side reveal, mirroring ChangelogColumn: mount the first
  // batch, then reveal more as the sentinel scrolls into view.
  const [displayedCount, setDisplayedCount] = useState<number>(
    CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE
  );
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  // Reset to the first batch whenever the (debounced) search query changes, so
  // a new search starts from the top of its result set. Done during render
  // rather than in an effect — React's recommended "adjust state when a value
  // changes" pattern — which avoids a second commit per keystroke.
  const [lastSearch, setLastSearch] = useState(debouncedSearch);
  if (debouncedSearch !== lastSearch) {
    setLastSearch(debouncedSearch);
    setDisplayedCount(CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE);
  }

  const hasMore = displayedCount < filtered.length;

  const loadMore = useCallback(() => {
    if (!hasMore || isLoadingMore) return;
    setIsLoadingMore(true);
    // Defer the bump so the skeletons paint before the next batch mounts.
    setTimeout(() => {
      setDisplayedCount((prev) =>
        Math.min(prev + CHANGELOG_INFINITE_SCROLL_CONFIG.SUBSEQUENT_BATCH_SIZE, filtered.length)
      );
      setIsLoadingMore(false);
    }, 0);
  }, [hasMore, isLoadingMore, filtered.length]);

  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    isLoadingMore,
    onLoadMore: loadMore,
    // Prefetch the next batch well before the sentinel reaches the viewport, and
    // fire on ANY intersection (threshold 0). A threshold of 0.1 against a 1px
    // sentinel is unreliable across browsers (notably Safari) and could leave
    // the grid stuck after the first batch on a manual scroll-to-bottom.
    rootMargin: '600px',
    threshold: 0,
  });

  // Reliability fallback to the IntersectionObserver above. The observer watches
  // a 1px sentinel, which some browser/layout combinations fire inconsistently —
  // leaving the grid stuck after the first batch on a manual scroll-to-bottom.
  // A passive window scroll/resize check that reveals the next batch when near
  // the bottom guarantees it keeps loading. loadMore is guarded against
  // double-fire, so this composes safely with the observer; and because the
  // effect re-runs whenever loadMore changes (after each batch), it also auto-
  // fills when the content is shorter than the viewport.
  useEffect(() => {
    if (!hasMore) return;
    const NEAR_BOTTOM_PX = 800;
    const check = () => {
      const doc = document.documentElement;
      // Only engage once content overflows the viewport — the observer already
      // covers the shorter-than-viewport case. (This also keeps the fallback
      // inert under jsdom, which reports scrollHeight 0.)
      if (doc.scrollHeight <= window.innerHeight) return;
      if (window.innerHeight + window.scrollY >= doc.scrollHeight - NEAR_BOTTOM_PX) {
        loadMore();
      }
    };
    check();
    window.addEventListener('scroll', check, { passive: true });
    window.addEventListener('resize', check);
    return () => {
      window.removeEventListener('scroll', check);
      window.removeEventListener('resize', check);
    };
  }, [hasMore, loadMore]);

  const displayed = useMemo(
    () => filtered.slice(0, displayedCount),
    [filtered, displayedCount]
  );

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <SearchBar value={search} onChange={setSearch} />
      </Box>

      {filtered.length === 0 ? (
        <EmptyState
          title="No companies found"
          message={
            debouncedSearch.trim()
              ? `No companies match “${debouncedSearch.trim()}”.`
              : 'No companies to display yet.'
          }
        />
      ) : (
        <>
          <Grid container spacing={2}>
            {displayed.map((company) => (
              <Grid key={company.id} size={GRID_ITEM_SIZE}>
                <CompanyCard company={company} />
              </Grid>
            ))}

            {isLoadingMore &&
              Array.from({ length: CHANGELOG_INFINITE_SCROLL_CONFIG.SKELETON_COUNT }).map(
                (_, index) => (
                  <Grid key={`skeleton-${index}`} size={GRID_ITEM_SIZE}>
                    <CompanyCardSkeleton />
                  </Grid>
                )
              )}
          </Grid>

          {hasMore && !isLoadingMore && (
            <div ref={sentinelRef} aria-hidden="true" style={{ height: '1px', width: '100%' }} />
          )}

          {!hasMore && filtered.length > CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE && (
            <Box sx={{ textAlign: 'center', py: 2 }} role="status">
              <Typography variant="body2" color="text.secondary">
                All {filtered.length} companies shown
              </Typography>
            </Box>
          )}
        </>
      )}
    </Box>
  );
}
