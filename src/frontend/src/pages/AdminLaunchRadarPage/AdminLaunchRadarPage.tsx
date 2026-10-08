import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import Pagination from '@mui/material/Pagination';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';
import { useGetLaunchRadarCardsQuery } from '../../features/admin/adminApi';
import {
  DEFAULT_LAUNCH_RADAR_SORT,
  LAUNCH_RADAR_SORTS,
  LAUNCH_RADAR_STATUSES,
  type LaunchRadarCard,
  type LaunchRadarCardsResponse,
  type LaunchRadarSort,
  type LaunchRadarStatus,
} from '../../features/admin/launchRadarTypes';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { RESPONSIVE } from '../../config/responsive';
import { RadarCard } from './components/RadarCard';
import type { CardAction } from './components/CardStatusLine';
import { DeleteCardDialog } from './components/DeleteCardDialog';
import { cardToggleId, parseSort } from './format';

/** Server page size. The list is never unbounded: each tab is paged by the API. */
const ROWS_PER_PAGE = 25;

/** One tab per status, in `LAUNCH_RADAR_STATUSES` order. A card is in exactly one tab. */
const TABS: Record<LaunchRadarStatus, { label: string; empty: string }> = {
  new: { label: 'New', empty: 'No new cards.' },
  saved: { label: 'Saved', empty: 'No saved cards.' },
  archived: { label: 'Archived', empty: 'No archived cards.' },
};

const SORT_LABEL: Record<LaunchRadarSort, string> = {
  announced: 'Announced',
  talent: 'Talent',
  vc: 'VC',
  added: 'Added',
};

/** What the live region says when a card leaves the list ("Saved Lightfield"). */
const LEFT_VERB: Record<CardAction | 'delete', string> = {
  save: 'Saved',
  unsave: 'Unsaved',
  archive: 'Archived',
  restore: 'Restored',
  delete: 'Deleted',
};

/** Read by screen readers, invisible on screen. */
const VISUALLY_HIDDEN = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  p: 0,
  m: '-1px',
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap',
  border: 0,
} as const;

/** A card that just left the list, and where it sat (for the next focus). */
interface Leaving {
  id: number;
  index: number;
}

function TabLabel({ label, count }: { label: string; count: number | undefined }) {
  return (
    <span>
      {label}
      {count !== undefined && (
        <>
          {' '}
          <Box component="span" sx={{ color: 'text.disabled', fontWeight: 400, ml: 0.25 }}>
            {count}
          </Box>
        </>
      )}
    </span>
  );
}

/**
 * /admin/launch-radar — the startups the Parallel loop found, one card each.
 * New / Saved / Archived tabs, sorted by the server (newest announcement,
 * Talent, VC or newest added; the sort is in the URL as `?sort=`); save,
 * unsave, archive and restore are one click, permanent delete (archived only)
 * goes through a confirm dialog.
 */
