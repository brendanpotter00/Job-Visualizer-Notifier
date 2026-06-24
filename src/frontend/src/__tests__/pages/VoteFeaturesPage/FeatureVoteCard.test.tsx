import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FeatureVoteCard } from '../../../pages/VoteFeaturesPage/FeatureVoteCard';
import type { FeatureListItem } from '../../../features/features/featuresApi';
import { logger } from '../../../lib/logger';

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
  useUpvoteFeatureMutation: () => [mockUpvoteTrigger, { isLoading: upvoteInFlight }],
  useRemoveUpvoteMutation: () => [mockRemoveTrigger, { isLoading: removeInFlight }],
}));

const SAMPLE: FeatureListItem = {
  id: 'resume-match-ai',
  title: 'AI resume matching notifications',
  description: 'Upload your resume and get matched to new postings.',
  createdAt: '2026-04-10T00:00:00Z',
  completedAt: null,
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
      // The modal uses its default `aria-labelledby` wiring (pass-1 a11y
      // contract), so the accessible name resolves to the rendered title.
      expect(await screen.findByRole('dialog', { name: /sign in to vote/i })).toBeInTheDocument();
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

    it('upvotes on keyboard activation (Enter key)', async () => {
      // Pins keyboard-driven voting — a swap from MUI IconButton to a
      // <div role="button"> without onKeyDown would silently break it.
      const user = userEvent.setup();
      render(<FeatureVoteCard feature={SAMPLE} />);
      const button = findUpvoteButton();
      button.focus();
      await user.keyboard('{Enter}');
      expect(mockUpvoteTrigger).toHaveBeenCalledWith('resume-match-ai');
    });

    it('advertises aria-pressed="false" when the feature is not yet upvoted', () => {
      render(<FeatureVoteCard feature={SAMPLE} />);
      expect(findUpvoteButton()).toHaveAttribute('aria-pressed', 'false');
    });

    it('does NOT open the sign-in modal', async () => {
      const user = userEvent.setup();
      render(<FeatureVoteCard feature={SAMPLE} />);
      await user.click(findUpvoteButton());
      expect(screen.queryByRole('dialog', { name: /sign in to vote/i })).not.toBeInTheDocument();
    });

    it('logs via logger.error when the upvote mutation rejects', async () => {
      const user = userEvent.setup();
      const loggerErrorSpy = vi.spyOn(logger, 'error').mockImplementation(() => {});
      const mockErr = new Error('boom');
      mockUpvoteTrigger.mockReturnValue({
        unwrap: () => Promise.reject(mockErr),
      });
      try {
        render(<FeatureVoteCard feature={SAMPLE} />);
        await user.click(findUpvoteButton());
        await waitFor(() => {
          expect(loggerErrorSpy).toHaveBeenCalledWith(expect.stringContaining('upvote'), mockErr);
        });
      } finally {
        loggerErrorSpy.mockRestore();
      }
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

    it('advertises aria-pressed="true" when the feature is already upvoted', () => {
      const upvoted: FeatureListItem = {
        ...SAMPLE,
        hasUpvoted: true,
        upvoteCount: 4,
      };
      render(<FeatureVoteCard feature={upvoted} />);
      expect(findUpvoteButton()).toHaveAttribute('aria-pressed', 'true');
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

  describe('read-only / shipped variant', () => {
    const shipped: FeatureListItem = {
      ...SAMPLE,
      completedAt: '2026-05-01T00:00:00Z',
    };

    it('renders the "Shipped" badge and the live dot', () => {
      render(<FeatureVoteCard feature={shipped} readOnly />);
      expect(screen.getByText('Shipped')).toBeInTheDocument();
      expect(screen.getByTestId('live-dot')).toBeInTheDocument();
    });

    it('does NOT render an upvote/remove button', () => {
      render(<FeatureVoteCard feature={shipped} readOnly />);
      expect(screen.queryByRole('button', { name: /upvote/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /remove upvote/i })).not.toBeInTheDocument();
    });

    it('still shows the (read-only) vote count, title, and description', () => {
      render(<FeatureVoteCard feature={shipped} readOnly />);
      expect(screen.getByLabelText('3 upvotes')).toBeInTheDocument();
      expect(screen.getByText(shipped.title)).toBeInTheDocument();
      expect(screen.getByText(shipped.description)).toBeInTheDocument();
    });

    it('clicking the card dispatches no mutation', async () => {
      mockAuthState.isAuthenticated = true;
      const user = userEvent.setup();
      render(<FeatureVoteCard feature={shipped} readOnly />);
      await user.click(screen.getByText(shipped.title));
      expect(mockUpvoteTrigger).not.toHaveBeenCalled();
      expect(mockRemoveTrigger).not.toHaveBeenCalled();
    });

    it('does not open the sign-in modal (no interactive control)', async () => {
      const user = userEvent.setup();
      render(<FeatureVoteCard feature={shipped} readOnly />);
      await user.click(screen.getByText(shipped.title));
      expect(screen.queryByRole('dialog', { name: /sign in to vote/i })).not.toBeInTheDocument();
    });
  });
});
