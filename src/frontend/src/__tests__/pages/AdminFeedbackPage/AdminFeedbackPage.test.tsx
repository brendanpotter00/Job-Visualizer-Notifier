import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import { AdminFeedbackPage } from '../../../pages/AdminFeedbackPage/AdminFeedbackPage';

// Node's built-in `Request` requires absolute URLs; RTK Query passes relative
// URLs. Shim the global to resolve them against a test origin.
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
  return render(
    <Provider store={makeStore()}>
      <AdminFeedbackPage />
    </Provider>
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const SAMPLE = [
  {
    id: 'fb1',
    message: 'Love the new dashboard',
    userId: 'u1',
    userEmail: 'alice@example.com',
    displayName: 'Alice',
    createdAt: '2026-06-02T10:00:00Z',
  },
  {
    id: 'fb2',
    message: 'Anonymous thought',
    userId: null,
    userEmail: null,
    displayName: null,
    createdAt: '2026-06-01T10:00:00Z',
  },
];

describe('AdminFeedbackPage', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  it('shows a loading spinner while the query is pending', () => {
    fetchMock.mockImplementation(() => new Promise(() => {}));
    renderPage();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders the heading, submission count, rows and "Anonymous" for null users', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ feedback: SAMPLE }));
    renderPage();

    expect(
      await screen.findByText('Love the new dashboard')
    ).toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: /admin · user feedback/i, level: 1 })
    ).toBeInTheDocument();
    expect(screen.getByText('2 submissions')).toBeInTheDocument();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('Anonymous')).toBeInTheDocument();
    expect(screen.getByText('Anonymous thought')).toBeInTheDocument();
  });

  it('uses the singular "submission" label for a single row', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ feedback: [SAMPLE[0]] }));
    renderPage();
    expect(await screen.findByText('1 submission')).toBeInTheDocument();
  });

  it('shows an empty state when there is no feedback', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ feedback: [] }));
    renderPage();
    expect(await screen.findByText(/no feedback has been submitted/i)).toBeInTheDocument();
  });

  it('shows an inline error with retry when the query fails', async () => {
    // Detail-less 500 → the component's generic fallback message is shown.
    fetchMock.mockResolvedValue(jsonResponse({}, 500));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText(/failed to load feedback/i)).toBeInTheDocument()
    );
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
