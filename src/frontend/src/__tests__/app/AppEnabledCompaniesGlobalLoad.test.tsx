import { describe, it, expect, vi, beforeEach, beforeAll, afterAll, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import App from '../../app/App';
import { createTestStore } from '../../test/testUtils';

// Mutable auth state so the single module mock below can flip per-test.
const mockAuthState = {
  isEnabled: true,
  isAuthenticated: true,
  getToken: vi.fn(),
};

vi.mock('../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: mockAuthState.isEnabled,
    isAuthenticated: mockAuthState.isAuthenticated,
    isLoading: false,
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: mockAuthState.getToken,
  }),
}));

vi.mock('@auth0/auth0-react', () => ({
  useAuth0: () => ({
    isAuthenticated: false,
    isLoading: false,
    user: null,
    loginWithRedirect: vi.fn(),
    logout: vi.fn(),
    getAccessTokenSilently: vi.fn(),
  }),
}));

vi.mock('@react-oauth/google', () => ({
  useGoogleOneTapLogin: vi.fn(),
}));

vi.mock('recharts', () => ({
  LineChart: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ResponsiveContainer: () => null,
  Legend: () => null,
}));

const enabledCompaniesCalls: string[] = [];

const server = setupServer(
  http.get('/api/users/enabled-companies', ({ request }) => {
    enabledCompaniesCalls.push(request.headers.get('authorization') ?? '');
    return HttpResponse.json({ companyIds: ['airbnb', 'stripe'] });
  }),
  http.get('/api/users', () => HttpResponse.json({})),
  http.get('/api/ashby/v1/jobBoard/:boardName/jobs', () =>
    HttpResponse.json({ jobs: [] })
  ),
  http.get('/api/lever/v0/postings/*', () => HttpResponse.json([])),
  http.get('/api/jobs', () => HttpResponse.json([]))
);

beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => {
  server.resetHandlers();
  enabledCompaniesCalls.length = 0;
});
afterAll(() => server.close());

describe('App — global enabled-companies load', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/'),
      writable: true,
      configurable: true,
    });
    vi.spyOn(window.history, 'pushState').mockImplementation(() => {});
    mockAuthState.getToken.mockReset();
  });

  it('hydrates enabled-companies on a fresh load of `/` without visiting /account', async () => {
    mockAuthState.isAuthenticated = true;
    mockAuthState.getToken.mockResolvedValue('tok-global');

    const store = createTestStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>
    );

    await waitFor(() => {
      expect(store.getState().enabledCompanies.ids).toEqual(['airbnb', 'stripe']);
    });
    expect(enabledCompaniesCalls).toEqual(['Bearer tok-global']);
  });

  it('does not fetch enabled-companies when signed out', async () => {
    mockAuthState.isAuthenticated = false;

    const store = createTestStore();
    render(
      <Provider store={store}>
        <App />
      </Provider>
    );

    // Give effects a chance to run; ids must remain null and no call must fire.
    await new Promise((r) => setTimeout(r, 50));
    expect(enabledCompaniesCalls).toEqual([]);
    expect(store.getState().enabledCompanies.ids).toBeNull();
  });
});
