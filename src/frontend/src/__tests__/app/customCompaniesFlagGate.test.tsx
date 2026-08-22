import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';

/**
 * REGRESSION GATE — with `VITE_CUSTOM_COMPANIES_ENABLED` off, the app must be
 * indistinguishable from one built before this feature existed:
 *
 *   1. no "Add Companies" entry in the sidebar, and
 *   2. no `/add-companies` route registered at all (not merely hidden), so
 *      navigating there renders nothing rather than an unreleased page — and
 *      the same for the pre-rename `/my-companies` path, whose redirect is
 *      behind the very same flag.
 *
 * The flag defaults to off, so a regression here ships the feature to
 * production silently. Both halves are asserted against a real `<App />`
 * render, because the route registration lives in App.tsx and cannot be
 * verified from the routes config alone.
 */

// Stand-in for the real page: this file gates routing, not page internals, and
// the marker makes "did the route match?" unambiguous.
vi.mock('../../pages/MyCompaniesPage', () => ({
  MyCompaniesPage: () => <div data-testid="my-companies-page">Add Companies page body</div>,
}));

// App imports the trend page from its own module (not the barrel) so it can be
// gated/mocked independently of the list page.
vi.mock('../../pages/MyCompaniesPage/MyCompanyTrendPage', () => ({
  MyCompanyTrendPage: () => <div data-testid="my-company-trend-page">Trend page body</div>,
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

// Thirteen full `<App />` renders in one file. On an idle machine it takes ~15s, and ten
// of them were measured blowing a 15s cap on a loaded machine (15013ms) — a red CI run
// that says nothing about the code. The renders are the point of this gate (route
// registration lives in App.tsx and cannot be checked from the routes config), so the cap
// is raised rather than the assertions thinned.
const FULL_APP_RENDER_TIMEOUT_MS = 45_000;

describe('custom company sources — feature flag gate', () => {
  describe('flag OFF (the default)', () => {
    it('registers NO /add-companies route', async () => {
      await renderAppAt('/add-companies', false);

      expect(screen.queryByTestId('my-companies-page')).not.toBeInTheDocument();
      // Not even the shell renders: `/add-companies` matches no child of the
      // layout route, so React Router declines the whole branch. That is the
      // point of gating registration rather than gating the page's contents.
      await waitFor(() =>
        expect(screen.queryByText('JOBS FROM THE SOURCE')).not.toBeInTheDocument()
      );
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('registers NO /add-companies/:id trend route', async () => {
      await renderAppAt('/add-companies/u-abc1234567', false);

      expect(screen.queryByTestId('my-company-trend-page')).not.toBeInTheDocument();
      await waitFor(() =>
        expect(screen.queryByText('JOBS FROM THE SOURCE')).not.toBeInTheDocument()
      );
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('registers NO legacy /my-companies redirect either', async () => {
      // The redirect is a route like any other, and it is gated on the same flag.
      // If it leaked past the gate, the old path would bounce a flag-off visitor
      // onto `/add-companies` — a URL that renders nothing — instead of the plain
      // 404 the app had before this feature existed.
      await renderAppAt('/my-companies/u-abc1234567', false);

      await waitFor(() =>
        expect(screen.queryByText('JOBS FROM THE SOURCE')).not.toBeInTheDocument()
      );
      expect(screen.queryByTestId('my-companies-page')).not.toBeInTheDocument();
      expect(screen.queryByTestId('my-company-trend-page')).not.toBeInTheDocument();
      expect(window.location.pathname).toBe('/my-companies/u-abc1234567');
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('shows NO "Add Companies" nav entry', async () => {
      await renderAppAt('/', false);
      await findShell();

      expect(screen.queryByText('Add Companies')).not.toBeInTheDocument();
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('leaves the existing nav items untouched', async () => {
      await renderAppAt('/', false);
      await findShell();

      // `getAllBy*`: at `/` the index page also has a "Recent Job Postings"
      // heading, so the nav label is not the only match.
      expect(screen.getAllByText('Recent Job Postings').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Company Hiring Trends').length).toBeGreaterThan(0);
      expect(screen.getAllByText('Saved Filters').length).toBeGreaterThan(0);
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('omits /add-companies from the exported nav config', async () => {
      vi.resetModules();
      vi.stubEnv('VITE_CUSTOM_COMPANIES_ENABLED', '');
      const { PRIMARY_NAV_ITEMS, USER_NAV_ITEMS, ROUTES } = await import('../../config/routes');

      expect(PRIMARY_NAV_ITEMS.map((i) => i.path)).not.toContain(ROUTES.MY_COMPANIES);
      expect(USER_NAV_ITEMS.map((i) => i.path)).not.toContain(ROUTES.MY_COMPANIES);
    }, FULL_APP_RENDER_TIMEOUT_MS);
  });

  describe('flag ON', () => {
    it('registers the /add-companies route', async () => {
      await renderAppAt('/add-companies', true);

      expect(await screen.findByTestId('my-companies-page')).toBeInTheDocument();
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('registers the /add-companies/:id trend route', async () => {
      await renderAppAt('/add-companies/u-abc1234567', true);

      expect(await screen.findByTestId('my-company-trend-page')).toBeInTheDocument();
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('shows the "Add Companies" nav entry', async () => {
      await renderAppAt('/', true);

      expect(await screen.findByText('Add Companies')).toBeInTheDocument();
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('appends /add-companies to the exported nav config', async () => {
      vi.resetModules();
      vi.stubEnv('VITE_CUSTOM_COMPANIES_ENABLED', 'true');
      const { PRIMARY_NAV_ITEMS, ROUTES } = await import('../../config/routes');

      const item = PRIMARY_NAV_ITEMS.find((i) => i.path === ROUTES.MY_COMPANIES);
      expect(item).toBeDefined();
      expect(item?.label).toBe('Add Companies');
      // The icon name must exist in NavigationDrawer's iconMap or the entry
      // renders as a blank square.
      expect(item?.icon).toBe('AddBusiness');
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('pins the path constants: /add-companies now, /my-companies as the legacy alias', async () => {
      const { ROUTES } = await import('../../config/routes');
      expect(ROUTES.MY_COMPANIES).toBe('/add-companies');
      expect(ROUTES.MY_COMPANY_DETAIL).toBe('/add-companies/:id');
      // The old path is not a free-floating string: the redirect route is built
      // from this constant, so a change here silently breaks every existing link.
      expect(ROUTES.MY_COMPANIES_LEGACY).toBe('/my-companies');
    }, FULL_APP_RENDER_TIMEOUT_MS);
  });

  /**
   * The rename kept the old URL alive. These are the cases that made the redirect
   * worth writing rather than just repointing the nav link: a tab someone left open
   * on `/my-companies`, and — the one a bare `<Navigate to={ROUTES.MY_COMPANIES}>`
   * would have quietly broken — a bookmark on one company's trend page, which must
   * land on THAT company and not on the list.
   */
  describe('legacy /my-companies redirect (flag ON)', () => {
    it('sends the bare list path to /add-companies', async () => {
      await renderAppAt('/my-companies', true);

      expect(await screen.findByTestId('my-companies-page')).toBeInTheDocument();
      expect(window.location.pathname).toBe('/add-companies');
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('carries the company id through to the trend page, not the list', async () => {
      await renderAppAt('/my-companies/u-abc1234567', true);

      expect(await screen.findByTestId('my-company-trend-page')).toBeInTheDocument();
      expect(window.location.pathname).toBe('/add-companies/u-abc1234567');
      // The list page is the wrong destination, and it is the destination a
      // sub-path-blind redirect would have picked.
      expect(screen.queryByTestId('my-companies-page')).not.toBeInTheDocument();
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('preserves the query string and hash', async () => {
      await renderAppAt('/my-companies/u-abc1234567?window=90d#jobs', true);

      expect(await screen.findByTestId('my-company-trend-page')).toBeInTheDocument();
      expect(window.location.pathname).toBe('/add-companies/u-abc1234567');
      expect(window.location.search).toBe('?window=90d');
      expect(window.location.hash).toBe('#jobs');
    }, FULL_APP_RENDER_TIMEOUT_MS);

    it('replaces the old entry instead of pushing a new one', async () => {
      // `replace`, not `push`: otherwise Back from `/add-companies` lands on
      // `/my-companies`, which immediately redirects forward again — a Back
      // button the user cannot escape.
      window.history.pushState({}, '', '/why');
      const lengthBefore = window.history.length;

      await renderAppAt('/my-companies', true);
      await screen.findByTestId('my-companies-page');

      expect(window.location.pathname).toBe('/add-companies');
      // pushState in renderAppAt added exactly one entry; the redirect must not
      // add a second on top of it.
      expect(window.history.length).toBe(lengthBefore + 1);
    }, FULL_APP_RENDER_TIMEOUT_MS);
  });
});
