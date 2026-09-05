import React from 'react';
import ReactDOM from 'react-dom/client';
import { Provider } from 'react-redux';
import { CssBaseline, ThemeProvider } from '@mui/material';
import { PostHogProvider } from '@posthog/react';
import App from './app/App';
import { store } from './app/store';
import { theme } from './config/theme';
import { ErrorBoundary } from './components/shared/ErrorBoundary';
import { AuthProviders } from './components/shared/AuthProviders';
import { CookieConsentBanner } from './components/shared/CookieConsentBanner';
import { POSTHOG_CONFIG } from './config/posthog';
import { posthog } from './lib/posthog';
import { WEBMCP_CONFIG, registerWebMcpTools } from './webmcp';

// WebMCP agent-driving surface — dead branch unless VITE_WEBMCP === '1' (only
// the e2e verification harness sets it). Store-only; the bridge in App captures
// router/auth out of band. With the flag off this is byte-identical to prod.
if (WEBMCP_CONFIG.isEnabled) {
  registerWebMcpTools(store);
}

const app = (
  <React.StrictMode>
    <ErrorBoundary>
      <AuthProviders>
        <Provider store={store}>
          <ThemeProvider theme={theme}>
            <CssBaseline />
            <App />
            <CookieConsentBanner />
          </ThemeProvider>
        </Provider>
      </AuthProviders>
    </ErrorBoundary>
  </React.StrictMode>
);

ReactDOM.createRoot(document.getElementById('root')!).render(
  POSTHOG_CONFIG.isEnabled ? (
    <PostHogProvider client={posthog}>{app}</PostHogProvider>
  ) : (
    app
  )
);
