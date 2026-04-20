import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { FeatureListItem } from '../../../features/features/featuresApi';

/**
 * VotingColumn branch coverage.
 *
 * The column has four mutually-exclusive render branches driven by RTK
 * Query's `useListFeaturesQuery()` result: loading, error (with retry),
 * empty, and data. `FeatureVoteCard` is mocked so the tests stay scoped to
 * the column's branching logic — the card itself is covered by its own
 * dedicated test file.
 */

type QueryResult = {
  data: FeatureListItem[] | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
};

let mockQueryResult: QueryResult = {
  data: undefined,
  isLoading: false,
  isError: false,
  error: undefined,
  refetch: vi.fn(),
};

vi.mock('../../../features/features/featuresApi', () => ({
  useListFeaturesQuery: () => mockQueryResult,
}));

// Keep FeatureVoteCard trivial so we can assert it rendered once per feature
// without pulling in its auth/modal machinery.
vi.mock('../../../pages/VoteFeaturesPage/FeatureVoteCard', () => ({
  FeatureVoteCard: ({ feature }: { feature: FeatureListItem }) => (
    <div data-testid={`feature-vote-card-${feature.id}`}>{feature.title}</div>
  ),
}));

// Import AFTER the mocks are registered so VotingColumn picks them up.
import { VotingColumn } from '../../../pages/VoteFeaturesPage/VotingColumn';

const SAMPLE_FEATURES: FeatureListItem[] = [
  {
    id: 'resume-match-ai',
    title: 'AI resume matching notifications',
    description: 'Upload your resume.',
    createdAt: '2026-04-10T00:00:00Z',
    upvoteCount: 3,
    hasUpvoted: false,
  },
  {
    id: 'location-normalization',
    title: 'Location normalization',
    description: 'Normalize job-posting locations.',
    createdAt: '2026-04-11T00:00:00Z',
    upvoteCount: 7,
    hasUpvoted: true,
  },
];

describe('VotingColumn', () => {
  beforeEach(() => {
    mockQueryResult = {
      data: undefined,
      isLoading: false,
      isError: false,
      error: undefined,
      refetch: vi.fn(),
    };
  });

  describe('loading branch', () => {
    it('renders the LoadingState spinner when isLoading is true', () => {
      mockQueryResult = { ...mockQueryResult, isLoading: true };
      render(<VotingColumn />);
      expect(screen.getByRole('progressbar')).toBeInTheDocument();
      expect(
        screen.queryByRole('alert')
      ).not.toBeInTheDocument();
    });
  });

  describe('error branch', () => {
    it('renders the ErrorState and surfaces the decoded message', () => {
      mockQueryResult = {
        ...mockQueryResult,
        isError: true,
        error: { data: { detail: 'upstream exploded' } },
      };
      render(<VotingColumn />);
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText(/upstream exploded/)).toBeInTheDocument();
    });

    it('retry button invokes refetch', async () => {
      const refetch = vi.fn();
      mockQueryResult = {
        ...mockQueryResult,
        isError: true,
        error: new Error('boom'),
        refetch,
      };
      const user = userEvent.setup();
      render(<VotingColumn />);
      await user.click(screen.getByRole('button', { name: /retry/i }));
      expect(refetch).toHaveBeenCalledTimes(1);
    });
  });

  describe('empty branch', () => {
    it('renders the EmptyState when data is an empty array', () => {
      mockQueryResult = { ...mockQueryResult, data: [] };
      render(<VotingColumn />);
      expect(screen.getByText(/no features yet/i)).toBeInTheDocument();
      expect(
        screen.queryByTestId(/feature-vote-card-/)
      ).not.toBeInTheDocument();
    });

    it('renders the EmptyState when data is undefined and not loading/erroring', () => {
      // data === undefined with !isLoading && !isError is the "cache empty"
      // edge case the UI must still render something for.
      mockQueryResult = { ...mockQueryResult, data: undefined };
      render(<VotingColumn />);
      expect(screen.getByText(/no features yet/i)).toBeInTheDocument();
    });
  });

  describe('data branch', () => {
    it('renders one FeatureVoteCard per feature in the data array', () => {
      mockQueryResult = { ...mockQueryResult, data: SAMPLE_FEATURES };
      render(<VotingColumn />);
      expect(
        screen.getByTestId('feature-vote-card-resume-match-ai')
      ).toBeInTheDocument();
      expect(
        screen.getByTestId('feature-vote-card-location-normalization')
      ).toBeInTheDocument();
      // Header renders in every branch; ensure we're still in the data branch
      // and not leaking loading/error/empty UI.
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByText(/no features yet/i)).not.toBeInTheDocument();
    });
  });
});
