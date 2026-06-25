import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { format } from 'date-fns';
import { adminApi, type AdminUserRow } from '../../../features/admin/adminApi';
import { UserVisitsModal } from '../../../pages/AdminUsersPage/components/UserVisitsModal';

// Node's built-in `Request` requires absolute URLs; RTK Query passes relative
// URLs. Shim the global to resolve them — same approach as adminApi.test.ts.
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

const USER: AdminUserRow = {
  id: 'u1',
  email: 'user@example.com',
  displayName: 'A User',
  signupProvider: 'google',
  createdAt: '2025-03-15T10:00:00Z',
  visitCount: 5,
  lastVisitAt: '2026-06-03T12:00:00Z',
  isAdmin: false,
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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function renderModal(user: AdminUserRow = USER) {
  const store = makeStore();
  return render(
    <Provider store={store}>
      <UserVisitsModal user={user} onClose={vi.fn()} />
    </Provider>
  );
}

describe('UserVisitsModal', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('shows the loading caption while the request is pending', () => {
    fetchMock.mockReturnValue(new Promise(() => {})); // never resolves
    renderModal();
    expect(screen.getByText('Loading visit history…')).toBeInTheDocument();
  });

  it('renders visit timestamps in the order the server returned them (newest first)', async () => {
    // Server orders DESC; the modal must render as-is without re-sorting.
    const visits = ['2026-06-10T12:00:00Z', '2026-06-03T12:00:00Z'];
    fetchMock.mockResolvedValue(jsonResponse({ visits, totalVisitCount: 2, truncated: false }));
    renderModal();

    const expected = visits.map((iso) => format(new Date(iso), 'MMM d, yyyy h:mm:ss a'));
    await waitFor(() => {
      expect(screen.getByText(expected[0])).toBeInTheDocument();
    });
    const items = screen.getAllByRole('listitem').map((li) => li.textContent);
    expect(items).toEqual(expected);
  });

  it('shows the count-vs-history gap caption when fewer timestamps than the total', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ visits: ['2026-06-03T12:00:00Z'], totalVisitCount: 5, truncated: false })
    );
    renderModal();
    await waitFor(() => {
      expect(screen.getByText(/Showing 1 of 5 visits/)).toBeInTheDocument();
    });
  });

  it('shows the empty-history message when no timestamps were logged', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ visits: [], totalVisitCount: 5, truncated: false }));
    renderModal();
    await waitFor(() => {
      expect(screen.getByText(/No individual visit timestamps recorded yet/)).toBeInTheDocument();
    });
  });

  it('shows an error alert when the request fails', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'boom' }, 500));
    renderModal();
    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });
  });
});
