import { useMemo } from 'react';
import { Box, Stack, Typography } from '@mui/material';
import { useAutoAnimate } from '@formkit/auto-animate/react';
import { useListFeaturesQuery } from '../../features/features/featuresApi';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState, EmptyState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { FeatureVoteCard } from './FeatureVoteCard';

export function VotingColumn() {
  const { data, isLoading, isError, error, refetch } = useListFeaturesQuery();
  const [parent] = useAutoAnimate<HTMLDivElement>();
  const [completedParent] = useAutoAnimate<HTMLDivElement>();

  const { upcoming, completed } = useMemo(() => {
    if (!data) {
      return { upcoming: undefined, completed: undefined };
    }
    // Upcoming = still open for votes; most-voted first (createdAt breaks ties).
    const upcoming = data
      .filter((f) => f.completedAt == null)
      .sort((a, b) => {
        if (b.upvoteCount !== a.upvoteCount) return b.upvoteCount - a.upvoteCount;
        return a.createdAt.localeCompare(b.createdAt);
      });
    // Completed = shipped; most-recently-shipped first.
    const completed = data
      .filter((f) => f.completedAt != null)
      .sort((a, b) => (b.completedAt as string).localeCompare(a.completedAt as string));
    return { upcoming, completed };
  }, [data]);

  const showEmpty = !isLoading && !isError && (!data || data.length === 0);
  const showUpcoming = !isLoading && !isError && upcoming && upcoming.length > 0;
  const showCompleted = !isLoading && !isError && completed && completed.length > 0;
  // Everything's shipped and there's nothing left to vote on — keep the heading
  // honest instead of leaving a bare title with no cards under it.
  const showAllShipped =
    !isLoading &&
    !isError &&
    upcoming &&
    upcoming.length === 0 &&
    completed &&
    completed.length > 0;

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h2">
        Vote on upcoming features
      </Typography>
      {isLoading && <LoadingState minHeight={200} />}
      {isError && (
        <ErrorState
          inline
          message={extractErrorMessage(error, 'Failed to load features.')}
          onRetry={() => {
            void refetch();
          }}
        />
      )}
      {showEmpty && (
        <EmptyState
          title="No features yet"
          message="Candidate features will appear here once they are seeded."
        />
      )}
      {showAllShipped && (
        <Typography variant="body2" color="text.secondary">
          Nothing open to vote on right now — everything below has shipped.
        </Typography>
      )}
      {showUpcoming && (
        <Box ref={parent} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {upcoming.map((feature) => (
            <FeatureVoteCard key={feature.id} feature={feature} />
          ))}
        </Box>
      )}
      {showCompleted && (
        <Box sx={{ pt: 2 }}>
          <Typography variant="h5" component="h2">
            Shipped — built with the community
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Completed features the community voted for. We listen and ship.
          </Typography>
          <Box ref={completedParent} sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {completed.map((feature) => (
              <FeatureVoteCard key={feature.id} feature={feature} readOnly />
            ))}
          </Box>
        </Box>
      )}
    </Stack>
  );
}
