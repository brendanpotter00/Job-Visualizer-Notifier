import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import App from '../../app/App';
import { createTestStore } from '../../test/testUtils';
import { ROUTES } from '../../config/routes';

/**
 * What `/` and unclaimed paths do, asserted against a real `<App />` because
 * that is where the routes live — the routes config alone cannot say whether a
 * path is mounted, mounted OUTSIDE RootLayout, or redirected.
 *
 * 2026-11-12 (owner decision): the landing page took `/` from the jobs board,
 * which moved to `/jobs`. Signed-out visitors see the landing page at `/`;
 * signed-in ones are sent to `/jobs`; anything unclaimed (the landing page's
 * old `/landing` included) goes to `/`. The branch logic itself is covered
 * exhaustively in `homeDestination.test.ts`; this file pins the wiring.
 */

// Stand-ins for the real pages: this file gates routing, not page internals,
// and the markers make "which route matched?" unambiguous. Mocking the landing
// page also keeps the lazy three/rapier scene out of this test process.
vi.mock('../../pages/LandingPage/LandingPage', () => {
  const LandingPage = () => <div data-testid="landing-page">Landing page body</div>;
  // Named export for direct imports, default for the React.lazy boundary in
  // HomeRoute — the route suspends forever if the default is missing.
  return { LandingPage, default: LandingPage };
});

vi.mock('../../pages/RecentJobPostingsPage/RecentJobPostingsPage', () => ({
  RecentJobPostingsPage: () => <div data-testid="recent-jobs-page">Jobs board</div>,
}));

/** Flipped per test; read by the useAuth mock on every render. */
const authState = { isAuthenticated: false, isLoading: false };

vi.mock('../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: authState.isAuthenticated,
    isLoading: authState.isLoading,
    user: authState.isAuthenticated ? { sub: 'auth0|test' } : null,
    login: vi.fn(),
    logout: vi.fn(),
    // Resolves: signed-in app hooks (enabled companies, saved filters) call it.
    getToken: () => Promise.resolve('test-token'),
  }),
}));

vi.mock('@auth0/auth0-react', () => ({
  useAuth0: () => ({
    isAuthenticated: authState.isAuthenticated,
    isLoading: authState.isLoading,
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

function renderAppAt(path: string) {
  window.history.pushState({}, '', path);
  return render(
    <Provider store={createTestStore()}>
      <App />
    </Provider>
  );
}

beforeEach(() => {
  authState.isAuthenticated = false;
  authState.isLoading = false;
  // Safety net: any hook that still reaches for the network gets an empty
  // object rather than an unhandled rejection.
  globalThis.fetch = vi.fn(
    async () => new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
  ) as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.pushState({}, '', '/');
});

const FULL_APP_RENDER_TIMEOUT_MS = 45_000;

describe('home route (/)', () => {
  it(
    'shows a signed-out visitor the landing page, full-bleed',
    async () => {
      renderAppAt(ROUTES.HOME);
      expect(await screen.findByTestId('landing-page')).toBeInTheDocument();
      // The sidebar's group caption is the cheapest proof the app chrome is
      // absent — only NavigationDrawer renders it.
      expect(screen.queryByText('JOBS FROM THE SOURCE')).not.toBeInTheDocument();
      expect(screen.queryByRole('banner')).not.toBeInTheDocument();
      expect(window.location.pathname).toBe('/');
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  it(
    'sends a signed-in visitor to /jobs, inside the app shell',
    async () => {
      authState.isAuthenticated = true;
      renderAppAt(ROUTES.HOME);
      expect(await screen.findByTestId('recent-jobs-page')).toBeInTheDocument();
      expect(window.location.pathname).toBe(ROUTES.RECENT_JOBS);
      expect(screen.queryByTestId('landing-page')).not.toBeInTheDocument();
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  // `replace`: Back from the board must not land on `/` and bounce forward.
  it(
    'replaces / in history rather than pushing when it redirects',
    async () => {
      authState.isAuthenticated = true;
      window.history.pushState({}, '', '/why');
      const lengthBefore = window.history.length;
      renderAppAt(ROUTES.HOME);
      await waitFor(() => expect(window.location.pathname).toBe(ROUTES.RECENT_JOBS));
      expect(window.history.length).toBe(lengthBefore + 1);
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  // A fresh Auth0 login returns to `/?code=…&state=…`; the board URL must not
  // inherit the callback params.
  it(
    'drops the Auth0 callback params on the way to /jobs',
    async () => {
      authState.isAuthenticated = true;
      renderAppAt('/?code=abc&state=xyz');
      await waitFor(() => expect(window.location.pathname).toBe(ROUTES.RECENT_JOBS));
      expect(window.location.search).toBe('');
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  // Recent Jobs filter links were shared as `/?category=…` before the move.
  it(
    'forwards an old shared filter link to /jobs, query intact, even signed out',
    async () => {
      renderAppAt('/?category=backend&level=mid');
      expect(await screen.findByTestId('recent-jobs-page')).toBeInTheDocument();
      expect(window.location.pathname).toBe(ROUTES.RECENT_JOBS);
      expect(window.location.search).toBe('?category=backend&level=mid');
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  it(
    'serves /jobs directly as the jobs board',
    async () => {
      renderAppAt(ROUTES.RECENT_JOBS);
      expect(await screen.findByTestId('recent-jobs-page')).toBeInTheDocument();
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );
});

describe('unclaimed paths', () => {
  it.each([['/landing'], ['/admin/landing-prototypes'], ['/no-such-page']])(
    '%s redirects to the landing page at /',
    async (path) => {
      renderAppAt(path);
      expect(await screen.findByTestId('landing-page')).toBeInTheDocument();
      await waitFor(() => expect(window.location.pathname).toBe('/'));
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  // The `?data=` fixture toggle is the one query the landing page reads, so a
  // redirect that dropped it would silently change what a shared link renders.
  it(
    'carries the query string and hash through the redirect',
    async () => {
      renderAppAt('/landing?data=sparse#faq');
      await screen.findByTestId('landing-page');
      await waitFor(() => expect(window.location.pathname).toBe('/'));
      expect(window.location.search).toBe('?data=sparse');
      expect(window.location.hash).toBe('#faq');
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );
});
