import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FeatureVoteCard } from '../../../pages/VoteFeaturesPage/FeatureVoteCard';
import type { FeatureListItem } from '../../../features/features/featuresApi';

const mockLogin = vi.fn();
let mockAuthState = {
  isEnabled: true,
  isAuthenticated: false,
  isLoading: false,
  login: mockLogin,
  logout: vi.fn(),
  getToken: vi.fn(),
  user: null,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

const mockUpvoteTrigger = vi.fn();
const mockRemoveTrigger = vi.fn();
let upvoteInFlight = false;
let removeInFlight = false;

vi.mock('../../../features/features/featuresApi', () => ({
  useUpvoteFeatureMutation: () => [
    mockUpvoteTrigger,
    { isLoading: upvoteInFlight },
  ],
  useRemoveUpvoteMutation: () => [
    mockRemoveTrigger,
    { isLoading: removeInFlight },
  ],
}));

const SAMPLE: FeatureListItem = {
  id: 'resume-match-ai',
  title: 'AI resume matching notifications',
  description: 'Upload your resume and get matched to new postings.',
  createdAt: '2026-04-10T00:00:00Z',
  upvoteCount: 3,
  hasUpvoted: false,
};

function findUpvoteButton() {
  return (
    screen.queryByRole('button', { name: /^upvote /i }) ??
    screen.getByRole('button', { name: /^remove upvote from /i })
  );
}

describe('FeatureVoteCard', () => {
  beforeEach(() => {
    mockLogin.mockReset();
    mockUpvoteTrigger.mockReset();
    mockRemoveTrigger.mockReset();
    // FeatureVoteCard calls `.unwrap()` on the mutation trigger result (for
    // observability — see featuresApi optimistic update). Mirror RTK Query's
    // trigger contract so the mock returns the `{ unwrap }` shape the real
    // hook returns.
    mockUpvoteTrigger.mockReturnValue({ unwrap: () => Promise.resolve(undefined) });
    mockRemoveTrigger.mockReturnValue({ unwrap: () => Promise.resolve(undefined) });
    upvoteInFlight = false;
    removeInFlight = false;
    mockAuthState = {
      isEnabled: true,
      isAuthenticated: false,
      isLoading: false,
      login: mockLogin,
      logout: vi.fn(),
      getToken: vi.fn(),
      user: null,
    };
  });

  describe('when anonymous', () => {
    it('clicking the upvote arrow opens the SignInPromptModal', async () => {
      const user = userEvent.setup();
      render(<FeatureVoteCard feature={SAMPLE} />);
      await user.click(findUpvoteButton());
      expect(
        await screen.findByRole('dialog', { name: /sign in prompt/i })
      ).toBeInTheDocument();
    });

    it('clicking the upvote arrow does NOT dispatch any mutation', async () => {
      const user = userEvent.setup();
      render(<FeatureVoteCard feature={SAMPLE} />);
      await user.click(findUpvoteButton());
      expect(mockUpvoteTrigger).not.toHaveBeenCalled();
      expect(mockRemoveTrigger).not.toHaveBeenCalled();
    });
  });

  describe('when authenticated and !hasUpvoted', () => {
    beforeEach(() => {
      mockAuthState.isAuthenticated = true;
    });

    it('clicking the upvote arrow dispatches the upvote mutation with the feature id', async () => {
      const user = userEvent.setup();
      render(<FeatureVoteCard feature={SAMPLE} />);
      await user.click(findUpvoteButton());
      expect(mockUpvoteTrigger).toHaveBeenCalledTimes(1);
      expect(mockUpvoteTrigger).toHaveBeenCalledWith('resume-match-ai');
      expect(mockRemoveTrigger).not.toHaveBeenCalled();
    });

    it('does NOT open the sign-in modal', async () => {
      const user = userEvent.setup();
      render(<FeatureVoteCard feature={SAMPLE} />);
      await user.click(findUpvoteButton());
      expect(
        screen.queryByRole('dialog', { name: /sign in prompt/i })
      ).not.toBeInTheDocument();
    });
  });

  describe('when authenticated and hasUpvoted', () => {
    beforeEach(() => {
      mockAuthState.isAuthenticated = true;
    });

    it('clicking the upvote arrow dispatches the remove mutation', async () => {
      const user = userEvent.setup();
      const upvoted: FeatureListItem = {
        ...SAMPLE,
        hasUpvoted: true,
        upvoteCount: 4,
      };
      render(<FeatureVoteCard feature={upvoted} />);
      await user.click(findUpvoteButton());
      expect(mockRemoveTrigger).toHaveBeenCalledTimes(1);
      expect(mockRemoveTrigger).toHaveBeenCalledWith('resume-match-ai');
      expect(mockUpvoteTrigger).not.toHaveBeenCalled();
    });
  });

  describe('disabled state', () => {
    it('disables the button while the upvote mutation is in flight', () => {
      mockAuthState.isAuthenticated = true;
      upvoteInFlight = true;
      render(<FeatureVoteCard feature={SAMPLE} />);
      expect(findUpvoteButton()).toBeDisabled();
    });

    it('disables the button while the remove mutation is in flight', () => {
      mockAuthState.isAuthenticated = true;
      removeInFlight = true;
      const upvoted: FeatureListItem = { ...SAMPLE, hasUpvoted: true };
      render(<FeatureVoteCard feature={upvoted} />);
      expect(findUpvoteButton()).toBeDisabled();
    });
  });

  describe('count and content', () => {
    it('renders the upvote count', () => {
      render(<FeatureVoteCard feature={SAMPLE} />);
      expect(screen.getByLabelText('3 upvotes')).toBeInTheDocument();
    });

    it('renders the title and description', () => {
      render(<FeatureVoteCard feature={SAMPLE} />);
      expect(screen.getByText(SAMPLE.title)).toBeInTheDocument();
      expect(screen.getByText(SAMPLE.description)).toBeInTheDocument();
    });
  });
});
