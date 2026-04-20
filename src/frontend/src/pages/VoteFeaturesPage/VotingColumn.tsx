import { Stack, Typography } from '@mui/material';
import { useListFeaturesQuery } from '../../features/features/featuresApi';
import { LoadingState } from '../../components/shared/LoadingIndicator';
import { ErrorState, EmptyState } from '../../components/shared/ErrorDisplay';
import { extractErrorMessage } from '../../lib/errors';
import { FeatureVoteCard } from './FeatureVoteCard';

export function VotingColumn() {
  const { data, isLoading, isError, error, refetch } = useListFeaturesQuery();

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
      {!isLoading && !isError && data && data.length > 0 && (
        <Stack spacing={2}>
          {data.map((feature) => (
            <FeatureVoteCard key={feature.id} feature={feature} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}
