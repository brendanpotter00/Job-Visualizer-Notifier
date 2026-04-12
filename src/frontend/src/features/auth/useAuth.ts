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
      return getAccessTokenSilently();
    }
    if (googleCredential) {
      return googleCredential;
    }
    throw new Error('Not authenticated');
  }, [isAuth0Authenticated, googleCredential, getAccessTokenSilently]);

  const login = useCallback(() => {
    void loginWithRedirect();
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
    googleCredential,
    setGoogleCredential,
  };
}
