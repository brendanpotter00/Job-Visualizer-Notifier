import React from 'react';
import ReactDOM from 'react-dom/client';
import { Provider } from 'react-redux';
import { CssBaseline, ThemeProvider } from '@mui/material';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { Auth0Provider } from '@auth0/auth0-react';
import App from './app/App';
import { store } from './app/store';
import { theme } from './config/theme';
import { AUTH_CONFIG } from './config/auth';
import { ErrorBoundary } from './components/shared/ErrorBoundary';
import { GoogleCredentialProvider } from './features/auth/GoogleCredentialContext';

function AuthProviders({ children }: { children: React.ReactNode }) {
  if (!AUTH_CONFIG.isEnabled) {
    return <GoogleCredentialProvider>{children}</GoogleCredentialProvider>;
  }
  return (
    <GoogleOAuthProvider clientId={AUTH_CONFIG.googleClientId}>
      <Auth0Provider
        domain={AUTH_CONFIG.domain}
        clientId={AUTH_CONFIG.clientId}
        authorizationParams={{
          redirect_uri: AUTH_CONFIG.redirectUri,
          audience: AUTH_CONFIG.audience,
          scope: 'openid profile email',
        }}
      >
        <GoogleCredentialProvider>{children}</GoogleCredentialProvider>
      </Auth0Provider>
    </GoogleOAuthProvider>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <AuthProviders>
        <Provider store={store}>
          <ThemeProvider theme={theme}>
            <CssBaseline />
            <App />
          </ThemeProvider>
        </Provider>
      </AuthProviders>
    </ErrorBoundary>
  </React.StrictMode>
);
