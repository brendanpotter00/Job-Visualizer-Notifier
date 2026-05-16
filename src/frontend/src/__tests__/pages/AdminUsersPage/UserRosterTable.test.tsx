import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi, type AdminUserRow } from '../../../features/admin/adminApi';
import { UserRosterTable } from '../../../pages/AdminUsersPage/components/UserRosterTable';

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

let mockCurrentUser: { id: string; isAdmin: boolean } | null = null;

vi.mock('../../../features/auth/useCurrentUser', () => ({
  useCurrentUser: () => ({
    user: mockCurrentUser,
    setUser: vi.fn(),
    loading: false,
    error: null,
    reload: vi.fn(),
  }),
}));

const PLAIN_USER: AdminUserRow = {
  id: 'plain-1',
  email: 'plain@example.com',
  displayName: 'Plain User',
  signupProvider: 'google',
  createdAt: '2025-03-15T10:00:00Z',
  isAdmin: false,
};

const ADMIN_USER: AdminUserRow = {
  id: 'admin-1',
  email: 'admin@example.com',
  displayName: 'Admin User',
  signupProvider: 'email',
  createdAt: '2025-01-20T10:00:00Z',
  isAdmin: true,
};

function makeStore() {
  return configureStore({
    reducer: { [adminApi.reducerPath]: adminApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: { extraArgument: { getTokenOrNull: () => Promise.resolve('t') } },
      }).concat(adminApi.middleware),
  });
}

function renderTable(users: AdminUserRow[]) {
  const store = makeStore();
  return render(
    <Provider store={store}>
      <UserRosterTable users={users} />
    </Provider>
  );
}

