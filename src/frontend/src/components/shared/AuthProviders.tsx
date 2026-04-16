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
