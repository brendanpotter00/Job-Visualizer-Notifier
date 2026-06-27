import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { UserMenu } from '../../../components/layout/UserMenu';

const mockLogin = vi.fn();
const mockLogout = vi.fn();
const mockGetToken = vi.fn();

let mockAuthState = {
  isEnabled: true,
  isAuthenticated: false,
  isLoading: false,
  login: mockLogin,
  logout: mockLogout,
  getToken: mockGetToken,
  user: null,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

const mockTrackSignInClick = vi.fn();
vi.mock('../../../features/analytics/events', () => ({
  trackSignInClick: (...args: unknown[]) => mockTrackSignInClick(...args),
}));

const mockUser = {
  id: 'abc123',
  providerSubject: 'auth0|test',
  email: 'test@example.com',
  displayName: null,
  givenName: 'Test',
  familyName: 'User',
  pictureUrl: 'https://example.com/photo.jpg',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  isAdmin: false,
};

vi.mock('../../../features/auth/authService', () => ({
  fetchCurrentUser: vi.fn(() => Promise.resolve(mockUser)),
}));

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('UserMenu', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState = {
      isEnabled: true,
      isAuthenticated: false,
      isLoading: false,
      login: mockLogin,
      logout: mockLogout,
      getToken: mockGetToken,
      user: null,
    };
    mockGetToken.mockResolvedValue('test-token');
  });

  describe('when auth is disabled', () => {
    it('renders nothing', () => {
      mockAuthState.isEnabled = false;
      const { container } = renderWithRouter(<UserMenu />);
      expect(container.innerHTML).toBe('');
    });
  });

  describe('when auth is loading', () => {
    it('shows a disabled Sign In button', () => {
      mockAuthState.isLoading = true;
      renderWithRouter(<UserMenu />);
      const button = screen.getByRole('button', { name: /sign in/i });
      expect(button).toBeDisabled();
    });
  });

  describe('when not authenticated', () => {
    it('renders Sign In button', () => {
      renderWithRouter(<UserMenu />);
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    });

    it('clicking Sign In calls login', async () => {
      const user = userEvent.setup();
      renderWithRouter(<UserMenu />);

      await user.click(screen.getByRole('button', { name: /sign in/i }));
      expect(mockLogin).toHaveBeenCalledTimes(1);
    });

    it('fires trackSignInClick with the "appbar" location on Sign In click', async () => {
      const user = userEvent.setup();
      renderWithRouter(<UserMenu />);

      await user.click(screen.getByRole('button', { name: /sign in/i }));
      expect(mockTrackSignInClick).toHaveBeenCalledWith('appbar');
    });

    it('surfaces login rejection in a Snackbar', async () => {
      mockLogin.mockRejectedValueOnce(new Error('Popup blocked by browser'));

      const user = userEvent.setup();
      renderWithRouter(<UserMenu />);

      await user.click(screen.getByRole('button', { name: /sign in/i }));

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Popup blocked by browser');
      });
    });
  });

  describe('when authenticated', () => {
    beforeEach(() => {
      mockAuthState.isAuthenticated = true;
    });

    it('renders avatar button', async () => {
      renderWithRouter(<UserMenu />);
      await waitFor(() => {
        expect(screen.getByLabelText('user menu')).toBeInTheDocument();
      });
    });

    it('opens menu when avatar is clicked', async () => {
      const user = userEvent.setup();
      renderWithRouter(<UserMenu />);

      await waitFor(() => {
        expect(screen.getByLabelText('user menu')).toBeInTheDocument();
      });

      await user.click(screen.getByLabelText('user menu'));
      expect(screen.getByText('Account')).toBeInTheDocument();
      expect(screen.getByText('Sign Out')).toBeInTheDocument();
    });

    it('shows user name and email in menu', async () => {
      const user = userEvent.setup();
      renderWithRouter(<UserMenu />);

      await waitFor(() => {
        expect(screen.getByLabelText('user menu')).toBeInTheDocument();
      });

      await user.click(screen.getByLabelText('user menu'));

      await waitFor(() => {
        expect(screen.getByText('Test User')).toBeInTheDocument();
        expect(screen.getByText('test@example.com')).toBeInTheDocument();
      });
    });

    it('clicking Sign Out calls logout and closes menu', async () => {
      const user = userEvent.setup();
      renderWithRouter(<UserMenu />);

      await waitFor(() => {
        expect(screen.getByLabelText('user menu')).toBeInTheDocument();
      });

      await user.click(screen.getByLabelText('user menu'));
      await user.click(screen.getByText('Sign Out'));

      expect(mockLogout).toHaveBeenCalledTimes(1);
    });

    it('renders avatar with user picture', async () => {
      renderWithRouter(<UserMenu />);

      await waitFor(() => {
        const avatar = screen.getByAltText('Test User');
        expect(avatar).toBeInTheDocument();
        expect(avatar).toHaveAttribute('src', 'https://example.com/photo.jpg');
      });
    });

    it('shows error message when profile load fails', async () => {
      const { fetchCurrentUser } = await import('../../../features/auth/authService');
      vi.mocked(fetchCurrentUser).mockRejectedValueOnce(new Error('Network error'));

      const user = userEvent.setup();
      renderWithRouter(<UserMenu />);

      await waitFor(() => {
        expect(screen.getByLabelText('user menu')).toBeInTheDocument();
      });

      await user.click(screen.getByLabelText('user menu'));

      await waitFor(() => {
        expect(screen.getByText('Network error')).toBeInTheDocument();
      });
    });
  });
});
