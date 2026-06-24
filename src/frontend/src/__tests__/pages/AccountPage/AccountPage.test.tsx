import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { AccountPage } from '../../../pages/AccountPage/AccountPage';
import { createTestStore } from '../../../test/testUtils';

const mockLogin = vi.fn();
const mockGetToken = vi.fn();

let mockAuthState = {
  isEnabled: true,
  isAuthenticated: false,
  isLoading: false,
  login: mockLogin,
  logout: vi.fn(),
  getToken: mockGetToken,
  user: null,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

const mockUser = {
  id: 'abc123',
  providerSubject: 'auth0|test',
  email: 'test@example.com',
  displayName: 'Test Display',
  givenName: 'Test',
  familyName: 'User',
  pictureUrl: 'https://example.com/photo.jpg',
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
  isAdmin: false,
};

const mockFetchCurrentUser = vi.fn();
const mockUpdateCurrentUser = vi.fn();

vi.mock('../../../features/auth/authService', () => ({
  fetchCurrentUser: (...args: unknown[]) => mockFetchCurrentUser(...args),
  updateCurrentUser: (...args: unknown[]) => mockUpdateCurrentUser(...args),
}));

function renderPage() {
  const store = createTestStore();
  return {
    store,
    ...render(
      <Provider store={store}>
        <MemoryRouter>
          <AccountPage />
        </MemoryRouter>
      </Provider>
    ),
  };
}

describe('AccountPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState = {
      isEnabled: true,
      isAuthenticated: false,
      isLoading: false,
      login: mockLogin,
      logout: vi.fn(),
      getToken: mockGetToken,
      user: null,
    };
    mockGetToken.mockResolvedValue('test-token');
    mockFetchCurrentUser.mockResolvedValue(mockUser);
    mockUpdateCurrentUser.mockResolvedValue(mockUser);
  });

  describe('when not authenticated', () => {
    it('shows sign in message', () => {
      renderPage();
      expect(screen.getByText('Sign in to view your account.')).toBeInTheDocument();
    });

    it('shows Sign In button', () => {
      renderPage();
      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    });

    it('clicking Sign In calls login', async () => {
      const user = userEvent.setup();
      renderPage();

      await user.click(screen.getByRole('button', { name: /sign in/i }));
      expect(mockLogin).toHaveBeenCalled();
    });
  });

  describe('when auth is loading', () => {
    it('shows loading spinner', () => {
      mockAuthState.isLoading = true;
      renderPage();
      expect(screen.getByRole('progressbar')).toBeInTheDocument();
    });
  });

  describe('when authenticated', () => {
    beforeEach(() => {
      mockAuthState.isAuthenticated = true;
    });

    it('fetches and displays user profile', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('test@example.com')).toBeInTheDocument();
        expect(screen.getByText('Test User')).toBeInTheDocument();
      });
    });

    it('shows display name in text field', async () => {
      renderPage();

      await waitFor(() => {
        const input = screen.getByLabelText('Display Name');
        expect(input).toHaveValue('Test Display');
      });
    });

    it('shows avatar with user picture', async () => {
      renderPage();

      await waitFor(() => {
        const avatar = screen.getByAltText('Test User');
        expect(avatar).toHaveAttribute('src', 'https://example.com/photo.jpg');
      });
    });

    it('Save Changes button is disabled when display name has not changed', async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getAllByRole('button', { name: /save changes/i })[0]).toBeDisabled();
      });
    });

    it('Save Changes button is enabled when display name changes', async () => {
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByLabelText('Display Name')).toBeInTheDocument();
      });

      const input = screen.getByLabelText('Display Name');
      await user.clear(input);
      await user.type(input, 'New Name');

      expect(screen.getAllByRole('button', { name: /save changes/i })[0]).toBeEnabled();
    });

    it('calls updateCurrentUser on save', async () => {
      const updatedUser = { ...mockUser, displayName: 'New Name' };
      mockUpdateCurrentUser.mockResolvedValue(updatedUser);
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByLabelText('Display Name')).toBeInTheDocument();
      });

      const input = screen.getByLabelText('Display Name');
      await user.clear(input);
      await user.type(input, 'New Name');
      await user.click(screen.getAllByRole('button', { name: /save changes/i })[0]);

      await waitFor(() => {
        expect(mockUpdateCurrentUser).toHaveBeenCalledWith('test-token', {
          displayName: 'New Name',
        });
      });
    });

    it('shows success message after saving', async () => {
      const updatedUser = { ...mockUser, displayName: 'New Name' };
      mockUpdateCurrentUser.mockResolvedValue(updatedUser);
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByLabelText('Display Name')).toBeInTheDocument();
      });

      const input = screen.getByLabelText('Display Name');
      await user.clear(input);
      await user.type(input, 'New Name');
      await user.click(screen.getAllByRole('button', { name: /save changes/i })[0]);

      await waitFor(() => {
        expect(screen.getByText('Changes saved.')).toBeInTheDocument();
      });
    });

    it('shows error when fetch fails', async () => {
      mockFetchCurrentUser.mockRejectedValue(new Error('Failed to fetch user (500)'));
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('Failed to fetch user (500)')).toBeInTheDocument();
      });
    });

    it('shows error when save fails', async () => {
      mockUpdateCurrentUser.mockRejectedValue(new Error('Failed to update user (500)'));
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByLabelText('Display Name')).toBeInTheDocument();
      });

      const input = screen.getByLabelText('Display Name');
      await user.clear(input);
      await user.type(input, 'New Name');
      await user.click(screen.getAllByRole('button', { name: /save changes/i })[0]);

      await waitFor(() => {
        expect(screen.getByText('Failed to update user (500)')).toBeInTheDocument();
      });
    });

    it('shows Retry button on fetch error', async () => {
      mockFetchCurrentUser.mockRejectedValue(new Error('Network error'));
      renderPage();

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
      });
    });

    it('shows the "Hide all admin features" toggle for admin users', async () => {
      mockFetchCurrentUser.mockResolvedValue({ ...mockUser, isAdmin: true });
      renderPage();

      await waitFor(() => {
        expect(screen.getByLabelText('Hide all admin features')).toBeInTheDocument();
      });
    });

    it('does not show the toggle for non-admin users', async () => {
      // mockUser.isAdmin is false by default
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('test@example.com')).toBeInTheDocument();
      });
      expect(screen.queryByLabelText('Hide all admin features')).not.toBeInTheDocument();
    });

    it('toggling the switch sets hideAdminFeatures in the store (ephemeral, demo-only)', async () => {
      mockFetchCurrentUser.mockResolvedValue({ ...mockUser, isAdmin: true });
      const user = userEvent.setup();
      const { store } = renderPage();

      const toggle = await screen.findByLabelText('Hide all admin features');
      expect(store.getState().ui.hideAdminFeatures).toBe(false);

      await user.click(toggle);
      expect(store.getState().ui.hideAdminFeatures).toBe(true);
    });

    it('shows the "Demo mode" toggle for admin users', async () => {
      mockFetchCurrentUser.mockResolvedValue({ ...mockUser, isAdmin: true });
      renderPage();

      await waitFor(() => {
        expect(screen.getByLabelText('Enable demo mode')).toBeInTheDocument();
      });
      // Caption explains the Recent-page swap so admins know what it does.
      expect(screen.getByText(/replaces the Recent Job Postings list/i)).toBeInTheDocument();
    });

    it('does not show the "Demo mode" toggle for non-admin users', async () => {
      // mockUser.isAdmin is false by default
      renderPage();

      await waitFor(() => {
        expect(screen.getByText('test@example.com')).toBeInTheDocument();
      });
      expect(screen.queryByLabelText('Enable demo mode')).not.toBeInTheDocument();
    });

    it('toggling the switch sets demoModeEnabled in the store (ephemeral, demo-only)', async () => {
      mockFetchCurrentUser.mockResolvedValue({ ...mockUser, isAdmin: true });
      const user = userEvent.setup();
      const { store } = renderPage();

      const toggle = await screen.findByLabelText('Enable demo mode');
      expect(store.getState().ui.demoModeEnabled).toBe(false);

      await user.click(toggle);
      expect(store.getState().ui.demoModeEnabled).toBe(true);

      await user.click(toggle);
      expect(store.getState().ui.demoModeEnabled).toBe(false);
    });
  });
});
