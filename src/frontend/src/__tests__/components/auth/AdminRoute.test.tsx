import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AdminRoute } from '../../../components/auth/AdminRoute';

interface MockUser {
  isAdmin: boolean;
}

let mockAuthState: {
  isEnabled: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  user: unknown;
  login: () => void;
  logout: () => void;
  getToken: () => Promise<string>;
};

let mockCurrentUserState: {
  user: MockUser | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

vi.mock('../../../features/auth/useCurrentUser', () => ({
  useCurrentUser: () => mockCurrentUserState,
}));

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<div>Home</div>} />
        <Route
          path="/admin/users"
          element={
            <AdminRoute>
              <div>Admin Content</div>
            </AdminRoute>
          }
        />
      </Routes>
    </MemoryRouter>
  );
}

describe('AdminRoute', () => {
  beforeEach(() => {
    mockAuthState = {
      isEnabled: true,
      isAuthenticated: true,
      isLoading: false,
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
      getToken: vi.fn().mockResolvedValue('test-token'),
    };
    mockCurrentUserState = {
      user: null,
      loading: false,
      error: null,
      reload: vi.fn(),
    };
  });

  it('shows loading state while the auth SDK is booting', () => {
    mockAuthState.isLoading = true;
    renderAt('/admin/users');
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByText('Home')).not.toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });

  it('redirects unauthenticated callers to the home route', () => {
    mockAuthState.isAuthenticated = false;
    renderAt('/admin/users');
    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });

  it('shows loading state on the very first render before the profile fetch starts', () => {
    // useCurrentUser initializes `loading: false` and only sets it true
    // inside its mount effect. The guard must treat this initial-frame
    // gap as still-resolving — otherwise an admin reloading /admin/users
    // flashes a redirect to / before the fetch has a chance to begin.
    mockCurrentUserState = {
      user: null,
      loading: false,
      error: null,
      reload: vi.fn(),
    };
    renderAt('/admin/users');
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByText('Home')).not.toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });

  it('shows loading state while the profile fetch is in flight', () => {
    mockCurrentUserState = {
      user: null,
      loading: true,
      error: null,
      reload: vi.fn(),
    };
    renderAt('/admin/users');
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });

  it('renders the protected children when the user is an admin', () => {
    mockCurrentUserState = {
      user: { isAdmin: true },
      loading: false,
      error: null,
      reload: vi.fn(),
    };
    renderAt('/admin/users');
    expect(screen.getByText('Admin Content')).toBeInTheDocument();
  });

  it('redirects non-admin authenticated users to the home route', () => {
    mockCurrentUserState = {
      user: { isAdmin: false },
      loading: false,
      error: null,
      reload: vi.fn(),
    };
    renderAt('/admin/users');
    expect(screen.getByText('Home')).toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();
  });

  it('renders an error state with retry instead of redirecting when /api/users fails', async () => {
    // Regression guard: a backend 500 / JWKS outage / network failure
    // would previously fall through `!user?.isAdmin` and redirect, hiding
    // an auth-layer outage as a "not authorized" denial. The guard must
    // now render an inline error with a retry button — never Navigate to
    // /jobs on a non-null error.
    const reload = vi.fn();
    mockCurrentUserState = {
      user: null,
      loading: false,
      error: '503 Service Unavailable',
      reload,
    };
    renderAt('/admin/users');

    // Error message is rendered (somewhere in the tree).
    expect(screen.getByText(/503 Service Unavailable/)).toBeInTheDocument();
    // No redirect to home.
    expect(screen.queryByText('Home')).not.toBeInTheDocument();
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument();

    // Retry button triggers reload.
    const retry = screen.getByRole('button', { name: /try again/i });
    await userEvent.click(retry);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  describe('feedback admin route', () => {
    function renderFeedbackAt(path: string) {
      return render(
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/" element={<div>Home</div>} />
            <Route
              path="/admin/feedback"
              element={
                <AdminRoute>
                  <div>Feedback Admin Content</div>
                </AdminRoute>
              }
            />
          </Routes>
        </MemoryRouter>
      );
    }

    it('renders the feedback admin content for an admin', () => {
      mockCurrentUserState = {
        user: { isAdmin: true },
        loading: false,
        error: null,
        reload: vi.fn(),
      };
      renderFeedbackAt('/admin/feedback');
      expect(screen.getByText('Feedback Admin Content')).toBeInTheDocument();
    });

    it('redirects a non-admin away from /admin/feedback', () => {
      mockCurrentUserState = {
        user: { isAdmin: false },
        loading: false,
        error: null,
        reload: vi.fn(),
      };
      renderFeedbackAt('/admin/feedback');
      expect(screen.getByText('Home')).toBeInTheDocument();
      expect(screen.queryByText('Feedback Admin Content')).not.toBeInTheDocument();
    });
  });
});
