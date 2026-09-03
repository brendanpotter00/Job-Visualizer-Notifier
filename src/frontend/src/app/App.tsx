import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useURLSync, useBrowserNavigation } from './hooks';
import { RootLayout } from '../components/layout/RootLayout.tsx';
import { CompaniesPage } from '../pages/CompaniesPage/CompaniesPage';
import { CuratedCompaniesPage } from '../pages/CuratedCompaniesPage';
import { RecentJobPostingsPage } from '../pages/RecentJobPostingsPage/RecentJobPostingsPage';
import { WhyPage } from '../pages/WhyPage/WhyPage.tsx';
import { AccountPage } from '../pages/AccountPage/AccountPage.tsx';
import { SavedFiltersPage } from '../pages/SavedFiltersPage';
import { VoteFeaturesPage } from '../pages/VoteFeaturesPage';
import { MyCompaniesPage } from '../pages/MyCompaniesPage';
// Imported from its own module (not the barrel) so the flag-gate test can mock
// each page independently.
import { MyCompanyTrendPage } from '../pages/MyCompaniesPage/MyCompanyTrendPage';
import { ROUTES } from '../config/routes';
import { CUSTOM_COMPANIES_CONFIG } from '../config/customCompanies';
import { QAPage } from '../pages/QAPage/QAPage.tsx';
import { AdminUsersPage } from '../pages/AdminUsersPage/AdminUsersPage.tsx';
import { AdminLocationNormalizationPage } from '../pages/AdminLocationNormalizationPage/AdminLocationNormalizationPage.tsx';
import { AdminEnrichmentPage } from '../pages/AdminEnrichmentPage/AdminEnrichmentPage.tsx';
import { AdminLocationPipelinePage } from '../pages/AdminLocationPipelinePage/AdminLocationPipelinePage.tsx';
import { AdminCustomCompaniesPage } from '../pages/AdminCustomCompaniesPage/AdminCustomCompaniesPage.tsx';
import { AdminFeedbackPage } from '../pages/AdminFeedbackPage/AdminFeedbackPage.tsx';
import { AdminRoute } from '../components/auth/AdminRoute.tsx';
import { useEnabledCompanies } from '../features/preferences/useEnabledCompanies';
import { useHydrateSavedFilters } from '../features/savedFilters/useHydrateSavedFilters';
import { useFeaturesAuthBridge } from '../features/features/useFeaturesAuthBridge';
import { useRecordVisit } from '../features/auth/useRecordVisit';
import { usePostHogPageview } from '../features/analytics/usePostHogPageview';
import { usePostHogIdentify } from '../features/analytics/usePostHogIdentify';
import { useSignupFunnel } from '../features/analytics/useSignupFunnel';
import { WEBMCP_CONFIG, WebMcpBridge } from '../webmcp';

/**
 * Redirects the pre-rename `/my-companies…` path onto `/add-companies…`.
 *
 * Mounted on a splat route, so it stands in for the list page AND everything
 * under it. It rebuilds the destination from whatever followed the old prefix
 * rather than sending everyone to the bare list, because the case that matters
 * is an open tab or a bookmark on `/my-companies/u-abc123` — one company's
 * trend page — quietly becoming "here is the list, go find it again". `search`
 * and `hash` ride along for the same reason. `replace` keeps the dead path out
 * of history so Back doesn't land on it and bounce forward again.
 */
function LegacyMyCompaniesRedirect() {
  const { pathname, search, hash } = useLocation();
  const suffix = pathname.slice(ROUTES.MY_COMPANIES_LEGACY.length);
  return <Navigate to={`${ROUTES.MY_COMPANIES}${suffix}${search}${hash}`} replace />;
}

/**
 * App content component with routing and hooks
 *
 * This component must be inside BrowserRouter to use hooks that
 * depend on React Router context (useLocation).
 */
