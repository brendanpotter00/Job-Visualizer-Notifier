import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SignInPromptModal } from '../../../../components/shared/SignInPrompt/SignInPromptModal';

const mockLogin = vi.fn();

type MockAuthState = {
  isEnabled: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: typeof mockLogin;
  logout: ReturnType<typeof vi.fn>;
  getToken: ReturnType<typeof vi.fn>;
  user: null;
};

let mockAuthState: MockAuthState = {
  isEnabled: true,
  isAuthenticated: false,
  isLoading: false,
  login: mockLogin,
  logout: vi.fn(),
  getToken: vi.fn(),
  user: null,
};

vi.mock('../../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

const DEFAULT_PROPS = {
  title: 'Sign in to vote',
  subtitle: 'Your upvote helps prioritize what we build next.',
  buttonText: 'Sign In',
  ariaLabel: 'Sign in prompt',
};

describe('SignInPromptModal', () => {
  beforeEach(() => {
    mockLogin.mockReset();
    mockLogin.mockResolvedValue(undefined);
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

  describe('Open/close visibility', () => {
    it('renders the prompt when open=true', () => {
      render(<SignInPromptModal {...DEFAULT_PROPS} open={true} onClose={vi.fn()} />);
      expect(screen.getByText(DEFAULT_PROPS.title)).toBeInTheDocument();
      expect(screen.getByText(DEFAULT_PROPS.subtitle)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: DEFAULT_PROPS.buttonText })
      ).toBeInTheDocument();
    });

    it('does not render the prompt when open=false', () => {
      render(<SignInPromptModal {...DEFAULT_PROPS} open={false} onClose={vi.fn()} />);
      expect(screen.queryByText(DEFAULT_PROPS.title)).not.toBeInTheDocument();
    });
  });

  describe('Close interaction', () => {
    it('calls onClose when the X close button is clicked', async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<SignInPromptModal {...DEFAULT_PROPS} open={true} onClose={onClose} />);
      await user.click(screen.getByRole('button', { name: /close/i }));
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe('CTA interaction', () => {
    it('calls login and onClose when the sign-in button is clicked', async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(<SignInPromptModal {...DEFAULT_PROPS} open={true} onClose={onClose} />);
      await user.click(
        screen.getByRole('button', { name: DEFAULT_PROPS.buttonText })
      );
      expect(mockLogin).toHaveBeenCalledTimes(1);
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe('Accessibility', () => {
    it('exposes the dialog with the provided aria-label', () => {
      render(<SignInPromptModal {...DEFAULT_PROPS} open={true} onClose={vi.fn()} />);
      expect(
        screen.getByRole('dialog', { name: DEFAULT_PROPS.ariaLabel })
      ).toBeInTheDocument();
    });

    it('falls back to the title as the aria-label when ariaLabel is omitted', () => {
      const { ariaLabel: _ignored, ...noAria } = DEFAULT_PROPS;
      render(<SignInPromptModal {...noAria} open={true} onClose={vi.fn()} />);
      expect(
        screen.getByRole('dialog', { name: DEFAULT_PROPS.title })
      ).toBeInTheDocument();
    });
  });
});
