import { Navigate } from 'react-router-dom';
import { LoadingState } from '../shared/LoadingIndicator';
import { useAuth } from '../../features/auth/useAuth';
import { useCurrentUser } from '../../features/auth/useCurrentUser';
import { ROUTES } from '../../config/routes';

/**
 * Guards admin-only routes.
 *
 * Render order matters here: the auth SDK boots first (isLoading flips to
 * false), then `/api/users` is fetched (loading flips to false). Until both
 * settle, the guard cannot distinguish "non-admin trying to reach /admin"
 * from "admin still loading their profile" — bouncing the latter to `/`
 * would create a flash redirect on every refresh of an admin's session.
 * The two-stage `LoadingState` keeps the guard truthful.
 */
export function AdminRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { user, loading: userLoading } = useCurrentUser();

  if (authLoading) return <LoadingState fullPage />;
  if (!isAuthenticated) return <Navigate to={ROUTES.RECENT_JOBS} replace />;
  if (userLoading && !user) return <LoadingState fullPage />;
  if (!user?.isAdmin) return <Navigate to={ROUTES.RECENT_JOBS} replace />;

  return <>{children}</>;
}
