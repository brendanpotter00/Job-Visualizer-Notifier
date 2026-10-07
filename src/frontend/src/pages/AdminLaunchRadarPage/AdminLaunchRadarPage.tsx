import { useState } from 'react';
import Box from '@mui/material/Box';
import Container from '@mui/material/Container';
import Pagination from '@mui/material/Pagination';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Typography from '@mui/material/Typography';
import { useGetLaunchRadarCardsQuery } from '../../features/admin/adminApi';
import type {
  LaunchRadarCard,
  LaunchRadarCardsResponse,
  LaunchRadarStatus,
} from '../../features/admin/launchRadarTypes';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { RESPONSIVE } from '../../config/responsive';
import { RadarCard } from './components/RadarCard';
import { DeleteCardDialog } from './components/DeleteCardDialog';
import { formatRunLine } from './format';

/** Server page size. The list is never unbounded: each tab is paged by the API. */
const ROWS_PER_PAGE = 25;

const EMPTY_COPY: Record<LaunchRadarStatus, string> = {
  new: 'No new cards.',
  archived: 'No archived cards.',
};

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
 * New / Archived tabs; archive and restore are one click, permanent delete
 * (archived only) goes through a confirm dialog.
 */
export function AdminLaunchRadarPage() {
  const [tab, setTab] = useState<LaunchRadarStatus>('new');
  const [page, setPage] = useState(0);
  const [pendingDelete, setPendingDelete] = useState<LaunchRadarCard | null>(null);

  const query = useGetLaunchRadarCardsQuery({ status: tab, page, rowsPerPage: ROWS_PER_PAGE });

  // Each (status, page) is its own cache entry. RTK Query's `data` is "the
  // latest result regardless of hook arg": after a tab switch it still holds
  // the OTHER tab's response until the new fetch resolves. `currentData` is the
  // result for the current arg only (undefined while it loads), so the list
  // reads `currentData` and the other tab's cards can never render under this
  // tab's heading (with live Archive buttons). The header (counts, last run,
  // spend) is global, so it may keep showing the latest response.
  // Hold the last resolved list, keyed by status, so paging within a tab does
  // not flash. Adjusting state during render (guarded) is React's sanctioned
  // alternative to a setState-in-effect (as in AdminFeedbackPage).
  const [last, setLast] = useState<{ status: LaunchRadarStatus; data: LaunchRadarCardsResponse }>();
  if (query.currentData && query.currentData !== last?.data) {
    setLast({ status: tab, data: query.currentData });
  }

  const header = query.data ?? last?.data;
  const listData = query.currentData ?? (last?.status === tab ? last.data : undefined);
  const total = listData?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / ROWS_PER_PAGE));

  // Archiving the last card on the last page leaves that page empty; step back
  // to the new last page instead of showing "No new cards." over a non-zero count.
  if (query.currentData && page > pageCount - 1) {
    setPage(pageCount - 1);
  }

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
      <Typography variant="h4" component="h1">
        Launch Radar
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, mb: 2, maxWidth: 560 }}>
        Startups the Parallel loop found, newest first.
        {header && ` ${formatRunLine(header.stats)}`}
      </Typography>

      <Tabs
        value={tab}
        onChange={(_, next: LaunchRadarStatus) => {
          setTab(next);
          setPage(0);
        }}
        aria-label="Launch Radar card lists"
        sx={{ borderBottom: 1, borderColor: 'divider', mb: 1.5 }}
      >
        <Tab
          value="new"
          id="radar-tab-new"
          aria-controls="radar-tabpanel"
          label={<TabLabel label="New" count={header?.counts.new} />}
          sx={{ textTransform: 'none' }}
        />
        <Tab
          value="archived"
          id="radar-tab-archived"
          aria-controls="radar-tabpanel"
          label={<TabLabel label="Archived" count={header?.counts.archived} />}
          sx={{ textTransform: 'none' }}
        />
      </Tabs>

      {query.error && (
        <Box sx={{ mb: 1.5 }}>
          <ErrorState
            inline
            message={extractErrorMessage(query.error, 'Failed to load Launch Radar cards')}
            onRetry={() => query.refetch()}
          />
        </Box>
      )}

      <Box id="radar-tabpanel" role="tabpanel" aria-labelledby={`radar-tab-${tab}`}>
        {!listData ? (
          <LoadingState caption="Loading cards…" />
        ) : cards.length === 0 ? (
          <Typography color="text.disabled" sx={{ textAlign: 'center', py: 2.25 }}>
            {EMPTY_COPY[tab]}
          </Typography>
        ) : (
          cards.map((card) => (
            <RadarCard key={card.id} card={card} onRequestDelete={setPendingDelete} />
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

      <DeleteCardDialog card={pendingDelete} onClose={() => setPendingDelete(null)} />
    </Container>
  );
}
