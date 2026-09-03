import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import App from '../../app/App';
import { createTestStore } from '../../test/testUtils';
import { ROUTES } from '../../config/routes';

/**
 * Route registration for the landing page, asserted against a real `<App />`
 * because that is where it lives — the routes config alone cannot say whether a
 * path is actually mounted, mounted OUTSIDE RootLayout, or redirected.
 *
 * Three things are pinned here, all of which broke or moved in the 2026-09-03
 * consolidation:
 *   1. `/landing` renders the page, full-bleed (no drawer/appbar around it);
 *   2. the pre-consolidation `/admin/landing-prototypes` still lands somewhere
 *      useful, because links to it were already shared by hand; and
 *   3. that redirect carries the query string, since `?data=` is the one URL
 *      knob the page still has.
 */

// Stand-in for the real page: this file gates routing, not page internals, and
// the marker makes "did the route match?" unambiguous. Mocking here also keeps
// the lazy three/rapier scene entirely out of this test process.
vi.mock('../../pages/LandingPage/LandingPage', () => {
  const LandingPage = () => <div data-testid="landing-page">Landing page body</div>;
  // Named export for direct imports, default for the React.lazy boundary in
  // App.tsx — the route suspends forever if the default is missing.
  return { LandingPage, default: LandingPage };
});

vi.mock('../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: false,
    isAuthenticated: false,
    isLoading: false,
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(),
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

function renderAppAt(path: string) {
  window.history.pushState({}, '', path);
  return render(
    <Provider store={createTestStore()}>
      <App />
    </Provider>
  );
}

beforeEach(() => {
  // Safety net: any hook that still reaches for the network gets an empty
  // object rather than an unhandled rejection.
  globalThis.fetch = vi.fn(
    async () =>
      new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
  ) as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.pushState({}, '', '/');
});

const FULL_APP_RENDER_TIMEOUT_MS = 45_000;

describe('landing page route', () => {
  it(
    'renders the landing page at /landing',
    async () => {
      renderAppAt(ROUTES.LANDING);
      expect(await screen.findByTestId('landing-page')).toBeInTheDocument();
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  // Mounted as a SIBLING of the layout route so it previews like a real
  // standalone page. The sidebar's group caption is the cheapest proof the app
  // chrome is absent — only NavigationDrawer renders it.
  it(
    'renders it full-bleed, outside the app shell',
    async () => {
      renderAppAt(ROUTES.LANDING);
      await screen.findByTestId('landing-page');
      expect(screen.queryByText('JOBS FROM THE SOURCE')).not.toBeInTheDocument();
      expect(screen.queryByRole('banner')).not.toBeInTheDocument();
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  it(
    'redirects the legacy /admin/landing-prototypes path onto /landing',
    async () => {
      renderAppAt(ROUTES.LANDING_LEGACY);
      expect(await screen.findByTestId('landing-page')).toBeInTheDocument();
      await waitFor(() => expect(window.location.pathname).toBe(ROUTES.LANDING));
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  // The `?data=` fixture toggle is the only query the page reads, so a redirect
  // that dropped the query would silently change what a shared link renders.
  it(
    'carries the query string and hash through the legacy redirect',
    async () => {
      renderAppAt(`${ROUTES.LANDING_LEGACY}?proto=gravity&data=sparse#faq`);
      await screen.findByTestId('landing-page');
      await waitFor(() => expect(window.location.pathname).toBe(ROUTES.LANDING));
      expect(window.location.search).toBe('?proto=gravity&data=sparse');
      expect(window.location.hash).toBe('#faq');
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );

  // `replace`, not `push`: otherwise Back lands on the dead path, which
  // immediately redirects forward again and traps the user.
  it(
    'replaces the legacy path in history rather than pushing',
    async () => {
      window.history.pushState({}, '', '/why');
      const lengthBefore = window.history.length;

      renderAppAt(ROUTES.LANDING_LEGACY);
      await screen.findByTestId('landing-page');
      await waitFor(() => expect(window.location.pathname).toBe(ROUTES.LANDING));

      // pushState in renderAppAt added exactly one entry; the redirect must not
      // add a second on top of it.
      expect(window.history.length).toBe(lengthBefore + 1);
    },
    FULL_APP_RENDER_TIMEOUT_MS
  );
});
