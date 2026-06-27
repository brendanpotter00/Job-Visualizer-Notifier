import { useState } from 'react';
import Container from '@mui/material/Container';
import Typography from '@mui/material/Typography';
import {
  useListAdminFeedbackQuery,
  type AdminFeedbackListResponse,
} from '../../features/admin/adminApi';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { FeedbackTable } from './components/FeedbackTable';
import { RESPONSIVE } from '../../config/responsive';

export function AdminFeedbackPage() {
  // Pagination/sort state lives here because it drives the server query — each
  // change refetches a single page instead of slicing a fetched array, so the
  // admin can reach all feedback (not just the first 200).
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const query = useListAdminFeedbackQuery({ page, rowsPerPage, sortDir });

  // Each (page, rowsPerPage, sortDir) is a distinct RTK Query cache key, so
  // ``query.data`` blips to undefined while a new page loads. Hold the last
  // resolved page so the table doesn't flash empty between pages. Adjusting
  // state during render (guarded) is React's sanctioned alternative to a
  // setState-in-effect for "remember the previous render's value".
  const [lastData, setLastData] = useState<AdminFeedbackListResponse>();
  if (query.data && query.data !== lastData) {
    setLastData(query.data);
  }

  const data = query.data ?? lastData;
  const feedback = data?.feedback ?? [];
  const total = data?.total ?? 0;

  if (query.isLoading && !lastData) {
    return <LoadingState fullPage caption="Loading feedback…" />;
  }

  if (query.error && !lastData) {
    return (
      <Container maxWidth="lg" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
        <ErrorState
          inline
          message={extractErrorMessage(query.error, 'Failed to load feedback')}
          onRetry={() => query.refetch()}
        />
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ py: RESPONSIVE.spacing.pageMarginY }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Admin · User Feedback
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {total.toLocaleString()} {total === 1 ? 'submission' : 'submissions'}
      </Typography>
      <FeedbackTable
        feedback={feedback}
        total={total}
        page={page}
        rowsPerPage={rowsPerPage}
        sortDir={sortDir}
        onPageChange={setPage}
        onRowsPerPageChange={(next) => {
          setRowsPerPage(next);
          setPage(0);
        }}
        onToggleSort={() => {
          setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
          setPage(0);
        }}
      />
    </Container>
  );
}
