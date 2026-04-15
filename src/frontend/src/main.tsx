import React from 'react';
import ReactDOM from 'react-dom/client';
import { Provider } from 'react-redux';
import { CssBaseline, ThemeProvider } from '@mui/material';
import App from './app/App';
import { store } from './app/store';
import { theme } from './config/theme';
import { ErrorBoundary } from './components/shared/ErrorBoundary';
import { AuthProviders } from './components/shared/AuthProviders';

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
