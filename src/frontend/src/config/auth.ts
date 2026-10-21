export interface AuthConfig {
  domain: string;
  clientId: string;
  redirectUri: string;
  audience: string;
  googleClientId: string;
  isEnabled: boolean;
  // QA-only bypass. When VITE_AUTH_BYPASS === 'true' the frontend skips real
  // Auth0/Google providers and useAuth() returns a fake authenticated user, so
  // auth-gated UI is reachable on Preview deploys where real OAuth callbacks
  // (dynamic preview URLs, CORS, etc.) cannot complete. Backend calls with the
  // resulting token will still 401 — this is deliberately frontend-only so the
  // flag has no authn value if it ever leaks outside Preview.
  bypassEnabled: boolean;
}

// Guarded so module evaluation doesn't crash in non-DOM contexts
// (SSR, Node-only tests that don't pull in jsdom).
const defaultRedirectUri = typeof window !== 'undefined' ? window.location.origin : '';

const bypassEnabled = import.meta.env.VITE_AUTH_BYPASS === 'true';

export const AUTH_CONFIG: AuthConfig = {
  domain: import.meta.env.VITE_AUTH0_DOMAIN ?? '',
  clientId: import.meta.env.VITE_AUTH0_CLIENT_ID ?? '',
  redirectUri: import.meta.env.VITE_AUTH0_REDIRECT_URI || defaultRedirectUri,
  audience: import.meta.env.VITE_AUTH0_AUDIENCE ?? '',
  googleClientId: import.meta.env.VITE_GOOGLE_CLIENT_ID ?? '',
  isEnabled: !!(import.meta.env.VITE_AUTH0_DOMAIN && import.meta.env.VITE_AUTH0_CLIENT_ID),
  bypassEnabled,
};

if (bypassEnabled) {
  console.warn(
    '[auth] VITE_AUTH_BYPASS is ON — using fake authenticated user. ' +
      'This should only happen on QA/Preview builds, never production.'
  );
}
