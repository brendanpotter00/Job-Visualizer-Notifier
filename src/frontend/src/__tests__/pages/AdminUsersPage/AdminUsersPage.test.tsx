import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import { AdminUsersPage } from '../../../pages/AdminUsersPage/AdminUsersPage';

// Node's built-in `Request` requires absolute URLs; RTK Query passes relative
// URLs. Shim the global to resolve them against a test origin — same approach
// used by adminApi.test.ts.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (typeof input === 'string' && input.startsWith('/')) {
      super(`http://localhost${input}`, init);
    } else {
      super(input, init);
    }
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

// AdminUsersPage children consume useCurrentUser (UserRosterTable uses it
// for the self-revoke disable check). Stub it.
vi.mock('../../../features/auth/useCurrentUser', () => ({
  useCurrentUser: () => ({
    user: { id: 'caller-id', isAdmin: true },
    setUser: vi.fn(),
    loading: false,
    error: null,
    reload: vi.fn(),
  }),
}));

function makeStore() {
  return configureStore({
    reducer: { [adminApi.reducerPath]: adminApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: {
          extraArgument: { getTokenOrNull: () => Promise.resolve('test-token') },
        },
      }).concat(adminApi.middleware),
  });
}

function renderPage() {
  const store = makeStore();
  return render(
    <Provider store={store}>
      <AdminUsersPage />
    </Provider>
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('AdminUsersPage', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('renders a loading spinner on initial mount while both queries are pending', async () => {
    // Never-resolving fetches so the page stays in the loading state.
    fetchMock.mockImplementation(() => new Promise(() => {}));

    renderPage();

    // The page-level LoadingState renders a CircularProgress with role
    // 'progressbar' and the caption "Loading admin data…".
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.getByText(/loading admin data/i)).toBeInTheDocument();
  });

  it('renders an error state with a retry button that refetches both queries', async () => {
    // First call: both queries fail. Second call (after retry): they
    // succeed. The page only renders the error state when at least one
    // query has an error.
    fetchMock.mockImplementation(() =>
      Promise.resolve(jsonResponse({ detail: 'kaboom' }, 500))
    );

    renderPage();

    // Wait for the error UI. AdminUsersPage uses the *inline* ErrorState
    // variant, which renders a Retry button (not "Try Again", which is
    // the card variant's label).
    const retry = await screen.findByRole('button', { name: /retry/i });
    expect(
      screen.getByText(/failed to load admin data|fetcherror|kaboom/i)
    ).toBeInTheDocument();

    const callsBeforeRetry = fetchMock.mock.calls.length;
    // Flip to success responses for both endpoints before clicking retry.
    fetchMock.mockImplementation((input: unknown) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/api/admin/users/stats')) {
        return Promise.resolve(
          jsonResponse({
            totalUsers: 1,
            firstSignupAt: '2025-01-01T00:00:00Z',
            latestSignupAt: '2025-01-02T00:00:00Z',
            byProvider: { google: 1 },
          })
        );
      }
      return Promise.resolve(
        jsonResponse({
          users: [
            {
              id: 'u1',
              email: 'r@example.com',
              displayName: 'Retry User',
              signupProvider: 'google',
              createdAt: '2025-01-01T00:00:00Z',
              isAdmin: false,
            },
          ],
        })
      );
    });

    await userEvent.click(retry);

    // Both queries must have been re-issued (one for users, one for stats).
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBeforeRetry);
    });
    const newCalls = fetchMock.mock.calls
      .slice(callsBeforeRetry)
      .map(([input]) => (input instanceof Request ? input.url : String(input)));
    expect(newCalls.some((u) => u.includes('/api/admin/users/stats'))).toBe(true);
    expect(newCalls.some((u) => /\/api\/admin\/users(?!\/stats)/.test(u))).toBe(true);
  });

  it('renders stat tiles and the user roster on success', async () => {
    fetchMock.mockImplementation((input: unknown) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/api/admin/users/stats')) {
        return Promise.resolve(
          jsonResponse({
            totalUsers: 2,
            firstSignupAt: '2025-01-01T00:00:00Z',
            latestSignupAt: '2025-02-01T00:00:00Z',
            byProvider: { google: 1, email: 1 },
          })
        );
      }
      return Promise.resolve(
        jsonResponse({
          users: [
            {
              id: 'u1',
              email: 'a@example.com',
              displayName: 'Alice',
              signupProvider: 'google',
              createdAt: '2025-01-01T00:00:00Z',
              isAdmin: false,
            },
            {
              id: 'u2',
              email: 'b@example.com',
              displayName: 'Bob',
              signupProvider: 'email',
              createdAt: '2025-02-01T00:00:00Z',
              isAdmin: true,
            },
          ],
        })
      );
    });

    renderPage();

    // Wait for the page header to appear (proves loading completed).
    await screen.findByRole('heading', { name: /admin · users/i });

    // Stat tile: "Total users" label + "2" value (via toLocaleString).
    expect(screen.getByText(/total users/i)).toBeInTheDocument();
    // The "2" appears in multiple places (total tile, etc.) — be permissive.
    expect(screen.getAllByText('2').length).toBeGreaterThan(0);

    // Roster table renders both users.
    expect(screen.getByText('a@example.com')).toBeInTheDocument();
    expect(screen.getByText('b@example.com')).toBeInTheDocument();
  });
});
