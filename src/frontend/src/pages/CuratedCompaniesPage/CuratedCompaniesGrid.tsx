import { useCallback, useEffect, useMemo, useState } from 'react';
import { Box, Grid, Typography } from '@mui/material';
import { EmptyState } from '../../components/shared/ErrorDisplay';
import { useDebouncedValue } from '../../hooks/useDebouncedValue';
import { CHANGELOG_INFINITE_SCROLL_CONFIG } from '../../constants/ui';
import type { CuratedCompany } from '../../features/companies/companiesApi';
import { CompanyCard } from './CompanyCard';
import { SearchBar } from './SearchBar';

interface CuratedCompaniesGridProps {
  companies: CuratedCompany[];
}

const GRID_ITEM_SIZE = { xs: 12, sm: 6, md: 4 } as const;

// Reveal the next batch when the viewport bottom comes within this many px of
// the page bottom. Small enough that we only ever load ~one batch ahead (so the
// page lazy-loads instead of rendering all ~130 cards up front), large enough
// to prefetch slightly before the user hits the very end.
const REVEAL_THRESHOLD_PX = 300;

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

  const [displayedCount, setDisplayedCount] = useState<number>(
    CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE
  );

  // Reset to the first batch whenever the (debounced) search query changes, so a
  // new search starts from the top of its result set. Done during render rather
  // than in an effect — React's recommended "adjust state when a value changes"
  // pattern — which avoids a second commit per keystroke.
  const [lastSearch, setLastSearch] = useState(debouncedSearch);
  if (debouncedSearch !== lastSearch) {
    setLastSearch(debouncedSearch);
    setDisplayedCount(CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE);
  }

  const hasMore = displayedCount < filtered.length;

  const revealMore = useCallback(() => {
    setDisplayedCount((count) =>
      Math.min(count + CHANGELOG_INFINITE_SCROLL_CONFIG.SUBSEQUENT_BATCH_SIZE, filtered.length)
    );
  }, [filtered.length]);

  // Reveal the next batch as the viewport nears the page bottom. A plain
  // window-scroll check (rather than an IntersectionObserver on a tiny sentinel)
  // is both reliable across browsers and precisely self-limiting: reading
  // scrollHeight forces a fresh layout, so each pass sees the true height and
  // stops exactly when the viewport is filled — no over-loading. The effect
  // re-runs after each reveal (displayedCount dep), which also auto-fills when
  // the initial batch is shorter than the viewport.
  useEffect(() => {
    if (!hasMore) return;
    const check = () => {
      const doc = document.documentElement;
      if (window.innerHeight + window.scrollY >= doc.scrollHeight - REVEAL_THRESHOLD_PX) {
        revealMore();
      }
    };
    check();
    window.addEventListener('scroll', check, { passive: true });
    window.addEventListener('resize', check);
    return () => {
      window.removeEventListener('scroll', check);
      window.removeEventListener('resize', check);
    };
  }, [hasMore, displayedCount, revealMore]);

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
          </Grid>

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
