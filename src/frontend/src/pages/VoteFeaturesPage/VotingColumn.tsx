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

  const sortedFeatures = useMemo(() => {
    if (!data) return data;
    return [...data].sort((a, b) => {
      if (b.upvoteCount !== a.upvoteCount) return b.upvoteCount - a.upvoteCount;
      return a.createdAt.localeCompare(b.createdAt);
    });
  }, [data]);

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
      {!isLoading && !isError && (!data || data.length === 0) && (
        <EmptyState
          title="No features yet"
          message="Candidate features will appear here once they are seeded."
        />
      )}
      {!isLoading && !isError && sortedFeatures && sortedFeatures.length > 0 && (
        <Box
          ref={parent}
          sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}
        >
          {sortedFeatures.map((feature) => (
            <FeatureVoteCard key={feature.id} feature={feature} />
          ))}
        </Box>
      )}
    </Stack>
  );
}
