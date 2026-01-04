import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { useURLSync, useBrowserNavigation } from './hooks';
import { RootLayout } from '../components/layout/RootLayout.tsx';
import { CompaniesPage } from '../pages/CompaniesPage/CompaniesPage';
import { RecentJobPostingsPage } from '../pages/RecentJobPostingsPage/RecentJobPostingsPage';
import { WhyPage } from '../pages/WhyPage/WhyPage.tsx';
import { ROUTES } from '../config/routes';
import { QAPage } from '../pages/QAPage/QAPage.tsx';

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
        <Route index element={<RecentJobPostingsPage />} />
        <Route path={ROUTES.COMPANIES} element={<CompaniesPage />} />
        <Route path={ROUTES.WHY} element={<WhyPage />} />
        <Route path={ROUTES.QA} element={<QAPage />} />
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
 * - / - Recent job postings page (all jobs across companies)
 * - /companies - Companies page (job analytics for selected company)
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
