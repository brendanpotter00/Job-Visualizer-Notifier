import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SignInPrompt } from '../../../../components/shared/SignInPrompt/SignInPrompt';

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

const mockTrackSignInClick = vi.fn();
vi.mock('../../../../features/analytics/events', () => ({
  trackSignInClick: (...args: unknown[]) => mockTrackSignInClick(...args),
}));

const DEFAULT_PROPS = {
  title: 'Sign in to do the thing',
  subtitle: 'Helpful subtitle',
  buttonText: 'Sign In',
};

describe('SignInPrompt', () => {
  beforeEach(() => {
    mockLogin.mockReset();
    mockLogin.mockResolvedValue(undefined);
    mockTrackSignInClick.mockClear();
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

  describe('Visibility', () => {
    it('renders title, subtitle, and CTA when user is signed out', () => {
      render(<SignInPrompt {...DEFAULT_PROPS} />);
      expect(screen.getByText(DEFAULT_PROPS.title)).toBeInTheDocument();
      expect(screen.getByText(DEFAULT_PROPS.subtitle)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: DEFAULT_PROPS.buttonText })
      ).toBeInTheDocument();
    });

    it('renders nothing when user is authenticated', () => {
      mockAuthState.isAuthenticated = true;
      const { container } = render(<SignInPrompt {...DEFAULT_PROPS} />);
      expect(container).toBeEmptyDOMElement();
    });

    it('renders nothing when auth is disabled', () => {
      mockAuthState.isEnabled = false;
      const { container } = render(<SignInPrompt {...DEFAULT_PROPS} />);
      expect(container).toBeEmptyDOMElement();
    });

    it('renders nothing while auth is loading', () => {
      mockAuthState.isLoading = true;
      const { container } = render(<SignInPrompt {...DEFAULT_PROPS} />);
      expect(container).toBeEmptyDOMElement();
    });
  });

  describe('Interaction', () => {
    it('calls login when the CTA is clicked', async () => {
      const user = userEvent.setup();
      render(<SignInPrompt {...DEFAULT_PROPS} />);
      await user.click(
        screen.getByRole('button', { name: DEFAULT_PROPS.buttonText })
      );
      expect(mockLogin).toHaveBeenCalledTimes(1);
    });

    it('fires trackSignInClick with the given ctaLocation before login', async () => {
      const user = userEvent.setup();
      render(<SignInPrompt {...DEFAULT_PROPS} ctaLocation="account_page" />);
      await user.click(
        screen.getByRole('button', { name: DEFAULT_PROPS.buttonText })
      );
      expect(mockTrackSignInClick).toHaveBeenCalledWith('account_page');
      expect(mockLogin).toHaveBeenCalledTimes(1);
    });

    it('does NOT fire trackSignInClick when ctaLocation is omitted', async () => {
      const user = userEvent.setup();
      render(<SignInPrompt {...DEFAULT_PROPS} />);
      await user.click(
        screen.getByRole('button', { name: DEFAULT_PROPS.buttonText })
      );
      expect(mockTrackSignInClick).not.toHaveBeenCalled();
      expect(mockLogin).toHaveBeenCalledTimes(1);
    });

    it('invokes onRequestClose after dispatching login', async () => {
      const onRequestClose = vi.fn();
      const user = userEvent.setup();
      render(<SignInPrompt {...DEFAULT_PROPS} onRequestClose={onRequestClose} />);
      await user.click(
        screen.getByRole('button', { name: DEFAULT_PROPS.buttonText })
      );
      expect(mockLogin).toHaveBeenCalledTimes(1);
      expect(onRequestClose).toHaveBeenCalledTimes(1);
    });

    it('does not require onRequestClose', async () => {
      const user = userEvent.setup();
      render(<SignInPrompt {...DEFAULT_PROPS} />);
      await user.click(
        screen.getByRole('button', { name: DEFAULT_PROPS.buttonText })
      );
      expect(mockLogin).toHaveBeenCalledTimes(1);
    });

    it('logs an error but does not throw when login rejects', async () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
      mockLogin.mockRejectedValueOnce(new Error('pop-up blocked'));
      const user = userEvent.setup();
      render(<SignInPrompt {...DEFAULT_PROPS} />);
      await user.click(
        screen.getByRole('button', { name: DEFAULT_PROPS.buttonText })
      );
      await vi.waitFor(() => {
        expect(consoleError).toHaveBeenCalled();
      });
      consoleError.mockRestore();
    });
  });
});
