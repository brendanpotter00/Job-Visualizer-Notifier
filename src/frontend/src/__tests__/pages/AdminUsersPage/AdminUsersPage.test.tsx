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

  it('renders the roster with an inline stats error when stats fails but users succeeds', async () => {
    // Partial-failure independence: the page must NOT collapse into a
    // full-page ErrorState when only one query fails. Roster must render;
    // the stat tile section gets its own inline ErrorState. This is the
    // exact conflated-failure pattern this PR exists to prevent.
    fetchMock.mockImplementation((input: unknown) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/api/admin/users/stats')) {
        return Promise.resolve(jsonResponse({ detail: 'stats kaboom' }, 500));
      }
      return Promise.resolve(
        jsonResponse({
          users: [
            {
              id: 'u1',
              email: 'roster@example.com',
              displayName: 'Roster User',
              signupProvider: 'google',
              createdAt: '2025-01-01T00:00:00Z',
              isAdmin: false,
            },
          ],
        })
      );
    });

    renderPage();

    // Wait for the page header — proves the loading gate cleared.
    await screen.findByRole('heading', { name: /admin · users/i });

    // Roster row is visible (the email cell renders the user).
    expect(screen.getByText('roster@example.com')).toBeInTheDocument();

    // The stat tile section is replaced by an inline ErrorState with a
    // Retry button. The page-level full-card ErrorState (which uses
    // "Try Again" copy) must NOT fire.
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
    // The "Total users" stat tile label should NOT be present — the
    // tile section was swapped for the inline error.
    expect(screen.queryByText(/total users/i)).not.toBeInTheDocument();
  });

  it('renders the stat tiles with an inline roster error when users fails but stats succeeds', async () => {
    // Inverse of the previous test: stats succeeds, users fails. Stat
    // tiles must render; the roster slot shows an inline error.
    fetchMock.mockImplementation((input: unknown) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/api/admin/users/stats')) {
        return Promise.resolve(
          jsonResponse({
            totalUsers: 7,
            firstSignupAt: '2025-01-01T00:00:00Z',
            latestSignupAt: '2025-02-01T00:00:00Z',
            byProvider: { google: 5, email: 2 },
          })
        );
      }
      return Promise.resolve(jsonResponse({ detail: 'roster kaboom' }, 500));
    });

    renderPage();

    await screen.findByRole('heading', { name: /admin · users/i });

    // Stat tile section renders — "Total users" label is present.
    expect(screen.getByText(/total users/i)).toBeInTheDocument();
    // The 7 from totalUsers is shown somewhere.
    expect(screen.getAllByText('7').length).toBeGreaterThan(0);

    // Roster slot is replaced by an inline error.
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('renders the users-section spinner and stats-section error when stats errors before users resolves', async () => {
    // Audit pass-3 finding: the prior loading gate had carve-outs for
    // ``!usersError && !statsError`` so if query A errored while B was
    // still loading, the page skipped the spinner and rendered an empty
    // roster (or empty stat slot) with no indicator that the other
    // query was still loading. The fix: each slot independently shows
    // its OWN spinner while loading-with-no-data, regardless of the
    // other slot's state.
    //
    // Setup: stats returns a 500 immediately. The users fetch is left
    // pending forever, so the roster slot must render its spinner while
    // the stats slot renders the inline error.
    const usersResolvers: Array<(value: unknown) => void> = [];
    fetchMock.mockImplementation((input: unknown) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/api/admin/users/stats')) {
        return Promise.resolve(jsonResponse({ detail: 'stats kaboom' }, 500));
      }
      // Users query: never resolves so we can assert the slot spinner.
      return new Promise<unknown>((resolve) => {
        usersResolvers.push(resolve);
      });
    });

    renderPage();

    // Wait for the heading to confirm we got past the page-level loading
    // gate (i.e. the page IS rendering the partial UI rather than the
    // full-page spinner).
    await screen.findByRole('heading', { name: /admin · users/i });

    // Stats slot shows its inline error + retry button.
    expect(screen.getByText(/stats kaboom|failed to load admin stats/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();

    // Users slot shows its spinner with the roster-loading caption.
    expect(screen.getByText(/loading user roster/i)).toBeInTheDocument();

    // Tidy up still-pending fetches so they don't leak into other tests.
    for (const resolve of usersResolvers) {
      resolve(jsonResponse({ users: [] }));
    }
  });

  it('does not render an "X total" header count when stats fails and users succeeds', async () => {
    // Audit pass-3 finding: the header rendered ``{totalUsers} total``
    // with ``totalUsers = stats?.totalUsers ?? users.length``. When
    // stats failed, the fallback to ``users.length`` silently rendered
    // the loaded-roster count as the authoritative total — admins
    // couldn't tell the stats endpoint was broken.
    //
    // Fix: when stats has errored and there's no stats data, the header
    // renders the dashed placeholder ``"— total"`` instead of a number.
    fetchMock.mockImplementation((input: unknown) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/api/admin/users/stats')) {
        return Promise.resolve(jsonResponse({ detail: 'stats kaboom' }, 500));
      }
      return Promise.resolve(
        jsonResponse({
          users: [
            {
              id: 'u1',
              email: 'a@example.com',
              displayName: null,
              signupProvider: 'google',
              createdAt: '2025-01-01T00:00:00Z',
              isAdmin: false,
            },
            {
              id: 'u2',
              email: 'b@example.com',
              displayName: null,
              signupProvider: 'google',
              createdAt: '2025-01-02T00:00:00Z',
              isAdmin: false,
            },
          ],
        })
      );
    });

    renderPage();

    await screen.findByRole('heading', { name: /admin · users/i });

    // Roster is rendered (the two emails appear).
    await screen.findByText('a@example.com');
    expect(screen.getByText('b@example.com')).toBeInTheDocument();

    // The header MUST NOT render "2 total" (the silent fallback to
    // ``users.length``). Instead, it must render the em-dash placeholder
    // so the admin can tell the count is unknown.
    expect(screen.queryByText(/^2 total$/)).not.toBeInTheDocument();
    expect(screen.getByText(/^— total$/)).toBeInTheDocument();
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