export function AdminLaunchRadarPage() {
  const [tab, setTab] = useState<LaunchRadarStatus>('new');
  const [page, setPage] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<{
    card: LaunchRadarCard;
    index: number;
  } | null>(null);
  // The sort lives in the URL so a sorted view can be bookmarked and shared.
  // The default is left out of the URL; an unknown value reads as the default.
  const [searchParams, setSearchParams] = useSearchParams();
  const sort = parseSort(searchParams.get('sort'));

  const query = useGetLaunchRadarCardsQuery({
    status: tab,
    page,
    rowsPerPage: ROWS_PER_PAGE,
    sort,
  });

  // Each (status, page, sort) is its own cache entry. After a tab switch RTK
  // Query's `data` still holds the OTHER tab's response until the new fetch
  // resolves; `currentData` is this arg's result only (undefined while it
  // loads). So the list reads `currentData` and never renders another tab's
  // cards, live buttons and all, under this tab's heading; the tab counts are
  // global and may show the latest response. `last` holds
  // the last resolved list per status so paging or re-sorting within a tab
  // does not flash (state adjusted during render, guarded, as in AdminFeedbackPage).
  const [last, setLast] = useState<{ status: LaunchRadarStatus; data: LaunchRadarCardsResponse }>();
  if (query.currentData && query.currentData !== last?.data) {
    setLast({ status: tab, data: query.currentData });
  }

  // `currentData` first: while a refetch is in flight `data` is the hook's
  // last tracked result, which predates a cache update made since (a card
  // that just left its tab, with its counts moved).
  const header = query.currentData ?? query.data ?? last?.data;
  const listData = query.currentData ?? (last?.status === tab ? last.data : undefined);
  const total = listData?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / ROWS_PER_PAGE));

  // Archiving the last card on the last page leaves that page empty; step back
  // to the new last page instead of showing "No new cards." over a non-zero count.
  if (query.currentData && page > pageCount - 1) {
    setPage(pageCount - 1);
  }

  // A card that leaves the list (Save, Unsave, Archive, Restore, Delete) takes
  // the focused button with it, which would drop keyboard focus to <body>. Once
  // it is gone from the rendered list, focus moves to the card that took its
  // place (the next one), or to the tab panel when it was the last. The live
  // region says what happened.
  const [leaving, setLeaving] = useState<Leaving | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const focusedFor = useRef<Leaving | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!leaving || focusedFor.current === leaving) return;
    const rendered = listData?.cards;
    if (!rendered || rendered.some((c) => c.id === leaving.id)) return; // not gone yet
    focusedFor.current = leaving;
    const next = rendered[leaving.index];
    const target = next ? document.getElementById(cardToggleId(next.id)) : panelRef.current;
    target?.focus();
  }, [leaving, listData]);

  const cardLeft = (card: Pick<LaunchRadarCard, 'id' | 'company'>, index: number, verb: string) => {
    setAnnouncement(`${verb} ${card.company}`);
    setLeaving({ id: card.id, index });
  };

  const changeSort = (next: LaunchRadarSort) => {
    setSearchParams(
      (prev) => {
        const params = new URLSearchParams(prev);
        if (next === DEFAULT_LAUNCH_RADAR_SORT) params.delete('sort');
        else params.set('sort', next);
        return params;
      },
      { replace: true }
    );
    setPage(0);
    setLeaving(null);
  };

  if (query.isLoading && !header) {
    return <LoadingState fullPage caption="Loading Launch Radar…" />;
  }

  if (query.error && !header) {
    return (
      <Container maxWidth="md" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
        <ErrorState
          inline
          message={extractErrorMessage(query.error, 'Failed to load Launch Radar cards')}
          onRetry={() => query.refetch()}
        />
      </Container>
    );
  }

  const cards = listData?.cards ?? [];

  return (
    <Container maxWidth="md" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      <Typography variant="h4" component="h1" sx={{ mb: 2 }}>
        Launch Radar
      </Typography>

      {/* Desktop (md+): the tabs and the sort share one row over one divider.
          Narrower: they stack, the divider under the tabs (where the selected
          tab's indicator sits) and the sort on its own row below, so nothing
          is clipped and the page never scrolls sideways. */}
      <Box
        sx={{
          display: 'flex',
          flexDirection: { xs: 'column', md: 'row' },
          flexWrap: 'wrap',
          alignItems: { xs: 'stretch', md: 'center' },
          columnGap: 2,
          borderBottom: { xs: 0, md: 1 },
          borderColor: 'divider',
          mb: 1.5,
        }}
      >
        <Tabs
          value={tab}
          onChange={(_, next: LaunchRadarStatus) => {
            setTab(next);
            setPage(0);
            setLeaving(null);
          }}
          aria-label="Launch Radar card lists"
          // Scrollable, not clipped: should the counts ever outgrow a phone,
          // the tab strip scrolls inside itself instead of cutting off a label.
          variant="scrollable"
          scrollButtons={false}
          sx={{ borderBottom: { xs: 1, md: 0 }, borderColor: 'divider' }}
        >
          {LAUNCH_RADAR_STATUSES.map((status) => (
            <Tab
              key={status}
              value={status}
              id={`radar-tab-${status}`}
              aria-controls="radar-tabpanel"
              label={<TabLabel label={TABS[status].label} count={header?.counts[status]} />}
              sx={{
                textTransform: 'none',
                // MUI's 90px minimum and 16px sides fit three tabs on a phone
                // only with the last one cut off; sm+ keeps the defaults.
                minWidth: RESPONSIVE.launchRadar.tabMinWidth,
                px: RESPONSIVE.launchRadar.tabPaddingX,
              }}
            />
          ))}
        </Tabs>
        {/* "Sort by" and the toggles wrap as two units: on the narrowest
            screens the toggles drop under the label, never off the edge. */}
        <Box
          sx={{
            display: 'flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: { xs: 'flex-start', sm: 'flex-end' },
            columnGap: 1,
            rowGap: 0.75,
            ml: { md: 'auto' },
            py: 0.75,
          }}
        >
          <Typography
            component="span"
            variant="body2"
            color="text.secondary"
            sx={{ whiteSpace: 'nowrap' }}
          >
            Sort by
          </Typography>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={sort}
            // Pressing the selected button again sends `null`: keep the sort.
            onChange={(_, next: LaunchRadarSort | null) => {
              if (next) changeSort(next);
            }}
            aria-label="Sort cards by"
          >
            {LAUNCH_RADAR_SORTS.map((key) => (
              <ToggleButton
                key={key}
                value={key}
                sx={{
                  textTransform: 'none',
                  whiteSpace: 'nowrap',
                  py: 0.25,
                  px: RESPONSIVE.launchRadar.sortButtonPaddingX,
                  // A clear keyboard focus ring (the default is a faint ripple).
                  '&.Mui-focusVisible': {
                    outline: '2px solid',
                    outlineColor: 'primary.main',
                    outlineOffset: '-2px',
                  },
                }}
              >
                {SORT_LABEL[key]}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>
      </Box>

      {query.error && (
        <Box sx={{ mb: 1.5 }}>
          <ErrorState
            inline
            message={extractErrorMessage(query.error, 'Failed to load Launch Radar cards')}
            onRetry={() => query.refetch()}
          />
        </Box>
      )}

      <Box
        id="radar-tabpanel"
        role="tabpanel"
        aria-labelledby={`radar-tab-${tab}`}
        // Focusable from script only: where focus lands when the last card leaves.
        tabIndex={-1}
        ref={panelRef}
      >
        {!listData ? (
          <LoadingState caption="Loading cards…" />
        ) : cards.length === 0 ? (
          <Typography color="text.disabled" sx={{ textAlign: 'center', py: 2.25 }}>
            {TABS[tab].empty}
          </Typography>
        ) : (
          cards.map((card, index) => (
            <RadarCard
              key={card.id}
              card={card}
              sort={sort}
              onRequestDelete={(c) => setPendingDelete({ card: c, index })}
              onLeave={(c, action) => cardLeft(c, index, LEFT_VERB[action])}
            />
          ))
        )}
      </Box>

      {total > ROWS_PER_PAGE && (
        <Pagination
          count={pageCount}
          page={page + 1}
          onChange={(_, next) => setPage(next - 1)}
          sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}
        />
      )}

      <Box role="status" aria-live="polite" sx={VISUALLY_HIDDEN}>
        {announcement}
      </Box>

      <DeleteCardDialog
        card={pendingDelete?.card ?? null}
        onClose={() => setPendingDelete(null)}
        onDeleted={(c) => cardLeft(c, pendingDelete?.index ?? 0, LEFT_VERB.delete)}
      />
    </Container>
  );
}
