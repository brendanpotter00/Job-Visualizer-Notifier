import { useCallback } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { AUTH_CONFIG } from '../../config/auth';
import { useGoogleCredential } from './useGoogleCredential';

export function useAuth() {
  const {
    isAuthenticated: isAuth0Authenticated,
    isLoading: isAuth0Loading,
    user: auth0User,
    loginWithRedirect,
    logout: auth0Logout,
    getAccessTokenSilently,
  } = useAuth0();

  const { googleCredential, setGoogleCredential } = useGoogleCredential();

  const isAuthenticated = AUTH_CONFIG.isEnabled && (isAuth0Authenticated || !!googleCredential);
  const isLoading = AUTH_CONFIG.isEnabled && isAuth0Loading;

  const getToken = useCallback(async () => {
    if (isAuth0Authenticated) {
      try {
        return await getAccessTokenSilently();
      } catch (error: unknown) {
        if (error instanceof Error && 'error' in error) {
          const auth0Error = error as { error: string };
          if (auth0Error.error === 'login_required' || auth0Error.error === 'consent_required') {
            throw new Error('Your session has expired. Please sign in again.');
          }
        }
        throw error;
      }
    }
    if (googleCredential) {
      return googleCredential;
    }
    throw new Error('Not authenticated');
  }, [isAuth0Authenticated, googleCredential, getAccessTokenSilently]);

  const login = useCallback(async () => {
    try {
      await loginWithRedirect();
    } catch (error) {
      // Rethrow so callers (e.g. sign-in buttons) can surface pop-up blocker,
      // CSP, or Auth0 misconfig errors instead of silently failing.
      console.error('[useAuth] Login redirect failed:', error);
      throw error;
    }
  }, [loginWithRedirect]);

  const logout = useCallback(() => {
    setGoogleCredential(null);
    if (isAuth0Authenticated) {
      auth0Logout({ logoutParams: { returnTo: window.location.origin } });
    }
  }, [isAuth0Authenticated, auth0Logout, setGoogleCredential]);

  return {
    isEnabled: AUTH_CONFIG.isEnabled,
    isAuthenticated,
    isLoading,
    user: auth0User,
    login,
    logout,
    getToken,
  };
}
