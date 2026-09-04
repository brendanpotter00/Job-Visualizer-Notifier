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
import { lazy, Suspense } from 'react';
import { LoadingState } from '../components/shared/LoadingIndicator';

/**
 * Lazy at the ROUTE, not just the 3D scene: the landing page's copy config and
 * mock-job fixtures would otherwise ride the main bundle onto every page and
 * build 28 fabricated jobs at app boot for a page most visitors never open.
 */
const LandingPage = lazy(() => import('../pages/LandingPage/LandingPage.tsx'));
import { AdminRoute } from '../components/auth/AdminRoute.tsx';
import { useEnabledCompanies } from '../features/preferences/useEnabledCompanies';
import { useHydrateSavedFilters } from '../features/savedFilters/useHydrateSavedFilters';
import { useRecentJobsUrlSync } from '../features/filters/useRecentJobsUrlSync';
import { useFeaturesAuthBridge } from '../features/features/useFeaturesAuthBridge';
import { useRecordVisit } from '../features/auth/useRecordVisit';
import { usePostHogPageview } from '../features/analytics/usePostHogPageview';
import { usePostHogIdentify } from '../features/analytics/usePostHogIdentify';
import { useSignupFunnel } from '../features/analytics/useSignupFunnel';
import { SubcategoryRevealProvider } from '../features/settings/subcategoryReveal';

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
 * Redirects the pre-consolidation `/admin/landing-prototypes` path onto
 * `/landing`.
 *
 * The old path had no sub-paths (the four designs were `?proto=` values, not
 * segments), so unlike the my-companies redirect there is no suffix to rebuild
 * — but `search` and `hash` still ride along, because the surviving `?data=`
 * fixture toggle is a query param and dropping it would silently change what a
 * shared link renders. `replace` keeps the dead path out of history so Back
 * doesn't land on it and bounce forward again.
 */
function LegacyLandingRedirect() {
  const { search, hash } = useLocation();
  return <Navigate to={`${ROUTES.LANDING}${search}${hash}`} replace />;
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
  // BEFORE useHydrateSavedFilters, and the order is load-bearing. A shared link
  // wins for that visit, and the mechanism is the slice's one-shot `hydrated`
  // guard: whichever hydration lands first is the one that sticks. This reads the
  // URL synchronously while saved filters need a round trip, so it would win
  // anyway — declaring it first makes that a decision instead of an accident.
  // Mounted at the root but SCOPED INTERNALLY to the Recent Jobs route, the same
  // way useURLSync above is scoped to /companies: it has to run before the
  // hydration hook, and the hydration hook lives here, but its query params
  // belong on one page only.
  useRecentJobsUrlSync();
  // Hydrate the filter slices (time windows, locations, active keyword list)
  // from saved filters once on sign-in; reset on sign-out. A no-op when the line
  // above already hydrated from a shared link — which is exactly the precedence
  // we want, and why the reader's own saved filters are neither read nor written
  // on such a visit.
  useHydrateSavedFilters();
  usePostHogPageview();
  usePostHogIdentify();
  // Top of the signup-conversion funnel: fires `signup_funnel_landing` once for
  // account-less visitors and keeps the `is_authenticated` super-property in sync.
  useSignupFunnel();

  return (
    <>
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
        {/* Sibling of the RootLayout route: renders full-bleed (no drawer/appbar)
            so the landing page reads like a real standalone page.
            Deliberately UNLISTED rather than admin-gated (owner decision,
            2026-08-10, reaffirmed on the 2026-09-03 consolidation): reachable
            by direct URL only — no nav entry, no changelog card — so reviewers
            can open it without signing in. Mock data only; nothing here touches
            real APIs. */}
        <Route
          path={ROUTES.LANDING}
          element={
            <Suspense fallback={<LoadingState fullPage />}>
              <LandingPage />
            </Suspense>
          }
        />
        {/* The pre-consolidation path, still routable so links already sent out
            keep working now that the four-prototype workspace is one page. */}
        <Route path={ROUTES.LANDING_LEGACY} element={<LegacyLandingRedirect />} />
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
      {/* ONE subscription to GET /api/jobs/settings for the whole app. Mounted
          here rather than per-consumer because JobChipsSection reads the flag
          once per card inside a virtualized list. */}
      <SubcategoryRevealProvider>
        <AppContent />
      </SubcategoryRevealProvider>
    </BrowserRouter>
  );
}

export default App;
