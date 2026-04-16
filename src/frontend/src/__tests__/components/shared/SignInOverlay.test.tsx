import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SignInOverlay } from '../../../components/shared/SignInOverlay';
import { SIGN_IN_OVERLAY_MESSAGES } from '../../../constants/messages';

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

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

describe('SignInOverlay', () => {
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

  describe('Visibility', () => {
    it('renders the CTA when user is signed out', () => {
      render(<SignInOverlay />);

      expect(screen.getByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).toBeInTheDocument();
      expect(screen.getByText(SIGN_IN_OVERLAY_MESSAGES.SUBTITLE)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: SIGN_IN_OVERLAY_MESSAGES.BUTTON_TEXT })
      ).toBeInTheDocument();
    });

    it('renders nothing when user is authenticated', () => {
      mockAuthState.isAuthenticated = true;
      const { container } = render(<SignInOverlay />);

      expect(container).toBeEmptyDOMElement();
    });

    it('renders nothing when auth is disabled', () => {
      mockAuthState.isEnabled = false;
      const { container } = render(<SignInOverlay />);

      expect(container).toBeEmptyDOMElement();
    });

    it('renders nothing while auth is loading to avoid flash', () => {
      mockAuthState.isLoading = true;
      const { container } = render(<SignInOverlay />);

      expect(container).toBeEmptyDOMElement();
    });
  });

  describe('Interaction', () => {
    it('calls login when the sign-in button is clicked', async () => {
      const user = userEvent.setup();
      render(<SignInOverlay />);

      await user.click(
        screen.getByRole('button', { name: SIGN_IN_OVERLAY_MESSAGES.BUTTON_TEXT })
      );

      expect(mockLogin).toHaveBeenCalledTimes(1);
    });

    it('logs an error but does not throw when login rejects', async () => {
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
      mockLogin.mockRejectedValueOnce(new Error('pop-up blocked'));

      const user = userEvent.setup();
      render(<SignInOverlay />);

      await user.click(
        screen.getByRole('button', { name: SIGN_IN_OVERLAY_MESSAGES.BUTTON_TEXT })
      );

      // Wait for the rejected promise to be handled
      await vi.waitFor(() => {
        expect(consoleError).toHaveBeenCalled();
      });

      consoleError.mockRestore();
    });
  });

  describe('Accessibility', () => {
    it('exposes the CTA as a labeled region', () => {
      render(<SignInOverlay />);

      expect(
        screen.getByRole('region', { name: SIGN_IN_OVERLAY_MESSAGES.ARIA_LABEL })
      ).toBeInTheDocument();
    });
  });

  describe('Background variants', () => {
    it('renders with the default background variant', () => {
      render(<SignInOverlay />);

      // Sanity check: the component still renders the expected CTA
      expect(screen.getByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).toBeInTheDocument();
    });

    it('renders with the paper background variant', () => {
      render(<SignInOverlay background="paper" />);

      expect(screen.getByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).toBeInTheDocument();
    });
  });
});
