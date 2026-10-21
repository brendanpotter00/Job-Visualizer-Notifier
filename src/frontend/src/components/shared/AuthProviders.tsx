import React from 'react';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { Auth0Provider } from '@auth0/auth0-react';
import { AUTH_CONFIG } from '../../config/auth';
import { GoogleCredentialProvider } from '../../features/auth/GoogleCredentialContext';
import { GoogleOneTap } from '../../features/auth/GoogleOneTap';

export function AuthProviders({ children }: { children: React.ReactNode }) {
  // Bypass short-circuits above real providers: dynamic preview URLs can't
  // complete real OAuth callbacks, and mounting Auth0Provider / GoogleOAuthProvider
  // with empty clientIds throws. useAuth module-dispatches to a fake impl.
  if (AUTH_CONFIG.bypassEnabled) {
    return <>{children}</>;
  }
  if (!AUTH_CONFIG.isEnabled) {
    return <>{children}</>;
  }
  return (
    <GoogleOAuthProvider clientId={AUTH_CONFIG.googleClientId}>
      <Auth0Provider
        domain={AUTH_CONFIG.domain}
        clientId={AUTH_CONFIG.clientId}
        cacheLocation="localstorage"
        useRefreshTokens
        useRefreshTokensFallback
        // Cap the background /authorize?prompt=none silent-auth (default 60s). A
        // Google-One-Tap-only user has no Auth0 refresh token, so this iframe
        // always runs and stalls on Chrome's blocked third-party cookies. One Tap
        // no longer waits on it (see GoogleOneTap.tsx), but bounding it to 8s
        // limits wasted background work and the transient "authenticated but
        // isLoading still true" window that gates UserMenu / SignInOverlay /
        // EditCompanyPreferencesLink.
        authorizeTimeoutInSeconds={8}
        authorizationParams={{
          redirect_uri: AUTH_CONFIG.redirectUri,
          audience: AUTH_CONFIG.audience,
          scope: 'openid profile email offline_access',
        }}
      >
        <GoogleCredentialProvider>
          <GoogleOneTap />
          {children}
        </GoogleCredentialProvider>
      </Auth0Provider>
    </GoogleOAuthProvider>
  );
}
