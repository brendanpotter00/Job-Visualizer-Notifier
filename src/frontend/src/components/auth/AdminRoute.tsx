import Container from '@mui/material/Container';
import { Navigate } from 'react-router-dom';
import { LoadingState } from '../shared/LoadingIndicator';
import { ErrorState } from '../shared/ErrorDisplay';
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
 *
 * The "not yet fetched" check is `!user && !error` rather than `loading`:
 * `useCurrentUser` initializes `loading: false` and only flips it true inside
 * the mount effect, so on the very first render an authenticated admin would
 * have `loading=false && user=null`, fall through every gate, and hit the
 * `!user?.isAdmin` redirect before the fetch could even start. Treating "no
 * user and no error yet" as still-resolving closes that initial-frame gap.
 *
 * Error-vs-unauthorized split: when `/api/users` itself fails (backend 500,
 * JWKS outage, network failure), `useCurrentUser` populates `error` but
 * leaves `user` null. Falling through to `Navigate to=/jobs` would be
 * indistinguishable from a real "not an admin" denial, so admins would
 * lose visibility into auth-layer outages. Instead we render an inline
 * error state with a retry button. The redirect ONLY fires when the user
 * is loaded successfully AND `user.isAdmin === false`.
 */
export function AdminRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { user, loading: userLoading, error: userError, reload: refetchUser } =
    useCurrentUser();

  if (authLoading) return <LoadingState fullPage />;
  if (!isAuthenticated) return <Navigate to={ROUTES.RECENT_JOBS} replace />;
  if (userLoading) return <LoadingState fullPage />;
  if (userError && !user) {
    return (
      <Container maxWidth="sm" sx={{ py: 6 }}>
        <ErrorState
          message={userError}
          title="Couldn't verify admin access"
          description="The user profile service is unreachable. This is usually transient — retry, or check Auth0 / backend health."
          onRetry={refetchUser}
        />
      </Container>
    );
  }
  // "Not yet fetched" — fetch hasn't begun (useCurrentUser initializes
  // loading=false, so a brand-new admin reload momentarily looks like
  // user=null/error=null. Treat as still-resolving.
  if (!user) return <LoadingState fullPage />;
  if (!user.isAdmin) return <Navigate to={ROUTES.RECENT_JOBS} replace />;

  return <>{children}</>;
}
