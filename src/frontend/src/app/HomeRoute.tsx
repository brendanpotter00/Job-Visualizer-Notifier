import { lazy, Suspense, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { LoadingState } from '../components/shared/LoadingIndicator';
import { AUTH_CONFIG } from '../config/auth';
import { ROUTES } from '../config/routes';
import { useAuth } from '../features/auth/useAuth';
import { hasStoredAuthSession, jobsSearchFrom, resolveHomeDestination } from './homeDestination';

// Lazy so the jobs board never pays for the landing page's chunk (and its
// nested three/rapier scene) — signed-in visitors only pass through `/`.
const LandingPage = lazy(() => import('../pages/LandingPage/LandingPage.tsx'));

/**
 * `/`: the landing page for signed-out visitors, a redirect to the jobs board
 * for signed-in ones. Every decision lives in `resolveHomeDestination`.
 *
 * Mounted as a SIBLING of the layout route (not inside RootLayout) so the
 * landing page renders full-bleed — no drawer, no app bar.
 */
export function HomeRoute() {
  const { isAuthenticated, isLoading } = useAuth();
  const { search, hash } = useLocation();
  // Probed once per mount: storage does not meaningfully change while `/` is
  // on screen, and Auth0 resolving is what moves the decision on from here.
  const [hasStoredSession] = useState(() => hasStoredAuthSession());

  const destination = resolveHomeDestination({
    isAuthenticated,
    isLoading,
    bypassEnabled: AUTH_CONFIG.bypassEnabled,
    search,
    hasStoredSession,
  });

  if (destination === 'jobs') {
    // `replace`: Back from the board must not land on `/` and bounce forward.
    return <Navigate to={`${ROUTES.RECENT_JOBS}${jobsSearchFrom(search)}${hash}`} replace />;
  }
  if (destination === 'wait') return <LoadingState fullPage />;
  return (
    <Suspense fallback={<LoadingState fullPage />}>
      <LandingPage />
    </Suspense>
  );
}

/**
 * Any path no route claims — including the landing page's old `/landing` and
 * `/admin/landing-prototypes` addresses — goes to `/` (owner decision,
 * 2026-11-12). Query and hash ride along so the landing page's `?data=`
 * fixture toggle and an old shared filter link both still mean something.
 */
export function UnknownPathRedirect() {
  const { search, hash } = useLocation();
  return <Navigate to={`${ROUTES.HOME}${search}${hash}`} replace />;
}
