import { useCallback, useEffect, useMemo, useState } from 'react';
import { Box, Card, CardContent, Chip, Link, Stack, Typography } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { format, parseISO } from 'date-fns';
import { Link as RouterLink } from 'react-router-dom';
import {
  CHANGELOG,
  CHANGELOG_TAGS,
  type ChangelogEntry,
  type ChangelogTag,
} from '../../config/changelog';
import { MultiSelectAutocomplete } from '../../components/shared/filters/MultiSelectAutocomplete';
import { useInfiniteScroll } from '../../hooks/useInfiniteScroll';
import { CHANGELOG_INFINITE_SCROLL_CONFIG, INFINITE_SCROLL_CONFIG } from '../../constants/ui';
import { CHANGELOG_MESSAGES } from '../../constants/messages';
import { ChangelogSkeletons } from './ChangelogSkeletons';
import { RESPONSIVE } from '../../config/responsive';

const BLACK_CHIP_SX: SxProps<Theme> = {
  bgcolor: 'common.black',
  color: 'common.white',
};

const TAG_SX: Record<ChangelogTag, SxProps<Theme>> = {
  feature: { bgcolor: 'success.main', color: 'success.contrastText' },
  improvement: BLACK_CHIP_SX,
  'new-companies': BLACK_CHIP_SX,
};

function isChangelogTag(value: string): value is ChangelogTag {
  return (CHANGELOG_TAGS as readonly string[]).includes(value);
}

export function ChangelogColumn() {
  const [selected, setSelected] = useState<ChangelogTag[]>([]);

  const visibleEntries: ChangelogEntry[] = useMemo(() => {
    const base =
      selected.length === 0
        ? [...CHANGELOG]
        : CHANGELOG.filter((entry) => entry.tags.some((tag) => selected.includes(tag)));
    return base.sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
  }, [selected]);

  // Incremental rendering: only mount the first `displayedCount` cards, then
  // reveal more as the sentinel scrolls into view. The data is all client-side,
  // so this caps the up-front DOM cost and keeps growing as entries are added.
  const [displayedCount, setDisplayedCount] = useState<number>(
    CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE
  );
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const hasMore = displayedCount < visibleEntries.length;

  const loadMore = useCallback(() => {
    if (!hasMore || isLoadingMore) return;

    setIsLoadingMore(true);
    // Defer the batch bump so the browser can paint the skeletons first,
    // mirroring RecentJobsList.
    setTimeout(() => {
      setDisplayedCount((prev) =>
        Math.min(
          prev + CHANGELOG_INFINITE_SCROLL_CONFIG.SUBSEQUENT_BATCH_SIZE,
          visibleEntries.length
        )
      );
      setIsLoadingMore(false);
    }, 0);
  }, [hasMore, isLoadingMore, visibleEntries.length]);

  const { sentinelRef } = useInfiniteScroll({
    hasMore,
    isLoadingMore,
    onLoadMore: loadMore,
    rootMargin: INFINITE_SCROLL_CONFIG.SENTINEL_ROOT_MARGIN,
    threshold: INFINITE_SCROLL_CONFIG.SENTINEL_THRESHOLD,
  });

  // Reset back to the first batch whenever the tag filter changes so a new
  // filter always starts from the top of its (re-sorted) result set.
  useEffect(() => {
    setDisplayedCount(CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE);
  }, [selected]);

  const displayedEntries = useMemo(
    () => visibleEntries.slice(0, displayedCount),
    [visibleEntries, displayedCount]
  );

  const handleAdd = (value: string) => {
    if (isChangelogTag(value)) {
      setSelected((prev) => (prev.includes(value) ? prev : [...prev, value]));
    }
  };

  const handleRemove = (value: string) => {
    setSelected((prev) => prev.filter((tag) => tag !== value));
  };

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h2">
        Changelog
      </Typography>
      <MultiSelectAutocomplete
        label="Tags"
        options={[...CHANGELOG_TAGS]}
        value={selected}
        onAdd={handleAdd}
        onRemove={handleRemove}
        placeholder="Filter by tag..."
      />
      {visibleEntries.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No changelog entries match the selected tags.
        </Typography>
      ) : (
        <Stack spacing={2}>
          {displayedEntries.map((entry) => (
            <Card key={entry.id} variant="outlined">
              <CardContent
                sx={{
                  p: RESPONSIVE.spacing.cardPadding,
                  '&:last-child': { pb: RESPONSIVE.spacing.cardPaddingBottom },
                }}
              >
                <Stack
                  direction="row"
                  justifyContent="space-between"
                  alignItems="flex-start"
                  spacing={2}
                  sx={{ mb: 1 }}
                >
                  <Typography variant="h6" component="h3">
                    {entry.title}
                  </Typography>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ whiteSpace: 'nowrap', pt: 0.5 }}
                  >
                    {format(parseISO(entry.date), 'MMM d, yyyy')}
                  </Typography>
                </Stack>
                <Typography variant="body2" color="text.secondary" sx={{ mb: entry.link ? 1 : 2 }}>
                  {entry.description}
                </Typography>
                {entry.link && (
                  <Typography variant="body2" sx={{ mb: 2 }}>
                    <Link component={RouterLink} to={entry.link.to}>
                      {entry.link.label}
                    </Link>
                  </Typography>
                )}
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {entry.tags.map((tag) => (
                    <Chip key={tag} label={tag} size="small" sx={TAG_SX[tag]} />
                  ))}
                </Box>
              </CardContent>
            </Card>
          ))}

          {/* Skeleton placeholders while the next batch is being revealed */}
          {isLoadingMore && (
            <ChangelogSkeletons count={CHANGELOG_INFINITE_SCROLL_CONFIG.SKELETON_COUNT} />
          )}

          {/* Sentinel that triggers loading the next batch when scrolled near */}
          {hasMore && !isLoadingMore && (
            <div ref={sentinelRef} aria-hidden="true" style={{ height: '1px', width: '100%' }} />
          )}

          {/* End-of-list message once everything is shown */}
          {!hasMore &&
            visibleEntries.length > CHANGELOG_INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE && (
              <Box sx={{ textAlign: 'center', py: 2 }} role="status">
                <Typography variant="body2" color="text.secondary">
                  {CHANGELOG_MESSAGES.ALL_LOADED(visibleEntries.length)}
                </Typography>
              </Box>
            )}
        </Stack>
      )}
    </Stack>
  );
}
