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

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <GoogleOAuthProvider clientId={AUTH_CONFIG.googleClientId || 'disabled'}>
        <Auth0Provider
          domain={AUTH_CONFIG.domain || 'disabled.auth0.com'}
          clientId={AUTH_CONFIG.clientId || 'disabled'}
          authorizationParams={{
            redirect_uri: AUTH_CONFIG.redirectUri,
            audience: AUTH_CONFIG.audience,
            scope: 'openid profile email',
          }}
        >
          <GoogleCredentialProvider>
            <Provider store={store}>
              <ThemeProvider theme={theme}>
                <CssBaseline />
                <App />
              </ThemeProvider>
            </Provider>
          </GoogleCredentialProvider>
        </Auth0Provider>
      </GoogleOAuthProvider>
    </ErrorBoundary>
  </React.StrictMode>
);
