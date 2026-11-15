import { useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { LoadingState } from '../components/shared/LoadingIndicator';
import { AUTH_CONFIG } from '../config/auth';
import { ROUTES } from '../config/routes';
import { useAuth } from '../features/auth/useAuth';
import { hasStoredAuthSession, jobsSearchFrom, resolveHomeDestination } from './homeDestination';

import { LandingPage } from '../pages/LandingPage/LandingPage';

export function HomeRoute() {
  const { isAuthenticated, isLoading } = useAuth();
  const { search, hash } = useLocation();
  const [hasStoredSession] = useState(() => hasStoredAuthSession());

  // The URL already left "/" underneath the router: Auth0's onRedirectCallback
  // replaceState'd to the sign-in's returnTo (e.g. /pricing?intent=pro) and React
  // Router applies that popstate as a TRANSITION, while auth0-react's
  // "signed in" lands as an URGENT update first. Deciding now would <Navigate>
  // to /jobs over the pending route; wait one beat and let the router catch up.
  if (window.location.pathname !== ROUTES.HOME) return <LoadingState fullPage />;

  const destination = resolveHomeDestination({
    isAuthenticated,
    isLoading,
    bypassEnabled: AUTH_CONFIG.bypassEnabled,
    search,
    hasStoredSession,
  });

  if (destination === 'jobs') {
    return <Navigate to={`${ROUTES.RECENT_JOBS}${jobsSearchFrom(search)}${hash}`} replace />;
  }
  if (destination === 'wait') return <LoadingState fullPage />;
  return <LandingPage />;
}

export function UnknownPathRedirect() {
  const { search, hash } = useLocation();
  return <Navigate to={`${ROUTES.HOME}${search}${hash}`} replace />;
}
