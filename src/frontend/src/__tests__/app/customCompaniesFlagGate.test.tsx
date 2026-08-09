import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';

/**
 * REGRESSION GATE — with `VITE_CUSTOM_COMPANIES_ENABLED` off, the app must be
 * indistinguishable from one built before this feature existed:
 *
 *   1. no "My Companies" entry in the sidebar, and
 *   2. no `/my-companies` route registered at all (not merely hidden), so
 *      navigating there renders nothing rather than an unreleased page.
 *
 * The flag defaults to off, so a regression here ships the feature to
 * production silently. Both halves are asserted against a real `<App />`
 * render, because the route registration lives in App.tsx and cannot be
 * verified from the routes config alone.
 */

// Stand-in for the real page: this file gates routing, not page internals, and
// the marker makes "did the route match?" unambiguous.
vi.mock('../../pages/MyCompaniesPage', () => ({
  MyCompaniesPage: () => <div data-testid="my-companies-page">My Companies page body</div>,
}));

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

/**
 * Renders the real `<App />` at `path` with the flag in the given state.
 *
 * App and testUtils are imported *dynamically, after* `resetModules()` so both
 * observe the stubbed env and share one module graph — a statically imported
 * `createTestStore` would build its store from a different copy of the API
 * slices than the freshly imported App renders against.
 */
async function renderAppAt(path: string, flagEnabled: boolean) {
  vi.resetModules();
  vi.stubEnv('VITE_CUSTOM_COMPANIES_ENABLED', flagEnabled ? 'true' : '');
  window.history.pushState({}, '', path);

  const [{ default: App }, { createTestStore }] = await Promise.all([
    import('../../app/App'),
    import('../../test/testUtils'),
  ]);

  return render(
    <Provider store={createTestStore()}>
      <App />
    </Provider>
  );
}

/**
 * Waits for the app shell to mount. Anchors on the sidebar's group caption,
 * which only NavigationDrawer renders — unlike the nav labels themselves,
 * which can collide with a page heading of the same name.
 */
function findShell() {
  return screen.findByText('JOBS FROM THE SOURCE');
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
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  window.history.pushState({}, '', '/');
});

describe('custom company sources — feature flag gate', () => {
  describe('flag OFF (the default)', () => {
    it('registers NO /my-companies route', async () => {
      await renderAppAt('/my-companies', false);

      expect(screen.queryByTestId('my-companies-page')).not.toBeInTheDocument();
      // Not even the shell renders: `/my-companies` matches no child of the
      // layout route, so React Router declines the whole branch. That is the
      // point of gating registration rather than gating the page's contents.
      await waitFor(() =>
        expect(screen.queryByText('JOBS FROM THE SOURCE')).not.toBeInTheDocument()
      );
    });

    it('shows NO "My Companies" nav entry', async () => {
      await renderAppAt('/', false);
      await findShell();

      expect(screen.queryByText('My Companies')).not.toBeInTheDocument();
    });

    it('leaves the existing nav items untouched', async () => {
      await renderAppAt('/', false);
      await findShell();

      // `getAllBy*`: at `/` the index page also has a "Recent Job Postings"
      // heading, so the nav label is not the only match.
      expect(screen.getAllByText('Recent Job Postings').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Company Hiring Trends').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Saved Filters').length).toBeGreaterThan(0);
    });

    it('omits /my-companies from the exported nav config', async () => {
      vi.resetModules();
      vi.stubEnv('VITE_CUSTOM_COMPANIES_ENABLED', '');
      const { PRIMARY_NAV_ITEMS, USER_NAV_ITEMS, ROUTES } = await import('../../config/routes');

      expect(PRIMARY_NAV_ITEMS.map((i) => i.path)).not.toContain(ROUTES.MY_COMPANIES);
      expect(USER_NAV_ITEMS.map((i) => i.path)).not.toContain(ROUTES.MY_COMPANIES);
    });
  });

  describe('flag ON', () => {
    it('registers the /my-companies route', async () => {
      await renderAppAt('/my-companies', true);

      expect(await screen.findByTestId('my-companies-page')).toBeInTheDocument();
    });

    it('shows the "My Companies" nav entry', async () => {
      await renderAppAt('/', true);

      expect(await screen.findByText('My Companies')).toBeInTheDocument();
    });

    it('appends /my-companies to the exported nav config', async () => {
      vi.resetModules();
      vi.stubEnv('VITE_CUSTOM_COMPANIES_ENABLED', 'true');
      const { PRIMARY_NAV_ITEMS, ROUTES } = await import('../../config/routes');

      const item = PRIMARY_NAV_ITEMS.find((i) => i.path === ROUTES.MY_COMPANIES);
      expect(item).toBeDefined();
      expect(item?.label).toBe('My Companies');
      // The icon name must exist in NavigationDrawer's iconMap or the entry
      // renders as a blank square.
      expect(item?.icon).toBe('AddBusiness');
    });

    it('keeps the path constant stable at /my-companies', async () => {
      const { ROUTES } = await import('../../config/routes');
      expect(ROUTES.MY_COMPANIES).toBe('/my-companies');
    });
  });
});
