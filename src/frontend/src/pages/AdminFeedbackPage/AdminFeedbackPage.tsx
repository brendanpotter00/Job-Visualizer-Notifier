import { useMemo } from 'react';
import Container from '@mui/material/Container';
import Typography from '@mui/material/Typography';
import { useListAdminFeedbackQuery } from '../../features/admin/adminApi';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { FeedbackTable } from './components/FeedbackTable';

export function AdminFeedbackPage() {
  const query = useListAdminFeedbackQuery();
  const feedback = useMemo(() => query.data ?? [], [query.data]);

  if (query.isLoading && feedback.length === 0) {
    return <LoadingState fullPage caption="Loading feedback…" />;
  }

  if (query.error) {
    return (
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <ErrorState
          inline
          message={extractErrorMessage(query.error, 'Failed to load feedback')}
          onRetry={() => query.refetch()}
        />
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Typography variant="h4" component="h1" gutterBottom>
        Admin · User Feedback
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {feedback.length.toLocaleString()}{' '}
        {feedback.length === 1 ? 'submission' : 'submissions'}
      </Typography>
      <FeedbackTable feedback={feedback} />
    </Container>
  );
}