function AppContent() {
  useURLSync();
  useBrowserNavigation();
  // Record one visit per full page load for the signed-in user (no-op when
  // anonymous). Mounted here so client-side route navigation doesn't re-fire.
  useRecordVisit();
  // Hydrate enabled-companies at the app root so selectors have it before
  // any page reads them.
  useEnabledCompanies();
  // Register the RTK Query token-getter BEFORE the hydrate hook below. On the
  // render where auth flips true, the hydrate hook fires the saved-filters /
  // keyword-lists requests; those must read a credential-bearing token getter
  // (not the stale anonymous one) or they go out without an Authorization header,
  // 401, and stick — the queries have no retry / refetchOnMountOrArgChange.
  // React runs effects in declaration order, so the bridge must come first.
  useFeaturesAuthBridge();
  // Hydrate the filter slices (time windows, locations, active keyword list)
  // from saved filters once on sign-in; reset on sign-out.
  useHydrateSavedFilters();
  usePostHogPageview();
  usePostHogIdentify();
  // Top of the signup-conversion funnel: fires `signup_funnel_landing` once for
  // account-less visitors and keeps the `is_authenticated` super-property in sync.
  useSignupFunnel();

  return (
    <>
      {/* Captures router navigate + auth login into module refs for the
          store-only WebMCP tools. Mounted only behind VITE_WEBMCP; renders
          null and touches no other state. */}
      {WEBMCP_CONFIG.isEnabled && <WebMcpBridge />}
      <Routes>
        <Route path="/" element={<RootLayout />}>
          <Route index element={<RecentJobPostingsPage />} />
          <Route path={ROUTES.COMPANIES} element={<CompaniesPage />} />
          <Route path={ROUTES.CURATED_COMPANIES} element={<CuratedCompaniesPage />} />
          <Route path={ROUTES.WHY} element={<WhyPage />} />
          <Route
            path={ROUTES.QA}
            element={
              <AdminRoute>
                <QAPage />
              </AdminRoute>
            }
          />
          <Route
            path={ROUTES.ADMIN_USERS}
            element={
              <AdminRoute>
                <AdminUsersPage />
              </AdminRoute>
            }
          />
          <Route
            path={ROUTES.ADMIN_LOCATION_NORMALIZATION}
            element={
              <AdminRoute>
                <AdminLocationNormalizationPage />
              </AdminRoute>
            }
          />
          {/* Public route — not admin-gated. Admins get a sidebar link
              (ADMIN_NAV_ITEMS); everyone else arrives via the Changelog card. */}
          <Route path={ROUTES.LOCATION_PIPELINE} element={<AdminLocationPipelinePage />} />
          <Route
            path={ROUTES.ADMIN_ENRICHMENT}
            element={
              <AdminRoute>
                <AdminEnrichmentPage />
              </AdminRoute>
            }
          />
          {/* Admin-gated only — deliberately NOT behind
              CUSTOM_COMPANIES_CONFIG.isEnabled, because an environment where
              the user-facing flag is off is exactly when an admin most wants
              to inspect what the feature did. */}
          <Route
            path={ROUTES.ADMIN_CUSTOM_COMPANIES}
            element={
              <AdminRoute>
                <AdminCustomCompaniesPage />
              </AdminRoute>
            }
          />
          <Route
            path={ROUTES.ADMIN_FEEDBACK}
            element={
              <AdminRoute>
                <AdminFeedbackPage />
              </AdminRoute>
            }
          />
          <Route path={ROUTES.ACCOUNT} element={<AccountPage />} />
          <Route path={ROUTES.SAVED_FILTERS} element={<SavedFiltersPage />} />
          <Route path={ROUTES.VOTE_FEATURES} element={<VoteFeaturesPage />} />
          {/* Flag-gated: with VITE_CUSTOM_COMPANIES_ENABLED off the route is
              not registered at all, so /add-companies is a 404 rather than a
              reachable-but-hidden page. */}
          {CUSTOM_COMPANIES_CONFIG.isEnabled && (
            <Route path={ROUTES.MY_COMPANIES} element={<MyCompaniesPage />} />
          )}
          {/* Private per-company trend page. Same flag gate — with the flag off
              the `/add-companies/:id` route is not registered, so a runtime id
              is a 404 rather than a reachable-but-empty page. */}
          {CUSTOM_COMPANIES_CONFIG.isEnabled && (
            <Route path={ROUTES.MY_COMPANY_DETAIL} element={<MyCompanyTrendPage />} />
          )}
        </Route>
        {/* The pre-rename path, still routable so tabs and bookmarks on
            /my-companies survive the rename. Behind the SAME flag as the two
            routes above: with the feature off neither the new path nor the old
            one is registered, so the app is byte-for-byte what shipped before
            the feature existed. Deliberately a sibling of the layout route
            rather than a child — the element only redirects, and mounting the
            whole shell (drawer, page hooks, its network calls) for a URL that
            is replaced on the first effect is work nobody ever sees. */}
        {CUSTOM_COMPANIES_CONFIG.isEnabled && (
          <Route
            path={`${ROUTES.MY_COMPANIES_LEGACY}/*`}
            element={<LegacyMyCompaniesRedirect />}
          />
        )}
      </Routes>
    </>
  );
}

/**
 * Root application component
 *
 * Coordinates routing, URL synchronization, and page rendering.
 * Uses React Router v6 for multi-page navigation and custom hooks
 * for URL/state synchronization.
 *
 * Routes:
 * - / - Recent job postings page (all jobs across companies)
 * - /companies - Companies page (job analytics for selected company)
 * - /why - Why This Was Built page (about and supported companies)
 * - /qa - QA page (scraper triggers, run history, debugging)
 * - /account - Account page (user profile management)
 * - /vote-features - Vote for features page (changelog + feature voting)
 */
function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}

export default App;