describe('UserRosterTable', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    mockCurrentUser = { id: 'caller-id', isAdmin: true };
  });

  it('renders rows with email, name, provider chip, and admin chip', () => {
    renderTable([PLAIN_USER, ADMIN_USER]);

    expect(screen.getByText('plain@example.com')).toBeInTheDocument();
    expect(screen.getByText('admin@example.com')).toBeInTheDocument();
    expect(screen.getByText('Plain User')).toBeInTheDocument();
    // The admin chip is rendered for ADMIN_USER's row. The header column
    // is also titled "Admin", so disambiguate by chip text content.
    const adminChip = screen
      .getAllByText('Admin')
      .find((el) => el.classList.contains('MuiChip-label'));
    expect(adminChip).toBeDefined();
  });

  function callDetails(call: [unknown, unknown]): { url: string; method: string | undefined } {
    const [input, init] = call;
    if (input instanceof Request) {
      return { url: input.url, method: input.method };
    }
    return {
      url: String(input),
      method: (init as RequestInit | undefined)?.method,
    };
  }

  it('opens the kebab menu and grants admin on click', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const user = userEvent.setup();
    renderTable([PLAIN_USER]);

    await user.click(screen.getByLabelText('Actions for plain@example.com'));
    await user.click(screen.getByRole('menuitem', { name: /make admin/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    const { url, method } = callDetails(
      fetchMock.mock.calls[0] as [unknown, unknown]
    );
    expect(url).toMatch(/\/api\/admin\/users\/plain-1\/admin$/);
    expect(method).toBe('POST');
  });

  it('opens the kebab menu and revokes admin on click', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const user = userEvent.setup();
    renderTable([ADMIN_USER]);

    await user.click(screen.getByLabelText('Actions for admin@example.com'));
    await user.click(screen.getByRole('menuitem', { name: /revoke admin/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    const { url, method } = callDetails(
      fetchMock.mock.calls[0] as [unknown, unknown]
    );
    expect(url).toMatch(/\/api\/admin\/users\/admin-1\/admin$/);
    expect(method).toBe('DELETE');
  });

  it('disables Make admin for rows that are already admins', async () => {
    const user = userEvent.setup();
    renderTable([ADMIN_USER]);

    await user.click(screen.getByLabelText('Actions for admin@example.com'));
    const makeAdmin = screen.getByRole('menuitem', { name: /make admin/i });
    expect(makeAdmin).toHaveAttribute('aria-disabled', 'true');
  });

  it('disables Revoke admin for the current user (self-revoke guardrail)', async () => {
    // Current user IS the admin in the table — Revoke should be disabled.
    mockCurrentUser = { id: ADMIN_USER.id, isAdmin: true };
    const user = userEvent.setup();
    renderTable([ADMIN_USER]);

    await user.click(screen.getByLabelText('Actions for admin@example.com'));
    const revoke = screen.getByRole('menuitem', { name: /revoke admin/i });
    expect(revoke).toHaveAttribute('aria-disabled', 'true');
  });

  it('surfaces server errors via an alert', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'User not found' }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      })
    );
    const user = userEvent.setup();
    renderTable([PLAIN_USER]);

    await user.click(screen.getByLabelText('Actions for plain@example.com'));
    await user.click(screen.getByRole('menuitem', { name: /make admin/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
    expect(screen.getByRole('alert')).toHaveTextContent(/user not found|failed/i);
  });

  it('filters the roster to admins only when the toggle is on, and restores when off', async () => {
    const user = userEvent.setup();
    renderTable([PLAIN_USER, ADMIN_USER]);

    // Sanity: both rows visible before toggling.
    expect(screen.getByText('plain@example.com')).toBeInTheDocument();
    expect(screen.getByText('admin@example.com')).toBeInTheDocument();
    expect(screen.getByText('2 users')).toBeInTheDocument();

    const toggle = screen.getByRole('switch', { name: /admins only/i });
    await user.click(toggle);

    // Plain user filtered out; admin remains.
    expect(screen.queryByText('plain@example.com')).not.toBeInTheDocument();
    expect(screen.getByText('admin@example.com')).toBeInTheDocument();
    expect(screen.getByText('1 user')).toBeInTheDocument();

    // Toggle off — full roster restored.
    await user.click(toggle);
    expect(screen.getByText('plain@example.com')).toBeInTheDocument();
    expect(screen.getByText('admin@example.com')).toBeInTheDocument();
    expect(screen.getByText('2 users')).toBeInTheDocument();
  });

  it('surfaces the 409 last-admin error verbatim in the Alert (cross-layer contract)', async () => {
    // Audit pass-3 finding: the existing 404 test covers a generic
    // server-error path but the 409 "Cannot revoke the last admin —
    // promote another user first." message is the headline contract
    // from pass 1 — and there was no end-to-end test pinning the
    // backend response → Alert text wiring. A regression anywhere in
    // the chain (RTK Query error shape → extractErrorMessage's
    // data.detail walk → Alert text) would silently swallow the
    // actionable message and leave the admin staring at a generic
    // "Failed to revoke admin from ..." fallback.
    //
    // Setup: ADMIN_USER is in the table, current user is a DIFFERENT
    // admin (so the self-revoke disable doesn't fire), and the backend
    // returns 409 with the exact contract body.
    mockCurrentUser = { id: 'caller-id', isAdmin: true };
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: 'Cannot revoke the last admin — promote another user first.',
        }),
        {
          status: 409,
          headers: { 'content-type': 'application/json' },
        }
      )
    );

    const user = userEvent.setup();
    renderTable([ADMIN_USER]);

    await user.click(screen.getByLabelText('Actions for admin@example.com'));
    await user.click(screen.getByRole('menuitem', { name: /revoke admin/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
    // EXACT contract string — not a regex. The Alert must contain the
    // backend's ``detail`` verbatim so the admin gets the actionable
    // "promote another user first" cue. Anything shorter (e.g. a
    // fallback to "Failed to revoke admin") means the cross-layer
    // wiring is broken.
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Cannot revoke the last admin — promote another user first.'
    );
  });
});
