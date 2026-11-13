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
