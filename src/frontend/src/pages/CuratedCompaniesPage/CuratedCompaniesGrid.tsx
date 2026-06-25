import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Grid, Typography } from '@mui/material';
import { EmptyState } from '../../components/shared/ErrorDisplay';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { CHANGELOG_INFINITE_SCROLL_CONFIG } from '../../constants/ui';
import type { CuratedCompany } from '../../features/companies/companiesApi';
import { CompanyCard } from './CompanyCard';
import { SearchBar } from './SearchBar';
import { RESPONSIVE } from '../../config/responsive';

interface CuratedCompaniesGridProps {
  companies: CuratedCompany[];
}

// 2-up on phones (was 1-up), 2-up sm, 3-up md+ (md restates the current value).
const GRID_ITEM_SIZE = RESPONSIVE.curatedCard.gridItemSize;

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

  const [visibleCount, setVisibleCount] = useState<number>(
    CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE
  );

  // Reset to the first batch whenever the (debounced) search query changes, so a
  // new search starts from the top of its result set. Done during render (not in
  // an effect) per React's "adjust state when a value changes" pattern.
  const [lastSearch, setLastSearch] = useState(debouncedSearch);
  if (debouncedSearch !== lastSearch) {
    setLastSearch(debouncedSearch);
    setVisibleCount(CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE);
  }

  const hasMore = visibleCount < filtered.length;
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const loadMore = useCallback(() => {
    setVisibleCount((count) =>
      Math.min(count + CHANGELOG_INFINITE_SCROLL_CONFIG.SUBSEQUENT_BATCH_SIZE, filtered.length)
    );
  }, [filtered.length]);

  // Standard infinite scroll: an IntersectionObserver watches a sentinel at the
  // bottom of the list and reveals the next batch when it scrolls into view.
  // Re-running on visibleCount re-observes after each reveal, which continues
  // loading as you scroll and auto-fills when the first batch is shorter than
  // the viewport.
  useEffect(() => {
    if (!hasMore) return;
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMore();
      },
      { rootMargin: '200px' }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, visibleCount, loadMore]);

  const displayed = useMemo(() => filtered.slice(0, visibleCount), [filtered, visibleCount]);

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
          <Grid container spacing={RESPONSIVE.curatedCard.gridSpacing}>
            {displayed.map((company) => (
              <Grid key={company.id} size={GRID_ITEM_SIZE}>
                <CompanyCard company={company} />
              </Grid>
            ))}
          </Grid>

          {hasMore && <Box ref={sentinelRef} aria-hidden="true" sx={{ height: '1px' }} />}

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
