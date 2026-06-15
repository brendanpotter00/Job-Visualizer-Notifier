import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useURLSync, useBrowserNavigation } from './hooks';
import { RootLayout } from '../components/layout/RootLayout.tsx';
import { CompaniesPage } from '../pages/CompaniesPage/CompaniesPage';
import { RecentJobPostingsPage } from '../pages/RecentJobPostingsPage/RecentJobPostingsPage';
import { WhyPage } from '../pages/WhyPage/WhyPage.tsx';
import { AccountPage } from '../pages/AccountPage/AccountPage.tsx';
import { VoteFeaturesPage } from '../pages/VoteFeaturesPage';
import { ROUTES } from '../config/routes';
import { QAPage } from '../pages/QAPage/QAPage.tsx';
import { AdminUsersPage } from '../pages/AdminUsersPage/AdminUsersPage.tsx';
import { AdminLocationNormalizationPage } from '../pages/AdminLocationNormalizationPage/AdminLocationNormalizationPage.tsx';
import { AdminLocationPipelinePage } from '../pages/AdminLocationPipelinePage/AdminLocationPipelinePage.tsx';
import { AdminFeedbackPage } from '../pages/AdminFeedbackPage/AdminFeedbackPage.tsx';
import { AdminRoute } from '../components/auth/AdminRoute.tsx';
import { useEnabledCompanies } from '../features/preferences/useEnabledCompanies';
import { useFeaturesAuthBridge } from '../features/features/useFeaturesAuthBridge';

/**
 * App content component with routing and hooks
 *
 * This component must be inside BrowserRouter to use hooks that
 * depend on React Router context (useLocation).
 */
function AppContent() {
  useURLSync();
  useBrowserNavigation();
  // Hydrate enabled-companies at the app root so selectors have it before
  // any page reads them.
  useEnabledCompanies();
  useFeaturesAuthBridge();

  return (
    <>
      <Routes>
        <Route path="/" element={<RootLayout />}>
          <Route index element={<RecentJobPostingsPage />} />
          <Route path={ROUTES.COMPANIES} element={<CompaniesPage />} />
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
            path={ROUTES.ADMIN_FEEDBACK}
            element={
              <AdminRoute>
                <AdminFeedbackPage />
              </AdminRoute>
            }
          />
          <Route path={ROUTES.ACCOUNT} element={<AccountPage />} />
          <Route path={ROUTES.VOTE_FEATURES} element={<VoteFeaturesPage />} />
        </Route>
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
