import { useCallback } from 'react';
import { useAuth0, type User } from '@auth0/auth0-react';
import { AUTH_CONFIG } from '../../config/auth';
import { useGoogleCredential } from './useGoogleCredential';

interface AuthResult {
  isEnabled: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | undefined;
  login: () => Promise<void>;
  logout: () => void;
  getToken: () => Promise<string>;
}

function useAuthReal(): AuthResult {
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

const BYPASS_USER: User = {
  sub: 'bypass|qa-dev-user',
  email: 'qa-dev@bypass.local',
  name: 'QA Dev User',
  given_name: 'QA',
  family_name: 'Dev',
  picture: '',
};

// Intentionally does NOT call any hooks that require Auth0/Google context, so
// it can run without AuthProviders mounting its real providers.
function useAuthBypass(): AuthResult {
  return {
    isEnabled: true,
    isAuthenticated: true,
    isLoading: false,
    user: BYPASS_USER,
    login: async () => {
      // No-op — already "signed in" as the bypass user.
    },
    logout: () => {
      // No-op — bypass is controlled by the env var, not runtime state.
      console.info('[useAuth] Logout ignored: bypass mode is active.');
    },
    getToken: async () => 'bypass-frontend-only-token',
  };
}

// Module-level dispatch: the env var is inlined at build time, so exactly one
// implementation is bound for the life of the bundle. This keeps hook rules
// satisfied (no runtime conditional hook calls) and guarantees useAuth0() /
// useGoogleCredential() are never invoked in bypass builds where their
// providers are not mounted.
export const useAuth = AUTH_CONFIG.bypassEnabled ? useAuthBypass : useAuthReal;
