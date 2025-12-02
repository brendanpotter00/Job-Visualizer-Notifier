import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useURLSync, useBrowserNavigation } from './hooks';
import { RootLayout } from '../components/layouts/RootLayout';
import { CompaniesPage } from '../pages/CompaniesPage/CompaniesPage';
import { RecentJobPostingsPage } from '../pages/RecentJobPostingsPage/RecentJobPostingsPage';
import { WhyPage } from '../pages/WhyPage';
import { ROUTES } from '../config/routes';

/**
 * App content component with routing and hooks
 *
 * This component must be inside BrowserRouter to use hooks that
 * depend on React Router context (useLocation).
 */
function AppContent() {
  // Custom hooks for URL synchronization (page-aware)
  useURLSync();
  useBrowserNavigation();

  return (
    <Routes>
      <Route path="/" element={<RootLayout />}>
        <Route index element={<CompaniesPage />} />
        <Route path={ROUTES.RECENT_JOBS} element={<RecentJobPostingsPage />} />
        <Route path={ROUTES.WHY} element={<WhyPage />} />
      </Route>
    </Routes>
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
 * - / - Companies page (job analytics for selected company)
 * - /recent-jobs - Recent job postings page (all jobs across companies)
 * - /why - Why This Was Built page (about and supported companies)
 */
function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}

export default App;
